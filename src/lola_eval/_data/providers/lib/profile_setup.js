import {
  cpSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { dirname, join, isAbsolute } from "node:path";
import { tmpdir } from "node:os";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { loadToolRegistry } from "./tool_registry.js";

const _LIB_DIR = dirname(fileURLToPath(import.meta.url));
const SCAFFOLD_SH = join(
  _LIB_DIR,
  "..",
  "..",
  "orchestrator",
  "scaffold_module.sh",
);

/**
 * Apply a profile's setup directives to a workdir before agent invocation.
 *
 * Directives (from vars.profile_setup_json):
 *   replace_config - path (relative to profilesDir) whose config_dir contents replace workdir's
 *   remove         - list of paths (relative to workdir) to delete
 *   copy           - list of {src, dst, mode, tag} file operations
 *   install_modules - list of paths (abs, or relative to profilesDir) to local
 *                     lola modules whose skills/commands/agents are scaffolded
 *                     into the workdir's project config (#3)
 *   flags          - reserved for future use
 *
 * @param {string} workdir        - working directory to modify
 * @param {string} targetCli      - CLI key in tool registry (e.g. 'claude-code')
 * @param {object} vars           - variables object containing profile_setup_json
 * @param {string} profilesDir    - base directory for resolving relative paths in directives
 * @returns {{ configDir: string, envVar: string, clearEnvVars: string[] }}
 */
export function applyProfile(workdir, targetCli, vars, profilesDir) {
  const raw = vars.profile_setup_json || "{}";
  const setup = JSON.parse(raw);

  // install_modules: scaffold each listed local lola module into the workdir's
  // project config (#3). Project-level .claude/skills etc. are discovered
  // regardless of the clean-room config dir, so this works alongside
  // legacyCleanRoom. Each module is scaffolded independently; a failure names
  // the offending module path.
  for (const mod of setup?.install_modules || []) {
    const moduleDir = isAbsolute(mod) ? mod : join(profilesDir, mod);
    try {
      execFileSync("bash", [SCAFFOLD_SH, moduleDir, workdir, targetCli],
        { stdio: ["ignore", "inherit", "inherit"] });
    } catch (err) {
      throw new Error(`install_modules scaffold failed for '${moduleDir}': ${err.message}`, { cause: err });
    }
  }

  if (
    !setup ||
    (!setup.replace_config && !setup.remove?.length && !setup.copy?.length)
  ) {
    return legacyCleanRoom(targetCli);
  }

  const registry = loadToolRegistry();
  const tool = registry[targetCli];
  if (!tool)
    throw new Error(`unknown target CLI in tool registry: ${targetCli}`);

  if (setup.replace_config) {
    const configDirPath = join(workdir, tool.config_dir);
    rmSync(configDirPath, { recursive: true, force: true });
    const templatePath = _resolveTemplatePath(
      setup.replace_config,
      profilesDir,
    );
    const templateConfigDir = join(templatePath, tool.config_dir);
    const source = existsSync(templateConfigDir)
      ? templateConfigDir
      : templatePath;
    mkdirSync(dirname(configDirPath), { recursive: true });
    cpSync(source, configDirPath, { recursive: true });
  }

  for (const p of setup.remove || []) {
    rmSync(join(workdir, p), { force: true, recursive: true });
  }

  for (const c of setup.copy || []) {
    const srcPath = isAbsolute(c.src) ? c.src : join(profilesDir, c.src);
    const dstPath = join(workdir, c.dst);
    const content = readFileSync(srcPath, "utf8");

    if (c.mode === "append") {
      _appendWithBookends(dstPath, content, c.tag || "default");
    } else {
      mkdirSync(dirname(dstPath), { recursive: true });
      writeFileSync(dstPath, content);
    }
  }

  const finalConfigDir = join(workdir, tool.config_dir);
  _preserveClaudeAuth(finalConfigDir, targetCli);
  return {
    configDir: finalConfigDir,
    envVar: tool.config_env,
    clearEnvVars: tool.clear_env || [],
  };
}

/**
 * Carry the host's claude-code subscription auth token into a clean-room
 * config dir. Subscription auth lives in `<host config>/.credentials.json`;
 * the clean room is a fresh dir, so without this the isolated `claude`
 * reports "Not logged in". Only the auth token is copied — settings and
 * plugins stay isolated. No-op for non-claude-code targets and when no
 * host credentials file exists (e.g. API-key auth via env).
 *
 * @param {string} configDir - clean-room config dir to seed
 * @param {string} targetCli - CLI key
 */
function _preserveClaudeAuth(configDir, targetCli) {
  if (targetCli !== "claude-code") return;
  const hostConfig =
    process.env.CLAUDE_CONFIG_DIR || join(process.env.HOME || "", ".claude");
  const src = join(hostConfig, ".credentials.json");
  if (existsSync(src)) {
    mkdirSync(configDir, { recursive: true });
    const dst = join(configDir, ".credentials.json");
    cpSync(src, dst);
    // Audit signal: subscription-auth credential just crossed a trust
    // boundary from $HOME into the eval clean-room. Without this log, a
    // user grepping stderr for "credentials" finds nothing and can't
    // tell whether the documented behavior actually fired.
    process.stderr.write(
      `[profile_setup] subscription-auth: copied ${src} -> ${dst}\n`,
    );
  }
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
  if (!tool)
    throw new Error(`unknown target CLI in tool registry: ${targetCli}`);

  const configDir = mkdtempSync(
    join(tmpdir(), `lola-eval-${targetCli}-config-`),
  );
  if (targetCli === "claude-code") {
    writeFileSync(
      join(configDir, "settings.json"),
      JSON.stringify({ enabledPlugins: {} }),
    );
  } else if (targetCli === "opencode") {
    writeFileSync(
      join(configDir, "opencode.jsonc"),
      JSON.stringify({
        $schema: "https://opencode.ai/config.json",
        plugin: [],
        permission: { "*": "allow" },
      }),
    );
  }
  _preserveClaudeAuth(configDir, targetCli);

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
  throw new Error(
    `replace_config path not found: ${configRef} (checked ${profilesDir || "no profiles_dir"})`,
  );
}

function _appendWithBookends(filePath, content, tag) {
  const beginMarker = `<!-- BEGIN ${tag} -->`;
  const endMarker = `<!-- END ${tag} -->`;
  const section = `${beginMarker}\n${content}\n${endMarker}`;

  if (!existsSync(filePath)) {
    mkdirSync(dirname(filePath), { recursive: true });
    writeFileSync(filePath, section + "\n");
    return;
  }

  let existing = readFileSync(filePath, "utf8");
  const beginIdx = existing.indexOf(beginMarker);
  const endIdx = existing.indexOf(endMarker);

  if (beginIdx !== -1 && endIdx !== -1) {
    existing =
      existing.slice(0, beginIdx) +
      section +
      existing.slice(endIdx + endMarker.length);
    writeFileSync(filePath, existing);
  } else {
    writeFileSync(filePath, existing.trimEnd() + "\n" + section + "\n");
  }
}
