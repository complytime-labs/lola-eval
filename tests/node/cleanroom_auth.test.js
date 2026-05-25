import { describe, it, expect } from "vitest";
import { mkdtempSync, writeFileSync, existsSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { legacyCleanRoom } from "../../src/lola_eval/_data/providers/lib/profile_setup.js";

function withHostConfig(dir, fn) {
  const prev = process.env.CLAUDE_CONFIG_DIR;
  process.env.CLAUDE_CONFIG_DIR = dir;
  try {
    return fn();
  } finally {
    if (prev === undefined) delete process.env.CLAUDE_CONFIG_DIR;
    else process.env.CLAUDE_CONFIG_DIR = prev;
    rmSync(dir, { recursive: true, force: true });
  }
}

describe("clean-room auth preservation", () => {
  it("copies host claude .credentials.json into the clean room", () => {
    const hostDir = mkdtempSync(join(tmpdir(), "host-claude-"));
    writeFileSync(join(hostDir, ".credentials.json"), '{"token":"abc"}');
    withHostConfig(hostDir, () => {
      const r = legacyCleanRoom("claude-code");
      expect(existsSync(join(r.configDir, ".credentials.json"))).toBe(true);
    });
  });

  it("is a no-op (no throw) when the host has no credentials", () => {
    const hostDir = mkdtempSync(join(tmpdir(), "host-empty-"));
    withHostConfig(hostDir, () => {
      const r = legacyCleanRoom("claude-code");
      expect(existsSync(join(r.configDir, ".credentials.json"))).toBe(false);
    });
  });

  it("does not copy claude credentials for the opencode target", () => {
    const hostDir = mkdtempSync(join(tmpdir(), "host-claude-"));
    writeFileSync(join(hostDir, ".credentials.json"), '{"token":"abc"}');
    withHostConfig(hostDir, () => {
      const r = legacyCleanRoom("opencode");
      expect(existsSync(join(r.configDir, ".credentials.json"))).toBe(false);
    });
  });
});
