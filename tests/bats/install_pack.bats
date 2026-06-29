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

@test "install_pack.sh: pack=project with no module_source and no workdir is a no-op" {
  # Mode 1 without LOLA_MODULE_SOURCE and without a workdir: nothing to
  # install or scaffold. The harness must NOT shell out to `lola install`
  # here. The stub echoes "lola stub ok: ..." on invocation; absence of that
  # string confirms the script short-circuited before calling lola.
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

@test "install_pack project mode auto-scaffolds .lola/modules" {
  TMPWD="$(mktemp -d)"
  mkdir -p "$TMPWD/.lola/modules/mymod/skills/greet"
  echo "# greet" > "$TMPWD/.lola/modules/mymod/skills/greet/SKILL.md"
  bash "$BATS_TEST_DIRNAME/../../src/lola_eval/_data/orchestrator/install_pack.sh" \
    project claude-code "$TMPWD"
  [ -f "$TMPWD/.claude/skills/greet/SKILL.md" ]
  rm -rf "$TMPWD"
}

@test "install_pack project mode is a no-op without .lola/modules" {
  TMPWD="$(mktemp -d)"
  run bash "$BATS_TEST_DIRNAME/../../src/lola_eval/_data/orchestrator/install_pack.sh" \
    project claude-code "$TMPWD"
  [ "$status" -eq 0 ]
  [ ! -d "$TMPWD/.claude" ]
  rm -rf "$TMPWD"
}

# A richer lola stub that mimics install's file footprint + context injection,
# so we can assert install_pack.sh restores the instruction file.
# Generalized to support both claude-code and opencode target CLIs.
write_lola_footprint_stub() {
  cat > "$TMP/bin/lola" <<'EOF'
#!/usr/bin/env bash
cmd="$1"; shift
if [[ "$cmd" == "mod" ]]; then exit 0; fi
if [[ "$cmd" == "install" ]]; then
  scope="project"; proj=""; cli=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      -a) cli="$2"; shift 2;;
      --scope) scope="$2"; shift 2;;
      -f) shift;;
      -*) shift;;
      *) [[ -z "${name:-}" ]] && name="$1" || proj="$1"; shift;;
    esac
  done
  root="$proj"; [[ "$scope" == "user" ]] && root="$HOME"
  cfg=".claude"; [[ "$cli" == "opencode" ]] && cfg=".opencode"
  mkdir -p "$root/$cfg/skills/demo" "$root/$cfg/commands" "$root/$cfg/agents"
  echo x > "$root/$cfg/skills/demo/SKILL.md"
  echo x > "$root/$cfg/commands/do-thing.md"
  echo x > "$root/$cfg/agents/helper.md"
  if [[ "$cli" == "opencode" ]]; then
    ifile="$root/AGENTS.md"
  else
    ifile="$root/CLAUDE.md"; [[ "$scope" == "user" ]] && ifile="$root/.claude/CLAUDE.md"
  fi
  mkdir -p "$(dirname "$ifile")"
  printf '\n\n<!-- lola:instructions:start -->\nINJECTED\n<!-- lola:instructions:end -->\n' >> "$ifile"
  exit 0
fi
exit 0
EOF
  chmod +x "$TMP/bin/lola"
}

write_lola_install_fail_stub() {
  cat > "$TMP/bin/lola" <<'EOF'
#!/usr/bin/env bash
cmd="$1"; shift
[[ "$cmd" == "mod" ]] && exit 0
if [[ "$cmd" == "install" ]]; then
  echo "lola: Module could not be installed" >&2
  exit 7
fi
exit 0
EOF
  chmod +x "$TMP/bin/lola"
}

@test "install_pack.sh: project scope installs skills and restores CLAUDE.md" {
  write_lola_footprint_stub
  WD="$TMP/wd"; mkdir -p "$WD"; printf '# starter ctx\n' > "$WD/CLAUDE.md"
  export HOME="$TMP/home"; mkdir -p "$HOME"
  export LOLA_MODULE_SOURCE="$BATS_TEST_DIRNAME/../fixtures/module-mini"
  export LOLA_INSTALL_SCOPE="project"
  run bash src/lola_eval/_data/orchestrator/install_pack.sh project claude-code "$WD"
  [ "$status" -eq 0 ]
  [ -f "$WD/.claude/skills/demo/SKILL.md" ]
  [ "$(cat "$WD/CLAUDE.md")" = "# starter ctx" ]
  [[ "$(cat "$WD/CLAUDE.md")" != *"INJECTED"* ]]
}

@test "install_pack.sh: project scope creates CLAUDE.md absent before -> removed after" {
  write_lola_footprint_stub
  WD="$TMP/wd"; mkdir -p "$WD"
  export HOME="$TMP/home"; mkdir -p "$HOME"
  export LOLA_MODULE_SOURCE="$BATS_TEST_DIRNAME/../fixtures/module-mini"
  export LOLA_INSTALL_SCOPE="project"
  run bash src/lola_eval/_data/orchestrator/install_pack.sh project claude-code "$WD"
  [ "$status" -eq 0 ]
  [ -f "$WD/.claude/agents/helper.md" ]
  [ ! -f "$WD/CLAUDE.md" ]
}

@test "install_pack.sh: project-user installs into HOME and restores HOME CLAUDE.md" {
  write_lola_footprint_stub
  WD="$TMP/wd"; mkdir -p "$WD"
  export HOME="$TMP/home"; mkdir -p "$HOME/.claude"
  export LOLA_MODULE_SOURCE="$BATS_TEST_DIRNAME/../fixtures/module-mini"
  export LOLA_INSTALL_SCOPE="user"
  run bash src/lola_eval/_data/orchestrator/install_pack.sh project-user claude-code "$WD"
  [ "$status" -eq 0 ]
  [ -f "$HOME/.claude/skills/demo/SKILL.md" ]
  [ ! -f "$HOME/.claude/CLAUDE.md" ]
  [ ! -f "$WD/CLAUDE.md" ]
}

@test "install_pack.sh: opencode project scope restores AGENTS.md" {
  write_lola_footprint_stub
  WD="$TMP/wd"; mkdir -p "$WD"; printf '# oc ctx\n' > "$WD/AGENTS.md"
  export HOME="$TMP/home"; mkdir -p "$HOME"
  export LOLA_MODULE_SOURCE="$BATS_TEST_DIRNAME/../fixtures/module-mini"
  export LOLA_INSTALL_SCOPE="project"
  run bash src/lola_eval/_data/orchestrator/install_pack.sh project opencode "$WD"
  [ "$status" -eq 0 ]
  [ -f "$WD/.opencode/skills/demo/SKILL.md" ]
  [ "$(cat "$WD/AGENTS.md")" = "# oc ctx" ]
  [[ "$(cat "$WD/AGENTS.md")" != *"INJECTED"* ]]
}

@test "install_pack.sh: failed lola install still restores instruction file and surfaces FAILED" {
  write_lola_install_fail_stub
  WD="$TMP/wd"; mkdir -p "$WD"; printf '# starter ctx\n' > "$WD/CLAUDE.md"
  export HOME="$TMP/home"; mkdir -p "$HOME"
  export LOLA_MODULE_SOURCE="$BATS_TEST_DIRNAME/../fixtures/module-mini"
  export LOLA_INSTALL_SCOPE="project"
  run bash src/lola_eval/_data/orchestrator/install_pack.sh project claude-code "$WD"
  [ "$status" -ne 0 ]
  [ "$(cat "$WD/CLAUDE.md")" = "# starter ctx" ]
  [[ "$output" == *"install_pack.sh: FAILED"* ]]
}
