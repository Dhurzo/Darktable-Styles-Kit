"""Package version must match the installed project metadata."""

from __future__ import annotations

import tomllib
from pathlib import Path

import dtstylekit

_ROOT = Path(__file__).resolve().parents[1]


def test_version_matches_pyproject() -> None:
    project = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert dtstylekit.__version__ == project["project"]["version"]
