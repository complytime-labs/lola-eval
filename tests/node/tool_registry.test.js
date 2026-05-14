import { describe, it, expect } from 'vitest';
import { loadToolRegistry } from '../../src/lola_eval/_data/providers/lib/tool_registry.js';

describe('tool_registry', () => {
  it('loads claude-code entry', () => {
    const reg = loadToolRegistry();
    expect(reg['claude-code']).toBeDefined();
    expect(reg['claude-code'].config_dir).toBe('.claude');
    expect(reg['claude-code'].config_env).toBe('CLAUDE_CONFIG_DIR');
  });

  it('loads opencode entry', () => {
    const reg = loadToolRegistry();
    expect(reg['opencode']).toBeDefined();
    expect(reg['opencode'].config_dir).toBe('.opencode');
  });

  it('every entry has required keys', () => {
    const reg = loadToolRegistry();
    const required = ['config_dir', 'config_env', 'clear_env', 'permission_flag'];
    for (const [name, entry] of Object.entries(reg)) {
      for (const key of required) {
        expect(entry).toHaveProperty(key);
      }
    }
  });
});
