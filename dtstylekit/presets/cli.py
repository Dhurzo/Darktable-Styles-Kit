"""CLI commands for preset management."""

import argparse
from pathlib import Path

from dtstylekit.paths import get_outputs_dir, get_presets_dir

from .embedder import DEFAULT_MODEL, build_embeddings
from .indexer import PresetIndexer
from .parser import parse_all_presets


def add_preset_subcommands(subparsers: argparse._SubParsersAction) -> None:
    """Add preset-related subcommands to the main parser."""
    preset_parser = subparsers.add_parser("preset", help="Preset management commands")
    preset_subparsers = preset_parser.add_subparsers(dest="preset_command", required=True)

    # Index command
    index_parser = preset_subparsers.add_parser(
        "index", help="Build/rebuild preset index and embeddings"
    )
    index_parser.add_argument(
        "--preset-dir",
        type=Path,
        default=get_presets_dir(),
        help="Directory containing .dtstyle files",
    )
    index_parser.add_argument(
        "--db-path",
        type=Path,
        default=get_outputs_dir() / "presets.db",
        help="Output SQLite database path",
    )
    index_parser.add_argument(
        "--embeddings-path",
        type=Path,
        default=get_outputs_dir() / "preset_embeddings.npy",
        help="Output embeddings .npy file path",
    )
    index_parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help="Sentence transformer model for embeddings",
    )
    index_parser.add_argument(
        "--skip-embeddings",
        action="store_true",
        help="Skip embedding generation (faster, keyword search only)",
    )
    index_parser.add_argument(
        "--force",
        action="store_true",
        help="Force rebuild even if outputs exist",
    )

    # Search command (for testing)
    search_parser = preset_subparsers.add_parser("search", help="Search presets")
    search_parser.add_argument("query", type=str, help="Search query")
    search_parser.add_argument(
        "--db-path",
        type=Path,
        default=get_outputs_dir() / "presets.db",
        help="SQLite database path",
    )
    search_parser.add_argument(
        "--embeddings-path",
        type=Path,
        default=get_outputs_dir() / "preset_embeddings.npy",
        help="Embeddings .npy file path",
    )
    search_parser.add_argument(
        "--mode",
        choices=["keyword", "semantic", "hybrid"],
        default="hybrid",
        help="Search mode",
    )
    search_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum results",
    )
    search_parser.add_argument(
        "--alpha",
        type=float,
        default=0.5,
        help="Hybrid search weight for semantic (0-1)",
    )


def cmd_preset_index(args: argparse.Namespace) -> int:
    """Execute the 'preset index' command."""
    preset_dir = args.preset_dir
    db_path = args.db_path
    embeddings_path = args.embeddings_path

    # Ensure output directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)
    embeddings_path.parent.mkdir(parents=True, exist_ok=True)

    # Validate preset directory
    if not preset_dir.exists():
        print(f"Error: Preset directory not found: {preset_dir}")
        return 1

    dtstyle_files = list(preset_dir.glob("*.dtstyle"))
    if not dtstyle_files:
        print(f"Error: No .dtstyle files found in {preset_dir}")
        return 1

    print(f"Found {len(dtstyle_files)} preset files in {preset_dir}")

    # Check if already indexed (unless force)
    if not args.force and db_path.exists() and embeddings_path.exists():
        print("Index already exists. Use --force to rebuild.")
        return 0

    # Parse presets
    print("Parsing presets...")
    presets = parse_all_presets(preset_dir)
    print(f"Parsed {len(presets)} presets successfully")

    # Build SQLite index
    print("Building SQLite index...")
    with PresetIndexer(db_path) as indexer:
        indexer.clear()
        count = indexer.index_presets(presets)
    print(f"Indexed {count} presets to {db_path}")

    # Generate embeddings
    if not args.skip_embeddings:
        print("Generating semantic embeddings...")
        build_embeddings(preset_dir, embeddings_path, args.model)
        print(f"Saved embeddings to {embeddings_path}")
    else:
        print("Skipping embedding generation (--skip-embeddings)")

    print("Index build complete!")
    return 0


def cmd_preset_search(args: argparse.Namespace) -> int:
    """Execute the 'preset search' command."""
    from .search import PresetSearcher

    searcher = PresetSearcher(args.db_path, args.embeddings_path)

    try:
        if args.mode == "keyword":
            results = searcher.keyword_search(args.query, args.limit)
        elif args.mode == "semantic":
            results = searcher.semantic_search(args.query, args.limit)
        else:
            results = searcher.hybrid_search(args.query, args.limit, args.alpha)

        if not results:
            print("No results found.")
            return 0

        print(f"\nSearch results for '{args.query}' ({args.mode}):")
        print("-" * 80)
        from dtstylekit.presets.models import clean_description

        for i, result in enumerate(results, 1):
            display = getattr(result.preset, "display_name", None) or result.preset.name
            category = getattr(result.preset, "category", None) or "-"
            print(f"{i}. [{category}] {display}")
            file_path = getattr(result.preset, "file_path", "") or "(unknown)"
            file_basename = file_path if file_path == "(unknown)" else Path(file_path).name
            print(f"   file: {file_basename}")
            cleaned = clean_description(result.preset.description)
            if cleaned:
                print(f"   Description: {cleaned[:100]}...")
            print(f"   IOPs: {result.preset.iop_list[:100]}...")
            print(f"   Score: {result.score:.4f}")
            print()

    finally:
        searcher.close()

    return 0


def main_preset(args: argparse.Namespace) -> int:
    """Dispatch preset subcommands."""
    if args.preset_command == "index":
        return cmd_preset_index(args)
    elif args.preset_command == "search":
        return cmd_preset_search(args)
    else:
        print(f"Unknown preset command: {args.preset_command}")
        return 1
