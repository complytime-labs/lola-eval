/**
 * Reset hook: invokes orchestrator/reset.sh with task_id and target_cli.
 * The bash script does the actual work (rsync starter → workdir, lola
 * uninstall, git init in workdir). This wrapper exists so we can mock it
 * in tests.
 */
import { spawn } from 'node:child_process';

export async function reset({ taskId, targetCli, workdir, scriptPath = 'orchestrator/reset.sh' }) {
  return await new Promise((resolve, reject) => {
    const child = spawn('bash', [scriptPath, taskId, targetCli, workdir], {
      stdio: ['ignore', 'inherit', 'inherit'],
    });
    child.on('close', code => {
      if (code === 0) resolve();
      else reject(new Error(`reset.sh exited ${code}`));
    });
    child.on('error', reject);
  });
}

export async function installPack({ packId, targetCli, workdir, scriptPath = 'orchestrator/install_pack.sh' }) {
  if (packId === 'none') return;
  const args = [scriptPath, packId, targetCli];
  if (workdir) args.push(workdir);
  // Capture stderr so we can surface lola's actual complaint (e.g.
  // "Module 'example-pack' not found") via the provider envelope's
  // error_message — landing in runs.db where the user can see it. Tee
  // to the parent's stderr too so the breadcrumb is still visible live.
  return await new Promise((resolve, reject) => {
    const child = spawn('bash', args, {
      stdio: ['ignore', 'inherit', 'pipe'],
    });
    let capturedStderr = '';
    child.stderr.on('data', chunk => {
      const text = chunk.toString('utf8');
      capturedStderr += text;
      process.stderr.write(text);
    });
    child.on('close', code => {
      if (code === 0) {
        resolve();
        return;
      }
      // Prefer the `install_pack.sh: FAILED ...` line if present (it has
      // the cleaned-up lola message). Fall back to the full stderr.
      const match = capturedStderr.match(/install_pack\.sh: FAILED [^\n]+/);
      const detail = match ? match[0] : capturedStderr.trim();
      const err = new Error(detail || `install_pack.sh exited ${code}`);
      err.exitCode = code;
      err.stderr = capturedStderr;
      reject(err);
    });
    child.on('error', reject);
  });
}
