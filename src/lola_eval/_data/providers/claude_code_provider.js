/**
 * Promptfoo custom provider: drives `claude -p` with stream-json.
 * See spec Section 5 for the contract.
 */
import { randomUUID } from 'node:crypto';
import { spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import { dirname, join, resolve as resolvePath } from 'node:path';

import { runAndCapture } from './lib/spawn.js';
import { parseTranscript } from './lib/streamjson.js';
import { buildEnvelope } from './lib/envelope.js';
import { reset, installPack } from './lib/reset.js';
import { sanitizePathComponent } from './lib/sanitize.js';

// Provider may be loaded from any cwd (matrix path, runner workspace, or
// from tests). Resolve orchestrator scripts relative to the provider file
// itself so reset.sh/install_pack.sh are always findable.
const _PROVIDER_DIR = dirname(fileURLToPath(import.meta.url));
const RESET_SH = resolvePath(_PROVIDER_DIR, '..', 'orchestrator', 'reset.sh');
const INSTALL_PACK_SH = resolvePath(_PROVIDER_DIR, '..', 'orchestrator', 'install_pack.sh');

function xdgStateRoot() {
  const x = process.env.XDG_STATE_HOME;
  const root = x ? x : join(process.env.HOME, '.local/state');
  return join(root, 'lola-eval');
}

function xdgCacheRoot() {
  const x = process.env.XDG_CACHE_HOME;
  const root = x ? x : join(process.env.HOME, '.cache');
  return join(root, 'lola-eval');
}

export default class ClaudeCodeProvider {
  constructor(options = {}) { this.options = options; }
  id() { return 'claude-code'; }

  async callApi(prompt, context) {
    const v = context.vars;
    const runId = randomUUID();
    // Workdir is unique per (task, model, pack, runId) so concurrent runs
    // of the same cell cannot race on the same filesystem path. Without
    // the runId suffix, two parallel `lola-eval test` invocations of the
    // same matrix would collide in reset.sh's `cp -a` step. runId is a
    // UUID; no sanitization needed.
    const packSlug = sanitizePathComponent(String(v.pack_id));
    const taskSlug = sanitizePathComponent(String(v.task_id));
    const modelSlug = sanitizePathComponent(String(v.target_model));
    const workdir = resolvePath(join(xdgCacheRoot(), 'work', taskSlug, modelSlug, packSlug, runId));
    const transcriptPath = join(xdgStateRoot(), 'transcripts', `${runId}.jsonl`);
    mkdirSync(join(xdgStateRoot(), 'transcripts'), { recursive: true });

    const log = (msg) => process.stderr.write(`[claude-code-provider] ${msg}\n`);
    log(`run_id=${runId.slice(0, 8)} task=${v.task_id} pack=${v.pack_id} model=${v.target_model}`);
    log(`transcript: ${transcriptPath}  (tail -f to watch)`);

    try {
      log(`reset workdir → ${workdir}`);
      await reset({ taskId: v.task_id, targetCli: 'claude-code', workdir, scriptPath: RESET_SH });
      log(`install pack ${v.pack_id} (workdir-scoped) ...`);
      await installPack({ packId: v.pack_id, targetCli: 'claude-code', workdir, scriptPath: INSTALL_PACK_SH });
      // Commit pack-installed files as a separate commit so the agent's
      // diff (computed via `git diff HEAD` after the agent runs) only
      // contains the agent's changes, not the pack scaffolding.
      await commitAll(workdir, 'pack-installed');
    } catch (err) {
      // install_pack.sh and reset.sh stream their own diagnostics to
      // stderr; repeating the full err message here would be a third
      // copy on the user's terminal. The runs.db row carries the full
      // text, and the final "Failures:" block reprints it once. Keep
      // this log to a breadcrumb only.
      log(`setup_error (see message above)`);
      // Deliberately NOT setting `error:` here: doing so causes promptfoo
      // to skip the python assertion (the judge), so no row lands in
      // runs.db and the runner falls back to a generic "no_run_produced"
      // diagnosis that hides the real cause. By returning only `output`
      // with exit_status=setup_error AND the captured error_message, the
      // judge IS invoked, persists a proper setup_error row to runs.db,
      // and the runner surfaces the actionable message to the user.
      return {
        output: JSON.stringify(buildEnvelope({
          runId, transcriptPath, turns: 0, toolCalls: [],
          exitStatus: 'setup_error', durationS: 0, diff: '', costUsd: 0,
          errorMessage: err && err.message ? err.message : String(err),
        })),
      };
    }

    // Clean room: isolated config dir so the user's plugins, settings, and
    // CLAUDE.md don't bleed into the run. Auth flows through env vars
    // (GOOGLE_APPLICATION_CREDENTIALS, CLAUDE_CODE_USE_VERTEX, etc.) which
    // are preserved. Only files explicitly added by the test case (via
    // target_extra_args like --plugin-dir) will be loaded.
    const cleanConfigDir = mkdtempSync(join(tmpdir(), 'lola-eval-claude-config-'));
    writeFileSync(join(cleanConfigDir, 'settings.json'), JSON.stringify({ enabledPlugins: {} }));
    const cleanEnv = { ...process.env };
    cleanEnv.CLAUDE_CONFIG_DIR = cleanConfigDir;
    delete cleanEnv.CLAUDE_CODE_PLUGIN_SEED_DIR;
    log(`clean room: CLAUDE_CONFIG_DIR=${cleanConfigDir}`);

    const budget = v.budget_usd ?? 10.00;
    const timeoutS = v.timeout_seconds ?? 600;
    const args = [
      '-p', prompt,
      '--model', v.target_model,
      '--output-format', 'stream-json',
      '--include-hook-events',
      '--max-budget-usd', String(budget),
      '--permission-mode', 'bypassPermissions',
      '--add-dir', workdir,
      '--verbose',
    ];
    const sysPromptFile = (v.system_prompt_file ?? '').trim();
    if (sysPromptFile) args.push('--append-system-prompt-file', sysPromptFile);
    const extraArgs = (v.target_extra_args ?? '').trim();
    if (extraArgs) args.push(...extraArgs.split(/\s+/));

    log(`spawning claude (model=${v.target_model}, budget=$${budget}, timeout=${timeoutS}s)…`);
    const result = await runAndCapture({
      cmd: 'claude',
      args,
      cwd: workdir,
      env: cleanEnv,
      transcriptPath,
      timeoutMs: timeoutS * 1000,
    });
    log(`claude returned (exit=${result.exitCode}, timedOut=${result.timedOut}, duration=${result.durationS.toFixed(1)}s)`);

    let transcriptText = '';
    try {
      transcriptText = readFileSync(transcriptPath, 'utf8');
    } catch (err) {
      log(`could not read transcript at ${transcriptPath}: ${err.message}`);
    }

    let summary;
    try {
      summary = parseTranscript(transcriptText);
    } catch (err) {
      log(`failed to parse transcript: ${err.message}`);
      summary = { turns: 0, toolCalls: [], costUsd: 0, durationMs: 0, exitStatus: 'target_error', suspectedLoop: false, unknownEventTypes: [] };
    }

    let exitStatus = summary.exitStatus;
    if (result.timedOut) exitStatus = 'target_timeout';
    else if (result.exitCode !== 0 && exitStatus === 'success') exitStatus = 'target_error';

    // When something went wrong, surface what we know — don't make the user
    // dig through transcript files post-mortem.
    if (exitStatus !== 'success') {
      const stderrSnippet = result.stderr.trim().split('\n').slice(-15).join('\n');
      const lastTranscriptLine = transcriptText.trim().split('\n').slice(-1)[0] || '(empty)';
      log(`!!! exit_status=${exitStatus} — diagnostics:`);
      log(`    transcript bytes: ${transcriptText.length}`);
      log(`    last transcript line: ${lastTranscriptLine.slice(0, 300)}`);
      if (stderrSnippet) {
        log(`    claude stderr (last 15 lines):`);
        for (const line of stderrSnippet.split('\n')) log(`      | ${line}`);
      }
    }

    log(`captured ${summary.turns} turns, ${summary.toolCalls.length} tool calls, exit_status=${exitStatus}`);

    // Follow-up turns: send canned messages after the initial run succeeds.
    let followupMessages = [];
    try { followupMessages = JSON.parse(v.followup_messages ?? '[]'); } catch {}
    if (followupMessages.length > 0 && exitStatus === 'success') {
      const { appendFileSync } = await import('node:fs');
      for (let i = 0; i < followupMessages.length; i++) {
        const msg = followupMessages[i];
        log(`sending follow-up ${i + 1}/${followupMessages.length}...`);
        const fuPath = `${transcriptPath}.followup${i}`;
        const fuArgs = [
          '-p', msg,
          '--continue',
          '--model', v.target_model,
          '--output-format', 'stream-json',
          '--max-budget-usd', String(Math.max(1, budget - summary.costUsd)),
          '--permission-mode', 'bypassPermissions',
          '--verbose',
        ];
        if (extraArgs) fuArgs.push(...extraArgs.split(/\s+/));
        const fuResult = await runAndCapture({
          cmd: 'claude', args: fuArgs, cwd: workdir,
          env: cleanEnv, transcriptPath: fuPath, timeoutMs: timeoutS * 1000,
        });
        log(`follow-up ${i + 1} returned (exit=${fuResult.exitCode}, duration=${fuResult.durationS.toFixed(1)}s)`);
        let fuText = '';
        try { fuText = readFileSync(fuPath, 'utf8'); } catch {}
        try {
          const fuSummary = parseTranscript(fuText);
          summary.turns += fuSummary.turns;
          summary.toolCalls.push(...fuSummary.toolCalls);
          summary.costUsd += fuSummary.costUsd;
          summary.inputTokens = (summary.inputTokens || 0) + (fuSummary.inputTokens || 0);
          summary.outputTokens = (summary.outputTokens || 0) + (fuSummary.outputTokens || 0);
          summary.cacheReadTokens = (summary.cacheReadTokens || 0) + (fuSummary.cacheReadTokens || 0);
          summary.cacheCreationTokens = (summary.cacheCreationTokens || 0) + (fuSummary.cacheCreationTokens || 0);
        } catch {}
        try { appendFileSync(transcriptPath, '\n' + fuText); } catch {}
      }
    }

    log(`diffing workdir...`);
    const diff = await gitDiff(workdir);
    log(`done. handing envelope to judge.`);

    try { rmSync(cleanConfigDir, { recursive: true, force: true }); } catch {}

    return {
      output: JSON.stringify(buildEnvelope({
        runId, transcriptPath,
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
      })),
      tokenUsage: undefined,
      cost: summary.costUsd,
    };
  }
}

async function commitAll(workdir, message) {
  // Stage and commit any pending changes (e.g., lola-installed pack files)
  // so they don't appear in the agent's later diff. No-op if nothing changed.
  await new Promise(resolve => {
    const child = spawn('git', ['-C', workdir, 'add', '-A'], { stdio: 'ignore' });
    child.on('close', () => resolve());
    child.on('error', () => resolve());
  });
  await new Promise(resolve => {
    const child = spawn('git', [
      '-C', workdir,
      '-c', 'user.name=harness',
      '-c', 'user.email=harness@local',
      '-c', 'commit.gpgsign=false',
      'commit', '--quiet', '--allow-empty', '-m', message,
    ], { stdio: 'ignore' });
    child.on('close', () => resolve());
    child.on('error', () => resolve());
  });
}

async function gitDiff(workdir) {
  // Stage everything so untracked additions appear.
  await new Promise(resolve => {
    const child = spawn('git', ['-C', workdir, 'add', '-A'], { stdio: 'ignore' });
    child.on('close', () => resolve());
    child.on('error', () => resolve());
  });
  // Diff against the pack-installed commit (the baseline before the agent ran),
  // not HEAD. If the agent committed its work, HEAD already contains the fix
  // and `diff --cached HEAD` would be empty.
  const baseRef = await new Promise(resolve => {
    const child = spawn('git', ['-C', workdir, 'log', '--all', '--format=%H', '--reverse'], { stdio: ['ignore', 'pipe', 'ignore'] });
    const chunks = [];
    child.stdout.on('data', d => chunks.push(d));
    child.on('close', () => {
      const lines = Buffer.concat(chunks).toString('utf8').trim().split('\n');
      // Second commit is pack-installed; fall back to first (starter) if only one exists.
      resolve(lines.length >= 2 ? lines[1] : lines[0] || 'HEAD');
    });
    child.on('error', () => resolve('HEAD'));
  });
  return await new Promise(resolve => {
    const child = spawn('git', ['-C', workdir, 'diff', '--no-color', baseRef], { stdio: ['ignore', 'pipe', 'ignore'] });
    const chunks = [];
    child.stdout.on('data', d => chunks.push(d));
    child.on('close', () => resolve(Buffer.concat(chunks).toString('utf8')));
    child.on('error', () => resolve(''));
  });
}
