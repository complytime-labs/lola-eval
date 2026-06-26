"""bundle.build_bundle: portable .tar.gz evidence packaging."""

from __future__ import annotations

import json
import tarfile

from lola_eval import bundle, store


def _row(**ov) -> dict:
    base = {
        "run_id": "r1",
        "timestamp": "2026-05-20T00:00:00Z",
        "fingerprint": "fp1",
        "target_cli": "claude-code",
        "target_model": "sonnet",
        "target_cli_ver": "2.1",
        "pack_id": "project",
        "task_id": "case-001",
        "task_version": "1",
        "rubric_version": "1",
        "exec_mode": "autonomous",
        "invocation": "passive",
        "judge_cli": "claude-code",
        "judge_model": "sonnet",
        "scores_json": json.dumps({"composite": 0.8, "components": {}, "explanation": ""}),
        "transcript_path": "/tmp/t.jsonl",
        "exit_status": "success",
        "workdir_diff": "HUGE" * 10,
    }
    base.update(ov)
    return base


def test_build_bundle_contains_all_artifacts(tmp_path):
    db = tmp_path / "runs.db"
    store.init_db(db)
    transcript = tmp_path / "t.jsonl"
    transcript.write_text('{"event": "start"}\n')
    row = _row(transcript_path=str(transcript), workdir_diff="diff --git a b\n")
    store.insert_run(db, row)

    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "case-001.md").write_text("# report\n")

    rows = store.export_rows(db, include_diff=True, include_paths=True)
    out = bundle.build_bundle(
        out_path=tmp_path / "evidence.tar.gz",
        db_path=db,
        rows=rows,
        reports_dir=reports,
        lola_eval_version="9.9.9",
        generated_at="2026-06-26T00:00:00+00:00",
    )

    with tarfile.open(out, "r:gz") as tar:
        names = tar.getnames()
        assert "manifest.json" in names
        assert "rows.json" in names
        assert "runs.db" in names
        assert "transcripts/r1.jsonl" in names
        assert "diffs/r1.diff" in names
        assert "reports/case-001.md" in names

        manifest = json.loads(tar.extractfile("manifest.json").read())

    assert manifest["row_count"] == 1
    assert manifest["transcripts"] == ["transcripts/r1.jsonl"]
    assert manifest["diffs"] == ["diffs/r1.diff"]
    assert manifest["reports"] == ["reports/case-001.md"]
    assert manifest["db"] == "runs.db"


def test_build_bundle_skips_missing_transcript(tmp_path):
    db = tmp_path / "runs.db"
    store.init_db(db)
    row = _row(transcript_path=str(tmp_path / "does-not-exist.jsonl"))
    store.insert_run(db, row)
    rows = store.export_rows(db, include_diff=True, include_paths=True)

    out = bundle.build_bundle(
        out_path=tmp_path / "evidence.tar.gz",
        db_path=db,
        rows=rows,
        reports_dir=None,
        lola_eval_version="9.9.9",
        generated_at="2026-06-26T00:00:00+00:00",
    )

    with tarfile.open(out, "r:gz") as tar:
        names = tar.getnames()
        assert not any(n.startswith("transcripts/") for n in names)
        assert "rows.json" in names
        assert "runs.db" in names
        manifest = json.loads(tar.extractfile("manifest.json").read())

    assert manifest["transcripts"] == []


def test_build_bundle_handles_no_reports_dir(tmp_path):
    db = tmp_path / "runs.db"
    store.init_db(db)
    store.insert_run(db, _row())
    rows = store.export_rows(db, include_diff=True, include_paths=True)

    out = bundle.build_bundle(
        out_path=tmp_path / "evidence.tar.gz",
        db_path=db,
        rows=rows,
        reports_dir=None,
        lola_eval_version="9.9.9",
        generated_at="2026-06-26T00:00:00+00:00",
    )

    with tarfile.open(out, "r:gz") as tar:
        names = tar.getnames()
        assert not any(n.startswith("reports/") for n in names)
        manifest = json.loads(tar.extractfile("manifest.json").read())

    assert manifest["reports"] == []


def test_build_bundle_uses_run_id_not_absolute_path_for_arcname(tmp_path):
    db = tmp_path / "runs.db"
    store.init_db(db)
    transcript = tmp_path / "deep" / "nested" / "t.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text("{}\n")
    assert transcript.is_absolute()
    row = _row(run_id="abc123", transcript_path=str(transcript))
    store.insert_run(db, row)
    rows = store.export_rows(db, include_diff=True, include_paths=True)

    out = bundle.build_bundle(
        out_path=tmp_path / "evidence.tar.gz",
        db_path=db,
        rows=rows,
        reports_dir=None,
        lola_eval_version="9.9.9",
        generated_at="2026-06-26T00:00:00+00:00",
    )

    with tarfile.open(out, "r:gz") as tar:
        names = tar.getnames()

    assert "transcripts/abc123.jsonl" in names
    assert not any(str(transcript) in n for n in names)
    assert not any(n.startswith("transcripts/") and tmp_path.name in n for n in names)


def test_build_bundle_sanitizes_traversing_run_id(tmp_path):
    """A crafted run_id (settable via the interactive orchestrator's --run-id)
    must not produce a tar member that escapes transcripts/ or diffs/."""
    db = tmp_path / "runs.db"
    store.init_db(db)
    transcript = tmp_path / "t.jsonl"
    transcript.write_text('{"event": "x"}\n')
    row = _row(
        run_id="../../etc/evil",
        transcript_path=str(transcript),
        workdir_diff="diff --git a b\n",
    )
    store.insert_run(db, row)
    rows = store.export_rows(db, include_diff=True, include_paths=True)

    out = bundle.build_bundle(
        out_path=tmp_path / "evidence.tar.gz",
        db_path=db,
        rows=rows,
        reports_dir=None,
        lola_eval_version="9.9.9",
        generated_at="2026-06-26T00:00:00+00:00",
    )

    with tarfile.open(out, "r:gz") as tar:
        names = tar.getnames()
    # Every member stays under its prefix dir; no ".." path segment escapes.
    for n in names:
        assert ".." not in n.split("/"), n
    assert any(n.startswith("transcripts/") and n.endswith(".jsonl") for n in names)
    assert any(n.startswith("diffs/") and n.endswith(".diff") for n in names)
