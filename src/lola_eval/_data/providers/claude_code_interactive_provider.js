/**
 * Promptfoo custom provider for exec_mode=interactive with target_cli=claude-code.
 *
 * Heavy lifting lives in lib/interactive_helper.js (workdir setup, persona
 * tmpfiles, orchestrator spawn) and in src/lola_eval/_data/interactive/
 * orchestrator.py (the multi-turn dialog itself). This file is a thin
 * wrapper that pins the target_cli identifier and the orchestrator script
 * paths.
 */
import { fileURLToPath } from 'node:url';
import { dirname, resolve as resolvePath } from 'node:path';

import { runInteractiveRow } from './lib/interactive_helper.js';

const _PROVIDER_DIR = dirname(fileURLToPath(import.meta.url));
const RESET_SH = resolvePath(_PROVIDER_DIR, '..', 'orchestrator', 'reset.sh');
const INSTALL_PACK_SH = resolvePath(_PROVIDER_DIR, '..', 'orchestrator', 'install_pack.sh');

export default class ClaudeCodeInteractiveProvider {
  constructor(options = {}) { this.options = options; }
  id() { return 'claude-code-interactive'; }

  async callApi(_prompt, context) {
    const log = (msg) => process.stderr.write(`[claude-code-interactive] ${msg}\n`);
    return runInteractiveRow({
      targetCli: 'claude-code',
      resetSh: RESET_SH,
      installPackSh: INSTALL_PACK_SH,
      vars: context.vars,
      log,
    });
  }
}
