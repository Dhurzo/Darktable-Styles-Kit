"""Preset resolution semantics (index, display name, path, fallback)."""

from __future__ import annotations

from pathlib import Path

from dtstylekit.presets.indexer import PresetIndexer
from dtstylekit.presets.parser import parse_preset
from dtstylekit.presets.resolver import PresetResolver


def _write_preset(path: Path, name: str) -> Path:
    path.write_text(
        (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<darktable_style version="1.0">\n'
            f"  <info><name>{name}</name><description></description>"
            "<iop_list></iop_list></info>\n"
            "  <style></style>\n"
            "</darktable_style>\n"
        ),
        encoding="utf-8",
    )
    return path


def _indexed_library(tmp_path: Path) -> tuple[Path, Path, Path]:
    preset_dir = tmp_path / "presets"
    preset_dir.mkdir()
    sepia = _write_preset(
        preset_dir / "examples_colors_sepia.dtstyle",
        "_l10n_darktable|_l10n_examples|_l10n_colors|_l10n_sepia",
    )
    other = _write_preset(
        preset_dir / "examples_colors_faded.dtstyle",
        "_l10n_darktable|_l10n_examples|_l10n_colors|_l10n_faded",
    )
    db_path = tmp_path / "presets.db"
    presets = [parse_preset(sepia), parse_preset(other)]
    assert all(preset is not None for preset in presets)
    with PresetIndexer(db_path) as indexer:
        indexer.index_presets([preset for preset in presets if preset is not None])
    return db_path, preset_dir, sepia


def test_resolve_filename_via_index(tmp_path: Path) -> None:
    db_path, preset_dir, sepia = _indexed_library(tmp_path)
    with PresetResolver(index_path=db_path, preset_dirs=[preset_dir]) as resolver:
        assert resolver.resolve("examples_colors_sepia.dtstyle") == sepia


def test_resolve_display_name_via_index(tmp_path: Path) -> None:
    db_path, preset_dir, sepia = _indexed_library(tmp_path)
    with PresetResolver(index_path=db_path, preset_dirs=[preset_dir]) as resolver:
        assert resolver.resolve("sepia") == sepia


def test_resolve_direct_path_without_index(tmp_path: Path) -> None:
    db_path, preset_dir, sepia = _indexed_library(tmp_path)
    with PresetResolver(index_path=tmp_path / "missing.db", preset_dirs=[preset_dir]) as resolver:
        assert resolver.resolve(str(sepia)) == sepia


def test_resolve_falls_back_to_preset_dirs(tmp_path: Path) -> None:
    db_path, preset_dir, sepia = _indexed_library(tmp_path)
    with PresetResolver(index_path=tmp_path / "missing.db", preset_dirs=[preset_dir]) as resolver:
        assert resolver.resolve("examples_colors_sepia.dtstyle") == sepia


def test_missing_preset_is_reported(tmp_path: Path) -> None:
    db_path, preset_dir, _ = _indexed_library(tmp_path)
    warnings: list[str] = []
    with PresetResolver(index_path=db_path, preset_dirs=[preset_dir]) as resolver:
        assert resolver.load_many(["nope"], warnings) == []
    assert any("Preset not found" in warning for warning in warnings)


def test_load_many_keeps_valid_presets(tmp_path: Path) -> None:
    db_path, preset_dir, sepia = _indexed_library(tmp_path)
    warnings: list[str] = []
    with PresetResolver(index_path=db_path, preset_dirs=[preset_dir]) as resolver:
        loaded = resolver.load_many(["sepia", "nope"], warnings)
    assert [preset.file_path for preset in loaded] == [sepia]
    assert len(warnings) == 1
