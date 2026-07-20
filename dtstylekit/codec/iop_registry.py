"""IOP Registry for Darktable styles.

Maps operation names to their parameter struct layouts, default values,
ranges, and verified sizes. Supports pack/unpack of binary blobs.
"""

from dataclasses import dataclass
from typing import ClassVar
import struct

from .xmp_codec import encode_xmp, decode_xmp


@dataclass(frozen=True)
class IOPRegistry:
    """Registry entry for a single IOP module."""
    operation: str
    version: int
    pack_format: str
    fields: tuple[str, ...]
    defaults: dict[str, float | int]
    ranges: dict[str, tuple[float | int, float | int]]
    size_bytes: int | None  # None = not verified against real .dtstyle
    blendop_cst: int  # 2 = scene (RGB_SCENE), 4 = display (RGB_DISPLAY)
    # Sentinel for curve-based IOPs (colorzones/rgbcurve/tonecurve):
    # when True, ``pack_params`` redirects to the curve-template system
    # rather than the standard struct.pack path.  ``curve_pack_size_override``
    # carries the exact byte count for the curve IOP when set.
    is_curve_iop: bool = False
    curve_pack_size_override: int | None = None


# Verified IOPs (from blob_size_calibration.md §1)
# Sizes verified by decoding existing .dtstyle blobs
_VERIFIED_IOPS = {
    "exposure": IOPRegistry(
        operation="exposure",
        version=6,
        # 1 int + 4 floats + 1 int = 6 items, 24 bytes
        pack_format="<iffffi",
        fields=(
            "mode", "black", "exposure", "deflicker_percentile",
            "deflicker_target_level", "compensate_exposure_bias"
        ),
        defaults={
            "mode": 0,  # MANUAL
            "black": 0.0,
            "exposure": 0.0,
            "deflicker_percentile": 50.0,
            "deflicker_target_level": -4.0,
            "compensate_exposure_bias": 0,  # gboolean
        },
        ranges={
            "mode": (0, 1),
            "black": (-1.0, 1.0),
            "exposure": (-18.0, 18.0),
            "deflicker_percentile": (0.0, 100.0),
            "deflicker_target_level": (-18.0, 18.0),
            "compensate_exposure_bias": (0, 1),
        },
        size_bytes=24,  # Verified from blob_size_calibration.md
        blendop_cst=4,  # RGB_DISPLAY (exposure is display-referred)
    ),
    "filmicrgb": IOPRegistry(
        operation="filmicrgb",
        version=6,
        # 18 floats + 11 ints = 29 items, 116 bytes
        pack_format="<18fiiIIiiiIIiI",
        fields=(
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
        ),
        defaults={
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
            "latitude": 0.01,
            "contrast": 1.0,
            "saturation": 0.0,
            "balance": 0.0,
            "noise_level": 0.2,
            "preserve_color": 3,  # POWER_NORM
            "version": 4,  # V5/2023
            "auto_hardness": 1,  # gboolean TRUE
            "custom_grey": 0,  # gboolean FALSE
            "high_quality_reconstruction": 1,
            "noise_distribution": 1,  # gaussian
            "shadows": 0,  # POLY_4/hard
            "highlights": 0,
            "compensate_icc_black": 0,
            "spline_version": 2,
            "enable_highlight_reconstruction": 0,
        },
        ranges={
            "grey_point_source": (0.0, 100.0),
            "black_point_source": (-16.0, -0.1),
            "white_point_source": (0.1, 16.0),
            "reconstruct_threshold": (-6.0, 6.0),
            "reconstruct_feather": (0.25, 6.0),
            "reconstruct_bloom_vs_details": (-100.0, 100.0),
            "reconstruct_grey_vs_color": (-100.0, 100.0),
            "reconstruct_structure_vs_texture": (-100.0, 100.0),
            "security_factor": (-50.0, 200.0),
            "grey_point_target": (1.0, 50.0),
            "black_point_target": (0.0, 20.0),
            "white_point_target": (0.0, 1600.0),
            "output_power": (1.0, 10.0),
            "latitude": (0.01, 99.0),
            "contrast": (0.0, 5.0),
            "saturation": (-200.0, 200.0),
            "balance": (-50.0, 50.0),
            "noise_level": (0.0, 6.0),
            "preserve_color": (0, 5),
            "version": (0, 4),
            "auto_hardness": (0, 1),
            "custom_grey": (0, 1),
            "high_quality_reconstruction": (0, 10),
            "noise_distribution": (0, 2),
            "shadows": (0, 2),
            "highlights": (0, 2),
            "compensate_icc_black": (0, 1),
            "spline_version": (0, 2),
            "enable_highlight_reconstruction": (0, 1),
        },
        size_bytes=116,  # Verified from blob_size_calibration.md
        blendop_cst=2,  # RGB_SCENE (filmicrgb is scene-referred)
    ),
    "colorbalancergb": IOPRegistry(
        operation="colorbalancergb",
        version=5,
        # 32 floats + 1 int = 33 items, 132 bytes (verified)
        pack_format="<32fi",
        fields=(
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
        ),
        defaults={
            "shadows_Y": 0.0, "shadows_C": 0.0, "shadows_H": 0.0,
            "midtones_Y": 0.0, "midtones_C": 0.0, "midtones_H": 0.0,
            "highlights_Y": 0.0, "highlights_C": 0.0, "highlights_H": 0.0,
            "global_Y": 0.0, "global_C": 0.0, "global_H": 0.0,
            "shadows_weight": 1.0, "white_fulcrum": 0.0, "highlights_weight": 1.0,
            "chroma_shadows": 0.0, "chroma_highlights": 0.0, "chroma_global": 0.0,
            "chroma_midtones": 0.0, "saturation_global": 0.0,
            "saturation_highlights": 0.0, "saturation_midtones": 0.0,
            "saturation_shadows": 0.0, "hue_angle": 0.0,
            "brilliance_global": 0.0, "brilliance_highlights": 0.0,
            "brilliance_midtones": 0.0, "brilliance_shadows": 0.0,
            "mask_grey_fulcrum": 0.1845, "vibrance": 0.0,
            "grey_fulcrum": 0.1845, "contrast": 0.0,
            "saturation_formula": 1,  # DTUCS
        },
        ranges={
            "shadows_Y": (-1.0, 1.0), "shadows_C": (0.0, 1.0), "shadows_H": (0.0, 360.0),
            "midtones_Y": (-1.0, 1.0), "midtones_C": (0.0, 1.0), "midtones_H": (0.0, 360.0),
            "highlights_Y": (-1.0, 1.0), "highlights_C": (0.0, 1.0), "highlights_H": (0.0, 360.0),
            "global_Y": (-1.0, 1.0), "global_C": (0.0, 1.0), "global_H": (0.0, 360.0),
            "shadows_weight": (0.0, 3.0), "white_fulcrum": (-16.0, 16.0), "highlights_weight": (0.0, 3.0),
            "chroma_shadows": (-1.0, 1.0), "chroma_highlights": (-1.0, 1.0), "chroma_global": (-1.0, 1.0),
            "chroma_midtones": (-1.0, 1.0), "saturation_global": (-1.0, 1.0),
            "saturation_highlights": (-1.0, 1.0), "saturation_midtones": (-1.0, 1.0),
            "saturation_shadows": (-1.0, 1.0), "hue_angle": (-180.0, 180.0),
            "brilliance_global": (-1.0, 1.0), "brilliance_highlights": (-1.0, 1.0),
            "brilliance_midtones": (-1.0, 1.0), "brilliance_shadows": (-1.0, 1.0),
            "mask_grey_fulcrum": (0.0, 1.0), "vibrance": (-1.0, 1.0),
            "grey_fulcrum": (0.0, 1.0), "contrast": (-1.0, 1.0),
            "saturation_formula": (0, 1),
        },
        size_bytes=132,  # Verified from blob_size_calibration.md
        blendop_cst=2,  # RGB_SCENE (colorbalancergb is scene-referred)
    ),
    "sigmoid": IOPRegistry(
        operation="sigmoid",
        version=3,
        # 12 floats + 2 ints = 14 items, 56 bytes
        # Field types in order: f,f,f,f,i,f,f,f,f,f,f,f,f,i
        pack_format="<ffffiffffffffi",
        fields=(
            "middle_grey_contrast", "contrast_skewness",
            "display_white_target", "display_black_target",
            "color_processing", "hue_preservation",
            "red_inset", "red_rotation",
            "green_inset", "green_rotation",
            "blue_inset", "blue_rotation",
            "purity", "base_primaries",
        ),
        defaults={
            "middle_grey_contrast": 1.5,
            "contrast_skewness": 0.0,
            "display_white_target": 100.0,
            "display_black_target": 0.0152,
            "color_processing": 0,  # PER_CHANNEL
            "hue_preservation": 100.0,
            "red_inset": 0.0, "red_rotation": 0.0,
            "green_inset": 0.0, "green_rotation": 0.0,
            "blue_inset": 0.0, "blue_rotation": 0.0,
            "purity": 0.0,
            "base_primaries": 0,  # WORK_PROFILE
        },
        ranges={
            "middle_grey_contrast": (0.1, 10.0),
            "contrast_skewness": (-1.0, 1.0),
            "display_white_target": (20.0, 1600.0),
            "display_black_target": (0.0, 15.0),
            "color_processing": (0, 1),
            "hue_preservation": (0.0, 100.0),
            "red_inset": (0.0, 0.99), "red_rotation": (-0.4, 0.4),
            "green_inset": (0.0, 0.99), "green_rotation": (-0.4, 0.4),
            "blue_inset": (0.0, 0.99), "blue_rotation": (-0.4, 0.4),
            "purity": (0.0, 1.0),
            "base_primaries": (0, 3),
        },
        size_bytes=56,  # Verified from blob_size_calibration.md
        blendop_cst=2,  # RGB_SCENE (sigmoid is scene-referred)
    ),
    "atrous": IOPRegistry(
        operation="atrous",
        version=2,
        # Verified size: 248 bytes = 62 items (from blob_size_calibration.md)
        # Use 1 int + 61 floats = 62 items = 248 bytes
        # This doesn't match the full 74-field catalog layout, but matches verified size
        pack_format="<i61f",
        fields=(
            "octaves",
            *(f"x_{c}_{b}" for c in range(6) for b in range(5)),  # 6x5 = 30
            *(f"y_{c}_{b}" for c in range(6) for b in range(5)),  # 6x5 = 30
            "mix",
        ),
        defaults={
            "octaves": 3,
            **{f"x_{c}_{b}": 0.0 for c in range(6) for b in range(5)},
            **{f"y_{c}_{b}": 0.0 for c in range(6) for b in range(5)},
            "mix": 1.0,
        },
        ranges={
            "octaves": (1, 6),
            **{f"x_{c}_{b}": (-2.0, 2.0) for c in range(6) for b in range(5)},
            **{f"y_{c}_{b}": (-2.0, 2.0) for c in range(6) for b in range(5)},
            "mix": (-2.0, 2.0),
        },
        size_bytes=248,  # Verified from blob_size_calibration.md
        blendop_cst=4,  # RGB_DISPLAY (atrous is display-referred)
    ),
    "bilat": IOPRegistry(
        operation="bilat",
        version=3,
        # Verified size: 20 bytes = 1 int (mode) + 4 floats (sigma_r, sigma_s, detail, midtone)
        # Defaults from C source: dt_iop_bilat_params_t {mode=1, sigma_r=0.5, sigma_s=0.5, detail=0.25, midtone=0.5}
        pack_format="<i4f",
        fields=("mode", "sigma_r", "sigma_s", "detail", "midtone"),
        defaults={"mode": 1, "sigma_r": 0.5, "sigma_s": 0.5, "detail": 0.25, "midtone": 0.5},
        ranges={
            "mode": (0, 1),                    # 0=bilateral, 1=local_laplacian
            "sigma_r": (0.0, 100.0),            # range radius
            "sigma_s": (0.0, 100.0),            # spatial radius
            "detail": (-1.0, 4.0),              # detail boost
            "midtone": (0.001, 1.0),            # midtone range
        },
        size_bytes=20,    # Verified from blob_size_calibration.md + checked against real .dtstyle
        blendop_cst=4,    # RGB_DISPLAY (bilat works in LAB, display-referred)
    ),
    "basecurve": IOPRegistry(
        operation="basecurve",
        version=6,
        # Verified size: 520 bytes from real .dtstyle files.
        # LAYOUT:
        #   basecurve[3][20] = 120 floats (x,y interleaved per channel) = 480 bytes
        #   basecurve_nodes[3]  = 3 ints  (12 bytes)
        #   basecurve_type[3]   = 3 ints  (12 bytes)
        #   exposure_fusion     = 1 int   (4 bytes)
        #   exposure_stops      = 1 float (4 bytes)
        #   exposure_bias       = 1 float (4 bytes)
        #   preserve_colors     = 1 int   (4 bytes)
        # Total: 480 + 40 = 520 bytes.
        #
        # basecurve is camera-specific — the curve data cannot be generated
        # from scratch.  It always comes from existing presets via
        # op_params_override.  pack_format uses the special sentinel
        # ``<basecurve>`` so ``pack_params`` raises a clear error.
        pack_format="<basecurve>",
        fields=(
            # Curve data is opaque; only scalar fields are exposed.
            # The VLM should NOT try to set basecurve params directly.
            "exposure_fusion",    # int 0=N
            "exposure_stops",     # float 0.01-4.0
            "exposure_bias",      # float -1.0-1.0
            "preserve_colors",    # enum 0-6
        ),
        defaults={
            "exposure_fusion": 0,
            "exposure_stops": 1.0,
            "exposure_bias": 1.0,
            "preserve_colors": 1,
        },
        ranges={
            "exposure_fusion": (0, 64),
            "exposure_stops": (0.01, 4.0),
            "exposure_bias": (-1.0, 1.0),
            "preserve_colors": (0, 6),
        },
        size_bytes=520,   # Verified from real .dtstyle files
        blendop_cst=2,     # RGB_SCENE (basecurve is scene-referred)
    ),
}

# Simple IOPs (Tier 1 from iop_modules_catalog.md)
# Sizes not verified (need real .dtstyle reference)
_SIMPLE_IOPS = {
    "vibrance": IOPRegistry(
        operation="vibrance",
        version=2,
        pack_format="<f",
        fields=("amount",),
        defaults={"amount": 25.0},
        ranges={"amount": (0.0, 100.0)},
        size_bytes=None,
        blendop_cst=4,
    ),
    "velvia": IOPRegistry(
        operation="velvia",
        version=2,
        pack_format="<ff",
        fields=("saturation", "strength"),
        defaults={"saturation": 100.0, "strength": 100.0},
        ranges={"saturation": (0.0, 200.0), "strength": (0.0, 100.0)},
        size_bytes=None,
        blendop_cst=4,
    ),
    "grain": IOPRegistry(
        operation="grain",
        version=2,
        pack_format="<ifff",
        fields=("channel", "scale", "strength", "midtones_bias"),
        defaults={"channel": 2, "scale": 1600.0, "strength": 25.0, "midtones_bias": 100.0},
        ranges={"channel": (0, 3), "scale": (20.0, 6400.0), "strength": (0.0, 100.0), "midtones_bias": (0.0, 100.0)},
        size_bytes=None,
        blendop_cst=4,
    ),
    "colorcontrast": IOPRegistry(
        operation="colorcontrast",
        version=2,
        pack_format="<ffffi",
        fields=("a_steepness", "a_offset", "b_steepness", "b_offset", "unbound"),
        defaults={"a_steepness": 1.0, "a_offset": 0.0, "b_steepness": 1.0, "b_offset": 0.0, "unbound": 1},
        ranges={"a_steepness": (0.0, 5.0), "a_offset": (-5.0, 5.0), "b_steepness": (0.0, 5.0), "b_offset": (-5.0, 5.0), "unbound": (0, 1)},
        size_bytes=None,
        blendop_cst=4,
    ),
    "splittoning": IOPRegistry(
        operation="splittoning",
        version=1,
        pack_format="<ffffff",
        fields=("shadow_hue", "shadow_saturation", "highlight_hue", "highlight_saturation", "balance", "compress"),
        defaults={"shadow_hue": 0.0, "shadow_saturation": 0.5, "highlight_hue": 0.2, "highlight_saturation": 0.5, "balance": 0.5, "compress": 33.0},
        ranges={"shadow_hue": (0.0, 1.0), "shadow_saturation": (0.0, 1.0), "highlight_hue": (0.0, 1.0), "highlight_saturation": (0.0, 1.0), "balance": (0.0, 1.0), "compress": (0.0, 100.0)},
        size_bytes=None,
        blendop_cst=4,
    ),
    "bloom": IOPRegistry(
        operation="bloom",
        version=1,
        pack_format="<fff",
        fields=("size", "threshold", "strength"),
        defaults={"size": 20.0, "threshold": 90.0, "strength": 25.0},
        ranges={"size": (0.0, 100.0), "threshold": (0.0, 100.0), "strength": (0.0, 100.0)},
        size_bytes=None,
        blendop_cst=4,
    ),
    "soften": IOPRegistry(
        operation="soften",
        version=1,
        pack_format="<ffff",
        fields=("size", "saturation", "brightness", "amount"),
        defaults={"size": 50.0, "saturation": 100.0, "brightness": 0.33, "amount": 50.0},
        ranges={"size": (0.0, 100.0), "saturation": (0.0, 100.0), "brightness": (-2.0, 2.0), "amount": (0.0, 100.0)},
        size_bytes=None,
        blendop_cst=4,
    ),
    "vignette": IOPRegistry(
        operation="vignette",
        version=4,
        # 6 floats + 1 uint32 + 2 floats + 2 ints = 11 items
        pack_format="<ffffffIffii",
        fields=("scale", "falloff_scale", "brightness", "saturation", "center_x", "center_y", "autoratio", "whratio", "shape", "dithering", "unbound"),
        defaults={"scale": 80.0, "falloff_scale": 50.0, "brightness": -0.5, "saturation": -0.5, "center_x": 0.0, "center_y": 0.0, "autoratio": 0, "whratio": 1.0, "shape": 1.0, "dithering": 0, "unbound": 1},
        ranges={"scale": (0.0, 200.0), "falloff_scale": (0.0, 200.0), "brightness": (-1.0, 1.0), "saturation": (-1.0, 1.0), "center_x": (-1.0, 1.0), "center_y": (-1.0, 1.0), "autoratio": (0, 1), "whratio": (0.0, 2.0), "shape": (0.0, 5.0), "dithering": (0, 2), "unbound": (0, 1)},
        size_bytes=None,
        blendop_cst=4,
    ),
    "colorbalance": IOPRegistry(
        operation="colorbalance",
        version=3,
        # 1 int + 13 floats = 14 items
        pack_format="<i13f",
        fields=("mode", "lift_r", "lift_g", "lift_b", "gamma_r", "gamma_g", "gamma_b", "gain_r", "gain_g", "gain_b", "saturation", "contrast", "grey", "saturation_out"),
        defaults={"mode": 0, "lift_r": 1.0, "lift_g": 1.0, "lift_b": 1.0, "gamma_r": 1.0, "gamma_g": 1.0, "gamma_b": 1.0, "gain_r": 1.0, "gain_g": 1.0, "gain_b": 1.0, "saturation": 1.0, "contrast": 1.0, "grey": 18.0, "saturation_out": 1.0},
        ranges={"mode": (0, 1), "lift_r": (0.0, 2.0), "lift_g": (0.0, 2.0), "lift_b": (0.0, 2.0), "gamma_r": (0.0, 2.0), "gamma_g": (0.0, 2.0), "gamma_b": (0.0, 2.0), "gain_r": (0.0, 2.0), "gain_g": (0.0, 2.0), "gain_b": (0.0, 2.0), "saturation": (0.0, 2.0), "contrast": (0.01, 1.99), "grey": (0.1, 100.0), "saturation_out": (0.0, 2.0)},
        size_bytes=None,
        blendop_cst=4,
    ),
    "shadhi": IOPRegistry(
        operation="shadhi",
        version=5,
        # 1 int + 8 floats + 1 uint32 + 1 float + 1 int = 12 items
        pack_format="<i8fIfi",
        fields=("order", "radius", "shadows", "whitepoint", "highlights", "reserved2", "compress", "shadows_ccorrect", "highlights_ccorrect", "flags", "low_approximation", "shadhi_algo"),
        defaults={"order": 0, "radius": 100.0, "shadows": 50.0, "whitepoint": 0.0, "highlights": -50.0, "reserved2": 0.0, "compress": 50.0, "shadows_ccorrect": 100.0, "highlights_ccorrect": 50.0, "flags": 1, "low_approximation": 0.000001, "shadhi_algo": 1},
        ranges={"order": (0, 1), "radius": (0.1, 500.0), "shadows": (-100.0, 100.0), "whitepoint": (-10.0, 10.0), "highlights": (-100.0, 100.0), "reserved2": (-100.0, 100.0), "compress": (0.0, 100.0), "shadows_ccorrect": (0.0, 100.0), "highlights_ccorrect": (0.0, 100.0), "flags": (0, 0xFFFFFFFF), "low_approximation": (0.0, 1.0), "shadhi_algo": (0, 1)},
        size_bytes=None,
        blendop_cst=4,
    ),
    "colorize": IOPRegistry(
        operation="colorize",
        version=2,
        pack_format="<ffffi",
        fields=("hue", "saturation", "source_lightness_mix", "lightness", "version"),
        defaults={"hue": 0.0, "saturation": 0.5, "source_lightness_mix": 50.0, "lightness": 50.0, "version": 0},
        ranges={"hue": (0.0, 1.0), "saturation": (0.0, 1.0), "source_lightness_mix": (0.0, 100.0), "lightness": (0.0, 100.0), "version": (0, 2)},
        size_bytes=None,
        blendop_cst=4,
    ),
    "monochrome": IOPRegistry(
        operation="monochrome",
        version=2,
        pack_format="<ffff",
        fields=("a", "b", "size", "highlights"),
        defaults={"a": 0.0, "b": 0.0, "size": 2.0, "highlights": 0.0},
        ranges={"a": (-2.0, 2.0), "b": (-2.0, 2.0), "size": (0.0, 10.0), "highlights": (0.0, 1.0)},
        size_bytes=None,
        blendop_cst=4,
    ),
    "colisa": IOPRegistry(
        operation="colisa",
        version=1,
        pack_format="<fff",
        fields=("contrast", "brightness", "saturation"),
        defaults={"contrast": 0.0, "brightness": 0.0, "saturation": 0.0},
        ranges={"contrast": (-1.0, 1.0), "brightness": (-1.0, 1.0), "saturation": (-1.0, 1.0)},
        size_bytes=None,
        blendop_cst=4,
    ),
    "lowpass": IOPRegistry(
        operation="lowpass",
        version=4,
        # 1 int + 4 floats + 2 ints = 7 items
        pack_format="<iffffii",
        fields=("order", "radius", "contrast", "brightness", "saturation", "lowpass_algo", "unbound"),
        defaults={"order": 0, "radius": 10.0, "contrast": 1.0, "brightness": 0.0, "saturation": 1.0, "lowpass_algo": 0, "unbound": 1},
        ranges={"order": (0, 1), "radius": (0.1, 500.0), "contrast": (-3.0, 3.0), "brightness": (-3.0, 3.0), "saturation": (-3.0, 3.0), "lowpass_algo": (0, 1), "unbound": (0, 1)},
        size_bytes=None,
        blendop_cst=4,
    ),
    "sharpen": IOPRegistry(
        operation="sharpen",
        version=1,
        pack_format="<fff",
        fields=("radius", "amount", "threshold"),
        defaults={"radius": 2.0, "amount": 0.5, "threshold": 0.5},
        ranges={"radius": (0.0, 99.0), "amount": (0.0, 2.0), "threshold": (0.0, 100.0)},
        size_bytes=None,
        blendop_cst=4,
    ),
    "highpass": IOPRegistry(
        operation="highpass",
        version=1,
        pack_format="<ff",
        fields=("sharpness", "contrast"),
        defaults={"sharpness": 50.0, "contrast": 50.0},
        ranges={"sharpness": (0.0, 100.0), "contrast": (0.0, 100.0)},
        size_bytes=None,
        blendop_cst=4,
    ),
    "levels": IOPRegistry(
        operation="levels",
        version=2,
        # 1 int + 6 floats = 7 items
        pack_format="<i6f",
        fields=("mode", "black", "gray", "white", "levels_r", "levels_g", "levels_b"),
        defaults={"mode": 0, "black": 0.0, "gray": 50.0, "white": 100.0, "levels_r": 0.0, "levels_g": 0.0, "levels_b": 0.0},
        ranges={"mode": (0, 1), "black": (0.0, 100.0), "gray": (0.0, 100.0), "white": (0.0, 100.0), "levels_r": (-100.0, 100.0), "levels_g": (-100.0, 100.0), "levels_b": (-100.0, 100.0)},
        size_bytes=None,
        blendop_cst=4,
    ),
}


# ---------------------------------------------------------------------------
# Curve-based IOPs.
# These IOPs store 3 × 20-node splines in addition to (small) scalar
# fields.  Because the binary layout is multiple hundred floats long and
# *cannot* be hand-built by an LLM, we register them with a virtual
# ``curve_preset`` field and redirect packing to the dedicated
# :mod:`dtstylekit.curves` subsystem.  ``pack_format`` is the size in
# bytes (which is the same value checked by :func:`curve_iop_size`).
# ---------------------------------------------------------------------------
_CURVE_IOPS = {
    "colorzones": IOPRegistry(
        operation="colorzones",
        version=5,
        pack_format="<curve>",  # placeholder — never actually struct-packed
        fields=(
            # Curve data is fully managed by ``curve_preset``; scalars
            # below are forwarded as kwargs to the curves.pack helpers.
            "channel",
            "strength",
            "mode",
            "splines_version",
            # Synthetic marker — not a real field on the struct but
            # recognised by ``pack_params`` and routed to the curve
            # templates subsystem before struct.pack ever sees it.
            "curve_preset",
        ),
        defaults={
            "channel": 0,
            "strength": 0.0,
            "mode": 0,  # ZONES_SMOOTH
            "splines_version": 1,
            "curve_preset": "identity",
        },
        ranges={
            "channel": (0, 2),
            "strength": (-200.0, 200.0),
            "mode": (0, 1),
            "splines_version": (0, 10),
            # ``curve_preset`` accepts *string* keys — range is informal,
            # the validator cross-checks against the curves registry.
            "curve_preset": ("identity", "inverted_s_strong"),
        },
        size_bytes=520,
        blendop_cst=4,
        is_curve_iop=True,
        curve_pack_size_override=520,
    ),
    "rgbcurve": IOPRegistry(
        operation="rgbcurve",
        version=1,
        pack_format="<curve>",
        fields=(
            "curve_autoscale",
            "compensate_middle_grey",
            "preserve_colors",
            "curve_preset",
        ),
        defaults={
            "curve_autoscale": 1,
            "compensate_middle_grey": 0,
            "preserve_colors": 0,
            "curve_preset": "identity",
        },
        ranges={
            "curve_autoscale": (0, 1),
            "compensate_middle_grey": (0, 1),
            "preserve_colors": (0, 2),
            "curve_preset": ("identity", "inverted_s_strong"),
        },
        size_bytes=516,
        blendop_cst=4,
        is_curve_iop=True,
        curve_pack_size_override=516,
    ),
    "tonecurve": IOPRegistry(
        operation="tonecurve",
        version=5,
        pack_format="<curve>",
        fields=(
            "tonecurve_autoscale_ab",
            "tonecurve_preset",
            "tonecurve_unbound_ab",
            "preserve_colors",
            "curve_preset",
        ),
        defaults={
            "tonecurve_autoscale_ab": 1,
            "tonecurve_preset": 0,
            "tonecurve_unbound_ab": 1,
            "preserve_colors": 0,
            "curve_preset": "identity",
        },
        ranges={
            "tonecurve_autoscale_ab": (0, 1),
            "tonecurve_preset": (0, 10),
            "tonecurve_unbound_ab": (0, 1),
            "preserve_colors": (0, 2),
            "curve_preset": ("identity", "inverted_s_strong"),
        },
        size_bytes=520,
        blendop_cst=4,
        is_curve_iop=True,
        curve_pack_size_override=520,
    ),
}


# Combined registry
IOP_REGISTRY: dict[str, IOPRegistry] = {}
IOP_REGISTRY.update(_VERIFIED_IOPS)
IOP_REGISTRY.update(_SIMPLE_IOPS)
IOP_REGISTRY.update(_CURVE_IOPS)


def get_registry(op: str) -> IOPRegistry | None:
    """Get registry entry for an operation name."""
    return IOP_REGISTRY.get(op)


def pack_params(op: str, params: dict) -> bytes:
    """Pack parameters into binary blob for an IOP.

    Merges with defaults, validates ranges, then struct.pack.

    For curve-based IOPs (``colorzones``, ``rgbcurve``, ``tonecurve``)
    this function recognises a virtual ``curve_preset`` field.  When
    present it overrides the binary spline data via the
    :mod:`dtstylekit.curves` subsystem; remaining scalars are still
    validated against the registry ranges and merged with defaults.

    Args:
        op: Operation name (e.g., "filmicrgb")
        params: Dictionary of parameter values.  May include the virtual
            ``curve_preset`` key for curve IOPs.

    Returns:
        Packed binary blob ready for encode_xmp()

    Raises:
        ValueError: If operation not in registry or parameter out of range
    """
    reg = get_registry(op)
    if reg is None:
        raise ValueError(f"Unknown operation: {op}")

    # Curve-based IOPs: delegate to the curve-template system.
    if reg.is_curve_iop:
        return _pack_curve_iop(reg, params)

    # basecurve: cannot be packed from scratch (camera-specific curve data).
    if reg.pack_format == "<basecurve>":
        raise ValueError(
            f"basecurve cannot be packed from scratch — it always comes "
            f"from existing presets via op_params_override. "
            f"To include basecurve, reference a preset blob."
        )

    # Merge defaults with provided params
    merged = {**reg.defaults, **params}

    # Validate ranges
    for field, (min_val, max_val) in reg.ranges.items():
        val = merged.get(field)
        if val is not None:
            if not (min_val <= val <= max_val):
                raise ValueError(f"{op}.{field}={val} out of range [{min_val}, {max_val}]")

    # Build values in field order
    values = [merged[field] for field in reg.fields]

    # Pack
    return struct.pack(reg.pack_format, *values)


def _pack_curve_iop(reg: "IOPRegistry", params: dict) -> bytes:
    """Pack a curve-based IOP via the curves templates subsystem.

    Args:
        reg: The IOP's registry entry.
        params: May include ``curve_preset`` plus scalar overrides
            (e.g. ``strength`` for colorzones, ``preserve_colors``
            for tonecurve, etc.).

    Returns:
        Packed bytes, exactly ``curve_pack_size_override`` (or the IOP
        size from ``dtstylekit.curves``).
    """
    # Lazy import to avoid a hard dependency cycle
    from dtstylekit.curves import apply_curve_template, curve_iop_size, REGISTRY as CURVE_REG

    if "curve_preset" not in params:
        raise ValueError(
            f"{reg.operation} is a curve-based IOP and requires a "
            f"'curve_preset' parameter in {sorted(t.name for t in CURVE_REG)}"
        )
    template = params.pop("curve_preset")
    if not isinstance(template, str):
        raise ValueError(f"curve_preset must be a string, got {type(template).__name__}")

    # Forward remaining scalars (e.g. colorzones.strength) as overrides
    kwargs = {k: v for k, v in params.items() if k in _CURVE_FORWARD_PARAMS.get(reg.operation, set())}
    blob = apply_curve_template(reg.operation, template, **kwargs)
    expected = reg.curve_pack_size_override or curve_iop_size(reg.operation)
    assert len(blob) == expected, (
        f"{reg.operation} curve_preset pack produced {len(blob)} bytes, "
        f"expected {expected}"
    )
    return blob


# Scalar parameters that are forwarded from ``curve_preset`` kwargs in
# addition to the curve nodes themselves.
_CURVE_FORWARD_PARAMS: dict[str, set[str]] = {
    "colorzones": {"strength", "mode", "channel"},
    "rgbcurve": {"curve_autoscale", "compensate_middle_grey", "preserve_colors"},
    "tonecurve": {"tonecurve_autoscale_ab", "tonecurve_preset", "tonecurve_unbound_ab", "preserve_colors"},
}


def unpack_params(op: str, blob: bytes) -> dict:
    """Unpack binary blob into parameter dictionary.

    Args:
        op: Operation name
        blob: Binary blob from decode_xmp()

    Returns:
        Dictionary mapping field names to values

    Raises:
        ValueError: If operation not in registry or blob size mismatch
    """
    reg = get_registry(op)
    if reg is None:
        raise ValueError(f"Unknown operation: {op}")

    # Curve IOPs: route to dedicated unpacker
    if reg.is_curve_iop:
        return _unpack_curve_iop(reg, blob)

    # basecurve: extract only the scalar portion at offset 480.
    if reg.pack_format == "<basecurve>":
        if len(blob) != 520:
            raise ValueError(f"basecurve blob must be 520 bytes, got {len(blob)}")
        # Layout at offset 480: 3i (nodes) + 3i (type) + i (fusion) + f (stops) + f (bias) + i (preserve)
        # Veryfied: <3i3iiffi = 40 bytes, yields (6,0,0, 2,0,0, 0, 1.0, 1.0, 1)
        nodes0, nodes1, nodes2, type0, type1, type2, fusion, stops, bias, preserve = \
            struct.unpack("<3i3iiffi", blob[480:480 + struct.calcsize("<3i3iiffi")])
        return {
            "basecurve_nodes_0": nodes0,
            "basecurve_nodes_1": nodes1,
            "basecurve_nodes_2": nodes2,
            "basecurve_type_0": type0,
            "basecurve_type_1": type1,
            "basecurve_type_2": type2,
            "exposure_fusion": fusion,
            "exposure_stops": stops,
            "exposure_bias": bias,
            "preserve_colors": preserve,
        }

    if reg.size_bytes is not None and len(blob) != reg.size_bytes:
        raise ValueError(f"Blob size mismatch for {op}: expected {reg.size_bytes}, got {len(blob)}")

    values = struct.unpack(reg.pack_format, blob)
    return dict(zip(reg.fields, values))


def _unpack_curve_iop(reg: "IOPRegistry", blob: bytes) -> dict:
    """Unpack a curve-based IOP blob back to a dict.

    The curve I/O modules in :mod:`dtstylekit.curves` do the heavy
    lifting.  We return a *partial* dict: scalars are reconstructed
    from defaults, but the spline data is reported under the synthetic
    ``curve_preset`` key as ``"(binary: <size> bytes)"`` because we don't
    know which template was used to produce the blob.
    """
    from dtstylekit.curves import (
        unpack_colorzones, unpack_rgbcurve, unpack_tonecurve,
    )
    if reg.operation == "colorzones":
        params = unpack_colorzones(blob)
        return {
            "channel": params.channel,
            "strength": params.strength,
            "mode": params.mode,
            "splines_version": params.splines_version,
            "curve_preset": "(binary: 520 bytes)",
        }
    if reg.operation == "rgbcurve":
        params = unpack_rgbcurve(blob)
        return {
            "curve_autoscale": params.curve_autoscale,
            "compensate_middle_grey": params.compensate_middle_grey,
            "preserve_colors": params.preserve_colors,
            "curve_preset": "(binary: 516 bytes)",
        }
    if reg.operation == "tonecurve":
        params = unpack_tonecurve(blob)
        return {
            "tonecurve_autoscale_ab": params.tonecurve_autoscale_ab,
            "tonecurve_preset": params.tonecurve_preset,
            "tonecurve_unbound_ab": params.tonecurve_unbound_ab,
            "preserve_colors": params.preserve_colors,
            "curve_preset": "(binary: 520 bytes)",
        }
    raise ValueError(f"_unpack_curve_iop: unknown operation {reg.operation}")


def verify_size(op: str, blob: bytes) -> bool:
    """Verify blob size matches expected size for operation.

    Args:
        op: Operation name
        blob: Binary blob

    Returns:
        True if size matches (or size not verified), False otherwise
    """
    reg = get_registry(op)
    if reg is None:
        return False
    if reg.size_bytes is None:
        return True  # Can't verify, assume OK
    return len(blob) == reg.size_bytes


def list_registered() -> list[str]:
    """Return sorted list of all registered operation names."""
    return sorted(IOP_REGISTRY.keys())


def list_verified() -> list[str]:
    """Return sorted list of operations with verified blob sizes."""
    return sorted(op for op, reg in IOP_REGISTRY.items() if reg.size_bytes is not None)


def list_unverified() -> list[str]:
    """Return sorted list of operations without verified blob sizes."""
    return sorted(op for op, reg in IOP_REGISTRY.items() if reg.size_bytes is None)


__all__ = [
    "IOPRegistry",
    "IOP_REGISTRY",
    "get_registry",
    "pack_params",
    "unpack_params",
    "verify_size",
    "list_registered",
    "list_verified",
    "list_unverified",
]