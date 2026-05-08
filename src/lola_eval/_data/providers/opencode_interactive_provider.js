/**
 * Promptfoo custom provider for exec_mode=interactive with target_cli=opencode.
 *
 * Mirror of claude_code_interactive_provider.js with the target CLI pinned
 * to opencode. See lib/interactive_helper.js for the shared logic.
 */
import { fileURLToPath } from 'node:url';
import { dirname, resolve as resolvePath } from 'node:path';

import { runInteractiveRow } from './lib/interactive_helper.js';

const _PROVIDER_DIR = dirname(fileURLToPath(import.meta.url));
const RESET_SH = resolvePath(_PROVIDER_DIR, '..', 'orchestrator', 'reset.sh');
const INSTALL_PACK_SH = resolvePath(_PROVIDER_DIR, '..', 'orchestrator', 'install_pack.sh');

export default class OpencodeInteractiveProvider {
  constructor(options = {}) { this.options = options; }
  id() { return 'opencode-interactive'; }

  async callApi(_prompt, context) {
    const log = (msg) => process.stderr.write(`[opencode-interactive] ${msg}\n`);
    return runInteractiveRow({
      targetCli: 'opencode',
      resetSh: RESET_SH,
      installPackSh: INSTALL_PACK_SH,
      vars: context.vars,
      log,
    });
  }
}
