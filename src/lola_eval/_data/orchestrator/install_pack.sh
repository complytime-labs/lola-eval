#!/usr/bin/env bash
# install_pack.sh — install a lola pack into a target CLI.
#
# Usage: install_pack.sh <pack_id> <target_cli> [workdir]
#
# Reserved pack_ids (no-op):
#   "none"     — baseline pass. Leave the workdir pack-free.
#   "project"  — Mode 1 sentinel. The project under evaluation is
#                responsible for its own pack provisioning (e.g. via
#                user-scope `lola install` ahead of CI, or its own
#                install hook). The harness does not enumerate or
#                install packs in this mode.
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

if [[ "$pack_id" == "none" || "$pack_id" == "project" ]]; then
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
