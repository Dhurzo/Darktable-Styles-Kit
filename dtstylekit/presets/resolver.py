"""Resolve preset names to files and fully-parsed :class:`Preset` objects.

The VLM can return a filename (``examples_colors_sepia.dtstyle``), a
display name (``sepia``), or a path.  Resolution is centralized here so
the CLI, the generation service and the eval harness all agree on the
lookup order and on which directories are searched.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from dtstylekit.paths import PROJECT_ROOT, get_outputs_dir, get_presets_dir

from .parser import parse_preset

if TYPE_CHECKING:
    from .indexer import PresetIndexer
    from .models import Preset

logger = logging.getLogger(__name__)


class PresetResolver:
    """Resolve preset names against the SQLite index and preset folders.

    Lookup order: index basename/path, index display name, direct path,
    then the configured preset directories.  Missing names are reported
    through the caller's warning list instead of raising.
    """

    def __init__(
        self,
        index_path: Path | None = None,
        preset_dirs: list[Path] | None = None,
    ) -> None:
        self.index_path = (
            Path(index_path) if index_path is not None else get_outputs_dir() / "presets.db"
        )
        if preset_dirs is None:
            preset_dirs = [
                get_presets_dir(),
                PROJECT_ROOT / "data" / "presets",
                PROJECT_ROOT / "dtstylekit" / "data" / "presets",
            ]
        self.preset_dirs = list(dict.fromkeys(Path(d) for d in preset_dirs))
        self._indexer: PresetIndexer | None = None
        self._index_loaded = False

    def _get_indexer(self) -> PresetIndexer | None:
        if self._index_loaded:
            return self._indexer
        self._index_loaded = True
        if not self.index_path.is_file():
            return None
        try:
            from .indexer import PresetIndexer

            indexer = PresetIndexer(self.index_path)
            indexer.connect()
            self._indexer = indexer
        except Exception as exc:  # pragma: no cover - corrupt/missing schema
            logger.warning("Could not open preset index %s: %s", self.index_path, exc)
        return self._indexer

    def resolve(self, name: str) -> Path | None:
        """Resolve ``name`` to a preset file, or return ``None``."""
        if not name:
            return None

        target = Path(name).name
        indexer = self._get_indexer()
        if indexer is not None:
            path = self._resolve_via_index(indexer, name, target)
            if path is not None and path.is_file():
                return path

        candidate = Path(name).expanduser()
        if candidate.is_file():
            return candidate

        return self._search_dirs(target)

    @staticmethod
    def _resolve_via_index(indexer: PresetIndexer, name: str, target: str) -> Path | None:
        conn = indexer.connect()
        row = conn.execute(
            """
            SELECT file_path FROM presets
            WHERE file_path = ? OR file_path LIKE ?
            LIMIT 1
            """,
            (name, f"%{target}"),
        ).fetchone()
        if row and row["file_path"]:
            return Path(row["file_path"])

        row = conn.execute(
            "SELECT file_path FROM presets WHERE display_name = ? LIMIT 1",
            (name,),
        ).fetchone()
        if row and row["file_path"]:
            return Path(row["file_path"])
        return None

    def _search_dirs(self, target: str) -> Path | None:
        for directory in self.preset_dirs:
            if not directory.is_dir():
                continue
            direct = directory / target
            if direct.is_file():
                return direct
            try:
                hits = sorted(directory.glob(target))
            except OSError:
                continue
            for hit in hits:
                if hit.is_file():
                    return hit
        return None

    def load(self, name: str, warnings: list[str] | None = None) -> Preset | None:
        """Resolve and parse one preset, accumulating user-facing warnings."""
        if not name:
            return None
        path = self.resolve(name)
        if path is None:
            message = f"Preset not found in index or on disk: {name}"
            logger.warning(message)
            if warnings is not None:
                warnings.append(message)
            return None
        try:
            preset = parse_preset(path)
        except Exception as exc:
            message = f"Preset parse error for {name}: {exc}"
            logger.warning(message)
            if warnings is not None:
                warnings.append(message)
            return None
        if preset is None:
            message = f"Preset parse returned None: {name}"
            logger.warning(message)
            if warnings is not None:
                warnings.append(message)
        return preset

    def load_many(self, names: list[str], warnings: list[str] | None = None) -> list[Preset]:
        """Resolve and parse a list of names, skipping failures."""
        presets: list[Preset] = []
        for name in names:
            preset = self.load(name, warnings)
            if preset is not None:
                presets.append(preset)
        return presets

    def close(self) -> None:
        if self._indexer is not None:
            self._indexer.close()
            self._indexer = None
            self._index_loaded = True

    def __enter__(self) -> PresetResolver:
        return self

    def __exit__(
        self,
        exc_type: type | None,
        exc_val: BaseException | None,
        exc_tb: object | None,
    ) -> None:
        self.close()
