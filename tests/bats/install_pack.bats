#!/usr/bin/env bats

setup() {
  REPO="$BATS_TEST_DIRNAME/../.."
  TMP="$(mktemp -d)"
  export PATH="$TMP/bin:$PATH"
  mkdir -p "$TMP/bin"
  cd "$REPO"
}

teardown() {
  rm -rf "$TMP"
}

# Stub `lola` for these tests
write_lola_stub() {
  cat > "$TMP/bin/lola" <<'EOF'
#!/usr/bin/env bash
# Stub: succeed unless pack ID contains "fail"
if [[ "$*" == *"fail"* ]]; then
  echo "lola: simulated failure" >&2
  exit 5
fi
echo "lola stub ok: $*"
exit 0
EOF
  chmod +x "$TMP/bin/lola"
}

@test "install_pack.sh: pack=none is a no-op" {
  write_lola_stub
  run bash src/lola_eval/_data/orchestrator/install_pack.sh none claude-code
  [ "$status" -eq 0 ]
}

@test "install_pack.sh: pack=project is a no-op (Mode 1 sentinel)" {
  # Mode 1: the project under evaluation provisions its own packs.
  # The harness must NOT shell out to `lola install` here. The stub
  # echoes "lola stub ok: ..." on invocation; absence of that string
  # confirms the script short-circuited before calling lola.
  write_lola_stub
  run bash src/lola_eval/_data/orchestrator/install_pack.sh project claude-code
  [ "$status" -eq 0 ]
  [[ "$output" != *"lola stub ok"* ]]
}

@test "install_pack.sh: invokes lola install with -a flag" {
  write_lola_stub
  run bash src/lola_eval/_data/orchestrator/install_pack.sh example-pack@deadbeef claude-code
  [ "$status" -eq 0 ]
  [[ "$output" == *"-a claude-code"* ]] || [[ "$output" == *"-a"*"claude-code"* ]]
}

@test "install_pack.sh: surfaces lola failure exit code" {
  write_lola_stub
  run bash src/lola_eval/_data/orchestrator/install_pack.sh fail-pack claude-code
  [ "$status" -ne 0 ]
}

@test "install_pack.sh: emits FAILED prefix line with lola message on failure" {
  # Real-world example: lola prints "Module 'foo' not found" to stdout
  # and exits 1. The script must extract the actionable line and surface
  # it on a stable `install_pack.sh: FAILED ...` prefix line so the JS
  # wrapper can forward it to the provider envelope.
  cat > "$TMP/bin/lola" <<'EOF'
#!/usr/bin/env bash
echo "Use 'lola mod ls' to see available modules"
echo "Module 'nonexistent-foo' not found"
exit 1
EOF
  chmod +x "$TMP/bin/lola"
  run bash src/lola_eval/_data/orchestrator/install_pack.sh nonexistent-foo claude-code
  [ "$status" -eq 1 ]
  [[ "$output" == *"install_pack.sh: FAILED"* ]]
  [[ "$output" == *"Module 'nonexistent-foo' not found"* ]]
}

@test "install_pack.sh: rejects unknown target_cli" {
  write_lola_stub
  run bash src/lola_eval/_data/orchestrator/install_pack.sh ok-pack unknown-cli
  [ "$status" -ne 0 ]
  [[ "$output" == *"unknown-cli"* ]]
}

@test "install_pack.sh: errors clearly when lola not found" {
  rm -f "$TMP/bin/lola"
  run env PATH="$TMP/bin" /usr/bin/bash src/lola_eval/_data/orchestrator/install_pack.sh some-pack claude-code
  [ "$status" -ne 0 ]
  [[ "$output" == *"lola"* ]]
}

@test "install_pack.sh: workdir-scoped install passes --scope project" {
  write_lola_stub
  workdir="$TMP/work"
  mkdir -p "$workdir"
  run bash src/lola_eval/_data/orchestrator/install_pack.sh example-pack@deadbeef claude-code "$workdir"
  [ "$status" -eq 0 ]
  [[ "$output" == *"--scope project"* ]]
}

@test "install_pack.sh: user-scope install when no workdir given" {
  write_lola_stub
  run bash src/lola_eval/_data/orchestrator/install_pack.sh example-pack@deadbeef claude-code
  [ "$status" -eq 0 ]
  [[ "$output" == *"--scope user"* ]]
}

@test "install_pack.sh: missing workdir is a hard error" {
  write_lola_stub
  run bash src/lola_eval/_data/orchestrator/install_pack.sh example-pack@deadbeef claude-code "/does/not/exist"
  [ "$status" -ne 0 ]
}

@test "install_pack.sh: strips @<ref> from pack_id when calling lola" {
  write_lola_stub
  run bash src/lola_eval/_data/orchestrator/install_pack.sh example-pack@local claude-code
  [ "$status" -eq 0 ]
  # The stub echoes its args; verify "example-pack" appears WITHOUT the @local suffix
  [[ "$output" == *"example-pack "* ]] || [[ "$output" == *"example-pack$'\n'"* ]]
  [[ "$output" != *"example-pack@local"* ]]
}
