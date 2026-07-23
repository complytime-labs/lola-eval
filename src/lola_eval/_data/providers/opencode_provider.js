/**
 * Promptfoo custom provider: drives `opencode run --format json`.
 * Same contract as claude_code_provider but invokes opencode.
 */
import { randomUUID } from "node:crypto";
import { mkdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, resolve as resolvePath } from "node:path";

import { runAndCapture } from "./lib/spawn.js";
import { buildEnvelope } from "./lib/envelope.js";
import { reset, installPack, preRun } from "./lib/reset.js";
import { sanitizePathComponent } from "./lib/sanitize.js";
import { applyProfile } from "./lib/profile_setup.js";
import { commitAll, getCurrentHead, gitDiff } from "./lib/git_helpers.js";
import { resolveModel } from "./lib/model_resolver.js";
import {
  detectBwrapSupport,
  warnNoSandbox,
  wrapAgent,
  prepareOverlays,
} from "./lib/sandbox.js";

// See claude_code_provider for rationale.
const _PROVIDER_DIR = dirname(fileURLToPath(import.meta.url));
const RESET_SH = resolvePath(_PROVIDER_DIR, "..", "orchestrator", "reset.sh");
const INSTALL_PACK_SH = resolvePath(
  _PROVIDER_DIR,
  "..",
  "orchestrator",
  "install_pack.sh",
);

function xdgStateRoot() {
  const root =
    process.env.XDG_STATE_HOME ?? join(process.env.HOME, ".local/state");
  return join(root, "lola-eval");
}
function xdgCacheRoot() {
  const root = process.env.XDG_CACHE_HOME ?? join(process.env.HOME, ".cache");
  return join(root, "lola-eval");
}

export default class OpencodeProvider {
  constructor(options = {}) {
    this.options = options;
  }
  id() {
    return "opencode";
  }

  async callApi(prompt, context) {
    const v = context.vars;
    // Capture the real host HOME before any per-cell / user-scope override so
    // the filesystem hide-list targets host discovery paths (e.g.
    // ~/.config/opencode), never the per-cell clean-room config.
    const hostHome = process.env.HOME;
    const runId = randomUUID();
    // Workdir is unique per (task, model, pack, runId) so concurrent runs
    // cannot race on the same filesystem path. See claude_code_provider
    // for rationale. runId is a UUID; no sanitization needed.
    const packSlug = sanitizePathComponent(String(v.pack_id));
    const taskSlug = sanitizePathComponent(String(v.task_id));
    const modelSlug = sanitizePathComponent(String(v.target_model));
    // Host config/cache bases (XDG-aware) for the sandbox hide-list. configHome
    // covers a non-default $XDG_CONFIG_HOME (opencode discovers config/agents
    // from $XDG_CONFIG_HOME/opencode). crossRunTmpfs empties the review-council
    // session cache; workRoot empties prior cells' workdirs — so a bare `none`
    // baseline cannot rediscover artifacts a prior cell left behind. workRoot
    // reuses xdgCacheRoot() (single source of truth for the work-cache path).
    const configHome = process.env.XDG_CONFIG_HOME || join(hostHome, ".config");
    const cacheBase = process.env.XDG_CACHE_HOME || join(hostHome, ".cache");
    const crossRunTmpfs = [join(cacheBase, "review-council")];
    const workRoot = join(xdgCacheRoot(), "work");
    const workdir = resolvePath(
      join(xdgCacheRoot(), "work", taskSlug, modelSlug, packSlug, runId),
    );
    const homedir = resolvePath(
      join(xdgCacheRoot(), "home", taskSlug, modelSlug, packSlug, runId),
    );
    mkdirSync(homedir, { recursive: true });
    // Per-cell empty overlay files the sandbox binds over host config files.
    const { emptyJson, emptyTxt } = prepareOverlays("opencode", homedir);
    const transcriptPath = join(
      xdgStateRoot(),
      "transcripts",
      `${runId}.jsonl`,
    );
    mkdirSync(join(xdgStateRoot(), "transcripts"), { recursive: true });

    const log = (msg) => process.stderr.write(`[opencode-provider] ${msg}\n`);
    log(
      `run_id=${runId.slice(0, 8)} task=${v.task_id} pack=${v.pack_id} model=${v.target_model}`,
    );
    log(`transcript: ${transcriptPath}  (tail -f to watch)`);

    try {
      log(`reset workdir → ${workdir}`);
      await reset({
        taskId: v.task_id,
        targetCli: "opencode",
        workdir,
        scriptPath: RESET_SH,
        includeIgnored: v.include_ignored_paths || "",
        homedir,
        cacheHome: cacheBase,
      });
      log(`install pack ${v.pack_id} (scope=${v.install_scope}) ...`);
      await installPack({
        packId: v.pack_id,
        targetCli: "opencode",
        workdir,
        scriptPath: INSTALL_PACK_SH,
        moduleSource: v.module_source || "",
        installScope: v.install_scope || "project",
        homedir,
      });
      await commitAll(workdir, "pack-installed");
      const preRunCmd = (v.pre_run ?? "").trim();
      if (preRunCmd) {
        log(`pre_run: ${preRunCmd}`);
        await preRun({ workdir, command: preRunCmd, env: process.env });
        await commitAll(workdir, "pre-run-provisioned");
      }
    } catch (err) {
      // install_pack.sh / reset.sh already printed the actionable text
      // to stderr above. Keep this to a breadcrumb so we don't print
      // a third copy. The full message lives in the envelope.error_message.
      log(`setup_error (see message above)`);
      // See claude_code_provider.js for why we omit `error:` here —
      // letting the judge run lets us persist a proper setup_error row
      // with the actual cause in error_message instead of falling back
      // to no_run_produced.
      return {
        output: JSON.stringify(
          buildEnvelope({
            runId,
            transcriptPath,
            turns: 0,
            toolCalls: [],
            exitStatus: "setup_error",
            durationS: 0,
            diff: "",
            costUsd: 0,
            errorMessage: err && err.message ? err.message : String(err),
          }),
        ),
      };
    }

    const profilesDir = process.env.LOLA_PROFILES_DIR || "";
    const profileResult = applyProfile(workdir, "opencode", v, profilesDir);
    await commitAll(workdir, "profile-applied");
    // User-scope cells: lola installed into <homedir>/.opencode (per-cell $HOME),
    // so the agent must read THAT config dir and run under the same HOME.
    if ((v.install_scope || "project") === "user") {
      profileResult.configDir = join(homedir, ".opencode");
      profileResult.envVar = "OPENCODE_CONFIG_DIR";
    }
    const baseRef = await getCurrentHead(workdir);

    const cleanEnv = { ...process.env };
    cleanEnv[profileResult.envVar] = profileResult.configDir;
    if ((v.install_scope || "project") === "user") cleanEnv.HOME = homedir;
    for (const key of profileResult.clearEnvVars) delete cleanEnv[key];
    log(`clean room: ${profileResult.envVar}=${profileResult.configDir}`);
    // NOTE (user scope): the agent runs with HOME=homedir (a fresh per-cell
    // dir), so host `$HOME`-derived discovery is already neutralized by the HOME
    // override itself; the hostHome-based hide-list then only masks host paths
    // the agent never reads (harmless) plus the shared `/etc/*` leaks (which do
    // apply). The kept-node_modules-to-avoid-reinstall property is a project-
    // scope concern (HOME=hostHome) and is unaffected by the sandbox here.

    const resolvedModel = await resolveModel(
      v.target_model,
      "opencode",
      ["models"],
      cleanEnv,
    );
    if (resolvedModel !== v.target_model) {
      log(`model resolved: ${v.target_model} → ${resolvedModel}`);
    }

    const timeoutS = v.timeout_seconds ?? 600;
    // `--pure` drops externally-cached opencode plugins from the run. Applied
    // unconditionally: it is the cheap partial mitigation that still holds on
    // the fallback path when the mount-namespace sandbox is unavailable.
    const args = [
      "run",
      "--pure",
      "--format",
      "json",
      "-m",
      resolvedModel,
      prompt,
    ];
    const extraArgs = (v.target_extra_args ?? "").trim();
    if (extraArgs) args.splice(1, 0, ...extraArgs.split(/\s+/));

    const profileFlags = JSON.parse(v.profile_flags || "[]");
    if (profileFlags.length) args.push(...profileFlags);

    const profilePermissions = (v.profile_permissions || "").trim();
    if (profilePermissions) {
      args.splice(1, 0, ...profilePermissions.split(/\s+/));
    } else {
      const skipPerms = v.profile_skip_permissions;
      if (
        skipPerms === "True" ||
        skipPerms === "true" ||
        skipPerms === undefined
      ) {
        args.splice(1, 0, "--auto");
      }
    }

    // Config-discovery isolation: run opencode under bwrap, which empties host
    // config/agents/plugins discovery paths. Unavailable → warn once and run
    // unsandboxed (still with --pure). See lib/sandbox.js.
    const sandboxSupported = detectBwrapSupport();
    if (!sandboxSupported) warnNoSandbox(log);
    const wrap = (cliArgs) =>
      wrapAgent({
        cli: "opencode",
        args: cliArgs,
        hostHome,
        configHome,
        emptyJson,
        emptyTxt,
        crossRunTmpfs,
        workRoot,
        workdir,
        supported: sandboxSupported,
      });

    log(`spawning opencode (model=${resolvedModel}, timeout=${timeoutS}s)…`);
    // Log the sandbox status on every cell (not just failures) so a fully
    // unsandboxed suite is visible, not just the first cell's one-time warning.
    log(
      `sandbox: ${sandboxSupported ? "bubblewrap (fs-isolated)" : "disabled (results may be skewed)"}`,
    );
    const wrapped = wrap(args);
    const result = await runAndCapture({
      cmd: wrapped.cmd,
      args: wrapped.args,
      cwd: workdir,
      env: cleanEnv,
      transcriptPath,
      timeoutMs: timeoutS * 1000,
    });
    log(
      `opencode returned (exit=${result.exitCode}, timedOut=${result.timedOut}, duration=${result.durationS.toFixed(1)}s)`,
    );

    const summary = parseOpencodeTranscript(transcriptPath);
    let exitStatus = result.timedOut
      ? "target_timeout"
      : result.exitCode === 0
        ? "success"
        : "target_error";

    // The stderr snippet rides along in the envelope (errorMessage) so the
    // judge persists it to runs.db's error_message column instead of
    // leaving it NULL on a target_error/target_timeout row.
    let errorMessage;
    if (exitStatus !== "success") {
      let transcriptText = "";
      try {
        transcriptText = readFileSync(transcriptPath, "utf8");
      } catch {
        /* transcript not written */
      }
      const stderrSnippet = result.stderr
        .trim()
        .split("\n")
        .slice(-15)
        .join("\n");
      errorMessage = stderrSnippet || undefined;
      const lastTranscriptLine =
        transcriptText.trim().split("\n").slice(-1)[0] || "(empty)";
      log(`!!! exit_status=${exitStatus} — diagnostics:`);
      log(`    command: opencode ${args.join(" ")}`);
      log(`    spawned: ${wrapped.cmd} ${wrapped.args.join(" ")}`);
      log(
        `    sandbox: ${sandboxSupported ? "bubblewrap (fs-isolated)" : "disabled (results may be skewed)"}`,
      );
      const cfgDir = cleanEnv.OPENCODE_CONFIG_DIR || "(unset)";
      log(`    OPENCODE_CONFIG_DIR=${cfgDir}`);
      log(`    resolved model: ${resolvedModel}`);
      log(`    transcript bytes: ${transcriptText.length}`);
      log(`    last transcript line: ${lastTranscriptLine.slice(0, 300)}`);
      if (stderrSnippet) {
        log(`    opencode stderr (last 15 lines):`);
        for (const line of stderrSnippet.split("\n")) log(`      | ${line}`);
      }
    }

    log(
      `captured ${summary.turns} turns, ${summary.toolCalls.length} tool calls, exit_status=${exitStatus}`,
    );

    // Follow-up turns
    let followupMessages = [];
    try {
      followupMessages = JSON.parse(v.followup_messages ?? "[]");
    } catch {
      /* malformed JSON — use empty default */
    }
    if (followupMessages.length > 0 && exitStatus === "success") {
      const { appendFileSync } = await import("node:fs");
      for (let i = 0; i < followupMessages.length; i++) {
        const msg = followupMessages[i];
        log(`sending follow-up ${i + 1}/${followupMessages.length}...`);
        const fuPath = `${transcriptPath}.followup${i}`;
        const fuArgs = [
          "run",
          "--pure",
          "--format",
          "json",
          "--auto",
          "--continue",
          "-m",
          resolvedModel,
          msg,
        ];
        const fuWrapped = wrap(fuArgs);
        const fuResult = await runAndCapture({
          cmd: fuWrapped.cmd,
          args: fuWrapped.args,
          cwd: workdir,
          env: cleanEnv,
          transcriptPath: fuPath,
          timeoutMs: timeoutS * 1000,
        });
        log(
          `follow-up ${i + 1} returned (exit=${fuResult.exitCode}, duration=${fuResult.durationS.toFixed(1)}s)`,
        );
        const fuSummary = parseOpencodeTranscript(fuPath);
        summary.turns += fuSummary.turns;
        summary.toolCalls.push(...fuSummary.toolCalls);
        summary.costUsd += fuSummary.costUsd;
        summary.inputTokens += fuSummary.inputTokens;
        summary.outputTokens += fuSummary.outputTokens;
        summary.cacheReadTokens += fuSummary.cacheReadTokens;
        summary.cacheCreationTokens += fuSummary.cacheCreationTokens;
        try {
          appendFileSync(transcriptPath, "\n" + readFileSync(fuPath, "utf8"));
        } catch {
          /* append failure — non-fatal */
        }
      }
    }

    const diff = await gitDiff(workdir, baseRef);
    log(`done. handing envelope to judge.`);

    return {
      output: JSON.stringify(
        buildEnvelope({
          runId,
          transcriptPath,
          turns: summary.turns,
          toolCalls: summary.toolCalls,
          exitStatus,
          durationS: result.durationS,
          diff,
          costUsd: summary.costUsd,
          inputTokens: summary.inputTokens,
          outputTokens: summary.outputTokens,
          cacheReadTokens: summary.cacheReadTokens,
          cacheCreationTokens: summary.cacheCreationTokens,
          errorMessage,
        }),
      ),
      cost: summary.costUsd,
    };
  }
}

function parseOpencodeTranscript(path) {
  let text;
  try {
    text = readFileSync(path, "utf8");
  } catch {
    return {
      turns: 0,
      toolCalls: [],
      costUsd: 0,
      inputTokens: 0,
      outputTokens: 0,
      cacheReadTokens: 0,
      cacheCreationTokens: 0,
    };
  }
  const lines = text.split("\n").filter((l) => l.trim().length > 0);
  let turns = 0,
    costUsd = 0;
  let inputTokens = 0,
    outputTokens = 0,
    cacheReadTokens = 0,
    cacheCreationTokens = 0;
  const toolCalls = [];
  for (const line of lines) {
    let evt;
    try {
      evt = JSON.parse(line);
    } catch {
      continue;
    }
    if (evt.type === "step_start") turns++;
    if (evt.type === "tool_use") {
      const part = evt.part ?? {};
      toolCalls.push({
        name: part.tool ?? "unknown",
        input: part.state?.input ?? {},
      });
    }
    if (evt.type === "step_finish") {
      const part = evt.part ?? {};
      const tokens = part.tokens ?? {};
      const cache = tokens.cache ?? {};
      inputTokens += tokens.input ?? 0;
      outputTokens += tokens.output ?? 0;
      cacheReadTokens += cache.read ?? 0;
      cacheCreationTokens += cache.write ?? 0;
      costUsd += part.cost ?? 0;
    }
  }
  return {
    turns,
    toolCalls,
    costUsd,
    inputTokens,
    outputTokens,
    cacheReadTokens,
    cacheCreationTokens,
  };
}
