"""``dtstylekit analyze`` subcommand.

Loads an image, runs the full analyzer pipeline, and emits either a
compact prompt-view or the full dataclass view as JSON to stdout. Exit
codes follow the conventional CLI pattern: 0 on success, 1 on failure,
2 on usage error.

The module exposes a single ``add_analyze_subcommand`` so the future
top-level CLI (:mod:`dtstylekit.cli`, Phase 6) can attach this to the
parent parser without copy-paste.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .pipeline import analyze_image


def add_analyze_subcommand(
    subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> None:
    """Register the ``analyze`` subcommand on ``subparsers``."""
    parser = subparsers.add_parser(
        "analyze",
        help="Analyze an image and print its signals as JSON.",
    )
    parser.add_argument(
        "image",
        type=Path,
        help="Path to a JPEG / TIFF / PNG file.",
    )
    parser.add_argument(
        "--bins",
        type=int,
        default=64,
        help="Histogram bins per channel (default 64).",
    )
    parser.add_argument(
        "--prompt",
        action="store_true",
        help="Emit the compact prompt-view JSON instead of the full dataclass view.",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON indent level (default 2; 0 produces compact output).",
    )


def cmd_analyze(args: argparse.Namespace) -> int:
    """Execute the ``analyze`` command. Returns the exit code."""
    image_path: Path = args.image

    if not image_path.exists():
        print(f"Error: image not found: {image_path}", file=sys.stderr)
        return 1

    try:
        analysis = analyze_image(image_path, bins=args.bins)
    except Exception as exc:  # pragma: no cover — defensive
        print(f"Error: analysis failed: {exc!s}", file=sys.stderr)
        return 1

    payload = analysis.to_prompt_dict() if args.prompt else analysis.to_dict()

    indent: int | None = args.indent if args.indent > 0 else None
    print(json.dumps(payload, indent=indent, default=_json_default))
    return 0


def main_analyze(args: argparse.Namespace) -> int:
    """Top-level entry used by the future parent CLI."""
    return cmd_analyze(args)


# ---------------------------------------------------------------------------
# JSON serialisation helper
# ---------------------------------------------------------------------------


def _json_default(value: object) -> object:
    """Fallback serializer for objects ``json.dumps`` does not know.

    Used only as a defensive measure — :meth:`ImageAnalysis.to_dict` already
    returns plain types, but the pipeline may surface EXIF values that are
    bytes / IfdTag subclasses in some edge cases.
    """
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="replace")
        except Exception:
            return repr(value)
    return str(value)
