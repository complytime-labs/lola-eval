"""Tests for the version doc-sync helper."""

from lola_eval.version_docs import main, sync_version_in_text


def test_rewrites_rpm_filename():
    text = "sudo dnf install ./dist/lola-eval-0.2.0-1.el10.x86_64.rpm"
    out = sync_version_in_text("0.2.0", "0.3.0", text)
    assert out == "sudo dnf install ./dist/lola-eval-0.3.0-1.el10.x86_64.rpm"


def test_rewrites_cli_version_line():
    text = "# lola-eval 0.2.0"
    out = sync_version_in_text("0.2.0", "0.3.0", text)
    assert out == "# lola-eval 0.3.0"


def test_rewrites_every_occurrence():
    text = (
        "wget https://example.invalid/releases/lola-eval-0.2.0-1.el10.x86_64.rpm\n"
        "sudo rpm -ivh --nodeps lola-eval-0.2.0-1.el10.x86_64.rpm\n"
    )
    out = sync_version_in_text("0.2.0", "0.3.0", text)
    assert "0.2.0" not in out
    assert out.count("lola-eval-0.3.0-1.el10.x86_64.rpm") == 2


def test_leaves_unrelated_version_tokens_untouched():
    """A bare version token, a different package's pin, and the providers
    package name must not be rewritten — only the two scoped patterns are."""
    text = (
        "promptfoo-0.2.0-rc1\n"
        "see version 0.2.0 of the spec\n"
        "lola-eval-providers 0.2.0\n"
    )
    out = sync_version_in_text("0.2.0", "0.3.0", text)
    assert out == text


def test_idempotent():
    text = "lola-eval-0.2.0-1.el10.x86_64.rpm and lola-eval 0.2.0"
    once = sync_version_in_text("0.2.0", "0.3.0", text)
    twice = sync_version_in_text("0.2.0", "0.3.0", once)
    assert once == twice


def test_main_rewrites_only_changed_files(tmp_path, capsys):
    hit = tmp_path / "README.md"
    hit.write_text("install lola-eval-0.2.0-1.el10.x86_64.rpm")
    miss = tmp_path / "OTHER.md"
    miss.write_text("unrelated 0.2.0 token")

    rc = main(["0.2.0", "0.3.0", str(hit), str(miss)])

    assert rc == 0
    assert hit.read_text() == "install lola-eval-0.3.0-1.el10.x86_64.rpm"
    assert miss.read_text() == "unrelated 0.2.0 token"
    out = capsys.readouterr().out
    assert "README.md" in out
    assert "OTHER.md" not in out
