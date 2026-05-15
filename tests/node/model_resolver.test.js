import { describe, it, expect, beforeEach } from 'vitest';
import { resolveModel, _clearCache, _parseModelList } from '../../src/lola_eval/_data/providers/lib/model_resolver.js';

const VERTEX_MODELS = [
  'google-vertex-anthropic/claude-sonnet-4-5@20250929',
  'google-vertex-anthropic/claude-sonnet-4-5@20250514',
  'google-vertex-anthropic/claude-haiku-4-5@20251001',
  'google-vertex-anthropic/claude-opus-4@20250918',
].join('\n');

const DIRECT_MODELS = [
  'anthropic/claude-sonnet-4-5',
  'anthropic/claude-haiku-4-5',
  'anthropic/claude-opus-4',
].join('\n');

describe('_parseModelList', () => {
  it('filters blank lines and headers', () => {
    const input = '# Available models\n\ngoogle-vertex-anthropic/claude-sonnet-4-5@20250929\n  \n';
    expect(_parseModelList(input)).toEqual([
      'google-vertex-anthropic/claude-sonnet-4-5@20250929',
    ]);
  });

  it('skips lines without a slash', () => {
    const input = 'claude-sonnet-4-5\ngoogle-vertex-anthropic/claude-sonnet-4-5@20250929\n';
    expect(_parseModelList(input)).toEqual([
      'google-vertex-anthropic/claude-sonnet-4-5@20250929',
    ]);
  });
});

describe('resolveModel', () => {
  beforeEach(() => _clearCache());

  it('passes through already-qualified model (contains /)', async () => {
    const result = await resolveModel('google-vertex-anthropic/claude-sonnet-4-5@20250929', 'unused', [], {});
    expect(result).toBe('google-vertex-anthropic/claude-sonnet-4-5@20250929');
  });

  it('passes through versioned model (contains @)', async () => {
    const result = await resolveModel('claude-sonnet-4-5@20250929', 'unused', [], {});
    expect(result).toBe('claude-sonnet-4-5@20250929');
  });

  it('resolves "sonnet" to latest Vertex sonnet', async () => {
    _clearCache();
    // Seed the cache directly to avoid shelling out
    const models = _parseModelList(VERTEX_MODELS);
    // Manually populate cache by calling with a fake cmd that will fail,
    // then inject. Instead, let's use the exported _clearCache and test
    // the parse + resolve logic by pre-seeding.
    // We'll use a helper approach: call resolveModel with a cmd that
    // echoes our model list.
    const result = await resolveModel('sonnet', 'echo', [VERTEX_MODELS], {});
    expect(result).toBe('google-vertex-anthropic/claude-sonnet-4-5@20250929');
  });

  it('resolves "haiku" to Vertex haiku', async () => {
    const result = await resolveModel('haiku', 'echo', [VERTEX_MODELS], {});
    expect(result).toBe('google-vertex-anthropic/claude-haiku-4-5@20251001');
  });

  it('resolves "opus" to Vertex opus', async () => {
    const result = await resolveModel('opus', 'echo', [VERTEX_MODELS], {});
    expect(result).toBe('google-vertex-anthropic/claude-opus-4@20250918');
  });

  it('resolves exact core name "claude-sonnet-4-5"', async () => {
    const result = await resolveModel('claude-sonnet-4-5', 'echo', [VERTEX_MODELS], {});
    expect(result).toBe('google-vertex-anthropic/claude-sonnet-4-5@20250929');
  });

  it('prefers latest version when multiple exist', async () => {
    // 20250929 > 20250514 lexicographically
    const result = await resolveModel('sonnet', 'echo', [VERTEX_MODELS], {});
    expect(result).toBe('google-vertex-anthropic/claude-sonnet-4-5@20250929');
  });

  it('works with direct API models (no @version)', async () => {
    const result = await resolveModel('sonnet', 'echo', [DIRECT_MODELS], {});
    expect(result).toBe('anthropic/claude-sonnet-4-5');
  });

  it('returns original alias on no match', async () => {
    const result = await resolveModel('nonexistent', 'echo', [VERTEX_MODELS], {});
    expect(result).toBe('nonexistent');
  });

  it('returns original alias when cmd fails', async () => {
    const result = await resolveModel('sonnet', 'false', [], {});
    expect(result).toBe('sonnet');
  });

  it('caches model list per cmd', async () => {
    const r1 = await resolveModel('sonnet', 'echo', [VERTEX_MODELS], {});
    // Second call with same cmd uses cache (even though args differ,
    // cache key is cmd only — the model list for a given CLI doesn't change)
    const r2 = await resolveModel('haiku', 'echo', ['should-not-parse'], {});
    expect(r1).toBe('google-vertex-anthropic/claude-sonnet-4-5@20250929');
    expect(r2).toBe('google-vertex-anthropic/claude-haiku-4-5@20251001');
  });
});
