#!/usr/bin/env bash
# End-to-end container integration test for lola-eval.
#
# Runs inside the container built from tests/container/Containerfile.
# Exercises the full harness with real CLIs against real API calls.
#
# Two phases per target:
#   basic  — single model, single case (quick sanity check)
#   matrix — multiple models, all cases, concurrency (full harness)
set -euo pipefail

PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0

pass() { echo "  PASS: $1"; PASS_COUNT=$((PASS_COUNT + 1)); }
fail() { echo "  FAIL: $1"; FAIL_COUNT=$((FAIL_COUNT + 1)); }
warn() { echo "  WARN: $1"; WARN_COUNT=$((WARN_COUNT + 1)); }

# ── CLI detection ────────────────────────────────────────────────────
CLAUDE_INSTALLED=false
OPENCODE_INSTALLED=false

if claude --version >/dev/null 2>&1; then
  CLAUDE_INSTALLED=true
  echo "claude:   $(claude --version 2>&1 | head -1)"
fi
if opencode --version >/dev/null 2>&1; then
  OPENCODE_INSTALLED=true
  echo "opencode: $(opencode --version 2>&1 | head -1)"
fi

if ! $CLAUDE_INSTALLED && ! $OPENCODE_INSTALLED; then
  echo "ERROR: Neither claude nor opencode CLI found on PATH."
  exit 1
fi

# ── Auth detection ───────────────────────────────────────────────────
has_claude_auth() {
  [[ -n "${ANTHROPIC_API_KEY:-}" ]] \
    || [[ -n "${CLAUDE_CODE_USE_VERTEX:-}" && -n "${ANTHROPIC_VERTEX_PROJECT_ID:-}" ]] \
    || [[ -n "${ANTHROPIC_VERTEX_PROJECT_ID:-}" && -n "${GOOGLE_CLOUD_PROJECT:-}" ]]
}

has_opencode_auth() {
  [[ -n "${ANTHROPIC_API_KEY:-}" ]] \
    || [[ -n "${GOOGLE_CLOUD_PROJECT:-}" ]]
}

TARGETS=()
if $CLAUDE_INSTALLED && has_claude_auth; then
  TARGETS+=("claude-code")
else
  $CLAUDE_INSTALLED && warn "claude installed but no auth env vars found — skipping"
fi
if $OPENCODE_INSTALLED && has_opencode_auth; then
  TARGETS+=("opencode")
else
  $OPENCODE_INSTALLED && warn "opencode installed but no auth env vars found — skipping"
fi

if [[ ${#TARGETS[@]} -eq 0 ]]; then
  echo "ERROR: No runnable targets — CLIs installed but auth env vars missing."
  echo "  ANTHROPIC_API_KEY:            ${ANTHROPIC_API_KEY:+(set)}"
  echo "  ANTHROPIC_VERTEX_PROJECT_ID:  ${ANTHROPIC_VERTEX_PROJECT_ID:+(set)}"
  echo "  GOOGLE_CLOUD_PROJECT:         ${GOOGLE_CLOUD_PROJECT:+(set)}"
  exit 1
fi

echo ""
echo "Targets: ${TARGETS[*]}"

# ── Helpers ──────────────────────────────────────────────────────────

setup_workspace() {
  local workdir
  workdir="$(mktemp -d /tmp/lola-eval-test-XXXXXX)"
  export XDG_STATE_HOME="$workdir/xdg-state"
  export XDG_CACHE_HOME="$workdir/xdg-cache"
  mkdir -p "$XDG_STATE_HOME" "$XDG_CACHE_HOME"
  cp -a /workspace/examples/tests "$workdir/tests"
  echo "$workdir"
}

validate_results() {
  local label="$1" results_dir="$2" exit_code="$3" expected_rows="$4"

  if [[ -f "$results_dir/runs.db" ]]; then
    pass "$label: runs.db exists"
  else
    fail "$label: runs.db missing"
  fi

  if [[ -f "$results_dir/last-run.json" ]]; then
    pass "$label: last-run.json exists"
    if python3 -c "
import json, sys
data = json.load(open('$results_dir/last-run.json'))
assert isinstance(data, list) and len(data) > 0, 'empty or not a list'
n = len(data)
expected = $expected_rows
if n < expected:
    print(f'  expected >= {expected} rows, got {n}', file=sys.stderr)
    sys.exit(1)
for row in data:
    for f in ('cli', 'model', 'task_id', 'pack_id', 'composite'):
        assert f in row, f'missing field: {f}'
print(f'  rows={n}  composites={[r[\"composite\"] for r in data]}')
"; then
      pass "$label: last-run.json has required fields and >= $expected_rows rows"
    else
      fail "$label: last-run.json validation failed"
    fi
  else
    fail "$label: last-run.json missing"
  fi

  if [[ -f "$results_dir/junit.xml" ]]; then
    pass "$label: junit.xml exists"
  else
    fail "$label: junit.xml missing"
  fi

  # Exit code 0 = threshold pass, 1 = score below threshold (non-deterministic),
  # 2 = setup/config error, anything else = unexpected.
  case $exit_code in
    0) pass "$label: lola-eval test passed (exit 0)" ;;
    1) warn "$label: score below threshold (exit 1) — agent non-determinism, not a harness bug" ;;
    2) fail "$label: setup error (exit 2)" ;;
    *) fail "$label: unexpected exit code $exit_code" ;;
  esac
}

# ── Run tests ────────────────────────────────────────────────────────
for target in "${TARGETS[@]}"; do

  # ── Phase 1: Basic ─────────────────────────────────────────────────
  echo ""
  echo "=== $target / basic ==="
  echo "    Single model (sonnet), single case (case-001-fix-bug)"

  WORKDIR="$(setup_workspace)"

  cat > "$WORKDIR/lola-eval.yaml" <<YAML
targets:
  - cli: $target
    models: [sonnet]

calculate_baseline: false

threshold:
  mode: absolute
  tolerance: 0.05
  timeout_is_failure: true

concurrency: 1
tests_dir: tests/lola-eval
results_dir: .lola-eval

judges:
  - {cli: claude-code, model: sonnet}

aggregation: mean
disagreement_threshold: 0.15

ci:
  junit_xml: true
  github_summary: false
  html_report: false
YAML

  set +e
  (cd "$WORKDIR" && python3 -m lola_eval test --case case-001-fix-bug)
  BASIC_EXIT=$?
  set -e

  validate_results "$target/basic" "$WORKDIR/.lola-eval" "$BASIC_EXIT" 1

  # ── Phase 2: Matrix ────────────────────────────────────────────────
  echo ""
  echo "=== $target / matrix ==="
  echo "    Two models (sonnet, haiku), all cases, concurrency 2"

  WORKDIR="$(setup_workspace)"

  cat > "$WORKDIR/lola-eval.yaml" <<YAML
targets:
  - cli: $target
    models:
      - sonnet
      - haiku

calculate_baseline: false

threshold:
  mode: absolute
  tolerance: 0.05
  timeout_is_failure: true

concurrency: 2
tests_dir: tests/lola-eval
results_dir: .lola-eval

judges:
  - {cli: claude-code, model: sonnet}

aggregation: mean
disagreement_threshold: 0.15

ci:
  junit_xml: true
  github_summary: false
  html_report: false
YAML

  set +e
  (cd "$WORKDIR" && python3 -m lola_eval test)
  MATRIX_EXIT=$?
  set -e

  # 2 models x 2 cases = 4 rows expected
  validate_results "$target/matrix" "$WORKDIR/.lola-eval" "$MATRIX_EXIT" 4

done

# ── Summary ──────────────────────────────────────────────────────────
echo ""
echo "=== Summary ==="
echo "  PASS: $PASS_COUNT"
echo "  WARN: $WARN_COUNT"
echo "  FAIL: $FAIL_COUNT"

if [[ $FAIL_COUNT -gt 0 ]]; then
  exit 1
fi
exit 0
