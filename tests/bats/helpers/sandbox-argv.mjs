/**
 * Print the exact argv the shipped opencode sandbox produces, with `strace`
 * spliced in front of the `opencode` token, one token per line.
 *
 * Used by tests/bats/sandbox_isolation.bats to drive REAL opencode under the
 * REAL wrapOpencode() output (not a reimplementation), so a regression in
 * buildBwrapArgs is caught by the live check.
 *
 * Usage: node sandbox-argv.mjs <emptyDir> <straceFile> <message>
 *   emptyDir   - writable dir for the {} / empty overlay files
 *   straceFile - path strace should write to
 *   message    - the opencode prompt (a bogus model makes it exit after
 *                config/agent discovery)
 */
import { join } from "node:path";
import {
  wrapAgent,
  detectBwrapSupport,
  prepareOverlays,
} from "../../../src/lola_eval/_data/providers/lib/sandbox.js";

const [emptyDir, straceFile, message] = process.argv.slice(2);
if (!emptyDir || !straceFile || !message) {
  process.stderr.write(
    "usage: sandbox-argv.mjs <emptyDir> <straceFile> <message>\n",
  );
  process.exit(2);
}

// Overlay files land under <emptyDir>/.sandbox (prepareOverlays owns creation).
const { emptyJson, emptyTxt } = prepareOverlays("opencode", emptyDir);

const supported = detectBwrapSupport();
if (!supported) {
  process.stderr.write("bwrap not usable\n");
  process.exit(3);
}

const hostHome = process.env.HOME;
const { cmd, args } = wrapAgent({
  cli: "opencode",
  args: ["run", "--pure", "-m", "bogus/bogus", message],
  hostHome,
  configHome: process.env.XDG_CONFIG_HOME || join(hostHome, ".config"),
  emptyJson,
  emptyTxt,
  supported,
});

// Splice strace immediately before the child command so we trace opencode.
// lastIndexOf: the wrapper's own args never contain a bare "opencode" token;
// only the child command does.
const i = args.lastIndexOf("opencode");
if (i < 0) {
  process.stderr.write("no opencode token in wrapped args\n");
  process.exit(4);
}
const spliced = [
  ...args.slice(0, i),
  "strace",
  "-f",
  "-e",
  "trace=openat",
  "-e",
  "signal=none",
  "-o",
  straceFile,
  ...args.slice(i),
];

process.stdout.write([cmd, ...spliced].join("\n") + "\n");
