# Security

This document explains the assumptions, trust boundaries, and known sharp edges
of running `lola-eval` against your own repository. It is targeted at users
who plan to embed the harness in CI or run it against unfamiliar packs.

## Threat model

In scope:

- Local code-execution boundary: the harness exists to run agent CLIs that
  execute arbitrary code in a working directory. The goal is to keep that
  execution from escaping the per-row working directory or modifying state
  outside the eval area.
- Auditability: every cross-trust-boundary action the harness performs
  (workdir wipes, credential reuse, profile installs) should be visible on
  stderr so a user reading a CI log can reconstruct what happened.

Out of scope:

- Sandboxing the agent against itself. The agent under evaluation runs with
  the same privileges as the calling user — see "Permission-bypass default"
  below. Running `lola-eval` against an untrusted pack on a machine with
  credentials, source trees, or production access is **not safe**.
- Network egress. The agent can reach anything the host can reach.
- Supply-chain integrity of the pack ecosystem itself. The harness verifies
  that the *bundled* binaries match their pinned SHA-256s (see
  `lola-eval doctor`), but does not vet pack contents you install.

## Permission-bypass default

By default the harness invokes the agent CLI with its safety prompts
disabled:

- `claude-code`: `--permission-mode bypassPermissions`
  (`src/lola_eval/_data/tools.json`)
- `opencode`: `--dangerously-skip-permissions`
  (`src/lola_eval/_data/tools.json`)

This is intentional: evals are non-interactive, and a CLI that pauses for a
confirmation will time out without producing a row. **It means an agent under
test can read, write, delete, and execute anything the calling user can.** The
harness mitigates this by:

- Constraining the agent's working directory to a per-row path under
  `$XDG_CACHE_HOME/lola-eval/work/` (see "Workdir isolation" below).
- Refusing in `reset.sh` to wipe any path outside `$XDG_CACHE_HOME`.

These mitigations make the *harness's own filesystem actions* safe. They do
not stop the agent from acting on paths it can reach: the agent inherits the
caller's filesystem rights and credentials. A profile can opt back into
permission prompts by setting `skip_permissions: false`, but this only makes
sense for human-driven debugging — under CI the row will hang and time out.

Treat every pack under evaluation as untrusted code. Run on disposable
infrastructure (containers, CI runners, ephemeral VMs) when evaluating
packs you do not control.

## Workdir isolation

The per-row agent workdir is constructed at
`$XDG_CACHE_HOME/lola-eval/work/<task>/<model>/<pack>/<runId>/` (default
root: `~/.cache/lola-eval/work/`). Source: `claude_code_provider.js`.

- The `runId` is a UUIDv4, so concurrent runs of the same matrix cell do not
  collide.
- `reset.sh` refuses (exit 2) to wipe any workdir that is not under
  `$XDG_CACHE_HOME`. This is the harness's last line of defense against a
  configuration bug that points the workdir at, say, the user's home
  directory. Source: `src/lola_eval/_data/orchestrator/reset.sh`.
- Post-run, the runner takes `git diff HEAD` against the workdir (a fresh
  one-commit repo). Only changes reachable from that diff are scored — a
  pack or agent action that mutates files outside the workdir is invisible
  to the judge but is *not* prevented from happening.

## Subscription-auth credential copy

`claude-code` targets running under subscription auth (no
`ANTHROPIC_API_KEY` in the environment) require a host-side credentials
file at `~/.claude/.credentials.json` (or `$CLAUDE_CONFIG_DIR/.credentials.json`).
The harness copies that file into the per-row clean-room config dir before
invoking the agent. Source:
`src/lola_eval/_data/providers/lib/profile_setup.js` (`_preserveClaudeAuth`).

This copy:

- Only fires when the target CLI is `claude-code` and the source file exists.
  No-op for `opencode` and for API-key auth (the env var is in scope already).
- Is logged at copy time:
  `[profile_setup] subscription-auth: copied <src> -> <dst>`
  Use this as the audit signal in CI logs.
- Is independent of `skip_permissions`. A profile that opts back into prompts
  still gets the credential copy — the credential is what makes the CLI
  callable at all under subscription auth, not what controls its prompts.

The clean-room config dir is created under `$TMPDIR` (or
`$<CLI>_CONFIG_DIR/.lola-eval-cleanroom/...` when a profile overrides
`config_env`). It is not gitignored by lola — it lives outside the repo.

## Reporting issues

There is no public upstream forge yet. The RPM's `URL:` field points at
`https://example.invalid/lola-eval` as a placeholder. Report issues via
whatever forge the binary you installed came from.
