"""Shared pytest fixtures for the lola-eval test suites.

Tests and the code under test shell out to ``git``. Without isolation, those
invocations inherit the developer's global and system git config, which makes
the suite non-hermetic: a global ``commit.gpgsign = true`` (with no signing key
in the sandbox) makes every test commit fail with exit 128, and a differing
``init.defaultBranch`` changes results. Point git's global and system config at
/dev/null for the whole session so results depend only on per-repo config the
tests set themselves. Mirrors the same isolation in
``tests/node/git_helpers.test.js``.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True, scope="session")
def _isolate_git_config():
    keys = ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM")
    saved = {k: os.environ.get(k) for k in keys}
    for k in keys:
        os.environ[k] = os.devnull
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
