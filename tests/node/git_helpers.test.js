import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { commitAll, getCurrentHead, gitDiff } from '../../src/lola_eval/_data/providers/lib/git_helpers.js';

const savedEnv = {};

beforeAll(() => {
  for (const key of ['GIT_CONFIG_GLOBAL', 'GIT_CONFIG_SYSTEM']) {
    savedEnv[key] = process.env[key];
    process.env[key] = '/dev/null';
  }
});

afterAll(() => {
  for (const [key, val] of Object.entries(savedEnv)) {
    if (val === undefined) delete process.env[key];
    else process.env[key] = val;
  }
});

function gitSync(dir, args) {
  return spawnSync('git', args, { cwd: dir, stdio: 'ignore' });
}

function initRepo() {
  const dir = mkdtempSync(join(tmpdir(), 'git-helpers-test-'));
  gitSync(dir, ['init']);
  gitSync(dir, ['config', 'user.name', 'test']);
  gitSync(dir, ['config', 'user.email', 'test@test.com']);
  writeFileSync(join(dir, 'README.md'), 'hello');
  gitSync(dir, ['add', '-A']);
  gitSync(dir, ['commit', '-m', 'initial']);
  return dir;
}

describe('commitAll', () => {
  it('commits staged files', async () => {
    const dir = initRepo();
    writeFileSync(join(dir, 'new.txt'), 'content');
    await commitAll(dir, 'test commit');
    const log = spawnSync('git', ['log', '--oneline'], { cwd: dir, encoding: 'utf8' });
    expect(log.stdout).toContain('test commit');
  });
});

describe('getCurrentHead', () => {
  it('returns HEAD sha', async () => {
    const dir = initRepo();
    const head = await getCurrentHead(dir);
    expect(head).toMatch(/^[0-9a-f]{40}$/);
  });
});

describe('gitDiff', () => {
  it('diffs against a base ref', async () => {
    const dir = initRepo();
    const base = await getCurrentHead(dir);
    writeFileSync(join(dir, 'change.txt'), 'new content');
    gitSync(dir, ['add', '-A']);
    gitSync(dir, ['commit', '-m', 'change']);
    const diff = await gitDiff(dir, base);
    expect(diff).toContain('change.txt');
    expect(diff).toContain('new content');
  });

  it('shows uncommitted changes against base', async () => {
    const dir = initRepo();
    const base = await getCurrentHead(dir);
    writeFileSync(join(dir, 'unstaged.txt'), 'stuff');
    const diff = await gitDiff(dir, base);
    expect(diff).toContain('unstaged.txt');
  });
});
