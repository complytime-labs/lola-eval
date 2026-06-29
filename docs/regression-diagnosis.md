# Diagnosing a score regression

A worked workflow for localizing why an eval score dropped, using only built-in commands. No stash/checkout dances — `compare-ref` runs both git refs in throwaway worktrees and never touches your working tree or current branch.

## 1. Is it real? (variance first)

Single-run composites carry meaningful noise. An eval row is non-deterministic end to end — the agent, its tool-call ordering, the judge — and bare-model cells have been observed swinging ~0.2 between identical runs. Rule of thumb: a single-run drop under ~0.15–0.2 is often noise, not signal.

Before debugging anything, do two cheap checks.

**Re-run the cell.** `--case` limits the matrix to one task_id, so this costs one case-width, not a full sweep:

```sh
lola-eval test --case my-case
```

If the second run lands back near the old score, you were looking at variance. Add `--pack` or `--profile` to narrow further when your matrix has those axes.

**Check the historical spread.** The `--cell` argument is `cli/model/task_id`:

```sh
lola-eval graph --cell claude-code/sonnet/my-case
```

This renders an ANSI chart of every recorded run for the cell, one line per pack, with the rubric's pass line drawn across (`--threshold` overrides it). If the "regression" sits inside the band the cell has always bounced around in, stop here.

Only a drop that reproduces across re-runs — or lands outside the historical spread — is worth localizing.

## 2. Which commit? (compare-ref)

```sh
lola-eval compare-ref main HEAD
```

`compare-ref` evaluates the repo at two git refs — each checked out into a throwaway detached `git worktree`, run through the full configured matrix, then removed — and prints a per-cell composite diff:

```
compare-ref: main -> HEAD

| Cell | main | HEAD | delta |
| --- | --- | --- | --- |
| claude-code/sonnet/my-case/project/none | 0.84 | 0.62 | -0.22 |
```

Cell keys are `cli/model/task_id/pack_id/profile_id`. A `-` means that ref produced no composite for the cell (the case didn't exist yet, or the row failed to run).

Two things worth knowing:

- **It is non-destructive by construction.** Your branch, working tree, and `.lola-eval/out/` are never touched; each ref's results land in an ephemeral out-dir inside its worktree and are deleted with it. If you have been hand-rolling a `git stash` / `checkout` / `test` / `baseline` loop to answer "which commit broke it", this replaces the whole dance.
- **It runs the matrix twice, at real cost.** Narrow with `--case <task_id>` to pay for one case instead of all of them; `--concurrency` and `--config` behave as in `test`. There is no threshold flag — you read the delta column yourself.

To pin a single commit, walk the suspects manually: `lola-eval compare-ref <suspect>^ <suspect> --case my-case` confirms or clears one commit per invocation.

## 3. Which cell, over time? (drift, lift, graph)

**`lola-eval drift`** compares each fingerprint's latest run against its earliest and prints the signed Δ composite — "did this cell get worse since we started tracking?". The table shows `model (now)` next to `model (then)` because the fingerprint deliberately excludes the model: a fixed config drifting as the model evolves under it is exactly the signal. `--fingerprint <hash>` limits to one cell; `--threshold-fail -0.10` makes it exit non-zero for CI.

**`lola-eval lift`** answers a different question: is the pack still beating the bare baseline? It prints the signed lift % of each pack row against its matching `pack_id=none` row, so it needs `calculate_baseline: true` pairs in history — until then it prints `(no pack-vs-baseline pairs yet …)`. A pack whose lift decays across runs is regressing even if its absolute composite still passes. `--threshold-fail -10.0` gates CI on it.

**`lola-eval graph`** is the raw time series behind both. Omit `--cell` to chart every cell in `runs.db`; use it with the drift table to see *when* a Δ happened, not just that it did.

## 4. What changed in behavior? (transcript-diff)

Once you know which cell and roughly when, diff the runs themselves:

```sh
lola-eval transcript-diff <run_a> <run_b>
```

Both arguments are run_ids. Two places to get them:

- the committed history ledger, `.lola-eval/ledger.jsonl` — each line carries `run_id`, `timestamp`, `composite`, and git provenance, so you can pick "the last good run before commit X" by reading the file at any checkout;
- `lola-eval export --format json` — every historical row from `runs.db`, each with its `run_id` (filter with `--task`, `--since`, `--fingerprint`).

The output is a structured before/after: composite and per-criterion scores, `exit_status`, tool calls, turns, diff bytes, token counters, cost, and duration, each with its signed delta. It warns when the two runs' fingerprints differ — they are then not strictly comparable.

This is where "the agent skipped its verification phase"-class findings come from: one rubric criterion collapsing while the others hold, tool calls halving, output tokens cratering. When the counters point somewhere, read the raw transcripts at `.lola-eval/out/transcripts/<run_id>.jsonl` for the two runs and diff the actual trajectories.

## 5. Lock the finding

Once you know what happened, make the diagnosis durable:

- **`lola-eval baseline update`** at the known-good state promotes it to `baseline.json`; commit that file. With `threshold.mode: regression` (or `both`), the next `lola-eval test` in CI fails any cell whose composite drops more than `tolerance` below that baseline — `baseline diff` is the human-readable delta table for reviewing the change, not the gate itself.
- **`lola-eval snapshot`** appends the runs you just analyzed to the committed ledger (`--dry-run` previews). Each ledger line carries the run_id and git SHA, so the next person diagnosing a regression starts at step 4 with the evidence already in the repo.
