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
from typing import TYPE_CHECKING

from dtstylekit.paths import get_outputs_dir, get_presets_dir

if TYPE_CHECKING:
    from dtstylekit.presets.indexer import PresetIndexer

logger = logging.getLogger(__name__)


def add_preset_subcommands(subparsers: argparse._SubParsersAction) -> None:
    """Register 'preset' subcommand."""
    from dtstylekit.presets.cli import add_preset_subcommands as _add

    _add(subparsers)


def add_vlm_subcommands(subparsers: argparse._SubParsersAction) -> None:
    """Register 'vlm' subcommand."""
    from dtstylekit.vlm.cli import add_vlm_parser

    add_vlm_parser(subparsers)


def add_curves_subcommands(subparsers: argparse._SubParsersAction) -> None:
    """Register 'curves' subcommand."""
    from dtstylekit.curves.cli import add_curves_parser

    add_curves_parser(subparsers)


def _load_selected_presets(
    spec: object,
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
    indexer: PresetIndexer | None = None
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


def _resolve_via_index(indexer: PresetIndexer, name: str) -> Path | None:
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


def _search_preset_dirs(name: str) -> Path | None:
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


def cmd_generate(args: argparse.Namespace) -> int:
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
            "ERROR: Preset index not built.\n"
            "  The semantic search index (presets.db + preset_embeddings.npy) is missing.\n"
            "  Fix it in one of three ways:\n"
            "    1. ./setup.sh                     (automatic: locate styles + build index)\n"
            "    2. dtstylekit preset index        (after symlinking a preset library)\n"
            "    3. export DTSTYLEKIT_PRESETS_DIR=/path/to/darktable/data/styles\n"
            "  See the 'Preset library setup' section of the README for details.",
            file=sys.stderr,
        )
        return 1

    searcher = PresetSearcher(db_path, emb_path)

    # Expand glob patterns in --references (e.g. '/path/refs/*.jpeg').
    import glob as _glob

    references: list[Path] = []
    for ref in args.references or []:
        if any(c in ref for c in "*?["):
            references.extend(Path(p) for p in sorted(_glob.glob(ref, recursive=True)))
        else:
            references.append(Path(ref).expanduser())
    references = [p for p in references if p.is_file()]
    if args.references and not references:
        logger.warning("No reference image files matched: %s", args.references)

    try:
        spec, vlm_report, vlm_warnings, analysis = generate_style_spec(
            image_path=args.image,
            direction=args.direction,
            searcher=searcher,
            analyzer=analyze_image,
            registry=IOP_REGISTRY,
            model=args.model,
            references=[str(p) for p in references],  # str | Path union
            refine_iterations=args.refine_iterations,
            refine_raw_path=args.refine_raw,
        )
    except Exception as exc:
        logger.error("Style spec generation failed: %s", exc)
        print(f"ERROR: Style spec generation failed: {exc}", file=sys.stderr)
        return 1

    # Accumulate all warnings in one place
    all_warnings: list[str] = list(vlm_warnings)

    # Load selected presets (with proper error accumulation)
    selected_presets = _load_selected_presets(spec, all_warnings)

    # Guard against empty styles: writing a .dtstyle with neither presets
    # nor adjustments produces a useless file that renders identical to
    # the baseline (visual_check.py reports "no visible effect").  Fail
    # loudly instead of silently shipping a no-op style.  We accept a
    # style with adjustments but no presets (the composer emits only the
    # scalar-adjusted modules) — what we reject is "absolutely nothing".
    if not selected_presets and not getattr(spec, "plugins", None):
        msg = (
            "Cannot generate a style: the VLM returned no selected presets "
            "and no scalar adjustments. Re-run with a different --model or "
            "provide --references that define the target aesthetic."
        )
        logger.error(msg)
        print(f"ERROR: {msg}", file=sys.stderr)
        if all_warnings:
            print("Warnings:", file=sys.stderr)
            for w in all_warnings:
                print(f"  - {w}", file=sys.stderr)
        return 1

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

    # Post-write guard: if the generated file has no enabled plugins (all
    # adjustments were silently skipped by the merger — every blob
    # failed to re-pack), refuse to call the result a style.  This catches
    # the "styled == baseline" symptom that visual_check reports as
    # identical-mean/identical-std.
    try:
        import xml.etree.ElementTree as _ET

        root = _ET.parse(dtstyle_path).getroot()
        enabled_plugins = [
            p for p in root.findall("style/plugin") if (p.findtext("enabled", "1") or "1") == "1"
        ]
        if not enabled_plugins:
            msg = (
                "Generated style has no enabled plugins — every adjustment "
                "was silently dropped by the composer (preset blobs could "
                "not be re-packed). Refusing to ship a no-op style."
            )
            logger.error(msg)
            print(f"ERROR: {msg}", file=sys.stderr)
            try:
                dtstyle_path.unlink()
            except OSError:
                pass
            return 1
    except Exception as exc:  # noqa: BLE001 — post-check is best-effort
        logger.warning("Post-write style check failed: %s", exc)

    try:
        generate_report(spec, selected_presets, analysis, vlm_report, report_path)
    except Exception as exc:
        # Report generation failure is non-fatal
        all_warnings.append(f"Report generation failed: {exc}")
        logger.warning("Report generation failed: %s", exc)

    # Natural-language explanation document (narrative companion to the
    # technical report).  It analyses the reference photographs and
    # explains, in plain language, how they are graded and why each
    # module/parameter of the generated style was chosen.
    if references:
        from dtstylekit.analyzer.pipeline import analyze_reference_hues
        from dtstylekit.composer.explanation import generate_explanation

        explanation_path = output_dir / f"{spec.style_name.replace(' ', '_')}_EXPLICACION.md"
        try:
            reference_analysis = analyze_reference_hues(references)
            generate_explanation(
                spec,
                selected_presets,
                analysis,
                reference_analysis=reference_analysis,
                reference_paths=[Path(p) for p in references],
                output_path=explanation_path,
                lang=args.lang,
            )
            print(f"✓ Explanation: {explanation_path}")
        except Exception as exc:
            all_warnings.append(f"Explanation generation failed: {exc}")
            logger.warning("Explanation generation failed: %s", exc)

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
    # Configure logging for *every* entry point (installed ``dtstylekit``
    # script and ``python -m dtstylekit.cli``).  Without this, the
    # orchestrator's progress logs are silent and a slow VLM call looks
    # like a hang.
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )

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
        help="VLM model (default: gemma3:27b)",
    )
    gen.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output directory (default: ./generated_styles)",
    )
    gen.add_argument(
        "--references",
        nargs="+",
        default=None,
        help="Reference-look images (glob accepted) the VLM derives the "
        "target aesthetic from, e.g. '/path/refs/*.jpeg'",
    )
    gen.add_argument(
        "--refine-iterations",
        type=int,
        default=0,
        help="Enable iterative generate→render→eval refinement (default: 0 = off). "
        "Requires --refine-raw. Each iteration re-prompts VLM with visual feedback.",
    )
    gen.add_argument(
        "--refine-raw",
        default=None,
        help="RAW file path for test renders during iterative refinement. "
        "Required if --refine-iterations > 0.",
    )
    gen.add_argument(
        "--lang",
        choices=("es", "en"),
        default="es",
        help="Language of the natural-language explanation document (default: es).",
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
        help="VLM model (default: gemma3:27b)",
    )
    ana.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output directory (default: ./generated_styles)",
    )
    ana.add_argument(
        "--references",
        nargs="+",
        default=None,
        help="Reference-look images (glob accepted) the VLM derives the "
        "target aesthetic from, e.g. '/path/refs/*.jpeg'",
    )
    ana.add_argument(
        "--lang",
        choices=("es", "en"),
        default="es",
        help="Language of the natural-language explanation document (default: es).",
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
