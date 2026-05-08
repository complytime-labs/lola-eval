/**
 * Promptfoo custom provider: drives `opencode run --format json`.
 * Same contract as claude_code_provider but invokes opencode.
 */
import { randomUUID } from 'node:crypto';
import { spawn } from 'node:child_process';
import { mkdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join, resolve as resolvePath } from 'node:path';

import { runAndCapture } from './lib/spawn.js';
import { buildEnvelope } from './lib/envelope.js';
import { reset, installPack } from './lib/reset.js';
import { sanitizePathComponent } from './lib/sanitize.js';

// See claude_code_provider for rationale.
const _PROVIDER_DIR = dirname(fileURLToPath(import.meta.url));
const RESET_SH = resolvePath(_PROVIDER_DIR, '..', 'orchestrator', 'reset.sh');
const INSTALL_PACK_SH = resolvePath(_PROVIDER_DIR, '..', 'orchestrator', 'install_pack.sh');

function xdgStateRoot() {
  const root = process.env.XDG_STATE_HOME ?? join(process.env.HOME, '.local/state');
  return join(root, 'lola-eval');
}
function xdgCacheRoot() {
  const root = process.env.XDG_CACHE_HOME ?? join(process.env.HOME, '.cache');
  return join(root, 'lola-eval');
}

export default class OpencodeProvider {
  constructor(options = {}) { this.options = options; }
  id() { return 'opencode'; }

  async callApi(prompt, context) {
    const v = context.vars;
    const runId = randomUUID();
    // Workdir is unique per (task, model, pack, runId) so concurrent runs
    // cannot race on the same filesystem path. See claude_code_provider
    // for rationale. runId is a UUID; no sanitization needed.
    const packSlug = sanitizePathComponent(String(v.pack_id));
    const taskSlug = sanitizePathComponent(String(v.task_id));
    const modelSlug = sanitizePathComponent(String(v.target_model));
    const workdir = resolvePath(join(xdgCacheRoot(), 'work', taskSlug, modelSlug, packSlug, runId));
    const transcriptPath = join(xdgStateRoot(), 'transcripts', `${runId}.jsonl`);
    mkdirSync(join(xdgStateRoot(), 'transcripts'), { recursive: true });

    const log = (msg) => process.stderr.write(`[opencode-provider] ${msg}\n`);
    log(`run_id=${runId.slice(0, 8)} task=${v.task_id} pack=${v.pack_id} model=${v.target_model}`);
    log(`transcript: ${transcriptPath}  (tail -f to watch)`);

    try {
      log(`reset workdir → ${workdir}`);
      await reset({ taskId: v.task_id, targetCli: 'opencode', workdir, scriptPath: RESET_SH });
      log(`install pack ${v.pack_id} (workdir-scoped) ...`);
      await installPack({ packId: v.pack_id, targetCli: 'opencode', workdir, scriptPath: INSTALL_PACK_SH });
      await commitAll(workdir, 'pack-installed');
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
        output: JSON.stringify(buildEnvelope({
          runId, transcriptPath, turns: 0, toolCalls: [],
          exitStatus: 'setup_error', durationS: 0, diff: '', costUsd: 0,
          errorMessage: err && err.message ? err.message : String(err),
        })),
      };
    }

    const timeoutS = v.timeout_seconds ?? 600;
    const args = [
      'run',
      '--format', 'json',
      '-m', v.target_model,
      prompt,
    ];

    log(`spawning opencode (model=${v.target_model}, timeout=${timeoutS}s)…`);
    const result = await runAndCapture({
      cmd: 'opencode',
      args,
      cwd: workdir,
      env: process.env,
      transcriptPath,
      timeoutMs: timeoutS * 1000,
    });
    log(`opencode returned (exit=${result.exitCode}, timedOut=${result.timedOut}, duration=${result.durationS.toFixed(1)}s)`);

    const summary = parseOpencodeTranscript(transcriptPath);
    let exitStatus = result.timedOut
      ? 'target_timeout'
      : (result.exitCode === 0 ? 'success' : 'target_error');

    if (exitStatus !== 'success') {
      let transcriptText = '';
      try { transcriptText = readFileSync(transcriptPath, 'utf8'); } catch {}
      const stderrSnippet = result.stderr.trim().split('\n').slice(-15).join('\n');
      const lastTranscriptLine = transcriptText.trim().split('\n').slice(-1)[0] || '(empty)';
      log(`!!! exit_status=${exitStatus} — diagnostics:`);
      log(`    transcript bytes: ${transcriptText.length}`);
      log(`    last transcript line: ${lastTranscriptLine.slice(0, 300)}`);
      if (stderrSnippet) {
        log(`    opencode stderr (last 15 lines):`);
        for (const line of stderrSnippet.split('\n')) log(`      | ${line}`);
      }
    }

    log(`captured ${summary.turns} turns, ${summary.toolCalls.length} tool calls, exit_status=${exitStatus}`);
    const diff = await gitDiff(workdir);
    log(`done. handing envelope to judge.`);

    return {
      output: JSON.stringify(buildEnvelope({
        runId, transcriptPath,
        turns: summary.turns,
        toolCalls: summary.toolCalls,
        exitStatus,
        durationS: result.durationS,
        diff,
        costUsd: summary.costUsd,
        // opencode's JSON output structure is not yet reverse-engineered for
        // token usage. Leave these undefined until a real run yields a
        // sample to parse — coercing to 0 would corrupt aggregates.
        inputTokens: undefined,
        outputTokens: undefined,
        cacheReadTokens: undefined,
        cacheCreationTokens: undefined,
      })),
      cost: summary.costUsd,
    };
  }
}

function parseOpencodeTranscript(path) {
  let text = '';
  try { text = readFileSync(path, 'utf8'); } catch { return { turns: 0, toolCalls: [], costUsd: 0 }; }
  const lines = text.split('\n').filter(l => l.trim().length > 0);
  let turns = 0, costUsd = 0;
  const toolCalls = [];
  for (const line of lines) {
    let evt; try { evt = JSON.parse(line); } catch { continue; }
    if (evt.type === 'message' && evt.role === 'assistant') turns++;
    if (evt.type === 'tool_call') toolCalls.push({ name: evt.name, input: evt.input ?? {} });
    if (evt.type === 'end' && evt.cost_usd) costUsd = evt.cost_usd;
  }
  return { turns, toolCalls, costUsd };
}

async function commitAll(workdir, message) {
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
      'commit', '--quiet', '--allow-empty', '-m', message,
    ], { stdio: 'ignore' });
    child.on('close', () => resolve());
    child.on('error', () => resolve());
  });
}

async function gitDiff(workdir) {
  // See claude_code_provider.gitDiff for rationale: stage first so untracked
  // files (REVIEW.md etc.) appear in the diff sent to the judge.
  await new Promise(resolve => {
    const child = spawn('git', ['-C', workdir, 'add', '-A'], { stdio: 'ignore' });
    child.on('close', () => resolve());
    child.on('error', () => resolve());
  });
  return await new Promise(resolve => {
    const child = spawn('git', ['-C', workdir, 'diff', '--cached', '--no-color', 'HEAD'], { stdio: ['ignore', 'pipe', 'ignore'] });
    const chunks = [];
    child.stdout.on('data', d => chunks.push(d));
    child.on('close', () => resolve(Buffer.concat(chunks).toString('utf8')));
    child.on('error', () => resolve(''));
  });
}
