import { describe, it, expect } from "vitest";
import { mkdtempSync, writeFileSync, readFileSync, chmodSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { reset } from "../../src/lola_eval/_data/providers/lib/reset.js";

// A fake reset.sh that records the LOLA_INCLUDE_IGNORED it received into the
// workdir ($3), so we can assert reset() threads it through per-row via env.
function fakeResetScript(dir) {
  const script = join(dir, "fake-reset.sh");
  writeFileSync(
    script,
    '#!/usr/bin/env bash\nmkdir -p "$3"\necho "[${LOLA_INCLUDE_IGNORED:-UNSET}]" > "$3/seen.txt"\n',
  );
  chmodSync(script, 0o755);
  return script;
}

describe("reset includeIgnored env passing (#13 opt-in)", () => {
  it("passes includeIgnored to reset.sh via LOLA_INCLUDE_IGNORED", async () => {
    const dir = mkdtempSync(join(tmpdir(), "reset-ii-"));
    const wd = join(dir, "wd");
    await reset({
      taskId: "t",
      targetCli: "claude-code",
      workdir: wd,
      scriptPath: fakeResetScript(dir),
      includeIgnored: "vendor/ *.log",
    });
    expect(readFileSync(join(wd, "seen.txt"), "utf8").trim()).toBe(
      "[vendor/ *.log]",
    );
  });

  it("leaves LOLA_INCLUDE_IGNORED unset when includeIgnored is empty", async () => {
    const dir = mkdtempSync(join(tmpdir(), "reset-ii-"));
    const wd = join(dir, "wd");
    await reset({
      taskId: "t",
      targetCli: "claude-code",
      workdir: wd,
      scriptPath: fakeResetScript(dir),
    });
    expect(readFileSync(join(wd, "seen.txt"), "utf8").trim()).toBe("[UNSET]");
  });
});
