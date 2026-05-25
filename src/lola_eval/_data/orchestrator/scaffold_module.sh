#!/usr/bin/env bash
# scaffold_module.sh — copy a lola module's skills/commands/agents into a
# target CLI's config dirs, replicating `lola install`'s layout for those
# three artifact types WITHOUT invoking `lola` (fast, deterministic, no
# network, no D-state stalls). Instructions (AGENTS.md) and MCP merging are
# intentionally NOT handled — modules needing those should use `lola install`.
#
# Usage: scaffold_module.sh <module_dir> <dest_root> <target_cli>
#   <dest_root>/.claude/{skills,commands,agents}   for claude-code
#   <dest_root>/.opencode/{skills,commands,agents} for opencode
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: $0 <module_dir> <dest_root> <target_cli>" >&2
  exit 64
fi

module_dir="$1"
dest_root="$2"
target_cli="$3"

if [[ ! -d "$module_dir" ]]; then
  echo "scaffold_module.sh: module dir '$module_dir' does not exist" >&2
  exit 1
fi

case "$target_cli" in
  claude-code) base="$dest_root/.claude" ;;
  opencode)    base="$dest_root/.opencode" ;;
  *)
    echo "scaffold_module.sh: unknown target_cli '$target_cli'" >&2
    exit 1
    ;;
esac

# Resolve the content directory: lola modules keep content at the module
# root, or under a `module/` or `lola-module/` subdirectory.
content="$module_dir"
if [[ ! -d "$module_dir/skills" && ! -d "$module_dir/commands" && ! -d "$module_dir/agents" ]]; then
  for sub in module lola-module; do
    if [[ -d "$module_dir/$sub/skills" || -d "$module_dir/$sub/commands" || -d "$module_dir/$sub/agents" ]]; then
      content="$module_dir/$sub"
      break
    fi
  done
fi

copied=0
for kind in skills commands agents; do
  if [[ -d "$content/$kind" ]]; then
    mkdir -p "$base/$kind"
    cp -a "$content/$kind/." "$base/$kind/"
    copied=1
  fi
done

if [[ "$copied" -eq 0 ]]; then
  echo "scaffold_module.sh: no skills/commands/agents found under $content" >&2
fi
echo "scaffold_module.sh: scaffolded $(basename "$module_dir") into $base" >&2
