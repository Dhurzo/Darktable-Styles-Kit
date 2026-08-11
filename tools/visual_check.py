#!/usr/bin/env python3
"""Visual smoke check for generated .dtstyle files.

Closes the biggest validation gap of dtstylekit: *structural* checks
(blob sizes, XMP encoding) prove a style imports, but not that it renders
a sane image.  This tool renders a deterministic synthetic test image
through darktable-cli with and without the style, and compares the
luminance statistics:

  * styled mean luminance < 5 or > 95 (0-100 scale) → style crushes
    blacks / burns whites (the classic "corrupted/black image" symptom);
  * styled stddev < 1 while baseline has texture → flat/empty output;
  * styled mean == baseline mean exactly → the style had no visible
    effect (e.g. all modules were dropped at import time).

Exit codes: 0 = OK, 1 = style looks broken, 2 = environment error.

Usage:
    python tools/visual_check.py --style generated_styles/foo.dtstyle
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Image generation (deterministic — no randomness)
# ---------------------------------------------------------------------------


def generate_test_image(path: Path, width: int = 1024, height: int = 768) -> None:
    """Write a gray gradient + color blocks PNG (deterministic)."""
    if Image is None:
        raise RuntimeError("Pillow is required (pip install pillow)")
    img = Image.new("RGB", (width, height))
    px = img.load()
    # Horizontal gray gradient 0..255
    for y in range(height):
        for x in range(width):
            v = (x * 255) // (width - 1)
            px[x, y] = (v, v, v)
    # Color blocks (four quadrants with solid hues)
    blocks = [
        (0, 0, width // 2, height // 2, (200, 40, 40)),
        (width // 2, 0, width, height // 2, (40, 200, 40)),
        (0, height // 2, width // 2, height, (40, 40, 200)),
        (width // 2, height // 2, width, height, (220, 200, 40)),
    ]
    for x0, y0, x1, y1, color in blocks:
        for y in range(y0, y1):
            for x in range(x0, x1):
                px[x, y] = color
    img.save(path)


def luminance_stats(path: Path) -> tuple[float, float]:
    """Return (mean, stddev) of Luminance (0-100 scale)."""
    if Image is None:
        raise RuntimeError("Pillow is required (pip install pillow)")
    img = Image.open(path).convert("L")
    hist = img.histogram()  # 256 bins of grayscale
    total = sum(hist)
    if total == 0:
        return 0.0, 0.0
    mean = sum(i * c for i, c in enumerate(hist)) / total
    var = sum(c * (i - mean) ** 2 for i, c in enumerate(hist)) / total
    # 0-255 → 0-100 scale (matches darktable's L in %)
    return mean * 100.0 / 255.0, (var ** 0.5) * 100.0 / 255.0


# ---------------------------------------------------------------------------
# darktable-cli helpers
# ---------------------------------------------------------------------------


def _run(cmd: list[str], env: dict, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, env=env,
    )


def _import_style_into_library(
    style_path: Path, name: str, work: Path
) -> None:
    """Register the style in the isolated library DB.

    darktable-cli has no ``--import-style`` option (the GUI-only flag
    does not exist in 5.x); styles are applied by *name* from the
    library database.  We mirror ``dt_style_save()`` (src/common/
    styles.c:1554) — decode the XMP blobs and insert rows into
    ``data.styles`` / ``data.style_items`` — after the baseline export
    has created the library.
    """
    import sqlite3

    from dtstylekit.codec.xmp_codec import decode_xmp

    dbs = sorted((work / "cfg" / "darktable").glob("*.db"))
    if not dbs:
        raise RuntimeError("no darktable library database found after first run")
    db_path = dbs[0]

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        # Table names differ across versions: modern darktable uses
        # ``data.styles`` / ``data.style_items`` (SQLite stores the dot
        # as part of the name), 5.x keeps the legacy ``styles`` /
        # ``style_items`` (main schema).

        def _exists(name: str) -> bool:
            return cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (name,),
            ).fetchone() is not None

        styles_tbl = "data.styles" if _exists("data.styles") else "styles"
        items_tbl = "data.style_items" if _exists("data.style_items") else "style_items"

        style_id = cur.execute(
            f"SELECT COALESCE(MAX(id), 0) + 1 FROM {styles_tbl}"
        ).fetchone()[0]
        cur.execute(
            f"INSERT INTO {styles_tbl} (id, name, description, iop_list) "
            "VALUES (?, ?, '', NULL)",
            (style_id, name),
        )
        root = ET.parse(style_path).getroot()
        for plugin in root.findall("style/plugin"):
            op_enc = plugin.findtext("op_params", "") or ""
            bl_enc = plugin.findtext("blendop_params", "") or ""
            cur.execute(
                f"INSERT INTO {items_tbl} "
                " (styleid, num, module, operation, op_params, enabled,"
                "  blendop_params, blendop_version, multi_priority,"
                "  multi_name, multi_name_hand_edited)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    style_id,
                    int(plugin.findtext("num", "0") or 0),
                    int(plugin.findtext("module", "0") or 0),
                    plugin.findtext("operation", "") or "",
                    decode_xmp(op_enc) if op_enc else b"",
                    int(plugin.findtext("enabled", "1") or 1),
                    decode_xmp(bl_enc) if bl_enc else b"",
                    int(plugin.findtext("blendop_version", "13") or 13),
                    int(plugin.findtext("multi_priority", "0") or 0),
                    plugin.findtext("multi_name", "") or "",
                    int(plugin.findtext("multi_name_hand_edited", "0") or 0),
                ),
            )
        conn.commit()
        print(f"    style '{name}' registered in {db_path.name} (id={style_id})")
    finally:
        conn.close()


def check_style(
    style_path: Path,
    darktable_cli: str | None = None,
    outdir: Path | None = None,
    width: int = 800,
) -> int:
    """Run the visual smoke check; returns process exit code."""
    if Image is None:
        print("ERROR: Pillow is required (pip install pillow)", file=sys.stderr)
        return 2

    cli = darktable_cli or shutil.which("darktable-cli")
    if not cli:
        print("ERROR: darktable-cli not found", file=sys.stderr)
        return 2

    style_path = Path(style_path)
    if not style_path.exists():
        print(f"ERROR: style file not found: {style_path}", file=sys.stderr)
        return 2

    # Style display name from the XML (used by darktable-cli --style)
    try:
        root = ET.parse(style_path).getroot()
        name = root.findtext("info/name", "").strip()
    except ET.ParseError as exc:
        print(f"ERROR: cannot parse style XML: {exc}", file=sys.stderr)
        return 2
    if not name:
        print("ERROR: style has no <info><name>", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        # Isolate the darktable library so we don't touch the user's.
        env = {"HOME": str(work), "XDG_CONFIG_HOME": str(work / "cfg"),
               "XDG_DATA_HOME": str(work / "data")}
        outdir = Path(outdir) if outdir else work
        outdir.mkdir(parents=True, exist_ok=True)

        test_img = work / "input.png"
        baseline = outdir / "baseline.png"
        styled = outdir / "styled.png"

        print(f"[1/4] Generating deterministic test image: {test_img}")
        generate_test_image(test_img)

        print(f"[2/4] Exporting baseline: {baseline} (creates the isolated library)")
        r = _run([cli, str(test_img), str(baseline), "--width", str(width)], env)
        if r.returncode != 0:
            print(f"ERROR: baseline export failed:\n{r.stdout}\n{r.stderr}", file=sys.stderr)
            return 2

        print(f"[3/4] Importing style '{name}' into isolated library")
        _import_style_into_library(style_path, name, work)

        print(f"[4/4] Exporting with style: {styled}")
        r = _run(
            [cli, str(test_img), str(styled), "--width", str(width), "--style", name],
            env,
        )
        if r.returncode != 0:
            print(f"ERROR: styled export failed:\n{r.stdout}\n{r.stderr}", file=sys.stderr)
            return 2

        base_mean, base_std = luminance_stats(baseline)
        sty_mean, sty_std = luminance_stats(styled)
        print(f"baseline: mean={base_mean:6.2f} std={base_std:6.2f}")
        print(f"styled:   mean={sty_mean:6.2f} std={sty_std:6.2f}")

        problems: list[str] = []
        if sty_mean < 5.0:
            problems.append(f"styled output is nearly black (mean {sty_mean:.2f})")
        if sty_mean > 95.0:
            problems.append(f"styled output is nearly white (mean {sty_mean:.2f})")
        if sty_std < 1.0 and base_std > 1.0:
            problems.append(f"styled output is flat (std {sty_std:.2f} vs baseline {base_std:.2f})")
        if abs(sty_mean - base_mean) < 0.5 and abs(sty_std - base_std) < 0.5:
            problems.append("style had no visible effect (identical to baseline)")

        if problems:
            for p in problems:
                print(f"FAIL: {p}", file=sys.stderr)
            return 1
        print("OK: styled output looks sane")
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--style", required=True, help="Path to the .dtstyle file")
    parser.add_argument("--darktable-cli", default=None, help="darktable-cli binary")
    parser.add_argument("--outdir", default=None, help="Where to write exports")
    parser.add_argument("--width", type=int, default=800, help="Export width")
    args = parser.parse_args(argv)
    return check_style(
        Path(args.style),
        darktable_cli=args.darktable_cli,
        outdir=Path(args.outdir) if args.outdir else None,
        width=args.width,
    )


if __name__ == "__main__":
    sys.exit(main())
