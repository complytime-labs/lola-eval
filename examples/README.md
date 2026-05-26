# lola-eval examples

Each subdirectory under `examples/` is a self-contained target-project layout (a project that *uses* lola-eval, not lola-eval itself). They are reference fixtures: `task smoke`, `task test:live`, and `task test:profiles` run against them, and they double as copy-from templates for setting up `lola-eval` in a new repo.

The directories are not redundant. Each one isolates a different combination of harness axes — pack mode (Mode 1 in-repo vs. Mode 2 external pinned), profile sweep (none/single/diamond), judge count, calculate-baseline mode, and the config-variant pattern. Pick the one whose combination is closest to what you want to learn or copy.

## Quick chooser

| You want to…                                                                                          | Look at                                                                 | Why this example                                                                                                                                                                                |
| ----------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| See the minimum runnable layout for a real project                                                    | `default/`                                                              | Mode 1 (no `packs:`), single config, one judge, no profiles. The shape `lola-eval init` produces, fleshed out with four real cases.                                                             |
| Run the same suite cheaply in CI and expensively in a periodic live job                               | `default/.lola-eval/config.yaml` + `config.live.yaml`                   | The config-variant pattern: same `test_sets/`, `profiles/`, `baseline.json`; different model/judge/timeout tier per `config.<name>.yaml`.                                                       |
| Prove the framework distinguishes a *quality* failure from an *infrastructure* failure                | `demos/case-005-negative-fail`                                          | Deliberately unsatisfiable rubric: agent runs cleanly, composite falls below `pass_threshold`. Exit code 1 (threshold), not 2/3 (setup/infra).                                                  |
| Test that a `profile`'s `install_modules` directive injects a local lola module before the agent runs | `demos/case-006-profile-skill` + `demos/.lola-eval/config.profile.yaml` | The case ships no in-repo module; the `withgreet` profile installs one. Validates the profile-side of skill provisioning.                                                                       |
| Test that an in-repo `.lola/modules/<x>` directory is auto-scaffolded into the agent's config         | `default/case-004-project-skill`                                        | Mode-1 auto-scaffold. The case fails (agent hits "Unknown skill") if the harness *doesn't* discover and scaffold the in-repo module.                                                            |
| Detect a skill that conflicts with another skill (rather than just adding load)                       | `conflict/` + `lola-eval profile-compare`                               | "Diamond" topology over `none → greet → {greet+farewell, greet+salute} → greet+farewell+salute`. The two 2-skill profiles isolate a specific conflicting skill from generic added-load effects. |
| Exercise *every* harness axis at once (multi-model, multi-judge, baseline+project, multi-profile)     | `showcase/`                                                             | 3 models × 4 cases × 5 profiles × 2 baselines = 120 rows, each scored by 2 judges (consensus). Costly; use `--estimate-cost` first.                                                             |
| See how to keep an agent-created `node_modules/` out of the post-run diff                             | `default/case-003-ts-npm`                                               | Validates the default gitignore baseline (`node_modules/`, `__pycache__/`, …): only intentional file changes reach the judge and drift store.                                                   |

## Pattern reference

Each pattern below is demonstrated by one or more examples. Use these as copy-from anchors when authoring your own `.lola-eval/`.

### Mode 1: in-repo (no `packs:` block)

Demonstrated by: every example here.

When the config has no `packs:` key, every row uses `pack_id="project"` — a sentinel meaning "no `lola install` runs." The agent is measured against its baseline behaviour on the test cases, optionally with an in-repo module auto-scaffolded into its config (see `default/case-004-project-skill`).

This is the right shape when the subject under test is the *project itself* (its prompts, its in-repo modules, its starters) rather than an externally distributed lola pack.

### Mode 2: external pinned packs

Not demonstrated under `examples/` (requires a pack the runner can `lola install`). The shape is documented in `docs/walkthrough.md` Step 7; the `default/.lola-eval/config.yaml` header points to it and explains the `calculate_baseline: true` toggle that pairs an `exec_mode=none` pass with the `exec_mode=project` pass for lift calculations.

`showcase/.lola-eval/config.yaml` sets `calculate_baseline: true` while remaining in Mode 1, so each cell produces both a project-pass row and a none-pass row — the lift denominator without needing an external pack.

### Config variants (`config.<name>.yaml`)

Demonstrated by: `default/` (`config.yaml`, `config.live.yaml`), `demos/` (`config.yaml`, `config.profile.yaml`).

A single `.lola-eval/` directory can hold multiple sibling configs that share `test_sets/`, `profiles/`, and `baseline.json`. Select with `--config <path>`. Common splits:

- `config.yaml` — the cheap CI matrix.
- `config.live.yaml` — opt-in, real-cost run (raised `timeouts:` block, pinned judges, no `junit_xml`/`github_summary`).
- `config.profile.yaml` — same fixtures, different `profiles:` list.

This is the recommended way to evaluate the same suite against different targets/judges without duplicating fixtures or maintaining wrapper scripts.

### Profiles

Demonstrated by:

- `demos/case-006-profile-skill` + `demos/.lola-eval/profiles/withgreet.yaml` — single profile that uses `install_modules` to inject a local module into the agent's project config.
- `conflict/` — five profiles forming a *diamond* over skill count (`none`, `greet`, `greet-farewell`, `greet-salute`, `greet-farewell-salute`).
- `showcase/` — five profiles scaled by *size* (`none`, `small`, `medium`, `large`, `combined`) where `combined` deliberately overlaps two Python advisors to exercise the same conflict-detection path on richer tasks.

Profiles add a configuration axis orthogonal to packs. Use them when the question is "does *this configuration* of the agent runtime produce different results on the same task?" — not "does this content in the workdir change behaviour?" (that's packs).

### Skill-conflict detection (diamond topology)

Demonstrated by: `conflict/`.

The five-profile sweep is a deliberate combinatorial shape:

```
                     greet-farewell-salute    (3 skills)
                    /                      \
       greet-farewell                       greet-salute
       (2 skills, control)                  (2 skills, conflict candidate)
                    \                      /
                     greet                  (1 skill)
                       |
                     none                   (0 skills, baseline)
```

`greet-farewell` and `greet-salute` have the same skill *count* but different skill *content*. If `greet-salute`'s composite drops more than `--tolerance` below `greet-farewell`'s, the `salute` module is the source of degradation — not "more skills slows the agent down" in general. Pair this sweep with `lola-eval profile-compare`:

```sh
lola-eval test --config examples/conflict/.lola-eval/config.yaml
lola-eval profile-compare --config examples/conflict/.lola-eval/config.yaml
```

### Negative cases (proving the framework grades correctly)

Demonstrated by:

- `demos/case-005-negative-fail` — text-only case where the rubric gates on a token the prompt never provides. A well-behaved agent runs cleanly, composite stays low, exit code 1 (threshold failure).
- `showcase/case-D-negative-skill-fail` — text-only case where high scores require invoking a skill that's only present under the `combined` profile. Validates that lift is real: profiles `none`/`small`/`medium` score below `pass_threshold`, `combined` clears it.

These cases must *intentionally* fail in some configurations; that's the point. A non-zero exit code is expected when invoking them in isolation.

### Multi-judge consensus

Demonstrated by: `showcase/.lola-eval/config.yaml` (two judges, `aggregation: mean`, `disagreement_threshold: 0.15`).

Other examples use a single pinned judge to keep drift comparable and costs low. Use multi-judge when you can afford it: `disagreement_action` surfaces rows where the judges disagree beyond the threshold, which is a useful signal for ambiguous rubrics.

### Hermetic post-run diff

Demonstrated by: `default/case-003-ts-npm`.

The case runs `npm install`, which creates `node_modules/`. The default `.gitignore` baseline (`node_modules/`, `__pycache__/`, `.venv/`, `vendor/`, `dist/`, …) means none of that reaches the judge or the fingerprint — only the intentional source change does. Copy this case when you want to verify that your custom `include_ignored_paths` doesn't accidentally widen the diff window.

## Running the examples

The Taskfile wires the live runners; the README of the root project documents what they cost. In short:

```sh
task smoke              # examples/default/, in-repo, costs real API tokens
task test:live          # examples/default/config.live.yaml, asserts invariants
task test:profiles      # examples/conflict/, runs the diamond + profile-compare
```

`showcase/` is not driven by a single Taskfile entry because it's expensive (120 cells per run, each scored by both judges). Always preview cost first:

```sh
lola-eval test --config examples/showcase/.lola-eval/config.yaml --estimate-cost
```

Then drop `--estimate-cost` once the budget looks right, or narrow with `--case` / `--profile` for iteration.

## Adding a new example

Place new fixtures under a fresh `examples/<name>/.lola-eval/`. Conventions:

1. Header-comment the `config.yaml` with what the example demonstrates and the exact `lola-eval test` invocation that runs it.
1. Cross-reference the example from this README's quick-chooser table and, if it warrants its own pattern, the pattern reference below it.
1. If the example is opt-in / costs money, add a Taskfile entry with a `prompt:` confirmation rather than running it from `task test`.
