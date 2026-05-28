import { describe, it, expect } from "vitest";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { runAndCapture } from "../../src/lola_eval/_data/providers/lib/spawn.js";

function captureStderr() {
  const writes = [];
  const orig = process.stderr.write.bind(process.stderr);
  process.stderr.write = (chunk, ...rest) => {
    writes.push(String(chunk));
    return orig(chunk, ...rest);
  };
  return {
    writes,
    restore: () => {
      process.stderr.write = orig;
    },
  };
}

function withHeartbeat(seconds, fn) {
  const prev = process.env.LOLA_HEARTBEAT_S;
  process.env.LOLA_HEARTBEAT_S = String(seconds);
  return Promise.resolve(fn()).finally(() => {
    if (prev === undefined) delete process.env.LOLA_HEARTBEAT_S;
    else process.env.LOLA_HEARTBEAT_S = prev;
  });
}

describe("runAndCapture heartbeat", () => {
  it("emits a heartbeat while a long-running child is in flight", async () => {
    const dir = mkdtempSync(join(tmpdir(), "hb-"));
    const cap = captureStderr();
    try {
      await withHeartbeat(0.05, async () => {
        // 50ms interval
        const r = await runAndCapture({
          cmd: "bash",
          args: ["-c", "sleep 0.4"],
          cwd: dir,
          env: process.env,
          transcriptPath: join(dir, "t.jsonl"),
          timeoutMs: 5000,
        });
        expect(r.exitCode).toBe(0);
        expect(r.timedOut).toBe(false);
      });
    } finally {
      cap.restore();
    }
    expect(
      cap.writes.filter((w) => w.includes("still running")).length,
    ).toBeGreaterThanOrEqual(1);
  });

  it("does not emit a heartbeat for a fast child (cleared on exit)", async () => {
    const dir = mkdtempSync(join(tmpdir(), "hb-"));
    const cap = captureStderr();
    try {
      await withHeartbeat(30, async () => {
        await runAndCapture({
          cmd: "bash",
          args: ["-c", "true"],
          cwd: dir,
          env: process.env,
          transcriptPath: join(dir, "t.jsonl"),
          timeoutMs: 5000,
        });
      });
    } finally {
      cap.restore();
    }
    expect(cap.writes.filter((w) => w.includes("still running")).length).toBe(
      0,
    );
  });
});
