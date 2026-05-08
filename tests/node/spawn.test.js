import { describe, it, expect } from 'vitest';
import { mkdtempSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { runAndCapture } from '../../src/lola_eval/_data/providers/lib/spawn.js';

function tmp() { return mkdtempSync(join(tmpdir(), 'spawn-test-')); }

describe('runAndCapture', () => {
  it('captures stdout to transcript file', async () => {
    const dir = tmp();
    const path = join(dir, 't.jsonl');
    const r = await runAndCapture({
      cmd: 'sh', args: ['-c', 'echo hello; echo world'],
      transcriptPath: path, timeoutMs: 5000,
    });
    expect(r.exitCode).toBe(0);
    expect(readFileSync(path, 'utf8')).toBe('hello\nworld\n');
    expect(r.timedOut).toBe(false);
  });

  it('reports non-zero exit', async () => {
    const dir = tmp();
    const path = join(dir, 't.jsonl');
    const r = await runAndCapture({
      cmd: 'sh', args: ['-c', 'exit 17'],
      transcriptPath: path, timeoutMs: 5000,
    });
    expect(r.exitCode).toBe(17);
  });

  it('kills process on timeout and flags timedOut', async () => {
    const dir = tmp();
    const path = join(dir, 't.jsonl');
    const r = await runAndCapture({
      cmd: 'sh', args: ['-c', 'sleep 5'],
      transcriptPath: path, timeoutMs: 200,
    });
    expect(r.timedOut).toBe(true);
    expect(r.exitCode).not.toBe(0);
  });

  it('captures stderr separately from transcript', async () => {
    const dir = tmp();
    const path = join(dir, 't.jsonl');
    const r = await runAndCapture({
      cmd: 'sh', args: ['-c', 'echo out; echo err >&2'],
      transcriptPath: path, timeoutMs: 5000,
    });
    expect(readFileSync(path, 'utf8')).toBe('out\n');
    expect(r.stderr).toBe('err\n');
  });

  it('reports duration in seconds', async () => {
    const dir = tmp();
    const path = join(dir, 't.jsonl');
    const r = await runAndCapture({
      cmd: 'sh', args: ['-c', 'sleep 0.1'],
      transcriptPath: path, timeoutMs: 5000,
    });
    expect(r.durationS).toBeGreaterThan(0.05);
    expect(r.durationS).toBeLessThan(2.0);
  });
});
