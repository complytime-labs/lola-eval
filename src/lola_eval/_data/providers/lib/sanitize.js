/**
 * sanitizePathComponent — coerce a string into a safe single-segment
 * filesystem path component.
 *
 * Replaces anything outside [a-zA-Z0-9._-] with `_`, then collapses
 * any literal '..' substring to '_' so dotdot path traversal is
 * impossible regardless of how the caller resolves the result.
 */
export function sanitizePathComponent(s) {
  if (typeof s !== 'string') return '';
  let out = s.replace(/[^a-zA-Z0-9._-]/g, '_');
  while (out.includes('..')) {
    out = out.replace('..', '_');
  }
  return out;
}
