"""Profile setup install_module directive (#3)."""

from __future__ import annotations

from lola_eval.profile import SetupDirectives


def test_setup_directives_accepts_install_module():
    sd = SetupDirectives(install_module="./mymod")
    assert sd.install_module == "./mymod"


def test_setup_directives_install_module_defaults_empty():
    sd = SetupDirectives()
    assert sd.install_module == ""
