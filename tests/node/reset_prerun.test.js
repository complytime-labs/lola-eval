import { describe, it, expect } from 'vitest';
import { mkdtempSync, existsSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { preRun } from '../../src/lola_eval/_data/providers/lib/reset.js';

describe('preRun', () => {
  it('runs the command in the workdir', async () => {
    const wd = mkdtempSync(join(tmpdir(), 'prerun-'));
    await preRun({ workdir: wd, command: 'echo hello > sentinel.txt' });
    expect(existsSync(join(wd, 'sentinel.txt'))).toBe(true);
    expect(readFileSync(join(wd, 'sentinel.txt'), 'utf8').trim()).toBe('hello');
  });

  it('rejects on non-zero exit with a pre_run-labelled error', async () => {
    const wd = mkdtempSync(join(tmpdir(), 'prerun-'));
    await expect(preRun({ workdir: wd, command: 'exit 7' }))
      .rejects.toThrow(/pre_run/);
  });
});
