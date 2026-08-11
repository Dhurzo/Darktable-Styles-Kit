#!/usr/bin/env python3
"""Adjust a base style per RAW based on exposure difference vs reference aggregate.

Strategy:
1. Compute aggregate stats of all Palander references (target look)
2. For each RAW preview, compute its stats
3. Calculate exposure delta and adjust:
   - exposure.exposure (EV shift)
   - filmicrgb.balance (shadow vs highlight weight)
   - filmicrgb.contrast (if needed)
   - colorbalancergb.shadows_Y / global_Y (brightness)
4. Output per-RAW .dtstyle files
"""

from __future__ import annotations

import logging
import os
import struct
from pathlib import Path

import numpy as np
from PIL import Image

from dtstylekit.codec.xmp_codec import decode_xmp, encode_xmp
import xml.etree.ElementTree as ET

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def compute_image_stats(image_path: Path) -> dict:
    """Compute luminance, saturation, RGB means."""
    img = Image.open(image_path).convert("RGB")
    arr = np.array(img, dtype=np.float32) / 255.0

    # Luminance (Rec. 709)
    lum = 0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2]
    # Saturation (max - min per pixel)
    sat = arr.max(-1) - arr.min(-1)

    r, g, b = arr[..., 0].mean(), arr[..., 1].mean(), arr[..., 2].mean()

    return {
        "mean_lum": float(lum.mean()),
        "std_lum": float(lum.std()),
        "mean_sat": float(sat.mean()),
        "r_mean": r,
        "g_mean": g,
        "b_mean": b,
        "r_over_g": r / max(g, 1e-6),
        "shadows_pct": float((lum < 0.15).mean()),
        "highlights_pct": float((lum > 0.85).mean()),
    }


def compute_reference_aggregate(ref_dir: Path) -> dict:
    """Compute aggregate stats of all reference images."""
    stats_list = []
    for f in sorted(ref_dir.glob("*.jpeg")):
        stats = compute_image_stats(f)
        stats_list.append(stats)
        logger.info("Ref %s: lum=%.3f sat=%.3f R/G=%.2f", f.name, stats["mean_lum"], stats["mean_sat"], stats["r_over_g"])

    # Aggregate: mean of means
    agg = {
        "mean_lum": float(np.mean([s["mean_lum"] for s in stats_list])),
        "std_lum": float(np.mean([s["std_lum"] for s in stats_list])),
        "mean_sat": float(np.mean([s["mean_sat"] for s in stats_list])),
        "r_mean": float(np.mean([s["r_mean"] for s in stats_list])),
        "g_mean": float(np.mean([s["g_mean"] for s in stats_list])),
        "b_mean": float(np.mean([s["b_mean"] for s in stats_list])),
        "r_over_g": float(np.mean([s["r_over_g"] for s in stats_list])),
        "shadows_pct": float(np.mean([s["shadows_pct"] for s in stats_list])),
        "highlights_pct": float(np.mean([s["highlights_pct"] for s in stats_list])),
    }
    logger.info("AGGREGATE TARGET: lum=%.3f sat=%.3f R/G=%.2f shadows=%.1f%% highlights=%.1f%%",
                agg["mean_lum"], agg["mean_sat"], agg["r_over_g"],
                agg["shadows_pct"]*100, agg["highlights_pct"]*100)
    return agg


def parse_style_params(style_path: Path) -> dict:
    """Parse .dtstyle and return plugin params as dicts."""
    root = ET.parse(style_path).getroot()
    params = {}
    for plugin in root.findall("style/plugin"):
        op = plugin.findtext("operation", "")
        op_enc = plugin.findtext("op_params", "") or ""
        if op_enc:
            blob = decode_xmp(op_enc)
            if op == "filmicrgb":
                vals = struct.unpack("<18fiiiiiiiIIiI", blob)
                fields = [
                    "grey_point_source", "black_point_source", "white_point_source",
                    "reconstruct_threshold", "reconstruct_feather",
                    "reconstruct_bloom_vs_details", "reconstruct_grey_vs_color",
                    "reconstruct_structure_vs_texture", "security_factor",
                    "grey_point_target", "black_point_target", "white_point_target",
                    "output_power", "latitude", "contrast", "saturation", "balance",
                    "noise_level", "preserve_color", "version", "auto_hardness",
                    "custom_grey", "high_quality_reconstruction", "noise_distribution",
                    "shadows", "highlights", "compensate_icc_black", "spline_version",
                    "enable_highlight_reconstruction"
                ]
                params["filmicrgb"] = dict(zip(fields, vals))
            elif op == "colorbalancergb":
                vals = struct.unpack("<32fi", blob)
                fields = [
                    "shadows_Y", "shadows_C", "shadows_H",
                    "midtones_Y", "midtones_C", "midtones_H",
                    "highlights_Y", "highlights_C", "highlights_H",
                    "global_Y", "global_C", "global_H",
                    "shadows_weight", "white_fulcrum", "highlights_weight",
                    "chroma_shadows", "chroma_highlights", "chroma_global",
                    "chroma_midtones", "saturation_global", "saturation_highlights",
                    "saturation_midtones", "saturation_shadows", "hue_angle",
                    "brilliance_global", "brilliance_highlights", "brilliance_midtones",
                    "brilliance_shadows", "mask_grey_fulcrum", "vibrance",
                    "grey_fulcrum", "contrast", "saturation_formula"
                ]
                params["colorbalancergb"] = dict(zip(fields, vals))
            elif op == "exposure":
                vals = struct.unpack("<iffffii", blob)
                fields = ["mode", "black", "exposure", "deflicker_percentile",
                          "deflicker_target_level", "compensate_exposure_bias",
                          "compensate_hilite_pres"]
                params["exposure"] = dict(zip(fields, vals))
    return params


def build_filmicrgb_blob(params: dict) -> bytes:
    """Pack filmicrgb params back to blob."""
    fields = [
        "grey_point_source", "black_point_source", "white_point_source",
        "reconstruct_threshold", "reconstruct_feather",
        "reconstruct_bloom_vs_details", "reconstruct_grey_vs_color",
        "reconstruct_structure_vs_texture", "security_factor",
        "grey_point_target", "black_point_target", "white_point_target",
        "output_power", "latitude", "contrast", "saturation", "balance",
        "noise_level", "preserve_color", "version", "auto_hardness",
        "custom_grey", "high_quality_reconstruction", "noise_distribution",
        "shadows", "highlights", "compensate_icc_black", "spline_version",
        "enable_highlight_reconstruction"
    ]
    vals = [params.get(f, 0) for f in fields]
    return struct.pack("<18fiiiiiiiIIiI", *vals)


def build_colorbalancergb_blob(params: dict) -> bytes:
    """Pack colorbalancergb params back to blob."""
    fields = [
        "shadows_Y", "shadows_C", "shadows_H",
        "midtones_Y", "midtones_C", "midtones_H",
        "highlights_Y", "highlights_C", "highlights_H",
        "global_Y", "global_C", "global_H",
        "shadows_weight", "white_fulcrum", "highlights_weight",
        "chroma_shadows", "chroma_highlights", "chroma_global",
        "chroma_midtones", "saturation_global", "saturation_highlights",
        "saturation_midtones", "saturation_shadows", "hue_angle",
        "brilliance_global", "brilliance_highlights", "brilliance_midtones",
        "brilliance_shadows", "mask_grey_fulcrum", "vibrance",
        "grey_fulcrum", "contrast", "saturation_formula"
    ]
    vals = [params.get(f, 0) for f in fields]
    return struct.pack("<32fi", *vals)


def build_exposure_blob(params: dict) -> bytes:
    """Pack exposure params back to blob."""
    fields = ["mode", "black", "exposure", "deflicker_percentile",
              "deflicker_target_level", "compensate_exposure_bias",
              "compensate_hilite_pres"]
    vals = [params.get(f, 0) for f in fields]
    return struct.pack("<iffffii", *vals)


def adjust_style_for_raw(
    base_params: dict,
    preview_stats: dict,
    target_stats: dict,
) -> dict:
    """Adjust style params based on exposure difference."""
    adjusted = {k: v.copy() for k, v in base_params.items()}

    preview_lum = preview_stats["mean_lum"]
    target_lum = target_stats["mean_lum"]

    # Exposure ratio (how much brighter/darker preview is vs target)
    if preview_lum > 0:
        lum_ratio = target_lum / preview_lum
        ev_shift = np.log2(max(lum_ratio, 0.01))  # EV difference
    else:
        ev_shift = 0.0

    logger.info("  Preview lum=%.3f, Target lum=%.3f, ratio=%.2f, EV shift=%.2f",
                preview_lum, target_lum, lum_ratio if preview_lum > 0 else 0, ev_shift)

    # 1. Adjust exposure.exposure (EV compensation)
    if "exposure" in adjusted:
        base_exp = adjusted["exposure"].get("exposure", 0.0)
        adjusted["exposure"]["exposure"] = base_exp + ev_shift
        logger.info("  exposure.exposure: %.3f -> %.3f", base_exp, adjusted["exposure"]["exposure"])

    # 2. Adjust filmicrgb if present
    if "filmicrgb" in adjusted:
        fr = adjusted["filmicrgb"]

        # Balance: shift toward highlights if preview is darker than target (need to lift)
        # shift toward shadows if preview is brighter than target (need to crush)
        base_balance = fr.get("balance", 0.0)
        if ev_shift > 0:  # preview darker than target -> need to lift shadows
            new_balance = max(base_balance, -3.0)  # less shadow-weighted
        else:  # preview brighter than target -> can be more shadow-weighted
            new_balance = min(base_balance, -3.0)
        fr["balance"] = new_balance
        logger.info("  filmicrgb.balance: %.1f -> %.1f", base_balance, new_balance)

        # Contrast: reduce if preview has high contrast already
        base_contrast = fr.get("contrast", 1.6)
        if preview_stats["std_lum"] > target_stats["std_lum"] * 1.2:
            fr["contrast"] = max(base_contrast * 0.8, 1.0)
        logger.info("  filmicrgb.contrast: %.2f -> %.2f", base_contrast, fr["contrast"])

        # Saturation: target is low sat (0.03), preview may be higher
        base_sat = fr.get("saturation", -25.0)
        if preview_stats["mean_sat"] > target_stats["mean_sat"] * 2:
            fr["saturation"] = min(base_sat, -30.0)  # more desat
        logger.info("  filmicrgb.saturation: %.1f -> %.1f", base_sat, fr["saturation"])

    # 3. Adjust colorbalancergb
    if "colorbalancergb" in adjusted:
        cb = adjusted["colorbalancergb"]

        # global_Y: compensate global brightness
        base_global_y = cb.get("global_Y", 0.0)
        if ev_shift > 0.5:  # significantly darker
            cb["global_Y"] = min(base_global_y + 0.05, 0.0)
        elif ev_shift < -0.5:  # significantly brighter
            cb["global_Y"] = max(base_global_y - 0.05, -0.1)
        logger.info("  colorbalancergb.global_Y: %.3f -> %.3f", base_global_y, cb["global_Y"])

        # shadows_Y: preserve shadow detail
        base_shadows_y = cb.get("shadows_Y", -0.2)
        if preview_stats["shadows_pct"] > target_stats["shadows_pct"] * 1.5:
            # Preview has more shadows -> don't crush them further
            cb["shadows_Y"] = max(base_shadows_y, -0.15)
        logger.info("  colorbalancergb.shadows_Y: %.3f -> %.3f", base_shadows_y, cb["shadows_Y"])

        # Ensure global_C=0 (no red cast)
        if cb.get("global_C", 0) > 0 and abs(cb.get("global_H", 0)) < 1:
            cb["global_C"] = 0.0
            logger.info("  colorbalancergb.global_C: FIXED to 0.0 (was >0 with H=0)")

    return adjusted


def write_adjusted_style(
    base_style_path: Path,
    adjusted_params: dict,
    output_path: Path,
    style_name: str,
) -> None:
    """Write adjusted params to new .dtstyle file."""
    # Read original XML
    tree = ET.parse(base_style_path)
    root = tree.getroot()

    # Update name
    info_name = root.find("info/name")
    if info_name is not None:
        info_name.text = style_name

    # Update each plugin's op_params
    for plugin in root.findall("style/plugin"):
        op = plugin.findtext("operation", "")
        if op in adjusted_params:
            if op == "filmicrgb":
                blob = build_filmicrgb_blob(adjusted_params[op])
            elif op == "colorbalancergb":
                blob = build_colorbalancergb_blob(adjusted_params[op])
            elif op == "exposure":
                blob = build_exposure_blob(adjusted_params[op])
            else:
                continue

            encoded = encode_xmp(blob)
            op_params_elem = plugin.find("op_params")
            if op_params_elem is not None:
                op_params_elem.text = encoded

    # Write
    tree.write(output_path, encoding="utf-8", xml_declaration=True)
    logger.info("Written: %s", output_path)


def main():
    # Paths
    base_style = Path("/tmp/palander/outputs/Palander_Editorial_DSC03470.dtstyle")  # has all modules
    ref_dir = Path("/tmp/palander/references")
    preview_dir = Path("/tmp/palander/outputs")
    output_dir = Path("/tmp/palander/outputs")

    if not base_style.exists():
        logger.error("Base style not found: %s", base_style)
        return 1

    # 1. Compute target aggregate from references
    target_stats = compute_reference_aggregate(ref_dir)

    # 2. Parse base style params
    base_params = parse_style_params(base_style)
    logger.info("Base style params: %s", {k: list(v.keys()) for k, v in base_params.items()})

    # 3. Process each RAW preview
    raw_previews = {
        "DSC03470": preview_dir / "DSC03470_preview.jpg",
        "DSC05881": preview_dir / "DSC05881_preview.jpg",
        "DSC05885": preview_dir / "DSC05885_preview.jpg",
        "DSC05889": preview_dir / "DSC05889_preview.jpg",
        "nikon_d700": preview_dir / "nikon_d700_preview.jpg",
    }

    for raw_name, preview_path in raw_previews.items():
        if not preview_path.exists():
            logger.warning("Preview not found: %s", preview_path)
            continue

        preview_stats = compute_image_stats(preview_path)
        logger.info("%s preview: lum=%.3f sat=%.3f R/G=%.2f",
                    raw_name, preview_stats["mean_lum"], preview_stats["mean_sat"], preview_stats["r_over_g"])

        # Adjust params
        adjusted = adjust_style_for_raw(base_params, preview_stats, target_stats)

        # Write per-RAW style
        out_path = output_dir / f"Palander_Adjusted_{raw_name}.dtstyle"
        write_adjusted_style(base_style, adjusted, out_path, f"Palander Adjusted {raw_name}")

    logger.info("Done! Generated per-RAW adjusted styles.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())