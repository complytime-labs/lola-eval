#!/usr/bin/env bash
# install_pack.sh — install a lola pack into a target CLI.
#
# Usage: install_pack.sh <pack_id> <target_cli> [workdir]
#
# Reserved pack_ids (Mode 1):
#   "none"          — baseline pass. Leave the workdir pack-free (no-op).
#   "project" /     — Mode 1 install. When $LOLA_MODULE_SOURCE is set, install
#   "project-user"    that local module via `lola mod add` + `lola install`
#                     (--scope from $LOLA_INSTALL_SCOPE: project | user), then
#                     restore the target's instruction file so no injected
#                     context leaks. When $LOLA_MODULE_SOURCE is unset, fall
#                     back to scaffolding any in-repo .lola/modules/ the
#                     starter ships. Runs under a per-cell $HOME set by the
#                     caller, isolating the lola registry and user-scope writes.
#
# Any other pack_id is treated as an external pack identifier (Mode 2)
# and installed via `lola install`. A trailing `@<ref>` is stripped
# before invoking `lola`. When `workdir` is given, install at project
# scope inside that directory; otherwise at user scope.
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "usage: $0 <pack_id> <target_cli> [workdir]" >&2
  exit 64
fi

pack_id="$1"
target_cli="$2"
workdir="${3:-}"

case "$target_cli" in
  claude-code|opencode) ;;
  *)
    echo "install_pack.sh: unknown target_cli '$target_cli'" >&2
    exit 1
    ;;
esac

if [[ "$pack_id" == "none" ]]; then
  exit 0
fi

if [[ "$pack_id" == "project" || "$pack_id" == "project-user" ]]; then
  # Mode 1: install the project's module under test via lola, then restore
  # the target's instruction file so the eval tests CLEAN behavior (no
  # context-file injection). Runs under a per-cell $HOME set by the caller,
  # which isolates the lola registry and any user-scope writes.
  scope="${LOLA_INSTALL_SCOPE:-project}"
  src="${LOLA_MODULE_SOURCE:-}"

  if [[ -z "$src" ]]; then
    # Back-compat: no LOLA_MODULE_SOURCE set. If the project under evaluation
    # ships in-repo lola modules under .lola/modules/, scaffold them into the
    # target's config so the agent can discover the skills/commands/agents.
    if [[ -n "$workdir" && -d "$workdir/.lola/modules" ]]; then
      script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
      for mod in "$workdir/.lola/modules"/*/; do
        [[ -d "$mod" ]] || continue
        echo "install_pack.sh: scaffolding project module $(basename "$mod") for $target_cli" >&2
        bash "$script_dir/scaffold_module.sh" "${mod%/}" "$workdir" "$target_cli"
      done
    fi
    exit 0
  fi
  if ! command -v lola >/dev/null 2>&1; then
    echo "install_pack.sh: lola CLI not on PATH (needed for module_source install)" >&2
    exit 2
  fi
  name="$(basename "$src")"

  # Resolve the instruction file lola will inject, per (target, scope).
  case "$target_cli:$scope" in
    claude-code:project) ifile="$workdir/CLAUDE.md" ;;
    claude-code:user)    ifile="$HOME/.claude/CLAUDE.md" ;;
    opencode:project)    ifile="$workdir/AGENTS.md" ;;
    opencode:user)       ifile="$HOME/AGENTS.md" ;;
    *) echo "install_pack.sh: unsupported target:scope '$target_cli:$scope'" >&2; exit 1 ;;
  esac

  # Snapshot the instruction file (or note its absence). Trap guarantees the
  # temp file is removed even if a later lola call fails under set -e.
  snap="$(mktemp)"
  install_log="$(mktemp)"
  trap 'rm -f "$snap" "$install_log"' EXIT
  existed=0
  if [[ -f "$ifile" ]]; then cp -a "$ifile" "$snap"; existed=1; fi

  # Register (best-effort, mirroring the Mode-2 branch) and install. Capture
  # lola's output so a failure is diagnosable, not a bare "exited 1".
  lola mod add "$src" -n "$name" </dev/null >/dev/null 2>&1 || true
  set +e
  if [[ "$scope" == "user" ]]; then
    lola install "$name" -a "$target_cli" --scope user -f </dev/null >"$install_log" 2>&1
  else
    lola install "$name" -a "$target_cli" --scope project "$workdir" -f </dev/null >"$install_log" 2>&1
  fi
  rc=$?
  set -e
  cat "$install_log" >&2

  # Clean up after lola: restore the instruction file to its pre-install state
  # ALWAYS — even when the install failed — so no injected context can leak.
  if [[ "$existed" -eq 1 ]]; then cp -a "$snap" "$ifile"; else rm -f "$ifile"; fi

  if [[ "$rc" -ne 0 ]]; then
    last_line="$(grep -v '^[[:space:]]*$' "$install_log" | tail -n1 || true)"
    echo "install_pack.sh: FAILED pack=$pack_id target=$target_cli scope=$scope: ${last_line:-lola exited $rc}" >&2
    exit "$rc"
  fi
  exit 0
fi

if ! command -v lola >/dev/null 2>&1; then
  echo "install_pack.sh: lola CLI not on PATH" >&2
  exit 2
fi

# A pack_id like `name@sha` from lola-eval.yaml is just the module name as
# `lola install` cares about — strip a trailing @<ref> if present.
module_name="${pack_id%%@*}"

# Path-based pack_ids (starting with / or ./) are local modules that need
# to be registered via `lola mod add` before they can be installed. The
# module name for `lola install` is derived from the directory basename.
if [[ "$module_name" == /* || "$module_name" == ./* || "$module_name" == ../* || "$module_name" == "." ]]; then
  pack_path="$(cd "$(dirname "$module_name")" 2>/dev/null && pwd)/$(basename "$module_name")"
  if [[ "$module_name" == "." ]]; then
    pack_path="$(pwd)"
  fi
  if [[ ! -d "$pack_path" ]]; then
    echo "install_pack.sh: pack path '$pack_path' does not exist" >&2
    exit 3
  fi
  derived_name="$(basename "$pack_path")"
  echo "install_pack.sh: registering local module '$derived_name' from $pack_path" >&2
  lola mod add "$pack_path" -n "$derived_name" 2>&1 || true
  module_name="$derived_name"
fi

# Run `lola install` and capture its output for diagnostics. We deliberately
# do NOT use `exec`: when lola fails (e.g. "Module not found"), its stderr
# is the actionable signal. We re-emit it under a recognizable prefix so
# the JS wrapper can capture and forward it to the provider envelope, which
# eventually lands in runs.db's `error_message` column. Without this, the
# user only sees "install_pack.sh exited 1" — useless for diagnosis.
lola_args=("install" "$module_name" "-a" "$target_cli")
if [[ -n "$workdir" ]]; then
  if [[ ! -d "$workdir" ]]; then
    echo "install_pack.sh: workdir '$workdir' does not exist" >&2
    exit 3
  fi
  cd "$workdir"
  lola_args+=("--scope" "project")
else
  lola_args+=("--scope" "user")
fi

# Capture BOTH stdout and stderr from lola into a temp file. lola writes
# its diagnostic output ("Module 'foo' not found") to stdout, so capturing
# only stderr would miss it. The merged buffer is mirrored to the parent's
# stderr (all of it is diagnostic in this context) so the user sees it
# live, and the failure summary at the bottom extracts the salient line.
# Plain redirection (no process substitution) keeps the exit code intact.
lola_log="$(mktemp)"
trap 'rm -f "$lola_log"' EXIT
set +e
lola "${lola_args[@]}" >"$lola_log" 2>&1
rc=$?
set -e
cat "$lola_log" >&2
if [[ "$rc" -eq 0 ]]; then
  exit 0
fi
# Final error line in a stable format. The JS wrapper greps for the
# `install_pack.sh: FAILED` prefix to extract the lola message and
# forwards it into the provider envelope's error_message field. We
# prefer lola's last non-empty line (typically the actionable "Module
# 'foo' not found"-style verdict) over the noisy header it prints first.
last_line="$(grep -v '^[[:space:]]*$' "$lola_log" | tail -n1 || true)"
lola_msg="${last_line:-lola exited $rc with no output}"
echo "install_pack.sh: FAILED pack=$pack_id target=$target_cli: $lola_msg" >&2
exit "$rc"
