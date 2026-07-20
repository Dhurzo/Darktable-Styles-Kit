"""Main CLI entry point for dtstylekit.

Subcommands:
  generate      - end-to-end: image -> analyze -> VLM -> style + report
  preset index  - build/rebuild the preset index
  preset search - search the preset library
  vlm generate  - generate a style spec via VLM (without final assembly)
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dtstylekit.paths import get_outputs_dir, get_presets_dir

logger = logging.getLogger(__name__)


def add_preset_subcommands(subparsers) -> None:
    """Register 'preset' subcommand."""
    from dtstylekit.presets.cli import add_preset_subcommands as _add

    _add(subparsers)


def add_vlm_subcommands(subparsers) -> None:
    """Register 'vlm' subcommand."""
    from dtstylekit.vlm.cli import add_vlm_parser

    add_vlm_parser(subparsers)


def add_curves_subcommands(subparsers) -> None:
    """Register 'curves' subcommand."""
    from dtstylekit.curves.cli import add_curves_parser

    add_curves_parser(subparsers)


def _load_selected_presets(
    spec,
    warnings: list[str],
) -> list:
    """Load preset files referenced by the StyleSpec.

    Accumulates errors/warnings for any presets that could not be
    loaded rather than silently skipping them.  Resolution order:

    1. ``spec.selected_preset_names`` (the VLM's ``selected_presets`` JSON
       field) — each entry is treated as a filename (e.g.
       "examples_colors_sepia.dtstyle") OR as a display name (e.g.
       "sepia").  We look the entry up in the SQLite index so we can use
       the persisted absolute ``file_path``.
    2. ``spec.iop_list`` is NOT a list of preset names (it is a CSV of
       op,priority pairs) — only consulted as a last-resort legacy
       fallback.
    """
    from pathlib import Path

    from dtstylekit.presets.parser import parse_preset

    # Resolve through the index so we use the persisted absolute file_path
    # rather than fragile relative globs.
    index_path = get_outputs_dir() / "presets.db"
    indexer = None
    if index_path.exists():
        from dtstylekit.presets.indexer import PresetIndexer

        indexer = PresetIndexer(index_path)
        indexer.connect()

    try:
        selected_presets: list = []
        preset_names = list(getattr(spec, "selected_preset_names", None) or [])

        # Legacy fallback: spec.iop_list is NOT a preset list, but earlier
        # versions of the code inspected it.  We intentionally do not
        # treat iop_list as preset filenames anymore; only emit a warning
        # when neither source yields presets.
        if not preset_names:
            warnings.append(
                "VLM returned no `selected_presets`; the composer will emit a "
                "style that contains only the scalar adjustments (no baseline)."
            )
            return selected_presets

        for name in preset_names:
            if not name:
                continue
            resolved_path: Path | None = None

            # 1. Direct filename lookup via the index (filename match).
            if indexer is not None:
                resolved_path = _resolve_via_index(indexer, name)

            # 2. Try as a relative path on disk directly.
            if resolved_path is None:
                candidate = Path(name)
                if candidate.exists():
                    resolved_path = candidate

            # 3. Search the preset library by filename.
            if resolved_path is None:
                resolved_path = _search_preset_dirs(name)

            if resolved_path is None:
                warnings.append(f"Preset not found in index or on disk: {name}")
                logger.warning("Preset not found: %s", name)
                continue

            try:
                p = parse_preset(resolved_path)
                if p is not None:
                    selected_presets.append(p)
                else:
                    warnings.append(f"Preset parse returned None: {name}")
                    logger.warning("Preset parse returned None: %s", name)
            except Exception as exc:
                warnings.append(f"Preset parse error for {name}: {exc}")
                logger.warning("Preset parse error for %s: %s", name, exc)

        return selected_presets
    finally:
        if indexer is not None:
            indexer.close()


def _resolve_via_index(indexer, name: str) -> "Path | None":
    """Try to resolve a preset name to a file path via the SQLite index.

    Matches the name against (a) the basename of the stored file_path
    and (b) ``display_name``.  Returns the absolute path or ``None``.
    """
    from pathlib import Path

    target = Path(name).name  # cope with "data/presets/foo.dtstyle"
    conn = indexer.connect()

    # (a) match basename
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

    # (b) match display_name
    row = conn.execute(
        "SELECT file_path FROM presets WHERE display_name = ? LIMIT 1",
        (name,),
    ).fetchone()
    if row and row["file_path"]:
        return Path(row["file_path"])

    return None


def _search_preset_dirs(name: str) -> "Path | None":
    """Search known preset directories for a file by name (fallback)."""
    from pathlib import Path

    target = Path(name).name
    for d in (get_presets_dir(), Path("data/presets"), Path("../../data/styles")):
        if not d.exists():
            continue
        # Try direct hit
        direct = d / target
        if direct.exists():
            return direct
        # Try glob (in case `name` already contains a wildcard)
        try:
            hits = list(d.glob(target))
            if hits:
                return hits[0]
        except OSError:
            continue
    return None


def cmd_generate(args) -> int:
    """End-to-end generation."""
    from dtstylekit.analyzer.pipeline import analyze_image
    from dtstylekit.codec.iop_registry import IOP_REGISTRY
    from dtstylekit.composer.generator import generate_dtstyle
    from dtstylekit.composer.report import generate_report
    from dtstylekit.presets.search import PresetSearcher
    from dtstylekit.vlm.orchestrator import generate_style_spec

    outputs_dir = get_outputs_dir()
    db_path = outputs_dir / "presets.db"
    emb_path = outputs_dir / "preset_embeddings.npy"

    if not db_path.exists() or not emb_path.exists():
        logger.error("Preset index not built. Run: dtstylekit preset index")
        print(
            "ERROR: Preset index not built. Run: dtstylekit preset index",
            file=sys.stderr,
        )
        return 1

    searcher = PresetSearcher(db_path, emb_path)

    spec, vlm_report, vlm_warnings, analysis = generate_style_spec(
        image_path=args.image,
        direction=args.direction,
        searcher=searcher,
        analyzer=analyze_image,
        registry=IOP_REGISTRY,
        model=args.model,
    )

    # Accumulate all warnings in one place
    all_warnings: list[str] = list(vlm_warnings)

    # Load selected presets (with proper error accumulation)
    selected_presets = _load_selected_presets(spec, all_warnings)

    # Generate .dtstyle + report
    output_dir = Path(args.output) if args.output else Path("./generated_styles")
    output_dir.mkdir(parents=True, exist_ok=True)

    dtstyle_path = output_dir / f"{spec.style_name.replace(' ', '_')}.dtstyle"
    report_path = output_dir / f"{spec.style_name.replace(' ', '_')}.md"

    try:
        generate_dtstyle(spec, selected_presets, dtstyle_path, analysis)
    except Exception as exc:
        logger.error("Style generation failed: %s", exc)
        print(f"ERROR: Style generation failed: {exc}", file=sys.stderr)
        return 1

    try:
        generate_report(spec, selected_presets, analysis, vlm_report, report_path)
    except Exception as exc:
        # Report generation failure is non-fatal
        all_warnings.append(f"Report generation failed: {exc}")
        logger.warning("Report generation failed: %s", exc)

    print(f"✓ Generated: {dtstyle_path}")
    if report_path.exists():
        print(f"✓ Report:    {report_path}")
    if all_warnings:
        print(f"⚠ {len(all_warnings)} warning(s):", file=sys.stderr)
        for w in all_warnings:
            print(f"  - {w}", file=sys.stderr)

    return 0


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="dtstylekit",
        description="AI-powered Darktable style generator",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # generate subcommand (primary name)
    gen = subparsers.add_parser(
        "generate",
        help="End-to-end style generation from an image",
    )
    gen.add_argument("image", help="Path to input JPEG/TIFF")
    gen.add_argument(
        "--direction",
        default="auto",
        help="Style direction (e.g., 'cinematic warm portrait')",
    )
    gen.add_argument(
        "--model",
        default=None,
        help="VLM model (default: qwen3-vl:8b)",
    )
    gen.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output directory (default: ./generated_styles)",
    )

    # analyze subcommand (alias for generate)
    ana = subparsers.add_parser(
        "analyze",
        help="Alias for 'generate' — analyze an image and generate a style",
    )
    ana.add_argument("image", help="Path to input JPEG/TIFF")
    ana.add_argument(
        "--direction",
        default="auto",
        help="Style direction (e.g., 'cinematic warm portrait')",
    )
    ana.add_argument(
        "--model",
        default=None,
        help="VLM model (default: qwen3-vl:8b)",
    )
    ana.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output directory (default: ./generated_styles)",
    )

    # preset subcommand
    add_preset_subcommands(subparsers)

    # vlm subcommand
    add_vlm_subcommands(subparsers)

    # curves subcommand
    add_curves_subcommands(subparsers)

    args = parser.parse_args(argv)

    if args.command in ("generate", "analyze"):
        return cmd_generate(args)
    elif args.command == "preset":
        from dtstylekit.presets.cli import main_preset
        return main_preset(args)
    elif args.command == "vlm":
        from dtstylekit.vlm.cli import cmd_vlm_generate
        return cmd_vlm_generate(args)
    elif args.command == "curves":
        from dtstylekit.curves.cli import cmd_curves
        return cmd_curves(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
