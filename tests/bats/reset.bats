#!/usr/bin/env bats

setup() {
  REPO="$BATS_TEST_DIRNAME/../.."
  TMP="$(mktemp -d)"
  export XDG_CACHE_HOME="$TMP/cache"
  export XDG_STATE_HOME="$TMP/state"
  cd "$REPO"
}

teardown() {
  rm -rf "$TMP"
}

@test "reset.sh creates workdir matching starter/" {
  bash src/lola_eval/_data/orchestrator/reset.sh case-001-fix-bug claude-code "$XDG_CACHE_HOME/lola-eval/work/case-001-fix-bug"
  workdir="$XDG_CACHE_HOME/lola-eval/work/case-001-fix-bug"
  [ -f "$workdir/src/calc/core.py" ]
  [ -f "$workdir/tests/test_core.py" ]
  [ -d "$workdir/.git" ]
}

@test "reset.sh wipes prior agent edits" {
  workdir="$XDG_CACHE_HOME/lola-eval/work/case-001-fix-bug"
  bash src/lola_eval/_data/orchestrator/reset.sh case-001-fix-bug claude-code "$workdir"
  echo "agent garbage" > "$workdir/src/calc/core.py"
  bash src/lola_eval/_data/orchestrator/reset.sh case-001-fix-bug claude-code "$workdir"
  ! grep -q "agent garbage" "$workdir/src/calc/core.py"
}

@test "reset.sh fails clearly on unknown task_id" {
  run bash src/lola_eval/_data/orchestrator/reset.sh nonexistent-task claude-code "$XDG_CACHE_HOME/lola-eval/work/x"
  [ "$status" -ne 0 ]
  [[ "$output" == *"nonexistent-task"* ]]
}

@test "reset.sh refuses to delete paths outside XDG_CACHE_HOME" {
  run bash src/lola_eval/_data/orchestrator/reset.sh case-001-fix-bug claude-code "/etc/passwd-derived"
  [ "$status" -ne 0 ]
  [[ "$output" == *"refusing"* ]]
}

@test "reset.sh creates a fresh git repo with one initial commit" {
  workdir="$XDG_CACHE_HOME/lola-eval/work/case-001-fix-bug"
  bash src/lola_eval/_data/orchestrator/reset.sh case-001-fix-bug claude-code "$workdir"
  cd "$workdir"
  count="$(git log --oneline | wc -l)"
  [ "$count" -eq 1 ]
}
