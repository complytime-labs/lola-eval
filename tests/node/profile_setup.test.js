import { describe, it, expect } from 'vitest';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { applyProfile, legacyCleanRoom } from '../../src/lola_eval/_data/providers/lib/profile_setup.js';

function makeWorkdir() {
  const dir = mkdtempSync(join(tmpdir(), 'profile-setup-test-'));
  mkdirSync(join(dir, '.claude'), { recursive: true });
  writeFileSync(join(dir, '.claude', 'settings.json'), '{"old": true}');
  writeFileSync(join(dir, 'AGENTS.md'), '# Original agents');
  writeFileSync(join(dir, 'CLAUDE.md'), '# Original claude');
  return dir;
}

describe('applyProfile', () => {
  it('replaces config directory', () => {
    const workdir = makeWorkdir();
    const profilesDir = mkdtempSync(join(tmpdir(), 'profiles-'));
    mkdirSync(join(profilesDir, 'configs', 'claude-bare', '.claude'), { recursive: true });
    writeFileSync(
      join(profilesDir, 'configs', 'claude-bare', '.claude', 'settings.json'),
      '{"enabledPlugins": {}}'
    );

    const result = applyProfile(workdir, 'claude-code', {
      profile_setup_json: JSON.stringify({
        replace_config: 'configs/claude-bare',
        remove: [],
        copy: [],
        flags: [],
      }),
    }, profilesDir);

    const settings = JSON.parse(readFileSync(join(workdir, '.claude', 'settings.json'), 'utf8'));
    expect(settings).toEqual({ enabledPlugins: {} });
    expect(result.envVar).toBe('CLAUDE_CONFIG_DIR');
  });

  it('removes listed files', () => {
    const workdir = makeWorkdir();
    const profilesDir = mkdtempSync(join(tmpdir(), 'profiles-'));

    applyProfile(workdir, 'claude-code', {
      profile_setup_json: JSON.stringify({
        replace_config: '',
        remove: ['AGENTS.md', 'CLAUDE.md'],
        copy: [],
        flags: [],
      }),
    }, profilesDir);

    expect(existsSync(join(workdir, 'AGENTS.md'))).toBe(false);
    expect(existsSync(join(workdir, 'CLAUDE.md'))).toBe(false);
  });

  it('copies files in replace mode', () => {
    const workdir = makeWorkdir();
    const profilesDir = mkdtempSync(join(tmpdir(), 'profiles-'));
    writeFileSync(join(profilesDir, 'custom.md'), '# Custom content');

    applyProfile(workdir, 'claude-code', {
      profile_setup_json: JSON.stringify({
        replace_config: '',
        remove: [],
        copy: [{ src: 'custom.md', dst: 'AGENTS.md', mode: 'replace', tag: '' }],
        flags: [],
      }),
    }, profilesDir);

    expect(readFileSync(join(workdir, 'AGENTS.md'), 'utf8')).toBe('# Custom content');
  });

  it('appends with bookend markers', () => {
    const workdir = makeWorkdir();
    const profilesDir = mkdtempSync(join(tmpdir(), 'profiles-'));
    writeFileSync(join(profilesDir, 'extra.md'), 'Extra content');

    applyProfile(workdir, 'claude-code', {
      profile_setup_json: JSON.stringify({
        replace_config: '',
        remove: [],
        copy: [{ src: 'extra.md', dst: 'AGENTS.md', mode: 'append', tag: 'my-section' }],
        flags: [],
      }),
    }, profilesDir);

    const content = readFileSync(join(workdir, 'AGENTS.md'), 'utf8');
    expect(content).toContain('# Original agents');
    expect(content).toContain('<!-- BEGIN my-section -->');
    expect(content).toContain('Extra content');
    expect(content).toContain('<!-- END my-section -->');
  });

  it('replaces existing bookend section on re-apply', () => {
    const workdir = makeWorkdir();
    writeFileSync(join(workdir, 'AGENTS.md'),
      '# Top\n<!-- BEGIN x -->\nold\n<!-- END x -->\n# Bottom');
    const profilesDir = mkdtempSync(join(tmpdir(), 'profiles-'));
    writeFileSync(join(profilesDir, 'new.md'), 'new content');

    applyProfile(workdir, 'claude-code', {
      profile_setup_json: JSON.stringify({
        replace_config: '',
        remove: [],
        copy: [{ src: 'new.md', dst: 'AGENTS.md', mode: 'append', tag: 'x' }],
        flags: [],
      }),
    }, profilesDir);

    const content = readFileSync(join(workdir, 'AGENTS.md'), 'utf8');
    expect(content).toContain('# Top');
    expect(content).toContain('new content');
    expect(content).not.toContain('old');
    expect(content).toContain('# Bottom');
  });

  it('returns legacy clean room when no profile setup', () => {
    const result = legacyCleanRoom('claude-code');
    expect(existsSync(result.configDir)).toBe(true);
    expect(result.envVar).toBe('CLAUDE_CONFIG_DIR');
  });
});
