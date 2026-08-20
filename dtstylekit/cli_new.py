"""New CLI entry point using Clean Architecture.

This CLI uses Use Cases (Interactors) instead of direct orchestration.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dtstylekit.di.container import get_container
from dtstylekit.di.services import configure_services
from dtstylekit.use_cases import GenerateStyleUseCase, IndexPresetsUseCase, SearchPresetsUseCase

# Configure DI container
configure_services()
container = get_container()

logger = logging.getLogger(__name__)


def cmd_generate(args: argparse.Namespace) -> int:
    """End-to-end generation using GenerateStyleUseCase."""
    use_case: GenerateStyleUseCase = container.resolve(GenerateStyleUseCase)

    from dtstylekit.use_cases.generate_style import GenerateStyleRequest

    request = GenerateStyleRequest(
        image_path=args.image,
        direction=args.direction,
        references=args.references,
        refine_iterations=args.refine_iterations,
        refine_raw_path=args.refine_raw,
        output_dir=Path(args.output) if args.output else None,
        lang=args.lang,
    )

    try:
        response = use_case.execute(request)
    except Exception as exc:
        logger.error("Style generation failed: %s", exc)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"✓ Generated: {response.dtstyle_path}")
    if response.report_path:
        print(f"✓ Report:    {response.report_path}")
    if response.explanation_path:
        print(f"✓ Explanation: {response.explanation_path}")
    if response.warnings:
        print(f"⚠ {len(response.warnings)} warning(s):", file=sys.stderr)
        for w in response.warnings:
            print(f"  - {w}", file=sys.stderr)

    return 0


def cmd_preset_index(args: argparse.Namespace) -> int:
    """Build preset index using IndexPresetsUseCase."""
    use_case: IndexPresetsUseCase = container.resolve(IndexPresetsUseCase)

    from dtstylekit.paths import get_presets_dir
    from dtstylekit.use_cases.index_presets import IndexPresetsRequest

    preset_dir = Path(args.preset_dir) if args.preset_dir else get_presets_dir()

    request = IndexPresetsRequest(
        preset_dir=preset_dir,
        force=args.force,
    )

    try:
        response = use_case.execute(request)
        print(response.message)
    except Exception as exc:
        logger.error("Indexing failed: %s", exc)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    return 0


def cmd_preset_search(args: argparse.Namespace) -> int:
    """Search presets using SearchPresetsUseCase."""
    use_case: SearchPresetsUseCase = container.resolve(SearchPresetsUseCase)

    from dtstylekit.use_cases.search_presets import SearchPresetsRequest

    request = SearchPresetsRequest(
        query=args.query,
        limit=args.limit,
        category=args.category,
    )

    try:
        response = use_case.execute(request)
    except Exception as exc:
        logger.error("Search failed: %s", exc)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if not response.results:
        print("No presets found.")
        return 0

    print(f"Found {response.total_found} preset(s):")
    for i, preset in enumerate(response.results, 1):
        print(
            f"  {i}. {preset.display_name or preset.name} (score: {getattr(preset, 'score', 'N/A')})"
        )
        print(f"     {preset.description[:80]}..." if preset.description else "")

    return 0


def cmd_preset_list(args: argparse.Namespace) -> int:
    """List all presets."""
    use_case: SearchPresetsUseCase = container.resolve(SearchPresetsUseCase)

    from dtstylekit.use_cases.search_presets import SearchPresetsRequest

    request = SearchPresetsRequest(
        query="",
        limit=args.limit,
        category=args.category,
    )

    try:
        response = use_case.execute(request)
    except Exception as exc:
        logger.error("List failed: %s", exc)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Total presets: {response.total_found}")
    for i, preset in enumerate(response.results, 1):
        cat = f"[{preset.category}]" if preset.category else ""
        print(f"  {i}. {preset.display_name or preset.name} {cat}")

    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate a style file."""
    _ = args
    print("Style validation not fully implemented yet", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )

    parser = argparse.ArgumentParser(
        prog="dtstylekit",
        description="AI-powered Darktable style generator (Clean Architecture)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # generate subcommand
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

    # preset subcommand
    preset = subparsers.add_parser("preset", help="Preset management")
    preset_sub = preset.add_subparsers(dest="preset_command", required=True)

    # preset index
    idx = preset_sub.add_parser("index", help="Build/rebuild the preset search index")
    idx.add_argument(
        "--preset-dir",
        default=None,
        help="Directory containing .dtstyle files (default: auto-detect)",
    )
    idx.add_argument(
        "--force",
        action="store_true",
        help="Force rebuild even if index exists",
    )

    # preset search
    search = preset_sub.add_parser("search", help="Search presets by query")
    search.add_argument("query", help="Search query")
    search.add_argument("--limit", type=int, default=5, help="Max results (default: 5)")
    search.add_argument("--category", default=None, help="Filter by category")

    # preset list
    lst = preset_sub.add_parser("list", help="List all presets")
    lst.add_argument("--limit", type=int, default=20, help="Max results (default: 20)")
    lst.add_argument("--category", default=None, help="Filter by category")

    # validate subcommand
    val = subparsers.add_parser("validate", help="Validate a .dtstyle file")
    val.add_argument("style", help="Path to .dtstyle file")

    args = parser.parse_args(argv)

    # Dispatch
    if args.command == "generate":
        return cmd_generate(args)
    elif args.command == "preset":
        if args.preset_command == "index":
            return cmd_preset_index(args)
        elif args.preset_command == "search":
            return cmd_preset_search(args)
        elif args.preset_command == "list":
            return cmd_preset_list(args)
    elif args.command == "validate":
        return cmd_validate(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
