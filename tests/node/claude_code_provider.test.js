import { describe, it, expect } from 'vitest';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import ClaudeCodeProvider from '../../src/lola_eval/_data/providers/claude_code_provider.js';

const REPO = resolve(import.meta.dirname, '../..');

function setupEnv(mode) {
  const xdgState = mkdtempSync(join(tmpdir(), 'state-'));
  const xdgCache = mkdtempSync(join(tmpdir(), 'cache-'));
  return {
    XDG_STATE_HOME: xdgState,
    XDG_CACHE_HOME: xdgCache,
    PATH: `${REPO}/tests/fixtures/fake-claude:${process.env.PATH}`,
    HOME: process.env.HOME,
    FAKE_MODE: mode,
  };
}

describe('ClaudeCodeProvider', () => {
  it('success path returns envelope with exit_status=success', async () => {
    const env = setupEnv('success');
    Object.assign(process.env, env);
    const p = new ClaudeCodeProvider({});
    const r = await p.callApi('fix the bug', {
      vars: {
        target_cli: 'claude-code', target_model: 'claude-sonnet-4-6',
        pack_id: 'none', task_id: 'case-001-fix-bug',
        task_version: '1', rubric_version: '1',
        exec_mode: 'autonomous', invocation: 'passive',
        judge_cli: 'opencode', judge_model: 'claude-sonnet-4-6',
        timeout_seconds: 30,
      },
    });
    const env2 = JSON.parse(r.output);
    expect(env2.exit_status).toBe('success');
    expect(env2.turns).toBe(3);
    expect(env2.run_id).toMatch(/[0-9a-f-]+/);
  });

  it('crash path returns envelope with exit_status=target_error', async () => {
    const env = setupEnv('crash');
    Object.assign(process.env, env);
    const p = new ClaudeCodeProvider({});
    const r = await p.callApi('fix the bug', {
      vars: {
        target_cli: 'claude-code', target_model: 'claude-sonnet-4-6',
        pack_id: 'none', task_id: 'case-001-fix-bug',
        task_version: '1', rubric_version: '1',
        exec_mode: 'autonomous', invocation: 'passive',
        judge_cli: 'opencode', judge_model: 'claude-sonnet-4-6',
        timeout_seconds: 30,
      },
    });
    const env2 = JSON.parse(r.output);
    expect(env2.exit_status).toBe('target_error');
  });
});
