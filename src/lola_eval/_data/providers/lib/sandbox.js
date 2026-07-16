/**
 * Config-discovery isolation for an agent-under-test via bubblewrap.
 *
 * Coding agents (opencode, claude) discover config, agents, and plugins from
 * host paths derived from the config base ($XDG_CONFIG_HOME, else ~/.config),
 * $HOME, and /etc (verified via strace), which contaminates eval results. We
 * run the agent under `bwrap` (bubblewrap): an empty tmpfs is mounted over each
 * host *capability* directory and each host config file is overlaid read-only
 * with an empty valid file ("{}" for JSON, empty otherwise).
 *
 * SCOPE: this masks config/agent/plugin *discovery* only. `bwrap --bind / /`
 * binds the host root read-WRITE, so it is NOT a write sandbox — an agent under
 * test (run with permission bypass) can still read and write host paths outside
 * the hide-set. Sandboxing the agent against itself is intentionally out of
 * scope; see SECURITY.md ("Sandboxing the agent against itself").
 *
 * The hide-set is per-CLI (see HIDE_SPECS); config-base paths follow the
 * inherited config home so a non-default $XDG_CONFIG_HOME is still covered:
 *   - opencode: capability dirs (agents/commands/skills/...) under
 *     `<configHome>/opencode`, its config files, and the HOME-relative
 *     `~/.claude` global config. Its kept node_modules/package.json/plugin(s),
 *     runtime cache (~/.cache/opencode) and auth (~/.local/share/opencode) are
 *     left intact, so no per-run npm reinstall is triggered. External plugins
 *     are additionally dropped via `opencode run --pure` (added by that
 *     provider).
 *   - claude-code: the enterprise dir /etc/claude-code (managed CLAUDE.md /
 *     managed-settings.json) and `<configHome>/anthropic`. claude's own config
 *     is already isolated by the provider via CLAUDE_CONFIG_DIR, so there are
 *     no file overlays and no reinstall risk.
 *
 * Both CLIs additionally get cross-run cache hiding when the provider supplies
 * `workRoot`/`workdir` and `crossRunTmpfs`, so a bare `none` baseline cannot
 * rediscover module artifacts a prior cell left behind (see buildBwrapArgs).
 * The provider owns those paths (single source of truth) rather than this
 * module reconstructing them from a cache root.
 *
 * bwrap is the sole engine: when it is unavailable (or refuses to start),
 * callers warn that results may be skewed and run the agent unsandboxed — a
 * skew warning, not a hard failure.
 *
 * This container injects ambient CAP_SYS_ADMIN, which unprivileged bwrap
 * refuses to start under; `setpriv --inh-caps=-all --ambient-caps=-all` drops
 * it. Detection tries the setpriv-prefixed launcher first and falls back to
 * bare `bwrap`, caching whichever actually works so a broken/old setpriv can
 * never shadow a functional bwrap.
 */
import { spawnSync } from "node:child_process";
import {
  existsSync,
  statSync,
  mkdirSync,
  mkdtempSync,
  writeFileSync,
  rmSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { resolve, join } from "node:path";

// Base bwrap mount set shared by the detection probe and the real command, so
// the probe fails whenever the real invocation would (keeping the "graceful
// skew fallback" promise honest on atypical kernels).
const BWRAP_BASE = ["--bind", "/", "/", "--dev", "/dev", "--proc", "/proc"];
const SETPRIV_PREFIX = ["--inh-caps=-all", "--ambient-caps=-all", "bwrap"];

// Child binary invoked inside the sandbox, keyed by CLI id.
const CLI_BINARY = { opencode: "opencode", "claude-code": "claude" };

/**
 * Per-CLI hide-spec: given the host HOME and config base (configHome), return
 * the discovery paths to neutralize. `dirs` are emptied via tmpfs;
 * `jsonFiles`/`txtFiles` are overlaid read-only with the empty "{}" / empty
 * file respectively. Config-base paths use `configHome` (XDG-aware); dotfile
 * paths use `hostHome`. Each entry is existence-gated by buildBwrapArgs.
 */
const HIDE_SPECS = {
  opencode(hostHome, configHome) {
    const cfg = `${configHome}/opencode`;
    return {
      // Capability dirs → emptied via tmpfs. KEEP node_modules/package.json/
      // plugin(s) (hiding them triggers a per-run npm reinstall + ~120
      // connects). `~/.claude` is included because an opencode agent can still
      // `find` claude's globally-installed skills/agents there (claude's own
      // config is isolated via CLAUDE_CONFIG_DIR, but the host dir persists).
      dirs: [
        `${cfg}/agents`,
        `${cfg}/agent`,
        `${cfg}/commands`,
        `${cfg}/command`,
        `${cfg}/skills`,
        `${cfg}/mode`,
        `${cfg}/modes`,
        `${hostHome}/.agents`,
        `${hostHome}/.opencode`,
        `${hostHome}/.claude`,
        "/etc/opencode",
      ],
      jsonFiles: [
        `${cfg}/opencode.jsonc`,
        `${cfg}/opencode.json`,
        `${cfg}/config.json`,
      ],
      txtFiles: [`${cfg}/AGENTS.md`, `${hostHome}/.npmrc`, "/etc/npmrc"],
    };
  },
  "claude-code"(hostHome, configHome) {
    // claude's own config is isolated via CLAUDE_CONFIG_DIR; only the
    // enterprise dir and the <configHome>/anthropic probe leak from the host.
    return {
      dirs: ["/etc/claude-code", `${configHome}/anthropic`],
      jsonFiles: [],
      txtFiles: [],
    };
  },
};

let _launch; // undefined=unprobed, null=unsupported, else {cmd, prefix}
let _setpriv = null;
let _warned = false;

/** Memoized: is `setpriv` on PATH? Used to build the cap-dropping launcher. */
function hasSetpriv() {
  if (_setpriv !== null) return _setpriv;
  const probe = spawnSync("setpriv", ["--help"], { stdio: "ignore" });
  _setpriv = !probe.error;
  return _setpriv;
}

/**
 * Candidate launchers in priority order: setpriv-prefixed `bwrap` first (drops
 * the ambient caps unprivileged bwrap refuses to start under), then bare
 * `bwrap`. Detection picks the first that actually works so a broken/old
 * setpriv cannot shadow a functional bwrap.
 */
function candidateLaunchers() {
  const launchers = [];
  if (hasSetpriv()) launchers.push({ cmd: "setpriv", prefix: SETPRIV_PREFIX });
  launchers.push({ cmd: "bwrap", prefix: [] });
  return launchers;
}

/** The launcher to use when detection has not resolved one (test/edge path). */
function defaultLaunch() {
  return candidateLaunchers()[0];
}

/**
 * Build the detection-probe argument array. It exercises the SAME mount types
 * the real invocation uses (`--tmpfs` and `--ro-bind`, over caller-provided
 * scratch paths) so a `supported=true` result implies those mounts actually
 * work on this kernel — not merely that a bare bind namespace starts. Runs
 * `true` under the mounts.
 */
export function buildProbeArgs({ tmpfsDir, roSrc, roDest }) {
  return [
    ...BWRAP_BASE,
    "--tmpfs",
    tmpfsDir,
    "--ro-bind",
    roSrc,
    roDest,
    "--die-with-parent",
    "true",
  ];
}

/**
 * Memoized: is bubblewrap usable here? Probes each candidate launcher with a
 * representative tmpfs + ro-bind mount over throwaway scratch paths, caching
 * the first launcher that exits 0. False (and _launch=null) if none work —
 * which also catches the cap/userns refusal this container would otherwise hit.
 */
export function detectBwrapSupport() {
  if (_launch !== undefined) return _launch !== null;
  _launch = null;
  let scratch;
  try {
    scratch = mkdtempSync(join(tmpdir(), "lola-bwrap-probe-"));
    const tmpfsDir = join(scratch, "d");
    const roSrc = join(scratch, "src");
    const roDest = join(scratch, "dst");
    mkdirSync(tmpfsDir, { recursive: true });
    writeFileSync(roSrc, "{}");
    writeFileSync(roDest, "");
    const probeArgs = buildProbeArgs({ tmpfsDir, roSrc, roDest });
    for (const launcher of candidateLaunchers()) {
      const probe = spawnSync(
        launcher.cmd,
        [...launcher.prefix, ...probeArgs],
        { stdio: "ignore" },
      );
      if (!probe.error && probe.status === 0) {
        _launch = launcher;
        break;
      }
    }
  } catch {
    _launch = null;
  } finally {
    if (scratch) {
      try {
        rmSync(scratch, { recursive: true, force: true });
      } catch {
        /* best-effort scratch cleanup */
      }
    }
  }
  return _launch !== null;
}

/** One-time skew warning when isolation is unavailable. */
export function warnNoSandbox(log = (m) => process.stderr.write(m + "\n")) {
  if (_warned) return;
  _warned = true;
  log(
    "[lola-eval] filesystem isolation unavailable (bubblewrap): " +
      "the agent may read host config/agents/plugins — results may be skewed.",
  );
}

/**
 * Create the per-cell empty overlay files a CLI's hide-spec needs, under
 * `<homedir>/.sandbox`: "{}" for JSON configs, empty for the rest (a char
 * device like /dev/null breaks opencode's config readFile). Returns
 * `{emptyJson, emptyTxt}`; both are `undefined` (and nothing is written) for a
 * CLI whose spec binds no config files (e.g. claude-code).
 */
export function prepareOverlays(cli, homedir) {
  const spec = HIDE_SPECS[cli];
  if (!spec) throw new Error(`sandbox: unknown cli "${cli}"`);
  const { jsonFiles, txtFiles } = spec("", "");
  if (jsonFiles.length === 0 && txtFiles.length === 0) {
    return { emptyJson: undefined, emptyTxt: undefined };
  }
  const dir = join(homedir, ".sandbox");
  mkdirSync(dir, { recursive: true });
  const emptyJson = join(dir, "empty.json");
  const emptyTxt = join(dir, "empty.txt");
  writeFileSync(emptyJson, "{}");
  writeFileSync(emptyTxt, "");
  return { emptyJson, emptyTxt };
}

/**
 * Build the bwrap argument array (everything between `bwrap` and the child
 * command) for `cli`. Bind the whole host root read-write, give the child
 * fresh /dev and /proc, then for each host discovery path in the CLI's
 * hide-spec that EXISTS:
 *   - capability directory  → `--tmpfs DIR`         (empty overlay)
 *   - JSON config file      → `--ro-bind EMPTY_JSON FILE`  ("{}" content)
 *   - other config file     → `--ro-bind EMPTY_TXT  FILE`  (empty content)
 * Existence-gating is required: bwrap errors trying to mkdir a tmpfs mountpoint
 * under a non-writable parent (e.g. /etc/opencode when absent), and a
 * non-existent path has nothing to leak.
 *
 * Cross-run cache hiding (provider-supplied, single source of truth):
 *   - `crossRunTmpfs`: each existing dir is `--tmpfs`-overlaid (e.g. the
 *     review-council session cache).
 *   - `workRoot` + `workdir`: the whole work root is `--tmpfs`-overlaid, then
 *     THIS run's `workdir` is rebound on top (order matters: the rebind must
 *     follow the tmpfs) so the agent keeps its CWD while every OTHER cell's
 *     workdir vanishes. The `workdir under workRoot` guard keeps the rebind
 *     honest. Paths are resolve()d so a trailing slash / `..` cannot silently
 *     defeat the prefix match.
 * Ends with `--die-with-parent`.
 */
export function buildBwrapArgs({
  cli,
  hostHome,
  configHome,
  emptyJson,
  emptyTxt,
  crossRunTmpfs = [],
  workRoot,
  workdir,
}) {
  const spec = HIDE_SPECS[cli];
  if (!spec) throw new Error(`sandbox: unknown cli "${cli}"`);
  const cfgHome = configHome || `${hostHome}/.config`;
  const { dirs, jsonFiles, txtFiles } = spec(hostHome, cfgHome);
  const isDir = (p) => existsSync(p) && statSync(p).isDirectory();
  const isFile = (p) => existsSync(p) && statSync(p).isFile();

  const args = [...BWRAP_BASE];
  for (const d of dirs) if (isDir(d)) args.push("--tmpfs", d);
  for (const f of jsonFiles)
    if (isFile(f)) args.push("--ro-bind", emptyJson, f);
  for (const f of txtFiles) if (isFile(f)) args.push("--ro-bind", emptyTxt, f);

  for (const d of crossRunTmpfs) {
    const norm = resolve(d);
    if (isDir(norm)) args.push("--tmpfs", norm);
  }

  if (workRoot && workdir) {
    const normRoot = resolve(workRoot);
    const normWorkdir = resolve(workdir);
    if (
      isDir(normRoot) &&
      isDir(normWorkdir) &&
      normWorkdir.startsWith(`${normRoot}/`)
    ) {
      args.push("--tmpfs", normRoot, "--bind", normWorkdir, normWorkdir);
    }
  }

  args.push("--die-with-parent");
  return args;
}

/**
 * Return the command to actually spawn for `cli` (child binary resolved via
 * CLI_BINARY: opencode→`opencode`, claude-code→`claude`). When `supported`,
 * wraps `<bin> <args>` in bwrap using the launcher detection resolved (setpriv
 * cap-dropping prefix or bare bwrap); otherwise returns it unchanged. Uses the
 * SAME cached launcher detection chose, so the spawned engine can never drift
 * from the one the support probe validated.
 */
export function wrapAgent({
  cli,
  args,
  hostHome,
  configHome,
  emptyJson,
  emptyTxt,
  crossRunTmpfs,
  workRoot,
  workdir,
  supported,
}) {
  const bin = CLI_BINARY[cli];
  if (!bin) throw new Error(`sandbox: unknown cli "${cli}"`);
  if (!supported) return { cmd: bin, args };
  const bwrapArgs = buildBwrapArgs({
    cli,
    hostHome,
    configHome,
    emptyJson,
    emptyTxt,
    crossRunTmpfs,
    workRoot,
    workdir,
  });
  const launch = _launch || defaultLaunch();
  const tail = [...bwrapArgs, bin, ...args];
  return { cmd: launch.cmd, args: [...launch.prefix, ...tail] };
}
