"""CLI subcommand for inspecting available curve templates.

Usage:
    dtstylekit curves list [--category CATEGORY]
    dtstylekit curves info <template_name>
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict


def add_curves_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register 'curves' subcommand."""
    parser = subparsers.add_parser(
        "curves",
        help="Inspect available curve templates for curve-based IOPs "
        "(colorzones, rgbcurve, tonecurve)",
    )
    sub = parser.add_subparsers(dest="curves_command", required=True)

    # ----- list -----------------------------------------------------------
    list_cmd = sub.add_parser(
        "list",
        help="List all available curve templates (optionally by category)",
    )
    list_cmd.add_argument(
        "--category",
        "-c",
        default=None,
        help="Filter templates by category (tone, contrast, vintage, filmic, color)",
    )
    list_cmd.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Only print template names (one per line), no tables",
    )

    # ----- info -----------------------------------------------------------
    info_cmd = sub.add_parser(
        "info",
        help="Print details about a single template (with sample nodes)",
    )
    info_cmd.add_argument("name", help="Template name (e.g. 's_strong')")


def cmd_curves_list(args: argparse.Namespace) -> int:
    """List all curve templates, optionally filtered by category."""
    from dtstylekit.curves import REGISTRY, list_templates

    try:
        templates = list_templates(args.category)
    except Exception as e:  # pragma: no cover -- defensive
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if not templates:
        if args.category:
            print(
                f"No templates found for category '{args.category}'. "
                f"Available categories: {sorted({t.category for t in REGISTRY})}",
                file=sys.stderr,
            )
        else:
            print("No templates registered.", file=sys.stderr)
        return 1

    if args.quiet:
        for tmpl in templates:
            print(tmpl.name)
        return 0

    # Group by category for visual clarity
    by_cat: dict[str, list] = defaultdict(list)
    for tmpl in templates:
        by_cat[tmpl.category].append(tmpl)

    print(f"Curve templates ({len(templates)} total")
    if args.category:
        print(f", filtered to category='{args.category}'")
    print("):")
    print()
    for cat in sorted(by_cat.keys()):
        items = by_cat[cat]
        print(f"  ── {cat} ({len(items)}) " + "─" * 50)
        for t in items:
            print(f"    {t.name:25s}  {t.title}")
            print(f"      {t.description[:100]}")
        print()

    # Also list IOP names that accept curve_preset
    print("Curve-receiving IOPs:")
    print("  colorzones, rgbcurve, tonecurve")
    print()
    print("Usage example:")
    print(f'  {{"operation": "tonecurve", "params": {{"curve_preset": "{templates[0].name}"}}}}')

    return 0


def cmd_curves_info(args: argparse.Namespace) -> int:
    """Print details of a single template."""
    from dtstylekit.curves import get_template

    try:
        tmpl = get_template(args.name)
    except KeyError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(f"Template: {tmpl.name}")
    print(f"Title:    {tmpl.title}")
    print(f"Category: {tmpl.category}")
    print(f"Channels: {tmpl.channels}")
    print()
    print("Description:")
    print(f"  {tmpl.description}")
    print()
    print("Nodes per channel:")
    for ch, nodes in tmpl.nodes_per_channel.items():
        print(f"  [{ch}]  ({len(nodes)} nodes)")
        if len(nodes) <= 12:
            for i, (x, y) in enumerate(nodes):
                print(f"    {i}: ({x:.4f}, {y:.4f})")
        else:
            print(f"    (omitted — {len(nodes)} nodes)")
    print()
    print("Pack into any of these curve-based IOPs:")
    print("  colorzones, rgbcurve, tonecurve")
    print()
    print("Example JSON:")
    print('  {"operation": "tonecurve", "params": {')
    print(f'    "curve_preset": "{tmpl.name}",')
    print("    ...other scalars...")
    print("  }}")

    return 0


def cmd_curves(args: argparse.Namespace) -> int:
    """Dispatch based on the chosen subcommand."""
    if args.curves_command == "list":
        return cmd_curves_list(args)
    if args.curves_command == "info":
        return cmd_curves_info(args)
    return 1
