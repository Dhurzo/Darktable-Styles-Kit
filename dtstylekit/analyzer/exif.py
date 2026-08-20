"""EXIF metadata extraction using ``exifread``.

Returns a plain dict of VLM-relevant tags. Missing tags are simply absent
from the dict (no exceptions raised) so the analyzer pipeline is robust
on inputs that lack EXIF (screenshots, stripped JPEGs, etc.).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import exifread

# Base tags the test suite and prompt builder care about.
# Anything else is still pulled in (under an ``exif:<id>`` key) but the
# the prompt filter module decides what to keep.
_BASE_TAGS = (
    "Image Make",
    "Image Model",
    "Image DateTime",
    "EXIF DateTimeOriginal",
    "EXIF ISOSpeedRatings",
    "EXIF FNumber",
    "EXIF ExposureTime",
    "EXIF FocalLength",
    "EXIF WhiteBalance",
    "EXIF Flash",
)


def extract_exif(path: str) -> dict[str, Any]:
    """Extract EXIF tags from ``path``.

    Args:
        path: Path to a JPEG/TIFF file readable by ``exifread``.

    Returns:
        Dict of EXIF tags. Keys are either standard tag names
        (``"EXIF FNumber"``, ``"Image Make"``, ...) or numeric private tags
        (``"exif:37500"``). Values are coerced to JSON-friendly types
        where possible.

    The function never raises on missing/corrupt EXIF — it returns an
    empty dict instead, which the pipeline records as ``"EXIF missing"``.
    """
    p = Path(path)
    if not p.exists():
        return {}

    try:
        with p.open("rb") as f:
            tags = exifread.process_file(f, details=True, stop_tag="UNDEF", strict=False)
    except (OSError, ValueError, AttributeError):
        # Corrupt file, truncated header, etc. — treat as empty.
        return {}

    result: dict[str, Any] = {}
    for name, tag in tags.items():
        if name in _BASE_TAGS or name.startswith("exif:"):
            result[str(name)] = _coerce(tag)
    return result


def _coerce(tag: Any) -> Any:
    """Convert an ``exifread`` tag value into a JSON-friendly type."""
    # Numeric values (ratios, integers implemented as ``IfdTag`` subclasses)
    # expose ``values``/``printable`` differently; try a sequence of fallbacks.
    try:
        values = tag.values
    except AttributeError:
        values = None

    if values is None:
        return str(tag)

    if isinstance(values, list | tuple):
        if len(values) == 1:
            return _scalar(values[0])
        return [_scalar(v) for v in values]

    return _scalar(values)


def _scalar(v: Any) -> Any:
    """Coerce a single EXIF scalar to a JSON-friendly primitive."""
    if v is None:
        return None
    if isinstance(v, str | int | float | bool):
        return v
    if isinstance(v, bytes):
        try:
            return v.decode("utf-8", errors="replace")
        except Exception:
            return repr(v)
    # Fallback: renderable string for unknown types (e.g. ``IfdTag``).
    return str(v)
