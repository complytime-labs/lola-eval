/**
 * Shared logic for the claude_code_interactive and opencode_interactive
 * providers. Spawns the Python orchestrator that drives the multi-turn
 * dialog, then parses its envelope output.
 *
 * The orchestrator (src/lola_eval/_data/interactive/orchestrator.py) does
 * the heavy lifting: subprocess management, turn-loop, transcript file
 * writing, git diff. This helper assembles its argv from the row vars
 * and shells out.
 */
import { randomUUID } from 'node:crypto';
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

import { reset, installPack } from './reset.js';
import { sanitizePathComponent } from './sanitize.js';

export function xdgStateRoot() {
  const x = process.env.XDG_STATE_HOME;
  const root = x ? x : join(process.env.HOME, '.local/state');
  return join(root, 'lola-eval');
}

export function xdgCacheRoot() {
  const x = process.env.XDG_CACHE_HOME;
  const root = x ? x : join(process.env.HOME, '.cache');
  return join(root, 'lola-eval');
}

/**
 * Build the argv that runs the target agent in single-turn print mode.
 * The orchestrator pipes the conversation history (as a single prompt
 * string) into the subprocess's stdin, so each invocation is stateless.
 */
function targetCommand(targetCli, targetModel) {
  if (targetCli === 'claude-code') {
    // claude --print reads from stdin when no positional prompt is given.
    return ['claude', '--print', '--model', targetModel,
            '--permission-mode', 'bypassPermissions'];
  }
  if (targetCli === 'opencode') {
    // opencode run -m <model> reads its prompt from stdin similarly.
    return ['opencode', 'run', '-m', targetModel];
  }
  throw new Error(`unknown target_cli: ${targetCli}`);
}

/**
 * Build the argv that runs the simulated user (a tools-disabled persona).
 * For opencode we use --agent simulated-user (the user is expected to
 * have configured this agent in their opencode config; we document the
 * one-line opencode agent definition in the walkthrough).
 *
 * For claude-code we ask for a system prompt that pins the persona via
 * --append-system-prompt; the persona body is also sent on stdin as part
 * of the conversation history, which keeps things consistent.
 */
function simulatedUserCommand(simCli, simModel) {
  if (simCli === 'claude-code') {
    return ['claude', '--print', '--model', simModel,
            '--permission-mode', 'bypassPermissions'];
  }
  if (simCli === 'opencode') {
    return ['opencode', 'run', '-m', simModel, '--agent', 'simulated-user'];
  }
  throw new Error(`unknown simulated_user_cli: ${simCli}`);
}

function spawnAndCapture(cmd, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, {
      stdio: ['ignore', 'pipe', 'pipe'],
      env: process.env,
    });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (d) => { stdout += d.toString(); });
    child.stderr.on('data', (d) => { stderr += d.toString(); });
    child.on('error', (err) => reject(err));
    child.on('close', (code) => {
      resolve({ code, stdout, stderr });
    });
  });
}

/**
 * Top-level handler shared by both interactive providers. Sets up the
 * workdir, writes per-row tmp files for the persona/prompt, invokes the
 * Python orchestrator, and returns the envelope as a promptfoo result.
 */
export async function runInteractiveRow({
  targetCli,
  resetSh,
  installPackSh,
  vars,
  log,
}) {
  const v = vars;
  const runId = randomUUID();
  // Workdir includes runId so concurrent runs of the same cell don't race
  // on the same filesystem path (reset.sh's `cp -a` collides otherwise).
  // runId is a UUID; no sanitization needed.
  const packSlug = sanitizePathComponent(String(v.pack_id));
  const taskSlug = sanitizePathComponent(String(v.task_id));
  const modelSlug = sanitizePathComponent(String(v.target_model));
  const workdir = join(xdgCacheRoot(), 'work', taskSlug, modelSlug, packSlug, runId);
  const transcriptDir = join(xdgStateRoot(), 'transcripts');
  mkdirSync(transcriptDir, { recursive: true });
  const transcriptPath = join(transcriptDir, `${runId}.jsonl`);

  log(`run_id=${runId.slice(0, 8)} task=${v.task_id} pack=${v.pack_id} model=${v.target_model}`);
  log(`mode=interactive max_turns=${v.max_turns} simulated_user=${v.simulated_user_cli}/${v.simulated_user_model}`);
  log(`transcript: ${transcriptPath}  (tail -f to watch)`);

  try {
    await reset({ taskId: v.task_id, targetCli, workdir, scriptPath: resetSh });
    await installPack({ packId: v.pack_id, targetCli, workdir, scriptPath: installPackSh });
    await commitAll(workdir, 'pack-installed');
  } catch (err) {
    // install_pack.sh / reset.sh already streamed the actionable text
    // to stderr. The full message lives in the envelope.error_message
    // and is reprinted once in the final "Failures:" block.
    log(`setup_error (see message above)`);
    // See claude_code_provider.js for why `error:` is omitted: it lets
    // the judge run, which persists a setup_error row to runs.db with
    // the actionable error_message instead of leaving the runner to
    // diagnose "no_run_produced".
    return {
      output: JSON.stringify({
        run_id: runId,
        transcript_path: transcriptPath,
        turns: 0,
        tool_calls: [],
        exit_status: 'setup_error',
        duration_s: 0,
        diff: '',
        cost_usd: 0,
        error_message: String(err.message || err),
      }),
    };
  }

  // Persona + prompt go through tmpfiles so the orchestrator can read them
  // off disk. Avoids argv length limits for verbose personas.
  const tmp = join(tmpdir(), `lola-eval-interactive-${runId}`);
  mkdirSync(tmp, { recursive: true });
  const personaPath = join(tmp, 'simulated_user.md');
  const promptPath = join(tmp, 'prompt.md');
  writeFileSync(personaPath, v.simulated_user_persona || '');
  writeFileSync(promptPath, v.prompt || '');

  const targetCmd = targetCommand(targetCli, v.target_model);
  const simCmd = simulatedUserCommand(v.simulated_user_cli, v.simulated_user_model);
  const python = process.env.LOLA_EVAL_PYTHON || 'python3';
  const orchestratorArgs = [
    '-m', 'lola_eval._data.interactive.orchestrator',
    '--target-command', JSON.stringify(targetCmd),
    '--simulated-user-command', JSON.stringify(simCmd),
    '--persona-file', personaPath,
    '--prompt-file', promptPath,
    '--max-turns', String(v.max_turns ?? 5),
    '--per-turn-timeout-s', String(v.timeout_seconds ?? 600),
    '--transcript-path', transcriptPath,
    '--workdir', workdir,
    '--run-id', runId,
  ];

  log(`spawning orchestrator: ${python} ${orchestratorArgs.join(' ')}`);
  const result = await spawnAndCapture(python, orchestratorArgs);

  if (result.code !== 0) {
    log(`orchestrator exited ${result.code}; stderr (last 20 lines):`);
    const lines = result.stderr.trim().split('\n').slice(-20);
    for (const line of lines) log(`  | ${line}`);
    return {
      output: JSON.stringify({
        run_id: runId,
        transcript_path: transcriptPath,
        turns: 0,
        tool_calls: [],
        exit_status: 'target_error',
        duration_s: 0,
        diff: '',
        cost_usd: 0,
        error_message: `orchestrator exited ${result.code}: ${result.stderr.trim().slice(-500)}`,
      }),
      error: `orchestrator exited ${result.code}`,
    };
  }

  // Orchestrator's stdout is the envelope JSON. Pass it through.
  let envelope;
  try {
    envelope = JSON.parse(result.stdout);
  } catch (err) {
    log(`orchestrator stdout was not valid JSON: ${err.message}`);
    log(`stdout (first 500 chars): ${result.stdout.slice(0, 500)}`);
    return {
      output: JSON.stringify({
        run_id: runId,
        transcript_path: transcriptPath,
        turns: 0,
        tool_calls: [],
        exit_status: 'target_error',
        duration_s: 0,
        diff: '',
        cost_usd: 0,
        error_message: `orchestrator stdout not JSON: ${err.message}`,
      }),
      error: `orchestrator stdout not JSON`,
    };
  }
  log(`orchestrator returned: turns=${envelope.turns} exit=${envelope.exit_status}`);
  return { output: JSON.stringify(envelope), tokenUsage: undefined };
}

function commitAll(workdir, message) {
  return new Promise((resolveOuter) => {
    const add = spawn('git', ['-C', workdir, 'add', '-A'], { stdio: 'ignore' });
    add.on('close', () => {
      const commit = spawn('git', [
        '-C', workdir,
        '-c', 'user.name=harness',
        '-c', 'user.email=harness@local',
        'commit', '--quiet', '--allow-empty', '-m', message,
      ], { stdio: 'ignore' });
      commit.on('close', () => resolveOuter());
      commit.on('error', () => resolveOuter());
    });
    add.on('error', () => resolveOuter());
  });
}
