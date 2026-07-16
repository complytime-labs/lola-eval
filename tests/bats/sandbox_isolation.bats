#!/usr/bin/env bats
#
# Live end-to-end proof that the bubblewrap sandbox actually hides host opencode
# config from REAL opencode (not a shell probe). Opt-in and dependency-gated so
# the default `task test` / `bats tests/bats` run skips it:
#
#   task sandbox:verify        # or: LOLA_SANDBOX_LIVE=1 bats tests/bats/sandbox_isolation.bats
#
# It plants a uniquely-named "canary" agent in the host opencode config, drives
# real opencode (bogus model → exits after config/agent discovery) through the
# SHIPPED wrapOpencode() output under strace, and asserts opencode never
# successfully opens the canary and never re-installs node_modules. The canary
# is removed in teardown even on failure.

setup() {
  [ "${LOLA_SANDBOX_LIVE:-0}" = "1" ] || skip "opt-in: set LOLA_SANDBOX_LIVE=1 (drives real opencode)"
  command -v opencode >/dev/null 2>&1 || skip "opencode not installed"
  command -v strace   >/dev/null 2>&1 || skip "strace not installed"
  command -v bwrap    >/dev/null 2>&1 || skip "bwrap not installed"
  command -v node     >/dev/null 2>&1 || skip "node not installed"

  REPO="$BATS_TEST_DIRNAME/../.."
  HELPER="$BATS_TEST_DIRNAME/helpers/sandbox-argv.mjs"
  TMP="$(mktemp -d)"
  STRACE="$TMP/oc.strace"

  # bwrap must actually be usable (userns/caps) here, else skip rather than fail.
  node -e 'import("'"$REPO"'/src/lola_eval/_data/providers/lib/sandbox.js").then(m=>process.exit(m.detectBwrapSupport()?0:1))' \
    || skip "bwrap present but not usable (user namespaces/caps unavailable)"

  CFG="$HOME/.config/opencode"
  AGENTS="$CFG/agents"
  CANARY="$AGENTS/lola-sandbox-canary-$$-${BATS_TEST_NUMBER:-0}.md"
  CREATED_AGENTS=0
  [ -d "$AGENTS" ] || { mkdir -p "$AGENTS" && CREATED_AGENTS=1; }
  printf '%s\n' "CANARY: this host agent MUST NOT be visible to sandboxed opencode" > "$CANARY"
}

teardown() {
  [ -n "${CANARY:-}" ] && rm -f "$CANARY"
  # Only remove the agents dir if this test created it and it is now empty.
  [ "${CREATED_AGENTS:-0}" = "1" ] && rmdir "$AGENTS" 2>/dev/null
  [ -n "${TMP:-}" ] && rm -rf "$TMP"
  # setup() may skip before TMP/CANARY are set; never let cleanup fail the run.
  return 0
}

@test "sandboxed opencode cannot read a host config agent (canary)" {
  # Build the REAL wrapped argv (setpriv/bwrap ... strace ... opencode ...).
  mapfile -t ARGV < <(node "$HELPER" "$TMP/empty" "$STRACE" "canary isolation check")
  [ "${#ARGV[@]}" -gt 0 ] || { echo "helper produced no argv"; false; }

  # Real opencode: discovers config/agents at startup, then fails on the bogus
  # model. We only care about what it managed to open before exiting.
  run timeout -s KILL 40 "${ARGV[@]}"
  [ -f "$STRACE" ] || { echo "strace produced no output; opencode did not start"; false; }

  # The canary lives in the host agents dir, which the sandbox tmpfs-empties.
  # Count openat() calls that returned a real fd (i.e. a SUCCESSFUL read) for
  # the canary — must be zero. ENOENT / <unfinished ...> lines don't count.
  local canary_name leaked
  canary_name="$(basename "$CANARY")"
  leaked="$(grep -F "$canary_name" "$STRACE" 2>/dev/null \
            | grep -vE 'ENOENT|<unfinished' \
            | grep -cE '= [0-9]+$' || true)"
  echo "canary successful-open count (expect 0): $leaked"
  [ "$leaked" -eq 0 ]

  # And the sandbox must not have forced a node_modules re-install (the failure
  # mode that hiding the whole config dir caused).
  local reinstall
  reinstall="$(grep -E 'openat' "$STRACE" 2>/dev/null \
               | grep 'O_CREAT' \
               | grep -c '/.config/opencode/node_modules/' || true)"
  echo "node_modules O_CREAT count (expect 0): $reinstall"
  [ "$reinstall" -eq 0 ]

  # Host canary must survive on disk (sandbox mounts were private).
  [ -f "$CANARY" ]
}
