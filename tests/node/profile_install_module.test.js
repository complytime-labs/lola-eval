import { describe, it, expect } from 'vitest';
import { mkdtempSync, mkdirSync, writeFileSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { applyProfile } from '../../src/lola_eval/_data/providers/lib/profile_setup.js';

describe('applyProfile install_module', () => {
  it('scaffolds a local module into the workdir project config', () => {
    const root = mkdtempSync(join(tmpdir(), 'instmod-'));
    const moduleDir = join(root, 'mymod');
    mkdirSync(join(moduleDir, 'skills', 'greet'), { recursive: true });
    writeFileSync(join(moduleDir, 'skills', 'greet', 'SKILL.md'), '# greet');
    const workdir = join(root, 'wd');
    mkdirSync(workdir, { recursive: true });

    applyProfile(workdir, 'claude-code',
      { profile_setup_json: JSON.stringify({ install_module: moduleDir }) },
      root);

    expect(existsSync(join(workdir, '.claude', 'skills', 'greet', 'SKILL.md'))).toBe(true);
  });
});
