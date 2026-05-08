#!/usr/bin/env bats
# reset.sh must validate target_cli as a known value before doing anything
# that interpolates it into shell or Python source.

setup() {
    REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
    RESET="$REPO_ROOT/src/lola_eval/_data/orchestrator/reset.sh"
    SCRATCH="$(mktemp -d)"
    export XDG_CACHE_HOME="$SCRATCH"
}

teardown() {
    rm -rf "$SCRATCH"
}

@test "reset.sh rejects unknown target_cli" {
    run "$RESET" example "evil-cli; rm -rf /" "$SCRATCH/lola-eval/work/x"
    [ "$status" -ne 0 ]
    [[ "$output" == *"unknown target_cli"* ]]
}

@test "reset.sh rejects target_cli with shell metachars" {
    run "$RESET" example "claude-code\$(touch /tmp/pwn-reset)" "$SCRATCH/lola-eval/work/x"
    [ "$status" -ne 0 ]
    [ ! -f "/tmp/pwn-reset" ]
}

@test "reset.sh accepts known target_cli claude-code" {
    # Will fail later (no starter), but must pass the cli validation.
    run "$RESET" some-task claude-code "$SCRATCH/lola-eval/work/x"
    [[ "$output" != *"unknown target_cli"* ]]
}

@test "reset.sh accepts known target_cli opencode" {
    run "$RESET" some-task opencode "$SCRATCH/lola-eval/work/x"
    [[ "$output" != *"unknown target_cli"* ]]
}
