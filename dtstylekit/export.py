"""Export a style to one or more images with per-image exposure normalization.

A ``.dtstyle`` stores fixed module parameters, including an exposure value.
That value cannot be correct for a set of photos with different exposures:
applying a style baked for a dark frame to a bright one blows its highlights.
The exporter therefore keeps the style's *look* and adjusts exposure per
image so the result reaches a reference brightness while staying below a
highlight-clipping limit.
"""

from __future__ import annotations

import logging
import math
import shutil
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from dtstylekit.codec.iop_registry import pack_params, unpack_params
from dtstylekit.codec.serializer import encode_plugin
from dtstylekit.codec.xmp_codec import decode_xmp, encode_xmp
from dtstylekit.vlm.iterative_refiner import compute_render_metrics, render_with_style

logger = logging.getLogger(__name__)

DEFAULT_TARGET_LUMINANCE = 0.20
DEFAULT_MAX_CLIP = 0.01


@dataclass
class ExportResult:
    """Outcome for one exported image."""

    output_path: Path
    source_path: Path
    exposure_ev: float
    mean_luminance: float
    clipped_pct: float


def _exposure_plugin(root: ET.Element) -> ET.Element | None:
    for plugin in root.findall("./style/plugin"):
        if plugin.findtext("operation") == "exposure":
            return plugin
    return None


def _plugin_params(plugin: ET.Element) -> dict:
    operation = plugin.findtext("operation") or ""
    blob = decode_xmp(plugin.findtext("op_params") or "")
    return unpack_params(operation, blob)


def style_exposure(style_path: str | Path) -> tuple[float, float]:
    """Return ``(exposure_ev, black)`` from a style's first exposure module."""
    root = ET.parse(style_path).getroot()
    plugin = _exposure_plugin(root)
    if plugin is None:
        return 0.0, 0.0
    params = _plugin_params(plugin)
    return float(params.get("exposure", 0.0)), float(params.get("black", 0.0))


def style_with_exposure(
    style_path: str | Path,
    exposure_ev: float,
    output_path: str | Path,
    *,
    black: float | None = None,
) -> Path:
    """Write a copy of ``style_path`` with the exposure module adjusted.

    If the style has no exposure module, one is appended.  ``black`` is left
    untouched unless explicitly supplied.
    """
    root = ET.parse(style_path).getroot()
    style = root.find("style")
    if style is None:
        raise ValueError(f"Not a darktable style (no <style>): {style_path}")

    plugin = _exposure_plugin(root)
    if plugin is None:
        nums = []
        for existing in style.findall("plugin"):
            try:
                nums.append(int(existing.findtext("num") or 0))
            except ValueError:
                pass
        encoded = encode_plugin(
            {
                "operation": "exposure",
                "params": {"exposure": exposure_ev, "black": black or 0.0},
                "num": (max(nums) + 1) if nums else 0,
                "module": 7,
            }
        )
        plugin = ET.SubElement(style, "plugin")
        for tag in (
            "num",
            "module",
            "operation",
            "op_params",
            "enabled",
            "blendop_params",
            "blendop_version",
            "multi_priority",
            "multi_name",
            "multi_name_hand_edited",
        ):
            value = encoded["op_params_encoded"] if tag == "op_params" else encoded["blendop_encoded"] if tag == "blendop_params" else encoded[tag]
            ET.SubElement(plugin, tag).text = str(value)
    else:
        params = _plugin_params(plugin)
        params["exposure"] = float(exposure_ev)
        if black is not None:
            params["black"] = float(black)
        blob = pack_params("exposure", params)
        blob_node = plugin.find("op_params")
        if blob_node is None:
            raise ValueError("exposure plugin has no <op_params> node")
        blob_node.text = encode_xmp(blob)

    destination = Path(output_path)
    ET.ElementTree(root).write(destination, encoding="UTF-8", xml_declaration=True)
    return destination


def reference_target_luminance(reference_paths: Sequence[str | Path]) -> float:
    """Reference mean luminance measured by the analyzer."""
    from dtstylekit.analyzer.pipeline import compute_reference_signature

    signature = compute_reference_signature([Path(p) for p in reference_paths])
    value = signature.get("global_luminance")
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError("Could not compute reference luminance")
    return float(value)


def _normalize_one(
    image: Path,
    style_path: Path,
    work_dir: Path,
    target_luminance: float,
    max_clip: float,
    preview_width: int,
) -> tuple[float, float, float]:
    """Find the exposure that best matches the target without clipping.

    Exposure and mean luminance are monotonic, so bracket the target and
    bisect.  Newton-style log2 steps overshoot badly because the filmic
    shoulder compresses highlights non-linearly; bisection converges in a
    handful of cheap 1200 px previews.  Renders above ``max_clip`` are only
    chosen when no clipping-free exposure exists.
    """
    base_ev, _black = style_exposure(style_path)
    rendered = 0

    def evaluate(ev: float) -> tuple[bool, float, float, float, float]:
        nonlocal rendered
        rendered += 1
        variant = style_with_exposure(
            style_path,
            ev,
            work_dir / f"preview_{image.stem}_{rendered}.dtstyle",
        )
        preview = render_with_style(
            image,
            variant,
            "apply",
            work_dir,
            width=preview_width,
        )
        if preview is None:
            raise RuntimeError(f"darktable failed to render {image}")
        metrics = compute_render_metrics(preview)
        error = abs(math.log2(target_luminance / max(metrics.mean_luminance, 1e-4)))
        return (
            metrics.clipped_pct <= max_clip,
            metrics.mean_luminance,
            metrics.clipped_pct,
            error,
            ev,
        )

    def score(item: tuple[bool, float, float, float, float]) -> tuple[int, float]:
        feasible, _lum, clip, error, _ev = item
        return (0, error) if feasible else (1, clip)

    current = evaluate(base_ev)
    best = current
    if current[0] and current[3] <= 0.12:
        return current[4], current[1], current[2]

    # An exposure above the clipping limit is unusable: first move down.
    if not current[0]:
        hi = base_ev
        lo = max(-6.0, base_ev - 1.0)
        while lo > -6.0:
            item = evaluate(lo)
            if score(item) < score(best):
                best = item
            if item[0]:
                break
            hi = lo
            lo = max(-6.0, lo - 1.0)
    elif current[1] < target_luminance:
        lo = base_ev
        hi = min(6.0, base_ev + 1.0)
        while hi < 6.0:
            item = evaluate(hi)
            if score(item) < score(best):
                best = item
            if item[1] >= target_luminance:
                break
            lo = hi
            hi = min(6.0, hi + 1.0)
    else:
        hi = base_ev
        lo = max(-6.0, base_ev - 1.0)
        while lo > -6.0:
            item = evaluate(lo)
            if score(item) < score(best):
                best = item
            if item[1] <= target_luminance:
                break
            hi = lo
            lo = max(-6.0, lo - 1.0)

    for _ in range(6):
        if abs(hi - lo) < 0.05:
            break
        mid = (lo + hi) / 2.0
        item = evaluate(mid)
        if score(item) < score(best):
            best = item
        if item[0] and item[3] <= 0.12:
            best = item
            break
        if item[1] < target_luminance:
            lo = mid
        else:
            hi = mid

    return best[4], best[1], best[2]


def apply_style_to_images(
    style_path: str | Path,
    image_paths: Sequence[str | Path],
    output_dir: str | Path,
    *,
    target_luminance: float = DEFAULT_TARGET_LUMINANCE,
    max_clip: float = DEFAULT_MAX_CLIP,
    preview_width: int = 1200,
    final_width: int | None = None,
    work_dir: str | Path | None = None,
) -> list[ExportResult]:
    """Apply ``style_path`` to every image, normalizing exposure per image.

    ``final_width=None`` renders at full resolution.  The returned list has
    one entry per image; failures raise ``RuntimeError``.
    """
    style = Path(style_path)
    if not style.exists():
        raise FileNotFoundError(style)
    if not 0.0 < target_luminance < 1.0:
        raise ValueError("target_luminance must be between 0 and 1")
    if not 0.0 <= max_clip <= 1.0:
        raise ValueError("max_clip must be between 0 and 1")

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    work = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="dtstylekit_apply_"))
    work.mkdir(parents=True, exist_ok=True)

    results: list[ExportResult] = []
    for image in (Path(p) for p in image_paths):
        if not image.exists():
            raise FileNotFoundError(image)
        exposure_ev, _lum, _clip = _normalize_one(
            image, style, work, target_luminance, max_clip, preview_width
        )
        variant = style_with_exposure(
            style, exposure_ev, work / f"final_{image.stem}.dtstyle"
        )
        rendered = render_with_style(
            image, variant, "apply", work, width=final_width
        )
        if rendered is None:
            raise RuntimeError(f"darktable failed to render {image}")
        destination = out / f"{image.stem}.jpg"
        shutil.copyfile(rendered, destination)
        final = compute_render_metrics(destination)
        logger.info(
            "Exported %s (EV %+.2f, lum=%.3f, clipped=%.1f%%)",
            destination,
            exposure_ev,
            final.mean_luminance,
            final.clipped_pct * 100.0,
        )
        results.append(
            ExportResult(
                output_path=destination,
                source_path=image,
                exposure_ev=exposure_ev,
                mean_luminance=final.mean_luminance,
                clipped_pct=final.clipped_pct,
            )
        )
    return results


__all__ = [
    "DEFAULT_MAX_CLIP",
    "DEFAULT_TARGET_LUMINANCE",
    "ExportResult",
    "apply_style_to_images",
    "reference_target_luminance",
    "style_exposure",
    "style_with_exposure",
]
