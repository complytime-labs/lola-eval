"""Portable evidence bundle: package DB rows + artifacts into one .tar.gz.

The bundle is self-contained so evidence survives ephemeral environments
(CI runners, containers). It collects the filtered DB rows, a copy of the
sqlite database, each row's transcript and workdir diff, and every report
file, then writes a manifest describing exactly what was included.
"""

from __future__ import annotations

import io
import json
import re
import tarfile
from pathlib import Path

# run_id is usually a generated UUID, but it can be set to a free-form string
# (e.g. the interactive orchestrator's --run-id), so it is not safe to trust as
# a path component. Slugify it before building an arcname so a value like
# "../../etc/x" cannot create a traversing member inside the archive.
_UNSAFE_ARCNAME_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def _safe_component(value: str) -> str:
    return _UNSAFE_ARCNAME_CHARS.sub("_", value)


def build_bundle(
    *,
    out_path: Path,
    db_path: Path,
    rows: list[dict],
    reports_dir: Path | None,
    lola_eval_version: str,
    generated_at: str,
) -> Path:
    """Write a .tar.gz evidence bundle and return out_path."""

    def _add_bytes(tar: tarfile.TarFile, arcname: str, data: bytes) -> None:
        info = tarfile.TarInfo(name=arcname)
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))

    transcripts: list[str] = []
    diffs: list[str] = []
    reports: list[str] = []

    out_path.parent.mkdir(parents=True, exist_ok=True)

    db_present = db_path.exists()

    with tarfile.open(out_path, "w:gz") as tar:
        if db_present:
            tar.add(db_path, arcname="runs.db")

        _add_bytes(tar, "rows.json", json.dumps(rows, indent=2).encode("utf-8"))

        for row in rows:
            run_id = row.get("run_id")
            if not run_id:
                continue
            # SECURITY: build the arcname from a slugified run_id (no path
            # separators), never the on-disk path, so neither a host path nor
            # a crafted run_id can traverse out of transcripts/ or diffs/.
            slug = _safe_component(str(run_id))

            tp = row.get("transcript_path")
            if tp and Path(tp).is_file():
                arcname = f"transcripts/{slug}.jsonl"
                tar.add(tp, arcname=arcname)
                transcripts.append(arcname)

            diff = row.get("workdir_diff")
            if isinstance(diff, str) and diff:
                arcname = f"diffs/{slug}.diff"
                _add_bytes(tar, arcname, diff.encode("utf-8"))
                diffs.append(arcname)

        if reports_dir is not None and reports_dir.is_dir():
            for path in sorted(reports_dir.rglob("*")):
                if path.is_file():
                    rel = path.relative_to(reports_dir)
                    arcname = f"reports/{rel.as_posix()}"
                    tar.add(path, arcname=arcname)
                    reports.append(arcname)

        manifest = {
            "schema_version": "1",
            "lola_eval_version": lola_eval_version,
            "generated_at": generated_at,
            "db": "runs.db" if db_present else None,
            "row_count": len(rows),
            "transcripts": transcripts,
            "diffs": diffs,
            "reports": reports,
        }
        _add_bytes(tar, "manifest.json", json.dumps(manifest, indent=2).encode("utf-8"))

    return out_path
