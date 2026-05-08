#!/usr/bin/env bash
# reset.sh — reset a task workdir to its pristine starter state.
#
# Usage: reset.sh <task_id> <target_cli> <workdir_abs_path>
#
# Steps:
#   1. Validate inputs (task exists, workdir is under XDG_CACHE_HOME)
#   2. Wipe and recreate workdir from examples/tests/lola-eval/<task_id>/starter/
#   3. Initialise git in the workdir + initial commit (so `git diff HEAD`
#      after the agent runs reflects the agent's changes)
#   4. Best-effort uninstall any lola modules currently installed for
#      target_cli, so packs from prior rows don't leak.
#
# DOES NOT touch: ~/.claude/.credentials.json, ~/.local/share/opencode/auth.json,
# or any user auth state.
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: $0 <task_id> <target_cli> <workdir>" >&2
  exit 64
fi

task_id="$1"
target_cli="$2"
workdir="$3"

case "$target_cli" in
  claude-code|opencode) ;;
  *)
    echo "reset.sh: unknown target_cli '$target_cli'" >&2
    exit 1
    ;;
esac

# Starter discovery resolves in this order:
#   1. $LOLA_TARGET_ROOT/$LOLA_TESTS_DIR/<task_id>/starter (set by the runner)
#   2. $cwd/examples/tests/lola-eval/<task_id>/starter (Phase-1 matrix path)
#   3. <package-data-root>/examples/tests/lola-eval/<task_id>/starter (init scaffold)
package_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
candidates=()
if [[ -n "${LOLA_TARGET_ROOT:-}" ]]; then
  candidates+=("$LOLA_TARGET_ROOT/${LOLA_TESTS_DIR:-tests/lola-eval}/$task_id/starter")
fi
candidates+=("$PWD/examples/tests/lola-eval/$task_id/starter")
candidates+=("$package_root/examples/tests/lola-eval/$task_id/starter")

starter=""
for c in "${candidates[@]}"; do
  if [[ -d "$c" ]]; then
    starter="$c"
    break
  fi
done
if [[ -z "$starter" ]]; then
  echo "reset.sh: task '$task_id' has no starter at any of:" >&2
  for c in "${candidates[@]}"; do echo "  $c" >&2; done
  exit 1
fi

# Safety: workdir must be under XDG_CACHE_HOME (or default ~/.cache).
xdg_cache="${XDG_CACHE_HOME:-$HOME/.cache}"
case "$workdir" in
  "$xdg_cache"/*) ;;
  *)
    echo "reset.sh: refusing to touch $workdir (not under XDG_CACHE_HOME=$xdg_cache)" >&2
    exit 2
    ;;
esac

# Wipe and recreate
rm -rf "$workdir"
mkdir -p "$workdir"
cp -a "$starter/." "$workdir/"

# Initial git state — gives us a clean HEAD to diff against post-run.
(
  cd "$workdir"
  git init --quiet
  git -c user.name="reset" -c user.email="reset@local" add -A
  git -c user.name="reset" -c user.email="reset@local" commit --quiet -m "starter" >/dev/null
)

# Uninstall any lola modules for this target_cli (best-effort).
if command -v lola >/dev/null 2>&1; then
  installed_json="$(lola list --json 2>/dev/null || echo '[]')"
  echo "$installed_json" | python3 -c "
import json, sys, subprocess
try:
    items = json.loads(sys.stdin.read())
except Exception:
    items = []
for item in items:
    name = item.get('name')
    if name:
        subprocess.run(['lola', 'uninstall', name, '-a', '$target_cli'], check=False)
" >/dev/null 2>&1 || true
fi

echo "reset.sh: $workdir reset to $task_id starter"
