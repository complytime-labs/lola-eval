"""harness doctor: environment health check."""
from __future__ import annotations
from unittest.mock import patch


from lola_eval import doctor


def test_run_returns_zero_on_healthy(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

    with patch.object(doctor, "_check_cli", return_value=(True, "fake 1.0.0")):
        rc = doctor.run()
    out = capsys.readouterr().out
    assert rc == 0
    assert "claude" in out
    assert "opencode" in out


def test_run_returns_nonzero_on_missing_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    def fake_check(cli):
        return (False, "not found") if cli == "claude" else (True, "v")

    with patch.object(doctor, "_check_cli", side_effect=fake_check):
        rc = doctor.run()
    assert rc == 1


def test_clean_dirs_wipes_state(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    from lola_eval import xdg
    p = xdg.state_dir() / "runs.db"
    p.write_text("data")
    doctor.clean_dirs(state=True, cache=False)
    assert not p.exists()


def test_clean_dirs_wipes_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    from lola_eval import xdg
    p = xdg.work_dir() / "scratch"
    p.mkdir(parents=True, exist_ok=True)
    (p / "a").write_text("x")
    doctor.clean_dirs(state=False, cache=True)
    assert not p.exists()


def test_clean_dirs_target_aware_cache_keeps_baseline(tmp_path):
    """I8: when target_results_dir is set, --cache wipes regenerable
    artifacts but never touches baseline.json or runs.db."""
    target = tmp_path / ".lola-eval"
    (target / "workspace").mkdir(parents=True)
    (target / "workspace" / "old.txt").write_text("stale")
    (target / "transcripts").mkdir()
    (target / "transcripts" / "t.jsonl").write_text("x")
    (target / "reports").mkdir()
    (target / "reports" / "r.html").write_text("html")
    (target / "runs.db").write_text("DB")
    (target / "baseline.json").write_text("{}")

    doctor.clean_dirs(cache=True, state=False, target_results_dir=target)

    assert not (target / "workspace").exists()
    assert not (target / "transcripts").exists()
    assert not (target / "reports").exists()
    # state files survive --cache
    assert (target / "runs.db").exists()
    assert (target / "baseline.json").exists()


def test_clean_dirs_target_aware_state_preserves_baseline(tmp_path):
    """I8: --state wipes runs.db + last-run.json but preserves
    baseline.json (the user committed that)."""
    target = tmp_path / ".lola-eval"
    target.mkdir(parents=True)
    (target / "runs.db").write_text("DB")
    (target / "last-run.json").write_text("[]")
    (target / "baseline.json").write_text("{}")

    doctor.clean_dirs(cache=False, state=True, target_results_dir=target)

    assert not (target / "runs.db").exists()
    assert not (target / "last-run.json").exists()
    assert (target / "baseline.json").exists(), "baseline.json must survive --state"
