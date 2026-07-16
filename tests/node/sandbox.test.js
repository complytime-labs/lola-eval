import { describe, it, expect } from "vitest";
import {
  mkdtempSync,
  mkdirSync,
  writeFileSync,
  existsSync,
  readFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  buildBwrapArgs,
  buildProbeArgs,
  prepareOverlays,
  wrapAgent,
} from "../../src/lola_eval/_data/providers/lib/sandbox.js";

// Plant a fake host HOME with a realistic ~/.config/opencode: capability dirs
// and config files to neutralize, plus KEEP paths (node_modules/package.json/
// plugin) that must never be touched. `configHome` defaults to <home>/.config
// so the planted tree matches the default XDG layout.
function plantHome() {
  const home = mkdtempSync(join(tmpdir(), "sbx-home-"));
  const cfg = join(home, ".config", "opencode");
  mkdirSync(join(cfg, "agents"), { recursive: true });
  mkdirSync(join(cfg, "node_modules"), { recursive: true });
  mkdirSync(join(cfg, "plugin"), { recursive: true });
  writeFileSync(join(cfg, "opencode.jsonc"), '{"x":1}');
  writeFileSync(join(cfg, "package.json"), "{}");
  writeFileSync(join(cfg, "AGENTS.md"), "host agents");
  return { home, cfg };
}

describe("buildBwrapArgs (opencode)", () => {
  it("emits base mounts, tmpfs for capability dirs, ro-bind for config files", () => {
    const { home, cfg } = plantHome();
    const emptyJson = "/tmp/empty.json";
    const emptyTxt = "/tmp/empty.txt";
    const args = buildBwrapArgs({
      cli: "opencode",
      hostHome: home,
      configHome: join(home, ".config"),
      emptyJson,
      emptyTxt,
    });

    // Fixed base + trailing --die-with-parent.
    expect(args.slice(0, 7)).toEqual([
      "--bind",
      "/",
      "/",
      "--dev",
      "/dev",
      "--proc",
      "/proc",
    ]);
    expect(args[args.length - 1]).toBe("--die-with-parent");

    const s = args.join(" ");
    // Capability dir emptied via tmpfs.
    expect(s).toContain(`--tmpfs ${join(cfg, "agents")}`);
    // JSON config overlaid with the "{}" file.
    expect(s).toContain(
      `--ro-bind ${emptyJson} ${join(cfg, "opencode.jsonc")}`,
    );
    // AGENTS.md overlaid with the empty file.
    expect(s).toContain(`--ro-bind ${emptyTxt} ${join(cfg, "AGENTS.md")}`);

    // KEEP paths are never referenced (hiding them triggers an npm reinstall).
    expect(s).not.toContain(join(cfg, "node_modules"));
    expect(s).not.toContain(join(cfg, "package.json"));
    expect(s).not.toContain(join(cfg, "plugin"));
  });

  it("hides the XDG_CONFIG_HOME-derived opencode dir, not the literal ~/.config", () => {
    // The agent inherits a non-default XDG_CONFIG_HOME; opencode discovers its
    // config/agents from $XDG_CONFIG_HOME/opencode, NOT ~/.config/opencode.
    const home = mkdtempSync(join(tmpdir(), "sbx-xdg-home-"));
    const configHome = mkdtempSync(join(tmpdir(), "sbx-xdg-cfg-"));
    const xdgCfg = join(configHome, "opencode");
    mkdirSync(join(xdgCfg, "agents"), { recursive: true });
    writeFileSync(join(xdgCfg, "opencode.json"), '{"host":true}');
    // A ~/.config/opencode under HOME that must NOT be what we target.
    mkdirSync(join(home, ".config", "opencode", "agents"), { recursive: true });

    const args = buildBwrapArgs({
      cli: "opencode",
      hostHome: home,
      configHome,
      emptyJson: "/tmp/e.json",
      emptyTxt: "/tmp/e.txt",
    });
    const s = args.join(" ");
    // The real (XDG) discovery dir is emptied...
    expect(s).toContain(`--tmpfs ${join(xdgCfg, "agents")}`);
    expect(s).toContain(
      `--ro-bind /tmp/e.json ${join(xdgCfg, "opencode.json")}`,
    );
    // ...and the literal ~/.config/opencode is NOT (XDG supersedes it).
    expect(s).not.toContain(join(home, ".config", "opencode"));
  });

  it("keeps HOME-relative dotfiles (~/.claude) hostHome-based, independent of configHome", () => {
    const home = mkdtempSync(join(tmpdir(), "sbx-dot-home-"));
    const configHome = mkdtempSync(join(tmpdir(), "sbx-dot-cfg-"));
    mkdirSync(join(home, ".claude", "agents"), { recursive: true });
    const args = buildBwrapArgs({
      cli: "opencode",
      hostHome: home,
      configHome,
      emptyJson: "/tmp/e.json",
      emptyTxt: "/tmp/e.txt",
    });
    // ~/.claude follows HOME, not XDG_CONFIG_HOME.
    expect(args.join(" ")).toContain(`--tmpfs ${join(home, ".claude")}`);
  });

  it("omits paths that do not exist", () => {
    const home = mkdtempSync(join(tmpdir(), "sbx-empty-home-"));
    const args = buildBwrapArgs({
      cli: "opencode",
      hostHome: home,
      configHome: join(home, ".config"),
      emptyJson: "/tmp/e.json",
      emptyTxt: "/tmp/e.txt",
    });
    const s = args.join(" ");
    expect(s).not.toContain(home);
    expect(args[0]).toBe("--bind");
    expect(args[args.length - 1]).toBe("--die-with-parent");
  });
});

describe("buildBwrapArgs (cross-run / cache hiding)", () => {
  it("empties each crossRunTmpfs dir that exists", () => {
    const home = mkdtempSync(join(tmpdir(), "sbx-rc-home-"));
    const reviewCouncil = mkdtempSync(join(tmpdir(), "sbx-rc-"));
    const args = buildBwrapArgs({
      cli: "opencode",
      hostHome: home,
      configHome: join(home, ".config"),
      emptyJson: "/tmp/e.json",
      emptyTxt: "/tmp/e.txt",
      crossRunTmpfs: [reviewCouncil],
    });
    expect(args.join(" ")).toContain(`--tmpfs ${reviewCouncil}`);
  });

  it("empties the work root but rebinds the current workdir on top", () => {
    const home = mkdtempSync(join(tmpdir(), "sbx-work-home-"));
    const workRoot = mkdtempSync(join(tmpdir(), "sbx-work-root-"));
    const workdir = join(workRoot, "taskA", "modelX", "none", "run1");
    mkdirSync(workdir, { recursive: true });
    mkdirSync(join(workRoot, "taskA", "modelX", "some-module", "run2"), {
      recursive: true,
    });

    const args = buildBwrapArgs({
      cli: "opencode",
      hostHome: home,
      configHome: join(home, ".config"),
      emptyJson: "/tmp/e.json",
      emptyTxt: "/tmp/e.txt",
      workRoot,
      workdir,
    });
    // tmpfs empties the whole work root, then the current workdir is rebound
    // back on top (order matters: rebind must follow the tmpfs).
    expect(args.join(" ")).toContain(
      `--tmpfs ${workRoot} --bind ${workdir} ${workdir}`,
    );
  });

  it("still hides the work cache when workRoot/workdir carry a trailing slash", () => {
    const home = mkdtempSync(join(tmpdir(), "sbx-slash-home-"));
    const workRoot = mkdtempSync(join(tmpdir(), "sbx-slash-root-"));
    const workdir = join(workRoot, "taskA", "run1");
    mkdirSync(workdir, { recursive: true });
    const args = buildBwrapArgs({
      cli: "opencode",
      hostHome: home,
      configHome: join(home, ".config"),
      emptyJson: "/tmp/e.json",
      emptyTxt: "/tmp/e.txt",
      workRoot: `${workRoot}/`, // raw value with a trailing slash
      workdir,
    });
    expect(args.join(" ")).toContain(
      `--tmpfs ${workRoot} --bind ${workdir} ${workdir}`,
    );
  });

  it("does not hide work/cross-run caches when none are passed", () => {
    const home = mkdtempSync(join(tmpdir(), "sbx-nocache-"));
    const args = buildBwrapArgs({
      cli: "opencode",
      hostHome: home,
      configHome: join(home, ".config"),
      emptyJson: "/tmp/e.json",
      emptyTxt: "/tmp/e.txt",
    });
    const s = args.join(" ");
    expect(s).not.toContain("--tmpfs " + home + "/.cache");
    // With no workRoot there is no --bind of a workdir back on top.
    expect(s).not.toContain("--bind " + home);
  });

  it("skips the work rebind when workdir is not under the work root", () => {
    const home = mkdtempSync(join(tmpdir(), "sbx-badwork-"));
    const workRoot = mkdtempSync(join(tmpdir(), "sbx-badwork-root-"));
    const outsideWorkdir = mkdtempSync(join(tmpdir(), "sbx-outside-"));
    const args = buildBwrapArgs({
      cli: "opencode",
      hostHome: home,
      configHome: join(home, ".config"),
      emptyJson: "/tmp/e.json",
      emptyTxt: "/tmp/e.txt",
      workRoot,
      workdir: outsideWorkdir,
    });
    const s = args.join(" ");
    expect(s).not.toContain(`--bind ${outsideWorkdir}`);
    expect(s).not.toContain(`--tmpfs ${workRoot}`);
  });

  it("applies the same cross-run hiding for claude-code (parity with opencode)", () => {
    const home = mkdtempSync(join(tmpdir(), "sbx-cc-xrun-home-"));
    const workRoot = mkdtempSync(join(tmpdir(), "sbx-cc-xrun-root-"));
    const workdir = join(workRoot, "taskA", "run1");
    const reviewCouncil = mkdtempSync(join(tmpdir(), "sbx-cc-rc-"));
    mkdirSync(workdir, { recursive: true });
    const args = buildBwrapArgs({
      cli: "claude-code",
      hostHome: home,
      configHome: join(home, ".config"),
      emptyJson: "/tmp/e.json",
      emptyTxt: "/tmp/e.txt",
      workRoot,
      workdir,
      crossRunTmpfs: [reviewCouncil],
    });
    const s = args.join(" ");
    expect(s).toContain(`--tmpfs ${reviewCouncil}`);
    expect(s).toContain(`--tmpfs ${workRoot} --bind ${workdir} ${workdir}`);
  });
});

describe("buildBwrapArgs (claude-code)", () => {
  it("empties the XDG-derived anthropic dir via tmpfs and uses no file overlays", () => {
    const home = mkdtempSync(join(tmpdir(), "sbx-cc-home-"));
    const configHome = join(home, ".config");
    const anthropic = join(configHome, "anthropic");
    mkdirSync(anthropic, { recursive: true });

    const args = buildBwrapArgs({
      cli: "claude-code",
      hostHome: home,
      configHome,
      emptyJson: "/tmp/e.json",
      emptyTxt: "/tmp/e.txt",
    });

    expect(args.slice(0, 7)).toEqual([
      "--bind",
      "/",
      "/",
      "--dev",
      "/dev",
      "--proc",
      "/proc",
    ]);
    expect(args[args.length - 1]).toBe("--die-with-parent");
    expect(args.join(" ")).toContain(`--tmpfs ${anthropic}`);
    // claude's hide-set has no file overlays.
    expect(args).not.toContain("--ro-bind");
  });
});

describe("prepareOverlays", () => {
  it("creates {} / empty overlay files for opencode (has file overlays)", () => {
    const homedir = mkdtempSync(join(tmpdir(), "sbx-ov-oc-"));
    const { emptyJson, emptyTxt } = prepareOverlays("opencode", homedir);
    expect(emptyJson).toBeTruthy();
    expect(emptyTxt).toBeTruthy();
    expect(existsSync(emptyJson)).toBe(true);
    expect(existsSync(emptyTxt)).toBe(true);
    expect(readFileSync(emptyJson, "utf8")).toBe("{}");
    expect(readFileSync(emptyTxt, "utf8")).toBe("");
  });

  it("writes no overlay files for claude-code (no file overlays)", () => {
    const homedir = mkdtempSync(join(tmpdir(), "sbx-ov-cc-"));
    const { emptyJson, emptyTxt } = prepareOverlays("claude-code", homedir);
    expect(emptyJson).toBeUndefined();
    expect(emptyTxt).toBeUndefined();
    // No .sandbox dir/files created (the claude spec binds no config files).
    expect(existsSync(join(homedir, ".sandbox"))).toBe(false);
  });
});

describe("buildProbeArgs", () => {
  it("exercises tmpfs AND ro-bind so support implies real mounts work", () => {
    const args = buildProbeArgs({
      tmpfsDir: "/scratch/d",
      roSrc: "/scratch/src",
      roDest: "/scratch/dst",
    });
    expect(args.slice(0, 7)).toEqual([
      "--bind",
      "/",
      "/",
      "--dev",
      "/dev",
      "--proc",
      "/proc",
    ]);
    const s = args.join(" ");
    // The two mount types the real invocation uses must be probed.
    expect(s).toContain("--tmpfs /scratch/d");
    expect(s).toContain("--ro-bind /scratch/src /scratch/dst");
    // Ends by running a trivial command under the mounts.
    expect(args.slice(-2)).toEqual(["--die-with-parent", "true"]);
  });
});

describe("wrapAgent", () => {
  it("resolves the child binary from the cli and passes through when unsupported", () => {
    const oc = wrapAgent({
      cli: "opencode",
      args: ["run", "hi"],
      hostHome: "/home/x",
      configHome: "/home/x/.config",
      emptyJson: "/tmp/e.json",
      emptyTxt: "/tmp/e.txt",
      supported: false,
    });
    expect(oc.cmd).toBe("opencode");
    expect(oc.args).toEqual(["run", "hi"]);

    const cc = wrapAgent({
      cli: "claude-code",
      args: ["-p", "hi"],
      hostHome: "/home/x",
      configHome: "/home/x/.config",
      supported: false,
    });
    expect(cc.cmd).toBe("claude");
    expect(cc.args).toEqual(["-p", "hi"]);
  });

  it("wraps opencode in bwrap (setpriv prefix when the launcher uses it) when supported", () => {
    const { home } = plantHome();
    const { cmd, args } = wrapAgent({
      cli: "opencode",
      args: ["run", "--pure", "hi"],
      hostHome: home,
      configHome: join(home, ".config"),
      emptyJson: "/tmp/e.json",
      emptyTxt: "/tmp/e.txt",
      supported: true,
    });
    expect(["setpriv", "bwrap"]).toContain(cmd);
    if (cmd === "setpriv") {
      expect(args.slice(0, 3)).toEqual([
        "--inh-caps=-all",
        "--ambient-caps=-all",
        "bwrap",
      ]);
    }
    expect(args).toContain("--bind");
    expect(args).toContain("--die-with-parent");
    const oc = args.lastIndexOf("opencode");
    expect(oc).toBeGreaterThan(-1);
    expect(args.slice(oc)).toEqual(["opencode", "run", "--pure", "hi"]);
  });

  it("wraps claude in bwrap with the claude binary tail when supported", () => {
    const home = mkdtempSync(join(tmpdir(), "sbx-cc-wrap-"));
    const { cmd, args } = wrapAgent({
      cli: "claude-code",
      args: ["-p", "hi"],
      hostHome: home,
      configHome: join(home, ".config"),
      supported: true,
    });
    expect(["setpriv", "bwrap"]).toContain(cmd);
    expect(args).toContain("--bind");
    expect(args).toContain("--die-with-parent");
    const cc = args.lastIndexOf("claude");
    expect(cc).toBeGreaterThan(-1);
    expect(args.slice(cc)).toEqual(["claude", "-p", "hi"]);
  });
});
