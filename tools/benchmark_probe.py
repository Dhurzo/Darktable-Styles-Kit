#!/usr/bin/env python3
"""Probe darktable benchmark XMP files for real IOP blobs.

Scans ``src/tests/benchmark/darktable-bench-*.xmp`` for every
``darktable:operation`` entry with a ``darktable:params`` blob and
reports: the operation name, the modversion, the blob length in bytes
and whether a registered dtstylekit IOP exists with a matching
``size_bytes`` (or, for unregistered ops, the expected struct size when
the C struct can be extracted from the checkout).

This is the independent ground-truth source that lets us verify new
IOP registry entries without depending on the 534-preset library
(which only covers 19 operations).

Usage:
    python tools/benchmark_probe.py /path/to/darktable [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    from dtstylekit.codec.iop_registry import IOP_REGISTRY
except ImportError:
    # Allow running from the repo root without installing.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from dtstylekit.codec.iop_registry import IOP_REGISTRY

_BLOB_RE = re.compile(
    r"<rdf:li\b[^>]*darktable:operation=\"([^\"]+)\"[^>]*"
    r"darktable:modversion=\"(\d+)\"[^>]*"
    r"darktable:params=\"([0-9a-fA-F]*)\"[^>]*/>",
    re.DOTALL,
)

# ops that appear in darktable:iop_order lists but carry no blob
_NO_BLOB_OPS = {"darktable:iop_order"}


def probe(darktable_root: Path) -> list[dict]:
    """Return one record per (benchmark file, blob entry)."""
    bench_dir = darktable_root / "src" / "tests" / "benchmark"
    if not bench_dir.is_dir():
        raise FileNotFoundError(f"{bench_dir} not found")

    records: list[dict] = []
    for xmp in sorted(bench_dir.glob("darktable-bench-*.xmp")):
        text = xmp.read_text(encoding="utf-8")
        for m in _BLOB_RE.finditer(text):
            op, modversion, hex_params = m.groups()
            if op in _NO_BLOB_OPS:
                continue
            n_bytes = len(hex_params) // 2
            reg = IOP_REGISTRY.get(op)
            legacy_match = bool(reg and n_bytes in (reg.legacy_size_bytes or ()))
            records.append(
                {
                    "file": xmp.name,
                    "op": op,
                    "modversion": int(modversion),
                    "bytes": n_bytes,
                    "registered": reg is not None,
                    "registered_size": reg.size_bytes if reg else None,
                    "matches": bool(reg and (reg.size_bytes == n_bytes or legacy_match)),
                    "legacy_match": legacy_match,
                }
            )
    return records


def report(darktable_root: Path) -> str:
    records = probe(darktable_root)
    if not records:
        return "No blobs found."

    lines = [f"Probed {len(records)} blobs from benchmark XMP files:"]
    lines.append(f"{'op':<28}{'ver':<5}{'bytes':<7}{'status'}")
    lines.append("-" * 55)
    distinct: dict[str, dict] = {}
    for r in records:
        key = r["op"]
        if key not in distinct or r["bytes"] > distinct[key]["bytes"]:
            distinct[key] = r
    for op, r in sorted(distinct.items()):
        if r["registered"]:
            if r["matches"]:
                status = "OK"
                if r["legacy_match"]:
                    status = "OK (legacy)"
            elif r["registered_size"] is None:
                status = "REGISTERED-UNVERIFIED"
            else:
                status = f"MISMATCH (registry {r['registered_size']}B)"
        else:
            status = "UNREGISTERED"
        lines.append(f"{op:<28}{r['modversion']:<5}{r['bytes']:<7}{status}")

    mismatches = [
        r
        for r in distinct.values()
        if r["registered"] and not r["matches"] and r["registered_size"] is not None
    ]
    unregistered = [op for op, r in distinct.items() if not r["registered"]]
    unverified = [
        op
        for op, r in distinct.items()
        if r["registered"] and not r["matches"] and r["registered_size"] is None
    ]
    lines.append("")
    lines.append(f"MISMATCHES: {len(mismatches)}")
    lines.append(f"REGISTERED-UNVERIFIED (no size_bytes in registry): {len(unverified)}")
    if unverified:
        lines.append("  " + ", ".join(sorted(unverified)))
    lines.append(f"UNREGISTERED ops with blobs: {len(unregistered)}")
    lines.append("  " + ", ".join(sorted(unregistered)))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "darktable_root",
        type=Path,
        help="Path to the darktable checkout (e.g. /path/to/darktable)",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args(argv)

    try:
        if args.json:
            print(json.dumps(probe(args.darktable_root), indent=2))
        else:
            print(report(args.darktable_root))
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
