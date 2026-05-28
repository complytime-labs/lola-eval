"""Profile setup install_modules directive (#3, list form)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from lola_eval.profile import SetupDirectives


def test_install_modules_accepts_list():
    sd = SetupDirectives(install_modules=["./a", "./b"])
    assert sd.install_modules == ["./a", "./b"]


def test_install_modules_coerces_bare_string():
    sd = SetupDirectives(install_modules="./mymod")
    assert sd.install_modules == ["./mymod"]


def test_install_modules_empty_string_becomes_empty_list():
    sd = SetupDirectives(install_modules="")
    assert sd.install_modules == []


def test_install_modules_defaults_empty():
    sd = SetupDirectives()
    assert sd.install_modules == []


def test_old_install_module_key_rejected():
    with pytest.raises(ValidationError):
        SetupDirectives(install_module="./mymod")
