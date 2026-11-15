"""Pytest fixtures: fresh demo source DB + temp work dir per test session."""
from __future__ import annotations

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.generate_demo import generate  # noqa: E402


@pytest.fixture(scope="session")
def source_db(tmp_path_factory) -> str:
    path = str(tmp_path_factory.mktemp("data") / "source.db")
    generate(path, seed=20261115)
    return path


@pytest.fixture()
def tmp_target(tmp_path) -> str:
    return str(tmp_path / "target.db")


@pytest.fixture()
def tmp_state(tmp_path) -> str:
    return str(tmp_path / "state.db")
