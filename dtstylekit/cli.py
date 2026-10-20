"""Main CLI entry point for dtstylekit.

Subcommands:
  generate      - end-to-end: image -> analyze -> VLM -> style + report
  apply         - apply a style to images with per-image exposure normalization
  preset index  - build/rebuild the preset index
  preset search - search the preset library
  vlm generate  - generate a style spec via VLM (without final assembly)
"""

from __future__ import annotations

import argparse
import logging
import sys
import tempfile
from pathlib import Path

from dtstylekit.paths import expand_paths, get_outputs_dir

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
    """Load the presets referenced by ``spec.selected_preset_names``.

    Kept as a thin compatibility wrapper for callers that still import it
    from :mod:`dtstylekit.cli`; resolution lives in
    :class:`dtstylekit.presets.resolver.PresetResolver`.
    """
    from dtstylekit.presets.resolver import PresetResolver

    preset_names = list(getattr(spec, "selected_preset_names", None) or [])
    if not preset_names:
        warnings.append(
            "VLM returned no `selected_presets`; the composer will emit a "
            "style that contains only the scalar adjustments (no baseline)."
        )
        return []

    with PresetResolver() as resolver:
        return resolver.load_many(preset_names, warnings)


_RAW_EXTS = {
    ".3fr", ".ari", ".arw", ".bay", ".cr2", ".cr3", ".crw", ".dcr", ".dng",
    ".erf", ".fff", ".iiq", ".k25", ".kdc", ".mef", ".mos", ".mrw", ".nef",
    ".nrw", ".orf", ".pef", ".raf", ".raw", ".rw2", ".rwl", ".sr2", ".srf",
    ".srw", ".x3f",
}


def _is_raw(path: Path) -> bool:
    return path.suffix.lower() in _RAW_EXTS


def _prepare_target(image: Path, refine_raw: str | None) -> tuple[Path, Path | None, Path | None]:
    """Return (image for analysis/VLM, bake image, refine RAW).

    RAW files are not readable by Pillow, so render a JPEG preview for the
    analyzer and VLM while keeping the RAW for style renders.  Passing a
    preview to the safety bake while the final style is applied to the RAW
    made the bake meaningless (0.248 on the JPEG vs 0.080 on the RAW).
    """
    raw = Path(refine_raw).expanduser() if refine_raw else None
    if _is_raw(image):
        from dtstylekit.render import render_preview

        preview = render_preview(
            image, Path(tempfile.mkdtemp(prefix="dtstylekit_preview_"))
        )
        if preview is None:
            raise RuntimeError(f"Could not render a preview from RAW: {image}")
        return preview, (raw or image), (raw or image)
    return image, (raw or image), raw


def cmd_generate(args: argparse.Namespace) -> int:
    """End-to-end generation."""
    from dtstylekit.analyzer.reference_filter import ReferenceFilterConfig
    from dtstylekit.generation import GenerationRequest, GenerationService
    from dtstylekit.presets.search import PresetSearcher

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

    references = expand_paths(args.references or [])
    if args.references and not references:
        logger.warning("No reference image files matched: %s", args.references)

    searcher = PresetSearcher(db_path, emb_path)
    service = GenerationService(searcher)
    try:
        image_path, bake_path, refine_raw = _prepare_target(
            Path(args.image).expanduser(), args.refine_raw
        )
        result = service.generate(
            GenerationRequest(
                image_path=image_path,
                direction=args.direction,
                references=references,
                reference_filter=ReferenceFilterConfig(
                    mode=args.reference_filter,
                    match=args.reference_match,
                    min_refs=args.reference_min,
                ),
                model=args.model,
                temperature=args.temperature if args.temperature is not None else 0.4,
                refine_iterations=args.refine_iterations,
                refine_raw_path=refine_raw,
                bake_path=bake_path,
            )
        )
        if result.filter_result and result.filter_result.summary:
            print(result.filter_result.summary)
        output = service.write(result, args.output, lang=args.lang)
    except Exception as exc:
        logger.error("Style generation failed: %s", exc)
        print(f"ERROR: Style generation failed: {exc}", file=sys.stderr)
        return 1
    finally:
        searcher.close()

    print(f"✓ Generated: {output.dtstyle_path}")
    if output.report_path.exists():
        print(f"✓ Report:    {output.report_path}")
    if output.explanation_path is not None:
        print(f"✓ Explanation: {output.explanation_path}")
    if result.warnings:
        print(f"⚠ {len(result.warnings)} warning(s):", file=sys.stderr)
        for warning in result.warnings:
            print(f"  - {warning}", file=sys.stderr)

    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    """Apply a style to images with per-image exposure normalization."""
    from dtstylekit.export import (
        DEFAULT_TARGET_LUMINANCE,
        apply_style_to_images,
        reference_target_luminance,
    )

    image_args = list(args.images)
    image_paths = expand_paths(image_args)
    if not image_paths:
        logger.error("No images matched: %s", image_args)
        return 1

    if args.target_luminance is not None:
        target = args.target_luminance
    elif args.references:
        refs = expand_paths(args.references)
        if not refs:
            logger.error("No reference images matched: %s", args.references)
            return 1
        from dtstylekit.analyzer.reference_filter import (
            ReferenceFilterConfig,
            filter_references,
        )

        filter_result = filter_references(
            refs,
            ReferenceFilterConfig(
                mode=args.reference_filter,
                match=args.reference_match,
                min_refs=args.reference_min,
            ),
        )
        if filter_result.error:
            print(f"ERROR: {filter_result.error}", file=sys.stderr)
            return 1
        if filter_result.summary:
            print(filter_result.summary)
        refs = filter_result.kept
        if not refs:
            print("ERROR: all reference images were rejected by the filter.", file=sys.stderr)
            return 1
        target = reference_target_luminance(refs, filter_result=filter_result)
        logger.info("Reference luminance: %.3f", target)
    else:
        target = DEFAULT_TARGET_LUMINANCE
        logger.warning(
            "No --references or --target-luminance supplied; using %.2f",
            target,
        )

    try:
        results = apply_style_to_images(
            args.style,
            image_paths,
            args.output,
            target_luminance=target,
            max_clip=args.max_clip,
            preview_width=args.preview_width,
            final_width=args.width,
        )
    except Exception as exc:
        logger.error("Apply failed: %s", exc)
        return 1

    print(f"✓ Exported {len(results)} image(s) to {Path(args.output).expanduser()}")
    for result in results:
        print(
            f"  {result.output_path.name}  EV {result.exposure_ev:+.2f}  "
            f"lum={result.mean_luminance:.3f}  clipped={result.clipped_pct:.1%}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="dtstylekit",
        description="AI-powered Darktable style generator",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # generate subcommand (primary name)
    gen = subparsers.add_parser(
        "generate",
        aliases=["analyze"],
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
        help="Output directory (default: <project>/generated_styles)",
    )
    gen.add_argument(
        "--references",
        nargs="+",
        default=None,
        help="Reference-look images (glob accepted) the VLM derives the "
        "target aesthetic from, e.g. '/path/refs/*.jpeg'",
    )
    gen.add_argument(
        "--reference-filter",
        choices=("off", "warn", "auto", "strict"),
        default="auto",
        help="Reference consistency policy (default: auto = drop clear outliers).",
    )
    gen.add_argument(
        "--reference-match",
        choices=("edit", "light", "both"),
        default="edit",
        help="Reference attribute used for consistency (default: edit).",
    )
    gen.add_argument(
        "--reference-min",
        type=int,
        default=2,
        help="Minimum number of references to keep (default: 2).",
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
    gen.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="VLM sampling temperature (default: 0.4). Higher = more creative.",
    )

    # apply subcommand
    app = subparsers.add_parser(
        "apply",
        help="Apply a style to images with per-image exposure normalization",
    )
    app.add_argument("style", help="Path to the .dtstyle file")
    app.add_argument(
        "images",
        nargs="+",
        help="Images or glob patterns (RAW/JPEG), e.g. 'photos/*.ARW'",
    )
    app.add_argument(
        "--output",
        "-o",
        default="outputs",
        help="Output directory (default: ./outputs)",
    )
    app.add_argument(
        "--references",
        nargs="+",
        default=None,
        help="Reference look images used to derive the target luminance",
    )
    app.add_argument(
        "--reference-filter",
        choices=("off", "warn", "auto", "strict"),
        default="auto",
        help="Reference consistency policy for the luminance target (default: auto).",
    )
    app.add_argument(
        "--reference-match",
        choices=("edit", "light", "both"),
        default="edit",
        help="Reference attribute used for consistency (default: edit).",
    )
    app.add_argument(
        "--reference-min",
        type=int,
        default=2,
        help="Minimum number of references to keep (default: 2).",
    )
    app.add_argument(
        "--target-luminance",
        type=float,
        default=None,
        help="Override the target mean luminance (0-1)",
    )
    app.add_argument(
        "--max-clip",
        type=float,
        default=0.01,
        help="Maximum fraction of pixels above 0.98 luminance (default: 0.01)",
    )
    app.add_argument(
        "--preview-width",
        type=int,
        default=1200,
        help="Width used while iterating exposure (default: 1200)",
    )
    app.add_argument(
        "--width",
        type=int,
        default=None,
        help="Final export width (default: full resolution)",
    )

    # preset subcommand
    add_preset_subcommands(subparsers)

    # vlm subcommand
    add_vlm_subcommands(subparsers)

    # curves subcommand
    add_curves_subcommands(subparsers)

    return parser


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

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command in ("generate", "analyze"):
        return cmd_generate(args)
    elif args.command == "apply":
        return cmd_apply(args)
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
