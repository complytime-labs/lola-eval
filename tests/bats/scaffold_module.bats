#!/usr/bin/env bats

setup() {
  REPO="$BATS_TEST_DIRNAME/../.."
  TMP="$(mktemp -d)"
  SCAFFOLD="$REPO/src/lola_eval/_data/orchestrator/scaffold_module.sh"
  # A fixture module with one skill, one command, one agent.
  MOD="$TMP/mymod"
  mkdir -p "$MOD/skills/greet" "$MOD/commands" "$MOD/agents"
  echo "# greet skill" > "$MOD/skills/greet/SKILL.md"
  echo "# do-thing" > "$MOD/commands/do-thing.md"
  echo "# reviewer" > "$MOD/agents/reviewer.md"
  DEST="$TMP/dest"
  mkdir -p "$DEST"
}

teardown() { rm -rf "$TMP"; }

@test "scaffold copies skills/commands/agents into .claude for claude-code" {
  bash "$SCAFFOLD" "$MOD" "$DEST" claude-code
  [ -f "$DEST/.claude/skills/greet/SKILL.md" ]
  [ -f "$DEST/.claude/commands/do-thing.md" ]
  [ -f "$DEST/.claude/agents/reviewer.md" ]
}

@test "scaffold copies into .opencode for opencode" {
  bash "$SCAFFOLD" "$MOD" "$DEST" opencode
  [ -f "$DEST/.opencode/skills/greet/SKILL.md" ]
  [ -f "$DEST/.opencode/commands/do-thing.md" ]
  [ -f "$DEST/.opencode/agents/reviewer.md" ]
}

@test "scaffold resolves content under a module/ subdirectory" {
  NESTED="$TMP/nested"
  mkdir -p "$NESTED/module/skills/x"
  echo "# x" > "$NESTED/module/skills/x/SKILL.md"
  bash "$SCAFFOLD" "$NESTED" "$DEST" claude-code
  [ -f "$DEST/.claude/skills/x/SKILL.md" ]
}

@test "scaffold rejects unknown target_cli" {
  run bash "$SCAFFOLD" "$MOD" "$DEST" bogus
  [ "$status" -ne 0 ]
  [[ "$output" == *"bogus"* ]]
}

@test "scaffold is idempotent (re-run does not error)" {
  bash "$SCAFFOLD" "$MOD" "$DEST" claude-code
  bash "$SCAFFOLD" "$MOD" "$DEST" claude-code
  [ -f "$DEST/.claude/skills/greet/SKILL.md" ]
}

@test "scaffold resolves content under a lola-module/ subdirectory" {
  NESTED="$TMP/nested-lm"
  mkdir -p "$NESTED/lola-module/skills/y"
  echo "# y" > "$NESTED/lola-module/skills/y/SKILL.md"
  bash "$SCAFFOLD" "$NESTED" "$DEST" claude-code
  [ -f "$DEST/.claude/skills/y/SKILL.md" ]
}
