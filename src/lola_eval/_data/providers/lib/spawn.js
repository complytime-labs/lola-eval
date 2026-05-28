/**
 * Subprocess spawn with transcript capture.
 *
 * Streams stdout to a file (the transcript). Captures stderr in memory.
 * Enforces wall-clock timeout via SIGKILL. Returns structured result.
 */
import { spawn } from "node:child_process";
import { createWriteStream, mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { performance } from "node:perf_hooks";

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

  // Heartbeat interval (seconds). A long-running agent/judge child writes its
  // detail to the transcript file, not the console, so without a heartbeat the
  // console looks dead for minutes — and CI runners that abort on "no output
  // for N minutes" would kill the job. Override via LOLA_HEARTBEAT_S.
  const heartbeatMs = (Number(process.env.LOLA_HEARTBEAT_S) || 30) * 1000;

  return await new Promise((resolve, reject) => {
    // cmd is always a hardcoded literal at call sites; env is a sanitized
    // clean-room environment for the child, not interpolated into the command.
    // lgtm[js/shell-command-constructed-from-input]
    const child = spawn(cmd, args, {
      cwd,
      env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let timedOut = false;

    const killer = setTimeout(() => {
      timedOut = true;
      try {
        child.kill("SIGKILL");
      } catch {
        /* already exited */
      }
    }, timeoutMs);

    const heartbeat = setInterval(() => {
      const elapsed = ((performance.now() - t0) / 1000).toFixed(0);
      process.stderr.write(
        `[lola-eval] ${cmd} still running (${elapsed}s elapsed; transcript: ${transcriptPath})…\n`,
      );
    }, heartbeatMs);

    const cleanup = () => {
      clearTimeout(killer);
      clearInterval(heartbeat);
    };

    child.stdout.pipe(out);
    child.stderr.on("data", (d) => stderrChunks.push(d));

    child.on("error", (err) => {
      cleanup();
      reject(err);
    });

    child.on("close", (code) => {
      cleanup();
      out.end(() => {
        resolve({
          exitCode: code ?? -1,
          timedOut,
          stderr: Buffer.concat(stderrChunks).toString("utf8"),
          durationS: (performance.now() - t0) / 1000,
        });
      });
    });
  });
}
