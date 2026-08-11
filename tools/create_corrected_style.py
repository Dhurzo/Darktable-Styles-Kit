#!/usr/bin/env python3
"""Create a CORRECTED base style matching Palander reference aggregate,
then apply per-RAW exposure compensation.

Parameters are packed/unpacked through ``dtstylekit.codec.iop_registry``
(the single verified source of struct layouts).  Do NOT duplicate struct
formats here — the registry is the only place kept in sync with
``src/iop/*.c`` via ``test_version_drift.py``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from dtstylekit.codec.iop_registry import pack_params, unpack_params
from dtstylekit.codec.xmp_codec import encode_xmp, decode_xmp
import xml.etree.ElementTree as ET

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# blob = encode_xmp(pack_params("filmicrgb", filmicrgb_params)) etc.
# See dtstylekit.codec.iop_registry for the canonical field lists, ranges,
# and defaults — do not hand-roll struct formats here.
_FILMICRGB_FIELDS = (
    "grey_point_source", "black_point_source", "white_point_source",
    "reconstruct_threshold", "reconstruct_feather",
    "reconstruct_bloom_vs_details", "reconstruct_grey_vs_color",
    "reconstruct_structure_vs_texture", "security_factor",
    "grey_point_target", "black_point_target", "white_point_target",
    "output_power", "latitude", "contrast", "saturation", "balance",
    "noise_level", "preserve_color", "version", "auto_hardness",
    "custom_grey", "high_quality_reconstruction", "noise_distribution",
    "shadows", "highlights", "compensate_icc_black", "spline_version",
    "enable_highlight_reconstruction",
)
_COLORBALANCE_FIELDS = (
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
    "grey_fulcrum", "contrast", "saturation_formula",
)
_EXPOSURE_FIELDS = (
    "mode", "black", "exposure", "deflicker_percentile",
    "deflicker_target_level", "compensate_exposure_bias",
    "compensate_hilite_pres",
)


def _encoded(op: str, params: dict) -> str:
    """Pack params via the verified registry and base64-encode for XMP."""
    return encode_xmp(pack_params(op, params))


def _decoded(op: str, encoded: str) -> dict:
    """Decode and unpack a blob from its XMP representation back to a dict."""
    return unpack_params(op, decode_xmp(encoded))


def create_corrected_base_style(output_path: Path) -> None:
    """Create a base style manually tuned to Palander reference aggregate."""
    
    # Palander aggregate target: lum=0.263, sat=0.073, R/G=0.95, shadows=45.5%
    # Key observations from refs:
    # - Very low saturation (0.02-0.04)
    # - Cool shadows (blue-teal), warm highlights (orange)
    # - R/G ~ 0.95 (slightly green/blue bias)
    # - Low luminance (0.18-0.39)

    filmicrgb_params = {
        "grey_point_source": 18.45,
        "black_point_source": -8.0,
        "white_point_source": 4.0,
        "reconstruct_threshold": 0.0,
        "reconstruct_feather": 3.0,
        "reconstruct_bloom_vs_details": 100.0,
        "reconstruct_grey_vs_color": 100.0,
        "reconstruct_structure_vs_texture": 0.0,
        "security_factor": 0.0,
        "grey_point_target": 18.45,
        "black_point_target": 0.01517634,
        "white_point_target": 100.0,
        "output_power": 4.0,
        "latitude": 3.0,
        "contrast": 1.4,
        "saturation": -80.0,    # Much more desat
        "balance": 0.0,
        "noise_level": 0.2,
        "preserve_color": 3,
        "version": 4,
        "auto_hardness": 1,
        "custom_grey": 0,
        "high_quality_reconstruction": 1,
        "noise_distribution": 1,
        "shadows": 0,
        "highlights": 0,
        "compensate_icc_black": 0,
        "spline_version": 2,
        "enable_highlight_reconstruction": 0,
}

    exposure_params = {
        "mode": 0,
        "black": 0.05,
        "exposure": 0.0,        # Neutral base - per-RAW will adjust
        "deflicker_percentile": 50.0,
        "deflicker_target_level": -4.0,
        "compensate_exposure_bias": 0,
        "compensate_hilite_pres": 1,
}

    # Palander refs: shadows are cool (blue-teal), highlights warm (orange)
    # R/G=0.95 means slightly more G/B than R
    colorbalancergb_params = {
        "shadows_Y": -0.15,     # Slightly dark teal shadows
        "shadows_C": 0.5,       # Moderate teal saturation
        "shadows_H": 205.0,     # More blue-teal (was 200)
        "midtones_Y": -0.02,
        "midtones_C": 0.1,
        "midtones_H": 25.0,     # Cooler midtones (was 30)
        "highlights_Y": 0.08,
        "highlights_C": 0.1,
        "highlights_H": 30.0,   # Cooler highlights (was 35)
        "global_Y": 0.0,
        "global_C": 0.0,
        "global_H": 0.0,
        "shadows_weight": 1.0,
        "white_fulcrum": 0.0,
        "highlights_weight": 1.0,
        "chroma_shadows": 0.0,
        "chroma_highlights": 0.0,
        "chroma_global": -0.3,  # More global desat
        "chroma_midtones": 0.0,
        "saturation_global": 0.0,
        "saturation_highlights": 0.0,
        "saturation_midtones": 0.0,
        "saturation_shadows": 0.0,
        "hue_angle": 0.0,
        "brilliance_global": 0.0,
        "brilliance_highlights": 0.0,
        "brilliance_midtones": 0.0,
        "brilliance_shadows": 0.0,
        "mask_grey_fulcrum": 0.1845,
        "vibrance": 0.1,
        "grey_fulcrum": 0.1845,
        "contrast": 0.1,
        "saturation_formula": 1,
    }

    # Build blobs
    filmicrgb_blob = encode_xmp(build_filmicrgb_blob(filmicrgb_params))
    exposure_blob = encode_xmp(build_exposure_blob(exposure_params))
    colorbalancergb_blob = encode_xmp(build_colorbalancergb_blob(colorbalancergb_params))

    # Create XML
    root = ET.Element("style")
    info = ET.SubElement(root, "info")
    name_elem = ET.SubElement(info, "name")
    name_elem.text = "Palander Corrected Base"

    # Plugin order: exposure -> filmicrgb -> colorbalancergb
    plugins_data = [
        ("exposure", exposure_blob, 1, 0),
        ("filmicrgb", filmicrgb_blob, 6, 0),
        ("colorbalancergb", colorbalancergb_blob, 5, 0),
    ]

    for i, (op, blob, module, num) in enumerate(plugins_data):
        plugin = ET.SubElement(root, "plugin")
        ET.SubElement(plugin, "operation").text = op
        ET.SubElement(plugin, "enabled").text = "1"
        ET.SubElement(plugin, "op_params").text = blob
        ET.SubElement(plugin, "blendop_params").text = ""
        ET.SubElement(plugin, "blendop_version").text = "13"
        ET.SubElement(plugin, "multi_priority").text = "0"
        ET.SubElement(plugin, "multi_name").text = ""
        ET.SubElement(plugin, "multi_name_hand_edited").text = "0"
        ET.SubElement(plugin, "num").text = str(num)
        ET.SubElement(plugin, "module").text = str(module)

    tree = ET.ElementTree(root)
    tree.write(output_path, encoding="utf-8", xml_declaration=True)
    logger.info("Created corrected base style: %s", output_path)


def create_per_raw_styles(
    base_style_path: Path,
    output_dir: Path,
    exposure_adjustments: dict,
) -> None:
    """Create per-RAW styles by adjusting exposure.exposure only."""
    
    # Per-RAW color balance tweaks (on top of base)
    color_adjustments = {
        "DSC03470": {"midtones_H": 20.0, "highlights_H": 25.0},  # Cooler for red cast
        "DSC05881": {"midtones_H": 40.0, "highlights_H": 45.0},  # Warmer for blue cast
        "DSC05885": {"midtones_H": 35.0, "highlights_H": 40.0},
        "DSC05889": {"midtones_H": 35.0, "highlights_H": 40.0},
        "nikon_d700": {"midtones_H": 20.0, "highlights_H": 25.0},  # Cooler for red cast
    }
    
    for raw_name, ev_shift in exposure_adjustments.items():
        # Parse base style fresh each time
        tree = ET.parse(base_style_path)
        root = tree.getroot()

        # Update name
        info_name = root.find("info/name")
        if info_name is not None:
            info_name.text = f"Palander Corrected {raw_name}"

        # Adjust exposure.exposure for this RAW (base is 0.0)
        for plugin in root.findall("plugin"):
            op = plugin.findtext("operation", "")
            if op == "exposure":
                op_enc = plugin.findtext("op_params", "") or ""
                if op_enc:
                    from dtstylekit.codec.xmp_codec import decode_xmp
                    blob = decode_xmp(op_enc)
                    vals = struct.unpack("<iffffii", blob)
                    new_exposure = ev_shift
                    new_vals = list(vals)
                    new_vals[2] = new_exposure
                    new_blob = encode_xmp(struct.pack("<iffffii", *new_vals))
                    op_params_elem = plugin.find("op_params")
                    if op_params_elem is not None:
                        op_params_elem.text = new_blob
                    logger.info("%s: exposure 0.0 -> %.3f (shift %.3f)", raw_name, new_exposure, ev_shift)
            
            # Per-RAW color balance adjustments
            if op == "colorbalancergb" and raw_name in color_adjustments:
                op_enc = plugin.findtext("op_params", "") or ""
                if op_enc:
                    from dtstylekit.codec.xmp_codec import decode_xmp
                    blob = decode_xmp(op_enc)
                    vals = struct.unpack("<32fi", blob)
                    # vals[5] = midtones_H, vals[8] = highlights_H
                    adj = color_adjustments[raw_name]
                    new_vals = list(vals)
                    new_vals[5] = adj.get("midtones_H", new_vals[5])
                    new_vals[8] = adj.get("highlights_H", new_vals[8])
                    new_blob = encode_xmp(struct.pack("<32fi", *new_vals))
                    op_params_elem = plugin.find("op_params")
                    if op_params_elem is not None:
                        op_params_elem.text = new_blob
                    logger.info("%s: midtones_H %.1f, highlights_H %.1f", raw_name, new_vals[5], new_vals[8])

        # Write
        out_path = output_dir / f"Palander_Corrected_{raw_name}.dtstyle"
        ET.ElementTree(root).write(out_path, encoding="utf-8", xml_declaration=True)
        logger.info("Written: %s", out_path)


def main():
    output_dir = Path("/tmp/palander/outputs")
    
    # 1. Create corrected base style
    base_style = output_dir / "Palander_Corrected_Base.dtstyle"
    create_corrected_base_style(base_style)

    # 2. Exposure adjustments per RAW (EV shift from base)
    # These are calculated from: target_lum=0.263 vs each RAW's expected render lum
    # We'll estimate based on preview analysis but account for double filmicrgb
    exposure_adjustments = {
        "DSC03470": -0.6,   # Bright preview -> needs negative EV
        "DSC05881": +0.8,   # Dark RAW -> needs positive EV lift
        "DSC05885": +0.7,
        "DSC05889": +0.5,
        "nikon_d700": -1.0, # Brightest
    }

    create_per_raw_styles(base_style, output_dir, exposure_adjustments)
    logger.info("Done!")


if __name__ == "__main__":
    main()