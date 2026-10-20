"""Project-wide path resolution.

Centralises the location of the preset library and the generated
``outputs/`` directory so the CLI works regardless of the current working
directory.  Paths can be overridden with environment variables, which also
decouples dtstylekit from the layout of the surrounding darktable checkout
(it historically lived inside ``/home/juan/Repos/darktable``).
"""

from __future__ import annotations

import glob
import os
from collections.abc import Iterable
from pathlib import Path

# dtstylekit/paths.py -> parent is the project root (dtstylekit/..).
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent


def get_presets_dir() -> Path:
    """Return the directory containing the ``.dtstyle`` preset library.

    Override with ``DTSTYLEKIT_PRESETS_DIR``.  Defaults to the bundled
    ``data/presets`` symlink (which points at the darktable style library).
    """
    env = os.environ.get("DTSTYLEKIT_PRESETS_DIR")
    if env:
        return Path(env)
    return PROJECT_ROOT / "data" / "presets"


def get_outputs_dir() -> Path:
    """Return the directory for the SQLite index, embeddings and generated files.

    Override with ``DTSTYLEKIT_OUTPUTS_DIR``.  Defaults to ``outputs/``
    inside the project root.
    """
    env = os.environ.get("DTSTYLEKIT_OUTPUTS_DIR")
    if env:
        return Path(env)
    return PROJECT_ROOT / "outputs"


def get_generated_dir() -> Path:
    """Return the default directory for generated ``.dtstyle`` files.

    Override with ``DTSTYLEKIT_GENERATED_DIR``.  Defaults to
    ``generated_styles/`` inside the project root, so generation works
    regardless of the current working directory.
    """
    env = os.environ.get("DTSTYLEKIT_GENERATED_DIR")
    if env:
        return Path(env)
    return PROJECT_ROOT / "generated_styles"


def expand_paths(
    patterns: Iterable[str | Path],
    *,
    recursive: bool = True,
    require_file: bool = True,
) -> list[Path]:
    """Expand user paths and glob patterns, optionally keeping only files.

    ``glob`` does not expand ``~`` itself, so expansion happens before
    pattern matching.  Literal paths are returned as-is (then filtered by
    ``require_file``); this keeps error messages useful for typos.
    """
    expanded: list[Path] = []
    for raw in patterns:
        path = Path(raw).expanduser()
        text = str(path)
        if any(char in text for char in "*?["):
            expanded.extend(Path(match) for match in sorted(glob.glob(text, recursive=recursive)))
        else:
            expanded.append(path)
    if require_file:
        return [path for path in expanded if path.is_file()]
    return expanded
