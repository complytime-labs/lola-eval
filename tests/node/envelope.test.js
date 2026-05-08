import { describe, it, expect } from 'vitest';
import { buildEnvelope, validateEnvelope } from '../../src/lola_eval/_data/providers/lib/envelope.js';

describe('buildEnvelope', () => {
  it('produces all required fields', () => {
    const env = buildEnvelope({
      runId: 'r1',
      transcriptPath: '/tmp/t.jsonl',
      turns: 3,
      toolCalls: [{ name: 'Bash', input: {} }],
      exitStatus: 'success',
      durationS: 12.5,
      diff: 'diff --git ...',
      costUsd: 0.01,
    });
    expect(env.run_id).toBe('r1');
    expect(env.transcript_path).toBe('/tmp/t.jsonl');
    expect(env.turns).toBe(3);
    expect(env.tool_calls).toHaveLength(1);
    expect(env.exit_status).toBe('success');
    expect(env.duration_s).toBe(12.5);
    expect(env.diff).toContain('diff --git');
    expect(env.cost_usd).toBe(0.01);
  });

  it('rejects unknown exit_status', () => {
    expect(() => buildEnvelope({
      runId: 'r1', transcriptPath: '/tmp/t', turns: 0, toolCalls: [],
      exitStatus: 'wat', durationS: 0, diff: '', costUsd: 0,
    })).toThrow(/exit_status/);
  });

  it('passes through token counts when supplied', () => {
    const env = buildEnvelope({
      runId: 'r1', transcriptPath: '/tmp/t', turns: 1, toolCalls: [],
      exitStatus: 'success', durationS: 1, diff: '', costUsd: 0.01,
      inputTokens: 143, outputTokens: 4422,
      cacheReadTokens: 1024, cacheCreationTokens: 256,
    });
    expect(env.input_tokens).toBe(143);
    expect(env.output_tokens).toBe(4422);
    expect(env.cache_read_tokens).toBe(1024);
    expect(env.cache_creation_tokens).toBe(256);
  });

  it('omits token fields when caller passes undefined (still snake_cased on the way out)', () => {
    const env = buildEnvelope({
      runId: 'r1', transcriptPath: '/tmp/t', turns: 1, toolCalls: [],
      exitStatus: 'success', durationS: 1, diff: '', costUsd: 0.01,
    });
    // Fields are present in the object shape but undefined: opencode and
    // legacy Claude transcripts may not supply them, and the schema is
    // documented as "may be undefined".
    expect(env.input_tokens).toBeUndefined();
    expect(env.output_tokens).toBeUndefined();
    expect(env.cache_read_tokens).toBeUndefined();
    expect(env.cache_creation_tokens).toBeUndefined();
  });
});

describe('validateEnvelope', () => {
  it('returns null for valid envelope', () => {
    const ok = {
      run_id: 'r1', transcript_path: '/x', turns: 0, tool_calls: [],
      exit_status: 'success', duration_s: 0, diff: '', cost_usd: 0,
    };
    expect(validateEnvelope(ok)).toBeNull();
  });

  it('flags missing field', () => {
    const bad = {
      run_id: 'r1', transcript_path: '/x', turns: 0, tool_calls: [],
      exit_status: 'success', duration_s: 0, diff: '',
      // cost_usd missing
    };
    expect(validateEnvelope(bad)).toMatch(/cost_usd/);
  });

  it('accepts envelopes that omit the optional token fields', () => {
    // Token fields are optional — opencode (and legacy Claude builds) won't
    // populate them. Validation must not fail their absence.
    const ok = {
      run_id: 'r1', transcript_path: '/x', turns: 0, tool_calls: [],
      exit_status: 'success', duration_s: 0, diff: '', cost_usd: 0,
    };
    expect(validateEnvelope(ok)).toBeNull();
  });
});
