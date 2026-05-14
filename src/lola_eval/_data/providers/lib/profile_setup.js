import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join, isAbsolute } from 'node:path';
import { tmpdir } from 'node:os';
import { loadToolRegistry } from './tool_registry.js';

/**
 * Apply a profile's setup directives to a workdir before agent invocation.
 *
 * Directives (from vars.profile_setup_json):
 *   replace_config - path (relative to profilesDir) whose config_dir contents replace workdir's
 *   remove         - list of paths (relative to workdir) to delete
 *   copy           - list of {src, dst, mode, tag} file operations
 *   flags          - reserved for future use
 *
 * @param {string} workdir        - working directory to modify
 * @param {string} targetCli      - CLI key in tool registry (e.g. 'claude-code')
 * @param {object} vars           - variables object containing profile_setup_json
 * @param {string} profilesDir    - base directory for resolving relative paths in directives
 * @returns {{ configDir: string, envVar: string, clearEnvVars: string[] }}
 */
export function applyProfile(workdir, targetCli, vars, profilesDir) {
  const raw = vars.profile_setup_json || '{}';
  const setup = JSON.parse(raw);
  if (!setup || (!setup.replace_config && !setup.remove?.length && !setup.copy?.length)) {
    return legacyCleanRoom(targetCli);
  }

  const registry = loadToolRegistry();
  const tool = registry[targetCli];
  if (!tool) throw new Error(`unknown target CLI in tool registry: ${targetCli}`);

  if (setup.replace_config) {
    const configDirPath = join(workdir, tool.config_dir);
    rmSync(configDirPath, { recursive: true, force: true });
    const templatePath = _resolveTemplatePath(setup.replace_config, profilesDir);
    const templateConfigDir = join(templatePath, tool.config_dir);
    const source = existsSync(templateConfigDir) ? templateConfigDir : templatePath;
    mkdirSync(dirname(configDirPath), { recursive: true });
    cpSync(source, configDirPath, { recursive: true });
  }

  for (const p of setup.remove || []) {
    rmSync(join(workdir, p), { force: true, recursive: true });
  }

  for (const c of setup.copy || []) {
    const srcPath = isAbsolute(c.src) ? c.src : join(profilesDir, c.src);
    const dstPath = join(workdir, c.dst);
    const content = readFileSync(srcPath, 'utf8');

    if (c.mode === 'append') {
      _appendWithBookends(dstPath, content, c.tag || 'default');
    } else {
      mkdirSync(dirname(dstPath), { recursive: true });
      writeFileSync(dstPath, content);
    }
  }

  return {
    configDir: join(workdir, tool.config_dir),
    envVar: tool.config_env,
    clearEnvVars: tool.clear_env || [],
  };
}

/**
 * Create a minimal clean-room config directory for a target CLI.
 * Used as fallback when no profile_setup_json directives are present.
 *
 * @param {string} targetCli - CLI key in tool registry
 * @returns {{ configDir: string, envVar: string, clearEnvVars: string[] }}
 */
export function legacyCleanRoom(targetCli) {
  const registry = loadToolRegistry();
  const tool = registry[targetCli];
  if (!tool) throw new Error(`unknown target CLI in tool registry: ${targetCli}`);

  const configDir = mkdtempSync(join(tmpdir(), `lola-eval-${targetCli}-config-`));
  if (targetCli === 'claude-code') {
    writeFileSync(join(configDir, 'settings.json'), JSON.stringify({ enabledPlugins: {} }));
  } else if (targetCli === 'opencode') {
    writeFileSync(join(configDir, 'opencode.jsonc'), JSON.stringify({
      "$schema": "https://opencode.ai/config.json",
      plugin: [],
      permission: { "*": "allow" },
    }));
  }

  return {
    configDir,
    envVar: tool.config_env,
    clearEnvVars: tool.clear_env || [],
  };
}

function _resolveTemplatePath(configRef, profilesDir) {
  if (isAbsolute(configRef)) return configRef;
  if (profilesDir) {
    const local = join(profilesDir, configRef);
    if (existsSync(local)) return local;
  }
  throw new Error(`replace_config path not found: ${configRef} (checked ${profilesDir || 'no profiles_dir'})`);
}

function _appendWithBookends(filePath, content, tag) {
  const beginMarker = `<!-- BEGIN ${tag} -->`;
  const endMarker = `<!-- END ${tag} -->`;
  const section = `${beginMarker}\n${content}\n${endMarker}`;

  if (!existsSync(filePath)) {
    mkdirSync(dirname(filePath), { recursive: true });
    writeFileSync(filePath, section + '\n');
    return;
  }

  let existing = readFileSync(filePath, 'utf8');
  const beginIdx = existing.indexOf(beginMarker);
  const endIdx = existing.indexOf(endMarker);

  if (beginIdx !== -1 && endIdx !== -1) {
    existing = existing.slice(0, beginIdx) + section + existing.slice(endIdx + endMarker.length);
    writeFileSync(filePath, existing);
  } else {
    writeFileSync(filePath, existing.trimEnd() + '\n' + section + '\n');
  }
}
