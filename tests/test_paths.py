"""Tests for portable path resolution helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from dtstylekit.paths import expand_paths, get_generated_dir


def test_expand_paths_expands_user_before_glob(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    refs = home / "refs"
    refs.mkdir(parents=True)
    first = refs / "a.jpg"
    first.write_bytes(b"x")
    (refs / "b.jpg").write_bytes(b"x")
    monkeypatch.setenv("HOME", str(home))

    assert expand_paths(["~/refs/*.jpg"]) == [first, refs / "b.jpg"]


def test_expand_paths_filters_missing_literals(tmp_path: Path) -> None:
    assert expand_paths([str(tmp_path / "nope.jpg")]) == []


def test_expand_paths_can_keep_missing_literals(tmp_path: Path) -> None:
    missing = tmp_path / "nope.jpg"
    assert expand_paths([missing], require_file=False) == [missing]


def test_get_generated_dir_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DTSTYLEKIT_GENERATED_DIR", str(tmp_path))
    assert get_generated_dir() == tmp_path
