import { describe, it, expect } from 'vitest';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { commitAll, getCurrentHead, gitDiff } from '../../src/lola_eval/_data/providers/lib/git_helpers.js';

function initRepo() {
  const dir = mkdtempSync(join(tmpdir(), 'git-helpers-test-'));
  spawnSync('git', ['init'], { cwd: dir, stdio: 'ignore' });
  spawnSync('git', ['config', 'user.name', 'test'], { cwd: dir, stdio: 'ignore' });
  spawnSync('git', ['config', 'user.email', 'test@test.com'], { cwd: dir, stdio: 'ignore' });
  writeFileSync(join(dir, 'README.md'), 'hello');
  spawnSync('git', ['add', '-A'], { cwd: dir, stdio: 'ignore' });
  spawnSync('git', ['commit', '-m', 'initial'], { cwd: dir, stdio: 'ignore' });
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
    spawnSync('git', ['add', '-A'], { cwd: dir, stdio: 'ignore' });
    spawnSync('git', ['commit', '-m', 'change'], { cwd: dir, stdio: 'ignore' });
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
