/**
 * Subprocess spawn with transcript capture.
 *
 * Streams stdout to a file (the transcript). Captures stderr in memory.
 * Enforces wall-clock timeout via SIGKILL. Returns structured result.
 */
import { spawn } from 'node:child_process';
import { createWriteStream, mkdirSync } from 'node:fs';
import { dirname } from 'node:path';
import { performance } from 'node:perf_hooks';

export async function runAndCapture({
  cmd,
  args = [],
  cwd,
  env,
  transcriptPath,
  timeoutMs,
}) {
  mkdirSync(dirname(transcriptPath), { recursive: true });
  const out = createWriteStream(transcriptPath);
  const stderrChunks = [];
  const t0 = performance.now();

  return await new Promise((resolve, reject) => {
    const child = spawn(cmd, args, { cwd, env, stdio: ['ignore', 'pipe', 'pipe'] });
    let timedOut = false;

    const killer = setTimeout(() => {
      timedOut = true;
      try { child.kill('SIGKILL'); } catch { /* already exited */ }
    }, timeoutMs);

    child.stdout.pipe(out);
    child.stderr.on('data', d => stderrChunks.push(d));

    child.on('error', err => {
      clearTimeout(killer);
      reject(err);
    });

    child.on('close', code => {
      clearTimeout(killer);
      out.end(() => {
        resolve({
          exitCode: code ?? -1,
          timedOut,
          stderr: Buffer.concat(stderrChunks).toString('utf8'),
          durationS: (performance.now() - t0) / 1000,
        });
      });
    });
  });
}
