"""Keep version-specific strings in documentation in sync with a bump.

`uv version` and `npm version` already update pyproject/uv.lock and
package.json/package-lock.json. The docs carry the version in two scoped
shapes that no standard tool knows about; this module rewrites exactly those
and nothing else, so an unrelated occurrence of the same number is never
touched.
"""

from __future__ import annotations

import sys
from pathlib import Path


def sync_version_in_text(old: str, new: str, text: str) -> str:
    """Return ``text`` with the project version updated from ``old`` to ``new``.

    Only two anchored patterns are rewritten:
    - the RPM artifact filename ``lola-eval-<old>-`` and
    - the CLI version line ``lola-eval <old>``.

    Every other occurrence of ``old`` is left untouched.
    """
    return text.replace(f"lola-eval-{old}-", f"lola-eval-{new}-").replace(
        f"lola-eval {old}", f"lola-eval {new}"
    )


def main(argv: list[str]) -> int:
    """``version_docs <old> <new> <file>...`` — rewrite each file in place.

    Prints the files that changed (or a no-change notice) and returns 0.
    """
    if len(argv) < 3:
        print("usage: version_docs <old> <new> <file>...", file=sys.stderr)
        return 2
    old, new, files = argv[0], argv[1], argv[2:]
    changed: list[str] = []
    for name in files:
        path = Path(name)
        text = path.read_text()
        updated = sync_version_in_text(old, new, text)
        if updated != text:
            path.write_text(updated)
            changed.append(name)
    if changed:
        print(f"version_docs: updated {', '.join(changed)}")
    else:
        print("version_docs: no doc changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
