"""Matrix -> promptfoo workspace materializer + invoker.

Constructs a promptfoo configuration on the fly inside
`<results_dir>/workspace/`, copies the bundled providers + judge into it,
shells out to `promptfoo` (or `npx --no-install promptfoo` as a fallback),
and reads the resulting rows back from runs.db so the threshold engine
has structured RowResult objects to grade.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path

import yaml

from lola_eval.config import LolaEvalConfig
from lola_eval.profile import load_profiles, ProfileConfig
from lola_eval.threshold import RowResult
from lola_eval import xdg
# Back-compat alias: tests import it via runner._connect_for_read; new code
# should prefer `from lola_eval.store import connect_read`.
from lola_eval.store import connect_read as _connect_for_read


class RunnerError(RuntimeError):
    """Raised when the runner cannot execute the requested matrix.

    Distinct from configuration errors (handled by ConfigError) and
    threshold failures (handled via the engine). The CLI surfaces these
    as setup errors (exit 2) with a clear message — no traceback.
    """


def run_matrix(cfg: LolaEvalConfig, target_root: Path,
               pack_filter=None, case_filter=None,
               no_baseline=False, concurrency=None,
               profile_filter=None) -> list[RowResult]:
    """Execute the configured eval matrix and return RowResult objects.

    Side effects:
      - Materializes <results_dir>/workspace/ with providers + judge.
      - Writes promptfooconfig.yaml + invokes `promptfoo eval`.
      - The judge persists rows to runs.db; we re-read them for grading.
      - Writes <results_dir>/last-run.json with composite scores per row.

    The pack axis is derived from the config mode:
      - Mode 1 (cfg.packs is None): pack_ids = ["project"]
      - Mode 2 (cfg.packs is set):  pack_ids = list(cfg.packs)
    ``calculate_baseline`` prepends "none" to the list in either mode.
    ``no_baseline`` strips "none" again; it's a no-op when "none" wasn't
    going to run anyway. ``pack_filter`` restricts to a single pack_id;
    useful in Mode 2 for iterating on one pack at a time.
    """
    results_dir = target_root / cfg.results_dir
    workspace = results_dir / "workspace"
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)

    data_root = files("lola_eval").joinpath("_data")
    _copy_resource_tree(data_root.joinpath("providers"), workspace / "providers")
    _copy_resource_tree(data_root.joinpath("orchestrator"), workspace / "orchestrator")
    _copy_resource_tree(data_root.joinpath("judges"), workspace / "judges")
    tools_json = data_root.joinpath("tools.json")
    (workspace / "tools.json").write_bytes(tools_json.read_bytes())

    tests_dir = target_root / cfg.tests_dir
    if not tests_dir.exists():
        raise FileNotFoundError(f"tests_dir not found: {tests_dir}")
    cases = sorted(p for p in tests_dir.iterdir() if p.is_dir())
    if case_filter:
        cases = [c for c in cases if c.name == case_filter]
    packs = list(cfg.packs) if cfg.packs is not None else ["project"]
    if cfg.calculate_baseline:
        packs = ["none"] + packs
    if pack_filter is not None:
        packs = [p for p in packs if p == pack_filter]
    if no_baseline:
        packs = [p for p in packs if p != "none"]

    profiles: list[ProfileConfig] = []
    if cfg.profiles_dir is not None:
        profiles_path = target_root / cfg.profiles_dir
        profiles = load_profiles(
            profiles_path,
            common_name=cfg.profiles_common,
            selected=cfg.profiles,
        )
        if profile_filter:
            profiles = [p for p in profiles if p.name == profile_filter]

    if not cases or not packs:
        raise RunnerError(
            f"matrix is empty after filters (cases={len(cases)}, packs={len(packs)}); "
            f"nothing to run"
        )

    _stage_starters(cases, results_dir)

    pf_config = _build_promptfoo_config(
        cfg, target_root, cases, packs, workspace,
        concurrency or cfg.concurrency, profiles=profiles,
    )
    pf_config_path = workspace / "promptfooconfig.yaml"
    pf_config_path.write_text(yaml.safe_dump(pf_config, sort_keys=False))

    pf_output = workspace / "results.json"
    cmd = _resolve_promptfoo_cmd() + ["eval", "-c", str(pf_config_path), "--output", str(pf_output)]
    env = os.environ.copy()
    env["LOLA_TARGET_ROOT"] = str(target_root)
    env["LOLA_TESTS_DIR"] = cfg.tests_dir
    # The trajectory judge runs in a separate `python3` spawned by promptfoo,
    # so it can't read the parent's cfg. Pass results_dir through the env so
    # judge writes runs.db to <target>/.lola-eval/ instead of XDG state.
    env["LOLA_RESULTS_DIR"] = str(results_dir)
    if cfg.profiles_dir is not None:
        env["LOLA_PROFILES_DIR"] = str((target_root / cfg.profiles_dir).resolve())
    # promptfoo spawns its own `python3` from PATH, which won't have the
    # editable lola_eval install. Inject our package's parent dir so the
    # copied trajectory_judge.py can `from lola_eval import ...`.
    import lola_eval as _le_pkg
    pkg_parent = str(Path(_le_pkg.__file__).resolve().parent.parent)
    existing_pp = env.get("PYTHONPATH")
    env["PYTHONPATH"] = pkg_parent + (os.pathsep + existing_pp if existing_pp else "")
    # Pin promptfoo's python interpreter to the same one running us so the
    # judge sees pyyaml, pydantic, etc.
    env.setdefault("PROMPTFOO_PYTHON", sys.executable)
    started_at = datetime.now(tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    promptfoo_timed_out = False
    # Inherit BOTH stdout and stderr so the user sees real-time progress.
    # promptfoo writes its per-row breadcrumbs, judge breadcrumbs, and the
    # final result table to stdout (not stderr); the structured eval data
    # we actually consume lives in the --output JSON file we passed above,
    # so we don't need to capture stdout for parsing. Capturing it instead
    # silences every progress line the user wants to see.
    try:
        result = subprocess.run(
            cmd, check=False, env=env,
            timeout=cfg.runner_timeout_seconds,
            stdout=None, stderr=None, text=True,
        )
        if result.returncode != 0:
            sys.stderr.write(
                f"[lola-eval-runner] promptfoo exited {result.returncode}\n"
            )
            sys.stderr.flush()
    except subprocess.TimeoutExpired:
        sys.stderr.write(
            f"[lola-eval-runner] promptfoo timed out after "
            f"{cfg.runner_timeout_seconds}s\n"
        )
        sys.stderr.flush()
        promptfoo_timed_out = True

    rows = _collect_rows(cfg, target_root, cases, packs, started_at,
                         promptfoo_timed_out=promptfoo_timed_out,
                         profiles=profiles)

    last_run = [
        {
            "cli": r.cli, "model": r.model,
            "task_id": r.task_id, "pack_id": r.pack_id,
            "profile_id": r.profile_id,
            "composite": r.composite,
            "rubric_pass_threshold": r.rubric_pass_threshold,
            "timed_out": r.timed_out,
        }
        for r in rows
    ]
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "last-run.json").write_text(json.dumps(last_run, indent=2) + "\n")
    return rows


def _resolve_promptfoo_cmd() -> list[str]:
    """Return argv prefix that invokes promptfoo.

    Resolution order:
      1. `promptfoo` on PATH (preferred — bundle install or system).
      2. `LOLA_PROMPTFOO_BIN` env var (used by the integration test
         to force a specific local binary regardless of cwd).
      3. `npx --no-install promptfoo` (works inside a repo with promptfoo
         installed in node_modules).
    """
    if shutil.which("promptfoo"):
        return ["promptfoo"]
    override = os.environ.get("LOLA_PROMPTFOO_BIN")
    if override:
        return [override]
    npx = shutil.which("npx")
    if not npx:
        raise FileNotFoundError(
            "promptfoo not found on PATH and `npx` unavailable. "
            "Install promptfoo (npm i -g promptfoo) or run inside the bundle."
        )
    return [npx, "--no-install", "promptfoo"]


def _build_test_vars(target, model, pack, case_dir, task_yaml, rubric_fm,
                     cfg, profile, persona_body):
    """Build the test vars dict for a single promptfoo test row.

    When ``profile`` is not None, profile-level overrides (budget, timeout,
    max_turns, prompt tier, judges, setup directives) are applied on top
    of the task-level defaults.
    """
    is_interactive = target.exec_mode == "interactive"
    sim_model = target.simulated_user_model or model
    primary_judge = cfg.judges[0] if cfg.judges else None

    budget = float(task_yaml.get("budget_usd", 10.0))
    timeout = int(task_yaml.get("timeout_seconds", 600))
    system_prompt = str(task_yaml.get("system_prompt_file", ""))
    followup = task_yaml.get("followup_messages", [])
    max_turns = target.max_turns
    profile_name = "none"
    profile_flags: list[str] = []
    profile_permissions = ""
    profile_skip_permissions = "true"
    judges_for_cell = cfg.judges
    setup_json = "{}"

    if profile:
        profile_name = profile.name
        budget = max(budget, profile.budget)
        timeout = max(timeout, profile.timeout)
        max_turns = profile.max_turns
        if profile.system_prompt_file is not None:
            system_prompt = profile.system_prompt_file
        if profile.post_prompt is not None:
            followup = profile.post_prompt
        if profile.judges is not None:
            judges_for_cell = profile.judges
        setup = profile.setup.get(target.cli)
        if setup:
            profile_flags = setup.flags
            setup_json = json.dumps(setup.model_dump())
        profile_permissions = profile.permissions
        profile_skip_permissions = str(profile.skip_permissions)

    task_prompt = (case_dir / "prompt.md").read_text()
    if profile and profile.prompt is not None:
        task_prompt = profile.prompt
    if profile and profile.pre_prompt:
        task_prompt = profile.pre_prompt + "\n" + task_prompt

    judges_var = json.dumps([
        {"judge_cli": j.cli, "judge_model": j.model}
        for j in (judges_for_cell or [])
    ])
    primary = judges_for_cell[0] if judges_for_cell else primary_judge

    test_vars = {
        "task_id": case_dir.name,
        "task_version": str(task_yaml.get("task_version", "1")),
        "rubric_version": str(rubric_fm.get("rubric_version", "1")),
        "rubric_pass_threshold": float(rubric_fm.get("pass_threshold", 0.6)),
        "pack_id": pack,
        "profile_name": profile_name,
        "target_cli": target.cli,
        "target_model": model,
        "exec_mode": target.exec_mode,
        "invocation": "active" if is_interactive else "passive",
        "judge_cli": primary.cli if primary else target.cli,
        "judge_model": primary.model if primary else model,
        "judges_json": judges_var,
        "aggregation": cfg.aggregation,
        "disagreement_threshold": cfg.disagreement_threshold,
        "disagreement_action": cfg.disagreement_action,
        "judge_timeout_seconds": cfg.judge_timeout_seconds,
        "timeout_seconds": timeout,
        "budget_usd": budget,
        "target_extra_args": str(task_yaml.get("target_extra_args", "")),
        "followup_messages": json.dumps(followup),
        "system_prompt_file": system_prompt,
        "prompt": task_prompt,
        "profile_setup_json": setup_json,
        "profile_flags": json.dumps(profile_flags),
        "profile_permissions": profile_permissions,
        "profile_skip_permissions": profile_skip_permissions,
    }
    if is_interactive:
        test_vars.update({
            "max_turns": max_turns,
            "simulated_user_cli": target.simulated_user_cli,
            "simulated_user_model": sim_model,
            "simulated_user_persona": persona_body,
        })
    return test_vars


def _build_promptfoo_config(cfg: LolaEvalConfig, target_root: Path,
                            cases: list[Path], packs: list[str],
                            workspace: Path, concurrency: int,
                            profiles=None) -> dict:
    """Render the promptfoo eval config from the matrix.

    Each provider entry is keyed by (cli, model). Each test row carries the
    full var set the trajectory judge expects. The python-assert points at
    the judge file we copied into the workspace.
    """
    provider_files = {
        "claude-code": "claude_code_provider.js",
        "opencode": "opencode_provider.js",
    }
    interactive_provider_files = {
        "claude-code": "claude_code_interactive_provider.js",
        "opencode": "opencode_interactive_provider.js",
    }

    # Tests may override the provider for any cli with a stub. The override
    # must be an absolute path to a .js file the runner copies into the
    # workspace so promptfoo can load it. The same override applies to
    # both autonomous and interactive paths so a stub provider can stand
    # in for either.
    override = os.environ.get("LOLA_PROVIDER_OVERRIDE")
    if override:
        override_src = Path(override).resolve()
        override_dst = workspace / "providers" / override_src.name
        override_dst.write_bytes(override_src.read_bytes())
        provider_files = {cli: override_src.name for cli in provider_files}
        interactive_provider_files = {
            cli: override_src.name for cli in interactive_provider_files
        }

    def _provider_filename_for(target) -> str:
        files = (
            interactive_provider_files
            if target.exec_mode == "interactive"
            else provider_files
        )
        name = files.get(target.cli)
        if not name:
            raise ValueError(f"unknown target cli: {target.cli}")
        return name

    def _provider_path_for(target) -> str:
        return f"file://{workspace}/providers/{_provider_filename_for(target)}"

    def _provider_object_for(target, model: str) -> dict:
        """Inline provider object for a single test.

        promptfoo's behavior: if a test sets ``provider:`` to a full
        object, that object overrides the top-level ``providers:`` list
        for that test — promptfoo runs the test exactly once against
        the inlined provider, not once per top-level entry. This is the
        only documented way to prevent matrix doubling when multiple
        (cli, model) cells back onto the same provider .js file: if we
        instead declared two top-level providers with the same id (the
        file://path) and let each test reference them by id, promptfoo
        would fan every test out across all matching providers, doubling
        rows and the LLM bill.

        We still emit a one-entry top-level ``providers:`` because
        promptfoo's config schema requires it ("Exactly one of 'targets'
        or 'providers' must be provided"). The entry is a placeholder —
        every test overrides it.
        """
        return {
            "id": _provider_path_for(target),
            "label": f"{target.cli}:{model}",
            "config": {"target_model": model},
        }

    judge_path = workspace / "judges" / "trajectory_judge.py"

    profile_list = profiles if profiles else [None]
    tests: list[dict] = []
    for case_dir in cases:
        task_yaml = yaml.safe_load((case_dir / "task.yaml").read_text())
        rubric_text = (case_dir / "rubric.md").read_text()
        m = re.match(r"---\n(.*?)\n---\n", rubric_text, re.DOTALL)
        if not m:
            raise ValueError(f"{case_dir / 'rubric.md'}: missing frontmatter")
        rubric_fm = yaml.safe_load(m.group(1)) or {}
        # Interactive targets need a simulated_user.md per case. Loading
        # it once here (per case) and passing the body via vars keeps the
        # JS provider thin and avoids reading the file repeatedly per row.
        persona_path = case_dir / "simulated_user.md"
        persona_body = persona_path.read_text() if persona_path.exists() else ""
        for t in cfg.targets:
            if t.exec_mode == "interactive" and not persona_body:
                raise ValueError(
                    f"target {t.cli}/{t.models} sets exec_mode=interactive "
                    f"but {persona_path} is missing. Create the file "
                    f"with persona instructions for the simulated user."
                )
            for model in t.models:
                for pack in packs:
                    for profile in profile_list:
                        if profile and t.cli not in profile.compatible_targets:
                            continue
                        test_vars = _build_test_vars(
                            t, model, pack, case_dir, task_yaml, rubric_fm,
                            cfg, profile, persona_body,
                        )
                        desc = f"{t.cli}/{model} pack={pack}"
                        if profile:
                            desc += f" profile={profile.name}"
                        desc += f" {case_dir.name}"
                        if t.exec_mode == "interactive":
                            desc += " [interactive]"
                        tests.append({
                            "description": desc,
                            "provider": _provider_object_for(t, model),
                            "vars": test_vars,
                            "assert": [{
                                "type": "python",
                                "value": f"file://{judge_path}",
                            }],
                        })

    # promptfoo requires a top-level `providers:` (or `targets:`) entry
    # even though every test inlines its own provider — see
    # _provider_object_for for the matrix-doubling rationale. Use the
    # first cell as the placeholder; it is overridden on every test.
    first_target = cfg.targets[0]
    first_model = first_target.models[0]
    placeholder_provider = _provider_object_for(first_target, first_model)

    return {
        "description": "lola-eval matrix",
        "providers": [placeholder_provider],
        "defaultTest": {"options": {"timeout": 600000}},
        "tests": tests,
        "evaluateOptions": {"maxConcurrency": concurrency},
    }


def _collect_rows(cfg: LolaEvalConfig, target_root: Path, cases: list[Path],
                  packs: list[str], since: str,
                  promptfoo_timed_out: bool = False,
                  profiles=None) -> list[RowResult]:
    """Read the rows the judge persisted into runs.db for this run.

    Picks the most recent row per (target_cli, target_model, task_id,
    pack_id, profile_id) with timestamp >= `since`. Each row gets one
    of three treatments:

      * judge persisted a row with normal exit_status -> graded normally
      * judge persisted a row with exit_status="judge_error" -> surfaced
        with ``failure_kind="judge_error"`` and the judge's
        error_message in failure_reason
      * judge did not persist anything -> if the parent promptfoo
        subprocess timed out we mark it ``target_timeout``; otherwise
        we mark it ``no_run_produced`` so the user sees the right cause
        instead of a generic "timeout" message that masks judge crashes,
        sqlite contention, import errors, etc.
    """
    db = xdg.db_path_for_target(target_root, cfg)
    rows: list[RowResult] = []
    case_ids = [c.name for c in cases]
    profile_ids = [p.name for p in profiles] if profiles else ["none"]
    rubric_threshold_by_task = {
        c.name: _read_rubric_threshold(c / "rubric.md")
        for c in cases
    }

    no_run_reason = (
        "judge did not persist a row (promptfoo crashed, sqlite contention, "
        "trajectory_judge import error, etc.); check stderr above for the "
        "actual cause"
    )

    if not db.exists():
        # No DB yet: every (target,case,pack,profile) is missing.
        for t in cfg.targets:
            for model in t.models:
                for case_id in case_ids:
                    for pack in packs:
                        for profile_id in profile_ids:
                            if promptfoo_timed_out:
                                rows.append(RowResult(
                                    cli=t.cli, model=model, task_id=case_id, pack_id=pack,
                                    profile_id=profile_id,
                                    composite=0.0,
                                    rubric_pass_threshold=rubric_threshold_by_task[case_id],
                                    timed_out=True,
                                    failure_kind="target_timeout",
                                    failure_reason=(
                                        f"promptfoo exceeded {cfg.runner_timeout_seconds}s "
                                        f"and no row was persisted before timeout"
                                    ),
                                ))
                            else:
                                rows.append(RowResult(
                                    cli=t.cli, model=model, task_id=case_id, pack_id=pack,
                                    profile_id=profile_id,
                                    composite=0.0,
                                    rubric_pass_threshold=rubric_threshold_by_task[case_id],
                                    failure_kind="no_run_produced",
                                    failure_reason=no_run_reason,
                                ))
        return rows

    conn = _connect_for_read(db)
    for t in cfg.targets:
        for model in t.models:
            for case_id in case_ids:
                for pack in packs:
                    for profile_id in profile_ids:
                        row = conn.execute(
                            "SELECT scores_json, exit_status, error_message, "
                            "judge_disagreement FROM runs "
                            "WHERE target_cli=? AND target_model=? AND task_id=? "
                            "AND pack_id=? AND profile_id=? AND timestamp >= ? "
                            "ORDER BY timestamp DESC LIMIT 1",
                            (t.cli, model, case_id, pack, profile_id, since),
                        ).fetchone()
                        if row is None:
                            if promptfoo_timed_out:
                                rows.append(RowResult(
                                    cli=t.cli, model=model, task_id=case_id, pack_id=pack,
                                    profile_id=profile_id,
                                    composite=0.0,
                                    rubric_pass_threshold=rubric_threshold_by_task[case_id],
                                    timed_out=True,
                                    failure_kind="target_timeout",
                                    failure_reason=(
                                        f"promptfoo exceeded {cfg.runner_timeout_seconds}s "
                                        f"and no row was persisted before timeout"
                                    ),
                                ))
                            else:
                                rows.append(RowResult(
                                    cli=t.cli, model=model, task_id=case_id, pack_id=pack,
                                    profile_id=profile_id,
                                    composite=0.0,
                                    rubric_pass_threshold=rubric_threshold_by_task[case_id],
                                    failure_kind="no_run_produced",
                                    failure_reason=no_run_reason,
                                ))
                            continue
                        if row["exit_status"] == "judge_error":
                            # Judge subprocess crashed. Surface the original
                            # error_message so the user sees the actual cause
                            # instead of a generic threshold-failure message.
                            scores = json.loads(row["scores_json"]) if row["scores_json"] else {}
                            explanation = scores.get("explanation") or ""
                            msg = row["error_message"] or explanation or "no detail available"
                            rows.append(RowResult(
                                cli=t.cli, model=model, task_id=case_id, pack_id=pack,
                                profile_id=profile_id,
                                composite=0.0,
                                rubric_pass_threshold=rubric_threshold_by_task[case_id],
                                failure_kind="judge_error",
                                failure_reason=msg,
                            ))
                            continue
                        if row["exit_status"] == "setup_error":
                            # Provider couldn't prepare the workdir or install
                            # the pack. The judge persists these so we can
                            # surface the actual cause (e.g. "Module not
                            # found" from `lola install`) instead of letting
                            # them collapse into a misleading "composite 0.0
                            # below threshold" or generic "no_run_produced".
                            msg = row["error_message"] or "no detail available"
                            rows.append(RowResult(
                                cli=t.cli, model=model, task_id=case_id, pack_id=pack,
                                profile_id=profile_id,
                                composite=0.0,
                                rubric_pass_threshold=rubric_threshold_by_task[case_id],
                                failure_kind="setup_error",
                                failure_reason=msg,
                            ))
                            continue
                        if row["exit_status"] == "judge_disagreement":
                            # Variance-aware fail: composite is real, but the
                            # judges disagreed beyond cfg.disagreement_threshold
                            # and the user opted in to treating it as a failure.
                            scores = json.loads(row["scores_json"]) if row["scores_json"] else {}
                            composite_val = scores.get("composite")
                            if composite_val is None:
                                composite_val = 0.0
                            disagreement = row["judge_disagreement"]
                            msg = row["error_message"] or "judges disagreed beyond threshold"
                            rows.append(RowResult(
                                cli=t.cli, model=model, task_id=case_id, pack_id=pack,
                                profile_id=profile_id,
                                composite=float(composite_val),
                                rubric_pass_threshold=rubric_threshold_by_task[case_id],
                                judge_disagreement=(
                                    float(disagreement) if disagreement is not None else None
                                ),
                                failure_kind="judge_disagreement",
                                failure_reason=msg,
                            ))
                            continue
                        scores = json.loads(row["scores_json"])
                        composite = scores.get("composite")
                        if composite is None:
                            composite = 0.0
                        disagreement = row["judge_disagreement"]
                        rows.append(RowResult(
                            cli=t.cli, model=model, task_id=case_id, pack_id=pack,
                            profile_id=profile_id,
                            composite=float(composite),
                            rubric_pass_threshold=rubric_threshold_by_task[case_id],
                            timed_out=row["exit_status"] == "target_timeout",
                            judge_disagreement=(
                                float(disagreement) if disagreement is not None else None
                            ),
                        ))
    conn.close()
    return rows


def _stage_starters(cases: list[Path], results_dir: Path) -> None:
    """Clone starter repos into <results_dir>/staging/<task_id> for cases
    that declare a ``starter_url`` in task.yaml.

    The staging directory is reused across runs: if the staged path already
    exists the clone is skipped. This avoids re-cloning identical repos on
    every matrix invocation while still picking up new cases.
    """
    for case_dir in cases:
        task_yaml = yaml.safe_load((case_dir / "task.yaml").read_text())
        url = task_yaml.get("starter_url")
        if not url:
            continue
        staging_dir = results_dir / "staging"
        staged = staging_dir / case_dir.name
        if staged.exists():
            return
        staging_dir.mkdir(parents=True, exist_ok=True)
        ref = task_yaml.get("starter_ref")
        shallow = task_yaml.get("starter_shallow_since", "30 days ago")
        cmd = ["git", "clone", f"--shallow-since={shallow}", "--single-branch"]
        if ref:
            cmd += ["--branch", ref]
        cmd += [url, str(staged)]
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=120)


def _read_rubric_threshold(rubric_path: Path) -> float:
    text = rubric_path.read_text()
    m = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return 0.6
    fm = yaml.safe_load(m.group(1)) or {}
    return float(fm.get("pass_threshold", 0.6))


def _copy_resource_tree(src, dst: Path) -> None:
    """Recursively copy a Traversable importlib.resources tree to dst."""
    dst.mkdir(parents=True, exist_ok=True)
    for entry in src.iterdir():
        target = dst / entry.name
        if entry.is_dir():
            _copy_resource_tree(entry, target)
        else:
            target.write_bytes(entry.read_bytes())
