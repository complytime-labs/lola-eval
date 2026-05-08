import { describe, it, expect } from 'vitest';
import { sanitizePathComponent } from '../../src/lola_eval/_data/providers/lib/sanitize.js';

describe('sanitizePathComponent', () => {
  it('preserves alphanumeric, dot, dash, underscore', () => {
    expect(sanitizePathComponent('claude-sonnet-4-6')).toBe('claude-sonnet-4-6');
    expect(sanitizePathComponent('case_001.fix-bug')).toBe('case_001.fix-bug');
  });

  it('replaces forward slashes', () => {
    expect(sanitizePathComponent('anthropic/claude-sonnet-4')).toBe('anthropic_claude-sonnet-4');
  });

  it('replaces backslashes', () => {
    expect(sanitizePathComponent('foo\\bar')).toBe('foo_bar');
  });

  it('neutralizes dotdot path traversal', () => {
    expect(sanitizePathComponent('../../etc/passwd')).not.toContain('..');
    expect(sanitizePathComponent('../../etc/passwd')).not.toContain('/');
  });

  it('replaces null bytes and control chars', () => {
    expect(sanitizePathComponent('foo\x00bar')).toBe('foo_bar');
    expect(sanitizePathComponent('foo\nbar')).toBe('foo_bar');
  });

  it('handles empty string', () => {
    expect(sanitizePathComponent('')).toBe('');
  });
});
