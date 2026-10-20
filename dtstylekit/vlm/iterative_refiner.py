"""Iterative style refinement: generate → render → evaluate → adjust.

Closes the feedback loop by rendering the generated style, measuring
visual metrics, and feeding corrections back to the VLM.
"""

import copy
import logging
import math
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dtstylekit.analyzer.models import ImageAnalysis
    from dtstylekit.eval.metrics import LookProfile

from dtstylekit.analyzer.models import ImageAnalysis
from dtstylekit.vlm.models import Plugin, StyleSpec

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


@dataclass
class RefinementResult:
    """Result of a refinement run: final spec plus how it ended.

    ``iterations_completed`` counts completed generate → render → evaluate
    cycles; ``passed`` is True when an iteration passed evaluation.
    """

    spec: StyleSpec
    iterations_completed: int
    passed: bool


def compute_render_metrics(image_path: Path) -> RenderMetrics:
    """Compute visual metrics from a rendered image."""
    import numpy as np
    from PIL import Image

    img = Image.open(image_path).convert("RGB")
    arr = np.asarray(img, dtype=np.float32) / 255.0

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


def _reference_distance(metrics: RenderMetrics, reference_analysis: dict) -> float:
    """Weighted distance between a render and the reference signature.

    Uses HSV saturation (exposure-invariant) rather than absolute chroma,
    luminance in the first term and red-minus-blue warmth in the third.
    """
    ref_lum = _as_float(reference_analysis.get("global_luminance"))
    ref_sat = _as_float(reference_analysis.get("global_saturation"))
    ref_warm = _as_float(reference_analysis.get("global_warmth_rb"))
    warmth = metrics.r_mean - metrics.b_mean
    return (
        abs(metrics.mean_luminance - ref_lum) / 0.3
        + abs(metrics.mean_hsv_saturation - ref_sat) / max(ref_sat, 0.1)
        + abs(warmth - ref_warm) / 0.3
    )


def _as_float(value: object, default: float = 0.0) -> float:
    """Narrow an arbitrary analysis value to float without bool leakage."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return default


def _reference_targets(
    reference_paths: list[Path], reference_analysis: dict | None
) -> dict[str, float]:
    """Reference targets from the signature, filling gaps from the images."""
    targets = {
        key: _as_float((reference_analysis or {}).get(key))
        for key in ("global_luminance", "global_saturation", "global_warmth_rb")
    }
    missing = [
        key
        for key in ("global_luminance", "global_saturation", "global_warmth_rb")
        if key not in (reference_analysis or {})
        and reference_paths
    ]
    if missing:
        metrics = [compute_render_metrics(Path(p)) for p in reference_paths]
        if metrics:
            if "global_luminance" in missing:
                targets["global_luminance"] = sum(
                    m.mean_luminance for m in metrics
                ) / len(metrics)
            if "global_saturation" in missing:
                targets["global_saturation"] = sum(
                    m.mean_hsv_saturation for m in metrics
                ) / len(metrics)
            if "global_warmth_rb" in missing:
                targets["global_warmth_rb"] = sum(
                    m.r_mean - m.b_mean for m in metrics
                ) / len(metrics)
    return targets


def compare_to_references(
    render_path: Path,
    reference_paths: list[Path],
    reference_analysis: dict | None = None,
) -> tuple[bool, list[str]]:
    """Compare a rendered image with the reference set.

    Returns ``(passed, feedback)``; feedback lines carry stable prefixes
    (``LUMINANCE KEY``, ``SATURATION``, ``WARMTH``) so the prompt builder
    can turn them into corrective guidance.
    """
    metrics = compute_render_metrics(Path(render_path))
    targets = _reference_targets([Path(p) for p in reference_paths], reference_analysis)
    feedback: list[str] = []

    lum_delta = metrics.mean_luminance - targets["global_luminance"]
    if abs(lum_delta) > 0.15:
        direction = "brighter" if lum_delta > 0 else "darker"
        feedback.append(
            f"LUMINANCE KEY: render is {direction} than reference "
            f"({metrics.mean_luminance:.2f} vs {targets['global_luminance']:.2f})"
        )

    warmth = metrics.r_mean - metrics.b_mean
    warm_delta = warmth - targets["global_warmth_rb"]
    if abs(warm_delta) > 0.15:
        direction = "warmer" if warm_delta > 0 else "cooler"
        feedback.append(
            f"WARMTH: render is {direction} than reference "
            f"(R-B {warmth:+.2f} vs {targets['global_warmth_rb']:+.2f})"
        )

    sat_delta = metrics.mean_hsv_saturation - targets["global_saturation"]
    if abs(sat_delta) > 0.15:
        direction = "more saturated" if sat_delta > 0 else "less saturated"
        feedback.append(
            f"SATURATION: render is {direction} than reference "
            f"(HSV {metrics.mean_hsv_saturation:.2f} vs "
            f"{targets['global_saturation']:.2f})"
        )

    return not feedback, feedback


def nudge_spec_toward_reference(
    spec: StyleSpec,
    metrics: RenderMetrics,
    reference_analysis: dict | None,
) -> StyleSpec:
    """Deterministically move a spec halfway toward gross reference targets.

    Returns a deep copy; the input spec is never mutated.  Only large
    mismatches are corrected (exposure ``> 0.25 EV``, saturation ratio
    outside ``0.75–1.33``) and corrections are clamped, because a single
    preview frame is no substitute for the VLM's creative judgement.
    """
    nudged = copy.deepcopy(spec)
    if not reference_analysis:
        return nudged

    def _find(operation: str) -> Plugin | None:
        for plugin in nudged.plugins:
            if plugin.operation == operation:
                return plugin
        return None

    # Exposure: log2 ratio toward the reference luminance.
    ref_lum = _as_float(reference_analysis.get("global_luminance"))
    if ref_lum > 1e-3 and metrics.mean_luminance > 1e-3:
        delta = max(-2.0, min(2.0, math.log2(ref_lum / metrics.mean_luminance)))
        if abs(delta) > 0.25:
            exposure = _find("exposure")
            if exposure is None:
                exposure = Plugin(operation="exposure", enabled=True, params={})
                nudged.plugins.append(exposure)
            current = _as_float(exposure.params.get("exposure"))
            exposure.params["exposure"] = max(-4.0, min(4.0, current + delta))

    # Saturation: desaturate a clearly oversaturated render.  Prefer the
    # existing global saturation control; otherwise add a gentle negative
    # global chroma (never rotate hue — that can blow a single channel).
    ref_sat = _as_float(reference_analysis.get("global_saturation"))
    if ref_sat > 1e-3 and metrics.mean_hsv_saturation > 1e-3:
        ratio = ref_sat / metrics.mean_hsv_saturation
        if ratio < 0.75:
            factor = max(0.25, ratio)
            cb = _find("colorbalancergb")
            if cb is not None and _as_float(cb.params.get("saturation_global")) != 0.0:
                current = _as_float(cb.params.get("saturation_global"))
                cb.params["saturation_global"] = current * factor
            else:
                if cb is None:
                    cb = Plugin(operation="colorbalancergb", enabled=True, params={})
                    nudged.plugins.append(cb)
                chroma = max(-0.4, -(1.0 - factor))
                cb.params["chroma_global"] = chroma

    # Warm cast: trim existing positive global chroma only; do not invent a
    # hue rotation.
    ref_warm = _as_float(reference_analysis.get("global_warmth_rb"))
    render_warm = metrics.r_mean - metrics.b_mean
    if render_warm > ref_warm + 0.15:
        cb = _find("colorbalancergb")
        if cb is not None:
            current_c = _as_float(cb.params.get("global_C"))
            if current_c > 0:
                cb.params["global_C"] = max(0.0, current_c - 0.1)

    return nudged


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
    import xml.etree.ElementTree as ET

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


def _warm_up(
    raw_path: Path, run_dir: Path, env: dict[str, str], width: int | None
) -> None:
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
    out_path = run_dir / f"render_{style_name.replace(' ', '_')}.jpg"

    try:
        _warm_up(Path(raw_path), run_dir, env, width)

        # Import style into library
        _import_style_into_library(style_path, style_name, run_dir)

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
            actual = list(run_dir.glob(f"render_{style_name.replace(' ', '_')}*.jpg"))
            if actual:
                return max(actual, key=lambda p: p.stat().st_mtime)
        logger.warning("Render failed: %s", result.stderr.decode() if result.stderr else "unknown")
        return None
    except Exception as e:
        logger.warning("Render error: %s", e)
        return None


def evaluate_metrics(
    metrics: RenderMetrics,
    target_analysis: ImageAnalysis,
    _tolerance: float = 0.15,  # reserved: evaluation strictness knob
    reference_look: "LookProfile | None" = None,
    reference_analysis: dict | None = None,
) -> tuple[bool, list[str]]:
    """Evaluate render metrics against target analysis.

    When ``reference_look`` (a :class:`~dtstylekit.eval.metrics.LookProfile`
    extracted from the reference image) is supplied, the evaluation also scores
    the *colour grade* the VLM was supposed to reproduce — hue / chroma /
    warmth / contrast — and feeds those errors back as refinement guidance,
    closing the look-fidelity loop (not just the safety checks).

    Returns (passed, feedback_list).
    """

    feedback = []
    passed = True

    target_lum = getattr(getattr(target_analysis, "luminance", None), "mean", 0.5)
    target_sat = getattr(getattr(target_analysis, "luminance", None), "saturation_mean", 0.2)
    getattr(getattr(target_analysis, "luminance", None), "shadows_pct", 0.1)

    # With reference-driven generation the reference look, not the target
    # photo, defines the intended brightness/colourfulness.  Comparing a
    # moody 0.203-luminance reference against a 0.30-luminance target made
    # every iteration "fail" as too dark (and pushed the VLM brighter).
    ref_lum = _as_float((reference_analysis or {}).get("global_luminance"))
    if ref_lum is not None and ref_lum > 0.01:
        target_lum = ref_lum
    ref_sat = _as_float((reference_analysis or {}).get("global_saturation"))
    # ``global_saturation`` is normalised HSV saturation, so it must be
    # compared with ``mean_hsv_saturation`` (not the un-normalised
    # ``mean_saturation``).  Mixing the two produced contradictory feedback:
    # "desaturates (0.19/0.31)" and "more saturated (HSV 0.48)" in the same
    # iteration.
    sat_value = metrics.mean_saturation
    if ref_sat is not None and ref_sat > 0.01:
        target_sat = ref_sat
        sat_value = metrics.mean_hsv_saturation

    # Luminance preservation (style shouldn't drastically change exposure)
    lum_ratio = metrics.mean_luminance / max(target_lum, 0.01)
    if not (0.7 <= lum_ratio <= 1.3):
        passed = False
        feedback.append(
            f"LUMINANCE SHIFT: target={target_lum:.2f} got={metrics.mean_luminance:.2f} "
            f"(ratio={lum_ratio:.2f}). Style {'darkens' if lum_ratio < 1 else 'brightens'} too much."
        )

    # Saturation increase (color grading should add saturation)
    sat_ratio = sat_value / max(target_sat, 0.01)
    if sat_ratio < 0.8:
        passed = False
        feedback.append(
            f"SATURATION LOSS: target={target_sat:.2f} got={sat_value:.2f} "
            f"(ratio={sat_ratio:.2f}). Style desaturates instead of grading."
        )

    # Red cast detection
    if metrics.has_red_cast:
        passed = False
        feedback.append(
            f"RED CAST: R/G={metrics.r_over_g:.2f} (R={metrics.r_mean:.2f} G={metrics.g_mean:.2f} B={metrics.b_mean:.2f}). "
            f"Check colorbalancergb.global_C=0.0 and global_H≠0 if global_C>0."
        )

    # Crushing detection
    if metrics.is_crushed:
        passed = False
        feedback.append(
            f"SHADOWS CRUSHED: mean_lum={metrics.mean_luminance:.2f} std={metrics.std_luminance:.2f}. "
            f"Reduce filmicrgb.balance, colorbalancergb.shadows_Y, global_Y."
        )

    # Highlight protection
    if metrics.highlights_pct > 0.4 and target_analysis.luminance.highlights_pct < 0.2:
        passed = False
        feedback.append(
            f"HIGHLIGHTS BLOWN: highlights_pct={metrics.highlights_pct:.1%}. "
            f"Reduce exposure.exposure, filmicrgb.white_point_source, colorbalancergb.highlights_Y."
        )

    # Color separation (teal shadows vs warm highlights)
    if metrics.r_over_g < 0.8 and metrics.b_mean > metrics.r_mean:
        passed = False
        feedback.append(
            f"BLUE CAST: R/G={metrics.r_over_g:.2f} B>R. Check colorbalancergb.shadows_H≠220+, global_H≠210."
        )

    # Look-fidelity loop: compare the rendered output's grade against the
    # reference look the VLM was given.  We build the achieved profile from
    # the already-computed render metrics (cheap; no re-read of the file).
    if reference_look is not None:
        from dtstylekit.eval.metrics import LookProfile

        achieved = LookProfile(
            r_over_g=metrics.r_over_g,
            r_mean=metrics.r_mean,
            g_mean=metrics.g_mean,
            b_mean=metrics.b_mean,
            mean_luminance=metrics.mean_luminance,
            mean_saturation=metrics.mean_saturation,
            shadows_pct=metrics.shadows_pct,
            highlights_pct=metrics.highlights_pct,
        )
        from dtstylekit.eval.metrics import compare_looks

        fid = compare_looks(reference_look, achieved)
        if not fid.safety_ok:
            passed = False
        elif not fid.passed:
            passed = False
        if fid.notes:
            feedback.extend(f"LOOK: {n}" for n in fid.notes)
        # Strong grade errors always force another iteration even if safety
        # happened to pass (a safe-but-wrong look is still wrong).
        if fid.hue_score < 0.7 or fid.chroma_score < 0.7:
            passed = False

    return passed, feedback


def build_refinement_prompt(
    original_direction: str,
    feedback: list[str],
    metrics: RenderMetrics,
    target_analysis: ImageAnalysis,
    reference_analysis: dict | None = None,
) -> str:
    """Build a refined direction prompt based on evaluation feedback."""
    target_lum = _metric_attr(target_analysis, "luminance", "mean")
    target_shadows = _metric_attr(target_analysis, "luminance", "shadows_pct")
    target_sat = _metric_attr(target_analysis, "luminance", "saturation_mean")

    lines = [
        original_direction,
        "",
        "[REFINEMENT FEEDBACK — PREVIOUS RENDER FAILED THESE CHECKS]",
    ]
    for f in feedback:
        lines.append(f"  ❌ {f}")

    lines.extend(
        [
            "",
            "[CORRECTIVE GUIDANCE]",
            f"• Target luminance: {target_lum:.2f} (current render: {metrics.mean_luminance:.2f})",
            f"• Target shadows: {target_shadows:.1%} (current render shadows: {metrics.shadows_pct:.1%})",
        ]
    )

    # Reference-driven corrections take precedence: they describe the
    # measured mismatch, not only target-image expectations.
    if reference_analysis:
        ref_lum = _as_float(reference_analysis.get("global_luminance"))
        if metrics.mean_luminance > ref_lum + 0.15:
            lines.append("• DECREASE exposure.exposure by -0.3 to -0.8 EV")
            lines.append("• SET filmicrgb.balance = 0 to +2 (avoid lifting shadows)")
        elif metrics.mean_luminance < ref_lum - 0.15:
            lines.append("• INCREASE exposure.exposure by +0.3 to +0.8 EV")

        ref_sat = _as_float(reference_analysis.get("global_saturation"))
        if metrics.mean_saturation > ref_sat + 0.10:
            lines.append(
                "• REDUCE filmicrgb.saturation toward 0 or negative; for colorful "
                "looks keep filmicrgb.saturation in [0, +15]"
            )
            lines.append("• REDUCE colorbalancergb.chroma_global by 0.05 to 0.15")
        elif metrics.mean_saturation < ref_sat - 0.10:
            lines.append("• INCREASE colorbalancergb.shadows_C / midtones_C / highlights_C")

        ref_warm = _as_float(reference_analysis.get("global_warmth_rb"))
        render_warm = metrics.r_mean - metrics.b_mean
        if render_warm > ref_warm + 0.05:
            lines.append("• GRADE COOLER: reduce colorbalancergb.global_C or shift global_H toward 200-220")
        elif render_warm < ref_warm - 0.05:
            lines.append("• GRADE WARMER: shift colorbalancergb.global_H toward 30-50")

    # Specific corrections based on target-image failure modes
    if target_lum > 0 and metrics.mean_luminance / target_lum < 0.8:
        lines.append("• INCREASE exposure.exposure by +0.2 to +0.4 EV")
        lines.append("• REDUCE filmicrgb.balance (make less negative, e.g. -3 → 0)")
        lines.append("• REDUCE colorbalancergb.shadows_Y magnitude (e.g. -0.25 → -0.15)")
        lines.append("• SET colorbalancergb.global_Y = 0.0")

    if metrics.has_red_cast:
        lines.append("• SET colorbalancergb.global_C = 0.0 (was >0 with global_H=0)")
        lines.append("• If deliberate warm cast needed: global_C=0.1 with global_H=45")

    if metrics.is_crushed:
        lines.append("• SET filmicrgb.balance = -3 to +3 (NOT ≤ -10)")
        lines.append("• SET colorbalancergb.shadows_Y > -0.2")
        lines.append("• SET colorbalancergb.global_Y = 0.0")

    if target_sat > 0 and metrics.mean_saturation / target_sat < 0.8:
        lines.append("• INCREASE colorbalancergb.shadows_C / highlights_C / midtones_C")
        lines.append(
            "• Use chroma_global = -0.15 to -0.25 for film-like desat (not filmicrgb.saturation)"
        )

    lines.append("")
    lines.append("Generate corrected JSON with ONLY the necessary parameter changes.")
    return "\n".join(lines)


def _metric_attr(analysis: object, group: str, field: str) -> float:
    """Read a numeric metric from an analysis object, tolerating mocks."""
    value = getattr(getattr(analysis, group, None), field, 0.0)
    return _as_float(value)


def iterative_refine(
    raw_path: Path,
    reference_paths: list[Path],
    direction: str,
    target_analysis: ImageAnalysis,
    generate_func: Callable[[str, list[str]], StyleSpec],
    max_iterations: int = 3,
    work_dir: Path | None = None,
    reference_look: "LookProfile | None" = None,
    reference_analysis: dict | None = None,
) -> RefinementResult:
    """Iterative refinement loop: generate → render → evaluate → adjust.

    Args:
        raw_path: Path to RAW file for test rendering
        reference_paths: Reference images for style direction
        direction: Initial style direction
        target_analysis: ImageAnalysis of target look (reference aggregate)
        generate_func: Callable(direction, reference_b64s) -> StyleSpec
        max_iterations: Maximum refinement iterations
        work_dir: Optional work directory (created if None)
        reference_look: Optional :class:`~dtstylekit.eval.metrics.LookProfile`
            of the reference look. When omitted but ``reference_paths`` are
            present, it is extracted automatically so the loop also corrects
            *colour grade* errors, not only safety.

    Returns:
        RefinementResult with the refined StyleSpec plus metadata about
        how the run ended (iterations completed, whether evaluation passed).
    """
    import base64

    from dtstylekit.eval.metrics import extract_look_profile

    if work_dir is None:
        work_dir = Path(tempfile.mkdtemp(prefix="dtstylekit_refine_"))
    else:
        work_dir.mkdir(parents=True, exist_ok=True)

    # Build the reference look profile once (drives look-fidelity feedback).
    if reference_look is None and reference_paths:
        try:
            reference_look = extract_look_profile(reference_paths[0])
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("Could not build reference look profile: %s", exc)

    # Encode references once
    ref_b64s = [base64.b64encode(p.read_bytes()).decode("ascii") for p in reference_paths]

    if max_iterations <= 0:
        spec = generate_func(direction, ref_b64s)
        return RefinementResult(spec=spec, iterations_completed=0, passed=False)

    current_direction = direction
    best_spec = None
    best_metrics = None

    for iteration in range(max_iterations):
        logger.info("=== Refinement iteration %d/%d ===", iteration + 1, max_iterations)

        # Generate style spec
        spec = generate_func(current_direction, ref_b64s)

        # Save temporary .dtstyle for rendering
        from dtstylekit.composer.generator import generate_dtstyle

        style_path = work_dir / f"iter_{iteration}.dtstyle"
        generate_dtstyle(spec, [], style_path, target_analysis)

        # Render test image
        style_name = spec.style_name or f"iter_{iteration}"
        rendered = render_with_style(raw_path, style_path, style_name, work_dir)

        if rendered is None:
            logger.warning("Render failed, stopping refinement")
            return RefinementResult(
                spec=best_spec or spec, iterations_completed=iteration, passed=False
            )

        # Evaluate
        metrics = compute_render_metrics(rendered)
        passed, feedback = evaluate_metrics(
            metrics,
            target_analysis,
            reference_look=reference_look,
            reference_analysis=reference_analysis,
        )
        if reference_analysis and reference_paths:
            ref_passed, ref_feedback = compare_to_references(
                rendered, reference_paths, reference_analysis
            )
            feedback.extend(ref_feedback)
            if not ref_passed:
                passed = False

        logger.info(
            "Iteration %d: passed=%s, lum=%.3f, sat=%.3f, R/G=%.2f",
            iteration + 1,
            passed,
            metrics.mean_luminance,
            metrics.mean_saturation,
            metrics.r_over_g,
        )
        for f in feedback:
            logger.info("  Feedback: %s", f)

        if passed:
            logger.info("✓ Style passed evaluation on iteration %d", iteration + 1)
            return RefinementResult(spec=spec, iterations_completed=iteration + 1, passed=True)

        # Keep best so far (least bad)
        if best_metrics is None or _score_metrics(metrics) > _score_metrics(best_metrics):
            best_spec = spec
            best_metrics = metrics

        # Build refined direction for next iteration
        if iteration < max_iterations - 1:
            current_direction = build_refinement_prompt(
                direction, feedback, metrics, target_analysis, reference_analysis
            )

    # Return best attempt even if not perfect
    logger.warning("Refinement completed without passing; returning best attempt")
    return RefinementResult(
        spec=best_spec or spec, iterations_completed=max_iterations, passed=False
    )


def _score_metrics(m: RenderMetrics) -> float:
    """Score metrics (higher = better)."""
    score = 0.0
    # Prefer luminance near 0.3-0.5 (not crushed, not blown)
    if 0.15 < m.mean_luminance < 0.7:
        score += 1.0
    # Prefer some saturation
    if m.mean_saturation > 0.1:
        score += 0.5
    # Penalize red cast
    if not m.has_red_cast:
        score += 1.0
    # Penalize crushing
    if not m.is_crushed:
        score += 1.0
    return score
