/**
 * Stub agent provider for integration tests. Mimics claude_code_provider's
 * envelope contract but returns canned responses from fixtures instead of
 * spawning `claude`. Records inputs to a sidecar file so tests can assert
 * what was called.
 */
import { randomUUID } from 'node:crypto';
import { readFileSync, appendFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';

export default class StubProvider {
  constructor(options = {}) { this.options = options; }
  id() { return 'stub'; }

  async callApi(prompt, context) {
    const v = context.vars;
    const fixturesDir = process.env.LOLA_STUB_FIXTURES;
    if (!fixturesDir) throw new Error('LOLA_STUB_FIXTURES not set');
    const inputLog = process.env.LOLA_STUB_INPUT_LOG;
    if (inputLog) {
      mkdirSync(dirname(inputLog), { recursive: true });
      appendFileSync(inputLog, JSON.stringify({ task: v.task_id, model: v.target_model, pack: v.pack_id }) + '\n');
    }
    const fixturePath = join(fixturesDir, `${v.task_id}__${v.pack_id}.json`);
    const envelope = JSON.parse(readFileSync(fixturePath, 'utf8'));
    envelope.run_id = randomUUID();
    return { output: JSON.stringify(envelope), cost: envelope.cost_usd ?? 0 };
  }
}
