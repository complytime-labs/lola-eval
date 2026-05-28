"""_resolve_promptfoo_cmd prefers the bundle bin over the npx fallback."""

from __future__ import annotations

import stat

from lola_eval import runner


def test_resolver_uses_bundle_bin_before_npx(tmp_path, monkeypatch):
    # No promptfoo on PATH, no explicit override -> must find the bundle bin.
    monkeypatch.setattr(
        runner.shutil, "which", lambda name: None if name == "promptfoo" else f"/usr/bin/{name}"
    )
    monkeypatch.delenv("LOLA_PROMPTFOO_BIN", raising=False)

    fake_bin = tmp_path / "promptfoo"
    fake_bin.write_text("#!/bin/sh\necho fake\n")
    fake_bin.chmod(fake_bin.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(runner, "_BUNDLE_PROMPTFOO_BIN", fake_bin)

    assert runner._resolve_promptfoo_cmd() == [str(fake_bin)]


def test_resolver_falls_back_to_npx_when_no_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(
        runner.shutil, "which", lambda name: None if name == "promptfoo" else f"/usr/bin/{name}"
    )
    monkeypatch.delenv("LOLA_PROMPTFOO_BIN", raising=False)
    monkeypatch.setattr(runner, "_BUNDLE_PROMPTFOO_BIN", tmp_path / "does-not-exist")

    assert runner._resolve_promptfoo_cmd() == ["/usr/bin/npx", "--no-install", "promptfoo"]
