import { readFileSync } from 'node:fs';
import { dirname, resolve as resolvePath } from 'node:path';
import { fileURLToPath } from 'node:url';

const _LIB_DIR = dirname(fileURLToPath(import.meta.url));

let _cached = null;

export function loadToolRegistry() {
  if (_cached) return _cached;
  const jsonPath = resolvePath(_LIB_DIR, '..', '..', 'tools.json');
  const text = readFileSync(jsonPath, 'utf8');
  _cached = JSON.parse(text);
  return _cached;
}
