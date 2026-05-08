/**
 * Provider envelope shape — JSON returned by every target provider.
 * The judge consumes this; strict validation catches drift at the
 * provider boundary before bad data corrupts scores.
 */

// Note: 'judge_error' is set by the trajectory judge in Python AFTER the
// envelope reaches it from the JS provider; it never appears in an
// envelope produced by the JS layer. It is listed here so the JS-side
// validation (validateEnvelope below — currently reserved for future
// round-trip checks; not wired into the runtime path because the Python
// runner is the authoritative reader) does not reject judge-marked rows
// if it ever runs against persisted data.
const VALID_EXIT_STATUSES = new Set([
  'success',
  'target_timeout',
  'target_error',
  'setup_error',
  'judge_error',
]);

const REQUIRED_FIELDS = [
  'run_id', 'transcript_path', 'turns', 'tool_calls',
  'exit_status', 'duration_s', 'diff', 'cost_usd',
];

export function buildEnvelope({
  runId, transcriptPath, turns, toolCalls,
  exitStatus, durationS, diff, costUsd,
  inputTokens, outputTokens, cacheReadTokens, cacheCreationTokens,
  errorMessage,
}) {
  if (!VALID_EXIT_STATUSES.has(exitStatus)) {
    throw new Error(`invalid exit_status: ${exitStatus}`);
  }
  // Token fields are optional. They round-trip as snake_case for parity
  // with the rest of the envelope and stay `undefined` when the upstream
  // parser couldn't supply them (e.g. opencode, legacy stream-json).
  // `error_message` is also optional — populated on setup_error /
  // target_error envelopes so the judge can persist the actual cause
  // (e.g. "Module 'foo' not found") to runs.db's error_message column.
  return {
    run_id: runId,
    transcript_path: transcriptPath,
    turns,
    tool_calls: toolCalls,
    exit_status: exitStatus,
    duration_s: durationS,
    diff,
    cost_usd: costUsd,
    input_tokens: inputTokens,
    output_tokens: outputTokens,
    cache_read_tokens: cacheReadTokens,
    cache_creation_tokens: cacheCreationTokens,
    error_message: errorMessage,
  };
}

export function validateEnvelope(env) {
  for (const f of REQUIRED_FIELDS) {
    if (!(f in env)) return `missing field: ${f}`;
  }
  if (!VALID_EXIT_STATUSES.has(env.exit_status)) {
    return `invalid exit_status: ${env.exit_status}`;
  }
  return null;
}

export { VALID_EXIT_STATUSES, REQUIRED_FIELDS };
