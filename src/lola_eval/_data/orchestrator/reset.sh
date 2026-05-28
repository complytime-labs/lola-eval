#!/usr/bin/env bash
# reset.sh — reset a task workdir to its pristine starter state.
#
# Usage: reset.sh <task_id> <target_cli> <workdir_abs_path>
#
# Steps:
#   1. Validate inputs (task exists, workdir is under XDG_CACHE_HOME)
#   2. Wipe and recreate workdir from $LOLA_TEST_SETS_DIR/<task_id>/starter/
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

# Pre-staged starter: if the runner cloned a starter_url into the staging
# directory, STARTER_STAGED_PATH points to it and takes top priority.
if [ -n "${STARTER_STAGED_PATH:-}" ] && [ -d "$STARTER_STAGED_PATH" ]; then
  STARTER="$STARTER_STAGED_PATH"
fi

# Starter discovery resolves in this order:
#   1. $STARTER_STAGED_PATH (set by the runner for cloned starter_url cases)
#   2. $LOLA_TEST_SETS_DIR/<task_id>/starter (set by the runner for local cases)
candidates=()
if [[ -n "${LOLA_TEST_SETS_DIR:-}" ]]; then
  candidates+=("$LOLA_TEST_SETS_DIR/$task_id/starter")
fi

starter="${STARTER:-}"
if [[ -z "$starter" ]]; then
  for c in "${candidates[@]}"; do
    if [[ -d "$c" ]]; then
      starter="$c"
      break
    fi
  done
fi
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
# Remove any existing .git from the starter (e.g. from git clone --local)
# so we get a fresh repo with a single "starter" commit.
(
  cd "$workdir"
  rm -rf .git
  git init --quiet

  # --- gitignore stack (eval integrity, #13) ------------------------
  # A fresh `git init` ignores the system gitignore stack, so artifacts
  # the agent creates (node_modules/, __pycache__/, ...) would land in
  # the post-run `git diff HEAD`, bloating runs.db and contaminating the
  # judge context AND the agent's in-scope corpus. Propagate the global
  # excludesfile, then ALWAYS append a default artifact baseline so the
  # safe scoping holds even when the starter ships no .gitignore.
  global_excludes="$(git config --global core.excludesfile 2>/dev/null || true)"
  if [ -n "$global_excludes" ] && [ -f "$global_excludes" ]; then
    git config core.excludesfile "$global_excludes"
  fi
  {
    echo "node_modules/"
    echo "__pycache__/"
    echo "*.pyc"
    echo ".venv/"
    echo "vendor/"
    echo "dist/"
    echo "*.egg-info/"
    echo ".tsbuildinfo"
  } >> .gitignore
  # Opt-in: LOLA_INCLUDE_IGNORED is a space/newline-separated list of
  # patterns to un-ignore for evals that intentionally target vendored
  # or generated code. Negations are appended last so they win.
  if [ -n "${LOLA_INCLUDE_IGNORED:-}" ]; then
    set -f
    for pat in $LOLA_INCLUDE_IGNORED; do
      echo "!${pat}" >> .gitignore
    done
    set +f
  fi

  git -c user.name="reset" -c user.email="reset@local" add -A
  git -c user.name="reset" -c user.email="reset@local" -c commit.gpgsign=false commit --quiet -m "starter" >/dev/null
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
