/**
 * Shared git helpers for eval harness providers.
 *
 * commitAll  — stage everything and commit (no-op-safe).
 * getCurrentHead — return the full SHA of HEAD.
 * gitDiff — stage everything and diff against a known base ref.
 */
import { spawn } from 'node:child_process';

export async function commitAll(workdir, message) {
  await _run('git', ['-C', workdir, 'add', '-A']);
  await _run('git', [
    '-C', workdir,
    '-c', 'user.name=harness',
    '-c', 'user.email=harness@local',
    '-c', 'commit.gpgsign=false',
    'commit', '--quiet', '--allow-empty', '-m', message,
  ]);
}

export async function getCurrentHead(workdir) {
  return (await _capture('git', ['-C', workdir, 'rev-parse', 'HEAD'])).trim();
}

export async function gitDiff(workdir, baseRef) {
  await _run('git', ['-C', workdir, 'add', '-A']);
  return await _capture('git', ['-C', workdir, 'diff', '--no-color', baseRef]);
}

function _run(cmd, args) {
  return new Promise(resolve => {
    const child = spawn(cmd, args, { stdio: 'ignore' });
    child.on('close', () => resolve());
    child.on('error', () => resolve());
  });
}

function _capture(cmd, args) {
  return new Promise(resolve => {
    const child = spawn(cmd, args, { stdio: ['ignore', 'pipe', 'ignore'] });
    const chunks = [];
    child.stdout.on('data', d => chunks.push(d));
    child.on('close', () => resolve(Buffer.concat(chunks).toString('utf8')));
    child.on('error', () => resolve(''));
  });
}
