"""Iterative style refinement: generate → render → evaluate → adjust.

Closes the feedback loop by rendering the generated style, measuring
visual metrics, and feeding corrections back to the VLM.
"""

import sys
from collections.abc import Callable
from pathlib import Path

# Ensure dtstylekit is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import logging
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dtstylekit.analyzer.models import ImageAnalysis

# Import for runtime use
from dtstylekit.analyzer.models import ImageAnalysis
from dtstylekit.vlm.models import StyleSpec

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
    sat = arr.max(-1) - arr.min(-1)

    # Shadows/highlights by luminance percentiles
    shadows_pct = float((lum < 0.15).mean())
    highlights_pct = float((lum > 0.85).mean())

    return RenderMetrics(
        mean_luminance=float(lum.mean()),
        std_luminance=float(lum.std()),
        mean_saturation=float(sat.mean()),
        r_mean=float(arr[..., 0].mean()),
        g_mean=float(arr[..., 1].mean()),
        b_mean=float(arr[..., 2].mean()),
        r_over_g=float(arr[..., 0].mean() / max(float(arr[..., 1].mean()), 1e-6)),  # type: ignore[operator]
        shadows_pct=shadows_pct,
        highlights_pct=highlights_pct,
    )


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


def render_with_style(
    raw_path: Path,
    style_path: Path,
    style_name: str,
    work_dir: Path,
    width: int = 1200,
) -> Path | None:
    """Render a RAW with the given style using isolated darktable library.

    Returns path to rendered JPG or None on failure.
    """
    out_path = work_dir / f"render_{style_name.replace(' ', '_')}.jpg"

    env = {
        "HOME": str(work_dir),
        "XDG_CONFIG_HOME": str(work_dir / "cfg"),
        "XDG_DATA_HOME": str(work_dir / "data"),
    }

    try:
        # First ensure library exists (baseline export)
        baseline = work_dir / "baseline_init.jpg"
        subprocess.run(
            ["darktable-cli", str(raw_path), str(baseline), "--width", str(width)],
            env=env,
            capture_output=True,
            timeout=120,
            check=False,
        )

        # Import style into library
        _import_style_into_library(style_path, style_name, work_dir)

        # Render with style
        result = subprocess.run(
            [
                "darktable-cli",
                str(raw_path),
                str(out_path),
                "--width",
                str(width),
                "--style",
                style_name,
            ],
            env=env,
            capture_output=True,
            timeout=180,
            check=False,
        )

        if result.returncode == 0 and out_path.exists():
            # darktable-cli doesn't overwrite - find actual output
            actual = list(work_dir.glob(f"render_{style_name.replace(' ', '_')}*.jpg"))
            if actual:
                return actual[-1]  # latest version
        logger.warning("Render failed: %s", result.stderr.decode() if result.stderr else "unknown")
        return None
    except Exception as e:
        logger.warning("Render error: %s", e)
        return None


def evaluate_metrics(
    metrics: RenderMetrics,
    target_analysis: ImageAnalysis,
    _tolerance: float = 0.15,  # reserved: evaluation strictness knob
) -> tuple[bool, list[str]]:
    """Evaluate render metrics against target analysis.

    Returns (passed, feedback_list).
    """
    feedback = []
    passed = True

    target_lum = getattr(getattr(target_analysis, "luminance", None), "mean", 0.5)
    target_sat = getattr(getattr(target_analysis, "luminance", None), "saturation_mean", 0.2)
    getattr(getattr(target_analysis, "luminance", None), "shadows_pct", 0.1)

    # Luminance preservation (style shouldn't drastically change exposure)
    lum_ratio = metrics.mean_luminance / max(target_lum, 0.01)
    if not (0.7 <= lum_ratio <= 1.3):
        passed = False
        feedback.append(
            f"LUMINANCE SHIFT: target={target_lum:.2f} got={metrics.mean_luminance:.2f} "
            f"(ratio={lum_ratio:.2f}). Style {'darkens' if lum_ratio < 1 else 'brightens'} too much."
        )

    # Saturation increase (color grading should add saturation)
    sat_ratio = metrics.mean_saturation / max(target_sat, 0.01)
    if sat_ratio < 0.8:
        passed = False
        feedback.append(
            f"SATURATION LOSS: target={target_sat:.2f} got={metrics.mean_saturation:.2f} "
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

    return passed, feedback


def build_refinement_prompt(
    original_direction: str,
    feedback: list[str],
    metrics: RenderMetrics,
    target_analysis: ImageAnalysis,
) -> str:
    """Build a refined direction prompt based on evaluation feedback."""
    target_lum = target_analysis.luminance.mean
    target_shadows = target_analysis.luminance.shadows_pct

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

    # Specific corrections based on failure modes
    if metrics.mean_luminance / max(target_lum, 0.01) < 0.8:
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

    if metrics.mean_saturation / max(target_analysis.luminance.saturation_mean, 0.01) < 0.8:
        lines.append("• INCREASE colorbalancergb.shadows_C / highlights_C / midtones_C")
        lines.append(
            "• Use chroma_global = -0.15 to -0.25 for film-like desat (not filmicrgb.saturation)"
        )

    lines.append("")
    lines.append("Generate corrected JSON with ONLY the necessary parameter changes.")
    return "\n".join(lines)


def iterative_refine(
    raw_path: Path,
    reference_paths: list[Path],
    direction: str,
    target_analysis: ImageAnalysis,
    generate_func: Callable[[str, list[str]], StyleSpec],
    max_iterations: int = 3,
    work_dir: Path | None = None,
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

    Returns:
        RefinementResult with the refined StyleSpec plus metadata about
        how the run ended (iterations completed, whether evaluation passed).
    """
    import base64

    if work_dir is None:
        work_dir = Path(tempfile.mkdtemp(prefix="dtstylekit_refine_"))
    else:
        work_dir.mkdir(parents=True, exist_ok=True)

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
            assert best_spec is not None
            return RefinementResult(spec=best_spec, iterations_completed=iteration, passed=False)

        # Evaluate
        metrics = compute_render_metrics(rendered)
        passed, feedback = evaluate_metrics(metrics, target_analysis)

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
                direction, feedback, metrics, target_analysis
            )

    # Return best attempt even if not perfect
    logger.warning("Refinement completed without passing; returning best attempt")
    assert best_spec is not None
    return RefinementResult(spec=best_spec, iterations_completed=max_iterations, passed=False)


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
