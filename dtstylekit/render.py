"""Darktable rendering and render-metric helpers.

Extracted from :mod:`dtstylekit.vlm.iterative_refiner` so that export and
composition code can render without depending on the VLM layer.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class RenderMetrics:
    """Visual metrics from a rendered test image."""

    mean_luminance: float
    std_luminance: float
    mean_saturation: float
    r_mean: float
    g_mean: float
    b_mean: float
    r_over_g: float
    shadows_pct: float
    highlights_pct: float
    mean_hsv_saturation: float = 0.0
    clipped_pct: float = 0.0

    @property
    def has_red_cast(self) -> bool:
        return self.r_over_g > 1.3 and self.r_mean > self.b_mean * 1.2

    @property
    def is_crushed(self) -> bool:
        return self.mean_luminance < 0.1 or self.std_luminance < 0.05

    @property
    def is_blown(self) -> bool:
        return self.mean_luminance > 0.9 or self.highlights_pct > 0.5


def _safe_style_name(name: str) -> str:
    """Normalize a style name to a safe file/darktable identifier.

    Darktable style names can contain spaces, but generated file paths must
    never contain directory separators or shell-like control sequences coming
    from user or VLM-provided text.
    """
    cleaned = re.sub(r"[^\w. -]+", "_", name)
    cleaned = re.sub(r"\s+", "_", cleaned).strip("_-. ")
    return cleaned or "style"


def find_darktable_cli() -> str | None:
    """Locate the ``darktable-cli`` executable."""
    return shutil.which("darktable-cli")


def compute_render_metrics(image_path: Path) -> RenderMetrics:
    """Compute visual metrics from a rendered image."""
    import numpy as np

    from dtstylekit.images import load_rgb_array

    arr = load_rgb_array(image_path)

    lum = 0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2]
    mx = arr.max(-1)
    mn = arr.min(-1)
    sat = mx - mn
    hsv_sat = np.where(mx > 1e-6, sat / np.maximum(mx, 1e-6), 0.0)

    # Shadows/highlights by luminance percentiles
    shadows_pct = float((lum < 0.15).mean())
    highlights_pct = float((lum > 0.85).mean())
    clipped_pct = float((lum > 0.98).mean())

    return RenderMetrics(
        mean_luminance=float(lum.mean()),
        std_luminance=float(lum.std()),
        mean_saturation=float(sat.mean()),
        r_mean=float(arr[..., 0].mean()),
        g_mean=float(arr[..., 1].mean()),
        b_mean=float(arr[..., 2].mean()),
        r_over_g=float(arr[..., 0].mean() / max(float(arr[..., 1].mean()), 1e-6)),
        shadows_pct=shadows_pct,
        highlights_pct=highlights_pct,
        mean_hsv_saturation=float(hsv_sat.mean()),
        clipped_pct=clipped_pct,
    )


def _mark_first_run_complete(work: Path) -> None:
    """Force darktable's first-run flag in an isolated HOME.

    The flag is written on shutdown by the first export, and a fast second
    export can start before it is flushed.  An empty flag means the first-run
    initialization is incomplete, so set it explicitly before measuring.
    """
    cfg = work / "cfg" / "darktable" / "darktablerc"
    if not cfg.exists():
        return
    lines = cfg.read_text(errors="replace").splitlines()
    key = "lua/luarc/darktable_first_run_complete="
    for i, line in enumerate(lines):
        if line.startswith(key):
            lines[i] = key + "TRUE"
            break
    else:
        lines.append(key + "TRUE")
    cfg.write_text("\n".join(lines) + "\n")


def _import_style_into_library(style_path: Path, name: str, work: Path) -> None:
    """Register the style in the isolated library DB (inlined from visual_check)."""
    import sqlite3

    from dtstylekit.codec.xmp_codec import decode_xmp

    dbs = sorted((work / "cfg" / "darktable").glob("*.db"))
    if not dbs:
        raise RuntimeError("no darktable library database found after first run")
    db_path = dbs[0]

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()

        def _exists(tbl: str) -> bool:
            return (
                cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (tbl,),
                ).fetchone()
                is not None
            )

        styles_tbl = "data.styles" if _exists("data.styles") else "styles"
        items_tbl = "data.style_items" if _exists("data.style_items") else "style_items"

        # Re-importing the same name must REPLACE it: darktable applies every
        # style that matches the name, so duplicate rows stack their IOPs
        # (the safety bake's second render came out double-exposed and was
        # accepted as safe).
        for (old_id,) in cur.execute(
            f"SELECT id FROM {styles_tbl} WHERE name=?", (name,)
        ).fetchall():
            cur.execute(f"DELETE FROM {items_tbl} WHERE styleid=?", (old_id,))
            cur.execute(f"DELETE FROM {styles_tbl} WHERE id=?", (old_id,))

        style_id = cur.execute(f"SELECT COALESCE(MAX(id), 0) + 1 FROM {styles_tbl}").fetchone()[0]
        cur.execute(
            f"INSERT INTO {styles_tbl} (id, name, description, iop_list) VALUES (?, ?, '', NULL)",
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
        logger.info("  style '%s' registered in %s (id=%s)", name, db_path.name, style_id)
    finally:
        conn.close()


def _prepare_run(work_dir: Path) -> tuple[Path, dict[str, str]]:
    """Create an isolated HOME for one darktable render."""
    run_dir = Path(tempfile.mkdtemp(prefix="run_", dir=work_dir))
    env = {
        "HOME": str(run_dir),
        "XDG_CONFIG_HOME": str(run_dir / "cfg"),
        "XDG_DATA_HOME": str(run_dir / "data"),
    }
    return run_dir, env


def _warm_up(raw_path: Path, run_dir: Path, env: dict[str, str], width: int | None) -> None:
    """Complete darktable's first-run initialization before measuring.

    The first export in a fresh HOME creates the library/config.  Force the
    first-run flag afterwards so the measured render does not depend on
    whether the flag was flushed before this process started.
    """
    cmd = ["darktable-cli", str(raw_path), str(run_dir / "baseline_init.jpg")]
    if width is not None:
        cmd += ["--width", str(width)]
    subprocess.run(
        cmd,
        env=env,
        capture_output=True,
        timeout=120,
        check=False,
    )
    _mark_first_run_complete(run_dir)


def render_preview(
    raw_path: Path,
    work_dir: Path,
    width: int = 1200,
) -> Path | None:
    """Render a RAW to a JPEG preview usable by Pillow/the VLM."""
    run_dir, env = _prepare_run(work_dir)
    _warm_up(Path(raw_path), run_dir, env, width)
    out_path = run_dir / "preview.jpg"
    result = subprocess.run(
        ["darktable-cli", str(raw_path), str(out_path), "--width", str(width)],
        env=env,
        capture_output=True,
        timeout=180,
        check=False,
    )
    if result.returncode == 0:
        actual = list(run_dir.glob("preview*.jpg"))
        if actual:
            return max(actual, key=lambda p: p.stat().st_mtime)
    logger.warning(
        "Preview render failed: %s",
        result.stderr.decode() if result.stderr else "unknown",
    )
    return None


def render_with_style(
    raw_path: Path,
    style_path: Path,
    style_name: str,
    work_dir: Path,
    width: int | None = 1200,
) -> Path | None:
    """Render a RAW with the given style using an isolated darktable library.

    Returns path to rendered JPG or None on failure.
    """
    # Each render gets a fresh HOME: reusing one library lets a second
    # style import stack onto the previous history, which produced a
    # double-exposed render in the safety bake.
    run_dir, env = _prepare_run(work_dir)
    safe_name = _safe_style_name(style_name)
    out_path = run_dir / f"render_{safe_name}.jpg"

    try:
        _warm_up(Path(raw_path), run_dir, env, width)

        # Import style into library
        _import_style_into_library(style_path, safe_name, run_dir)

        # Render with style
        cmd = [
            "darktable-cli",
            str(raw_path),
            str(out_path),
            "--style",
            style_name,
        ]
        if width is not None:
            cmd += ["--width", str(width)]
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            timeout=300,
            check=False,
        )

        if result.returncode == 0 and out_path.exists():
            # darktable-cli doesn't overwrite - find actual output
            actual = list(run_dir.glob(f"render_{safe_name}*.jpg"))
            if actual:
                return max(actual, key=lambda p: p.stat().st_mtime)
        logger.warning("Render failed: %s", result.stderr.decode() if result.stderr else "unknown")
        return None
    except Exception as e:
        logger.warning("Render error: %s", e)
        return None
