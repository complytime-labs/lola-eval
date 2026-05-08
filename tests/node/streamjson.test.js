import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { parseTranscript } from '../../src/lola_eval/_data/providers/lib/streamjson.js';

const FIX = resolve(import.meta.dirname, '../fixtures/transcripts');

function load(file) {
  return readFileSync(resolve(FIX, file), 'utf8');
}

describe('parseTranscript', () => {
  it('extracts turn count from result event', () => {
    const summary = parseTranscript(load('claude-success.jsonl'));
    expect(summary.turns).toBe(3);
  });

  it('counts tool calls correctly', () => {
    const summary = parseTranscript(load('claude-success.jsonl'));
    expect(summary.toolCalls).toHaveLength(2);
    expect(summary.toolCalls[0].name).toBe('Bash');
    expect(summary.toolCalls[1].name).toBe('Edit');
  });

  it('captures cost and duration', () => {
    const summary = parseTranscript(load('claude-success.jsonl'));
    expect(summary.costUsd).toBe(0.012);
    expect(summary.durationMs).toBe(18345);
  });

  it('exit reason "success" maps to exit_status=success', () => {
    const summary = parseTranscript(load('claude-success.jsonl'));
    expect(summary.exitStatus).toBe('success');
  });

  it('exit reason "max_turns" maps to exit_status=target_timeout', () => {
    const summary = parseTranscript(load('claude-loop.jsonl'));
    expect(summary.exitStatus).toBe('target_timeout');
  });

  it('detects loop pattern (3+ identical Bash commands in a row)', () => {
    const summary = parseTranscript(load('claude-loop.jsonl'));
    expect(summary.suspectedLoop).toBe(true);
  });

  it('non-loop transcripts are not flagged', () => {
    const summary = parseTranscript(load('claude-success.jsonl'));
    expect(summary.suspectedLoop).toBe(false);
  });

  it('tolerates unknown event types without crashing', () => {
    const lines = [
      '{"type":"system","subtype":"init","model":"x"}',
      '{"type":"NEW_FUTURE_EVENT","payload":{}}',
      '{"type":"result","subtype":"success","total_cost_usd":0,"duration_ms":1,"num_turns":0,"is_error":false}',
    ].join('\n') + '\n';
    const summary = parseTranscript(lines);
    expect(summary.exitStatus).toBe('success');
    expect(summary.unknownEventTypes).toContain('NEW_FUTURE_EVENT');
  });

  it('throws on malformed JSON line', () => {
    expect(() => parseTranscript('not json\n')).toThrow();
  });

  it('handles missing result event (truncated transcript) gracefully', () => {
    const lines = '{"type":"system","subtype":"init","model":"x"}\n';
    const summary = parseTranscript(lines);
    expect(summary.exitStatus).toBe('target_error');
    expect(summary.turns).toBe(0);
  });

  it('extracts token counts from a result event with usage fields', () => {
    const lines = [
      '{"type":"system","subtype":"init","model":"x"}',
      '{"type":"result","subtype":"success","total_cost_usd":0.05,"duration_ms":1000,"num_turns":3,"is_error":false,'
        + '"usage":{"input_tokens":143,"output_tokens":4422,"cache_read_input_tokens":1024,"cache_creation_input_tokens":256}}',
    ].join('\n') + '\n';
    const summary = parseTranscript(lines);
    expect(summary.inputTokens).toBe(143);
    expect(summary.outputTokens).toBe(4422);
    expect(summary.cacheReadTokens).toBe(1024);
    expect(summary.cacheCreationTokens).toBe(256);
  });

  it('returns undefined token counts when result event has no usage block', () => {
    const lines = [
      '{"type":"system","subtype":"init","model":"x"}',
      '{"type":"result","subtype":"success","total_cost_usd":0,"duration_ms":1,"num_turns":0,"is_error":false}',
    ].join('\n') + '\n';
    const summary = parseTranscript(lines);
    expect(summary.inputTokens).toBeUndefined();
    expect(summary.outputTokens).toBeUndefined();
    expect(summary.cacheReadTokens).toBeUndefined();
    expect(summary.cacheCreationTokens).toBeUndefined();
  });

  it('returns undefined token counts when the result event is missing entirely', () => {
    const lines = '{"type":"system","subtype":"init","model":"x"}\n';
    const summary = parseTranscript(lines);
    expect(summary.inputTokens).toBeUndefined();
    expect(summary.outputTokens).toBeUndefined();
    expect(summary.cacheReadTokens).toBeUndefined();
    expect(summary.cacheCreationTokens).toBeUndefined();
  });
});
