/**
 * Stream-JSON transcript parser for `claude --output-format=stream-json`.
 *
 * Inputs: the full transcript as a UTF-8 string (newline-delimited JSON).
 * Output: a structured summary with turn count, tool calls, exit status,
 * cost, duration, and forward-compat hints (unknown event types).
 *
 * Maps Claude Code result.subtype → harness exit_status:
 *   success    → 'success'
 *   max_turns  → 'target_timeout'
 *   error_*    → 'target_error'
 *   (none/missing) → 'target_error'  (truncated transcript)
 */

const KNOWN_EVENT_TYPES = new Set(['system', 'assistant', 'user', 'result']);

function mapExitStatus(resultSubtype) {
  if (!resultSubtype) return 'target_error';
  if (resultSubtype === 'success') return 'success';
  if (resultSubtype === 'max_turns') return 'target_timeout';
  return 'target_error';
}

function detectLoop(toolCalls, threshold = 3) {
  // Loop heuristic: 3+ Bash calls in a row with the same `command`.
  let streak = 1;
  for (let i = 1; i < toolCalls.length; i++) {
    const a = toolCalls[i - 1], b = toolCalls[i];
    if (a.name === 'Bash' && b.name === 'Bash'
        && JSON.stringify(a.input) === JSON.stringify(b.input)) {
      streak++;
      if (streak >= threshold) return true;
    } else {
      streak = 1;
    }
  }
  return false;
}

export function parseTranscript(text) {
  const lines = text.split('\n').filter(l => l.trim().length > 0);

  const toolCalls = [];
  const unknownEventTypes = new Set();
  let turns = 0;
  let costUsd = 0;
  let durationMs = 0;
  let exitStatus = 'target_error';
  // Token counts default to undefined: a missing result event or a result
  // event without `usage` (older Claude Code builds) must be distinguishable
  // from a real zero-token row, so we deliberately don't coerce to 0.
  let inputTokens;
  let outputTokens;
  let cacheReadTokens;
  let cacheCreationTokens;

  for (const line of lines) {
    let evt;
    try {
      evt = JSON.parse(line);
    } catch (err) {
      throw new Error(`malformed transcript line: ${line.slice(0, 80)}`);
    }
    if (!KNOWN_EVENT_TYPES.has(evt.type)) {
      unknownEventTypes.add(evt.type);
      continue;
    }
    if (evt.type === 'assistant' && evt.message?.content) {
      for (const block of evt.message.content) {
        if (block.type === 'tool_use') {
          toolCalls.push({ name: block.name, input: block.input });
        }
      }
    }
    if (evt.type === 'result') {
      turns = evt.num_turns ?? 0;
      costUsd = evt.total_cost_usd ?? 0;
      durationMs = evt.duration_ms ?? 0;
      exitStatus = mapExitStatus(evt.subtype);
      inputTokens = evt.usage?.input_tokens;
      outputTokens = evt.usage?.output_tokens;
      cacheReadTokens = evt.usage?.cache_read_input_tokens;
      cacheCreationTokens = evt.usage?.cache_creation_input_tokens;
    }
  }

  return {
    turns,
    toolCalls,
    costUsd,
    durationMs,
    exitStatus,
    inputTokens,
    outputTokens,
    cacheReadTokens,
    cacheCreationTokens,
    suspectedLoop: detectLoop(toolCalls),
    unknownEventTypes: [...unknownEventTypes],
  };
}
