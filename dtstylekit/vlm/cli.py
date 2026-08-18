"""CLI subcommand for VLM style generation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def add_vlm_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'vlm generate' subcommand."""
    parser = subparsers.add_parser(
        "vlm",
        help="VLM-backed style generation",
    )
    vlm_sub = parser.add_subparsers(dest="vlm_command", required=True)
    gen = vlm_sub.add_parser("generate", help="Generate style spec from image")
    gen.add_argument("image", help="Path to JPEG/TIFF image")
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
        help="Output path for spec JSON (default: stdout)",
    )


def cmd_vlm_generate(args: argparse.Namespace) -> int:
    """Handle 'vlm generate'."""
    from dtstylekit.analyzer.pipeline import analyze_image
    from dtstylekit.codec.iop_registry import IOP_REGISTRY
    from dtstylekit.paths import get_outputs_dir
    from dtstylekit.presets.search import PresetSearcher
    from dtstylekit.vlm.orchestrator import generate_style_spec

    outputs_dir = get_outputs_dir()
    db_path = outputs_dir / "presets.db"
    emb_path = outputs_dir / "preset_embeddings.npy"

    if not db_path.exists() or not emb_path.exists():
        print(
            "ERROR: Preset index not built. Run: dtstylekit preset index",
            file=sys.stderr,
        )
        return 1

    searcher = PresetSearcher(db_path, emb_path)
    spec, report, warnings, _ = generate_style_spec(
        image_path=args.image,
        direction=args.direction,
        searcher=searcher,
        analyzer=analyze_image,
        registry=IOP_REGISTRY,
        model=args.model,
    )

    out = {
        "spec": spec.to_dict(),
        "report": report,
        "warnings": warnings,
    }

    json_str = json.dumps(out, indent=2)
    if args.output:
        Path(args.output).write_text(json_str)
        print(f"Wrote {args.output}", file=sys.stderr)
    else:
        print(json_str)
    return 0
