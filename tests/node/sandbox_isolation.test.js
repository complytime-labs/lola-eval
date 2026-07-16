import { describe, it, expect } from "vitest";
import {
  mkdtempSync,
  mkdirSync,
  writeFileSync,
  readFileSync,
  existsSync,
} from "node:fs";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  detectBwrapSupport,
  wrapAgent,
} from "../../src/lola_eval/_data/providers/lib/sandbox.js";

const supported = detectBwrapSupport();

// Build the real wrapped command via wrapAgent, then swap the trailing
// "opencode <args>" for a credential-free shell probe so the actual bwrap
// mechanism (tmpfs + ro-bind overlays) is exercised without a live opencode.
function probeCommand({ hostHome, emptyJson, emptyTxt }, probeScript) {
  const { cmd, args } = wrapAgent({
    cli: "opencode",
    args: ["run", "--pure"],
    hostHome,
    configHome: join(hostHome, ".config"),
    emptyJson,
    emptyTxt,
    supported: true,
  });
  const cut = args.lastIndexOf("opencode");
  const probeArgs = [...args.slice(0, cut), "/bin/sh", "-c", probeScript];
  return { cmd, probeArgs };
}

describe.skipIf(!supported)("sandbox isolation (real bwrap)", () => {
  it("child sees emptied capability dir and {} config, host survives", () => {
    const home = mkdtempSync(join(tmpdir(), "sbx-home-"));
    const cfg = join(home, ".config", "opencode");
    const agents = join(cfg, "agents");
    mkdirSync(agents, { recursive: true });
    writeFileSync(join(agents, "godev.md"), "HOST AGENT CONTENT");
    writeFileSync(join(cfg, "opencode.jsonc"), '{"host":true}');

    const emptyDir = mkdtempSync(join(tmpdir(), "sbx-empty-"));
    const emptyJson = join(emptyDir, "empty.json");
    const emptyTxt = join(emptyDir, "empty.txt");
    writeFileSync(emptyJson, "{}");
    writeFileSync(emptyTxt, "");

    const { cmd, probeArgs } = probeCommand(
      { hostHome: home, emptyJson, emptyTxt },
      'ls -A "$CFG/agents" | wc -l; cat "$CFG/opencode.jsonc"',
    );
    const res = spawnSync(cmd, probeArgs, {
      env: { ...process.env, CFG: cfg },
      encoding: "utf8",
    });
    expect(res.status).toBe(0);
    const lines = res.stdout.trim().split("\n");
    // First line: agents dir count inside the namespace — emptied by tmpfs.
    expect(lines[0].trim()).toBe("0");
    // Remaining lines: the config file the child reads — overlaid with "{}".
    expect(lines.slice(1).join("\n")).toBe("{}");

    // Host copies untouched on disk.
    expect(existsSync(join(agents, "godev.md"))).toBe(true);
    expect(readFileSync(join(agents, "godev.md"), "utf8")).toBe(
      "HOST AGENT CONTENT",
    );
    expect(readFileSync(join(cfg, "opencode.jsonc"), "utf8")).toBe(
      '{"host":true}',
    );
  });

  it("hides a sibling cell's workdir but keeps the current run's workdir", () => {
    const home = mkdtempSync(join(tmpdir(), "sbx-work-home-"));
    const cacheHome = mkdtempSync(join(tmpdir(), "sbx-work-cache-"));
    const workRoot = join(cacheHome, "lola-eval", "work");
    const workdir = join(workRoot, "taskA", "modelX", "none", "run1");
    const leakdir = join(workRoot, "taskA", "modelX", "some-module", "run2");
    mkdirSync(workdir, { recursive: true });
    mkdirSync(leakdir, { recursive: true });
    writeFileSync(join(workdir, "keep.txt"), "CURRENT-RUN");
    writeFileSync(join(leakdir, "MODULE.md"), "LEAKED MODULE ARTIFACT");

    const emptyDir = mkdtempSync(join(tmpdir(), "sbx-empty-"));
    const emptyJson = join(emptyDir, "empty.json");
    const emptyTxt = join(emptyDir, "empty.txt");
    writeFileSync(emptyJson, "{}");
    writeFileSync(emptyTxt, "");

    const { cmd, args } = wrapAgent({
      cli: "opencode",
      args: ["run", "--pure"],
      hostHome: home,
      configHome: join(home, ".config"),
      emptyJson,
      emptyTxt,
      workRoot,
      workdir,
      supported: true,
    });
    const cut = args.lastIndexOf("opencode");
    const probe =
      'cat "$KEEP" 2>&1; echo "---"; cat "$LEAK" 2>&1; echo "---"; ' +
      'ls "$WROOT/taskA/modelX" 2>&1';
    const probeArgs = [...args.slice(0, cut), "/bin/sh", "-c", probe];
    const res = spawnSync(cmd, probeArgs, {
      env: {
        ...process.env,
        KEEP: join(workdir, "keep.txt"),
        LEAK: join(leakdir, "MODULE.md"),
        WROOT: workRoot,
      },
      encoding: "utf8",
    });
    expect(res.status).toBe(0);
    const [current, leaked, listing] = res.stdout.split("---");
    // The current run's own workdir survives the tmpfs (rebound on top).
    expect(current.trim()).toBe("CURRENT-RUN");
    // The sibling module-pack workdir is gone inside the namespace.
    expect(leaked).toContain("No such file");
    // Only the rebound `none` cell is visible under the shared model dir.
    expect(listing.trim()).toBe("none");

    // Host copies untouched (mounts were private to the child namespace).
    expect(readFileSync(join(leakdir, "MODULE.md"), "utf8")).toBe(
      "LEAKED MODULE ARTIFACT",
    );
  });
});
