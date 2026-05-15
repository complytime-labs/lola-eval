import { execFileSync } from 'node:child_process';

const _cache = new Map();

export function _clearCache() { _cache.clear(); }

export function _parseModelList(stdout) {
  return stdout
    .split('\n')
    .map(l => l.trim())
    .filter(l => l.length > 0 && !l.startsWith('#') && l.includes('/'));
}

function coreName(modelId) {
  const afterSlash = modelId.includes('/') ? modelId.split('/').pop() : modelId;
  return afterSlash.split('@')[0];
}

function versionKey(modelId) {
  const at = modelId.indexOf('@');
  return at === -1 ? '' : modelId.slice(at + 1);
}

export async function resolveModel(alias, cmd, args, env) {
  if (alias.includes('/') || alias.includes('@')) return alias;

  const cacheKey = cmd;
  if (!_cache.has(cacheKey)) {
    try {
      const stdout = execFileSync(cmd, args, {
        env,
        timeout: 15_000,
        encoding: 'utf8',
        stdio: ['ignore', 'pipe', 'ignore'],
      });
      _cache.set(cacheKey, _parseModelList(stdout));
    } catch {
      return alias;
    }
  }

  const models = _cache.get(cacheKey);
  const lower = alias.toLowerCase();

  const exact = models.filter(m => coreName(m).toLowerCase() === lower);
  if (exact.length > 0) {
    exact.sort((a, b) => versionKey(b).localeCompare(versionKey(a)));
    return exact[0];
  }

  const fuzzy = models.filter(m => coreName(m).toLowerCase().includes(lower));
  if (fuzzy.length > 0) {
    fuzzy.sort((a, b) => versionKey(b).localeCompare(versionKey(a)));
    return fuzzy[0];
  }

  return alias;
}
