"""Verified IOP definitions."""

from dtstylekit.codec.registry_types import IOPRegistry

# Verified IOPs (from blob_size_calibration.md §1)
# Sizes verified by decoding existing .dtstyle blobs
_VERIFIED_IOPS = {
    "exposure": IOPRegistry(
        operation="exposure",
        version=7,
        # 1 int + 4 floats + 2 ints = 7 items, 28 bytes
        pack_format="<iffffii",
        fields=(
            "mode",
            "black",
            "exposure",
            "deflicker_percentile",
            "deflicker_target_level",
            "compensate_exposure_bias",
            "compensate_hilite_pres",
        ),
        defaults={
            "mode": 0,  # MANUAL
            "black": 0.0,
            "exposure": 0.0,
            "deflicker_percentile": 50.0,
            "deflicker_target_level": -4.0,
            "compensate_exposure_bias": 0,  # gboolean
            "compensate_hilite_pres": 1,  # gboolean TRUE (v7)
        },
        ranges={
            "mode": (0, 1),
            "black": (-1.0, 1.0),
            "exposure": (-18.0, 18.0),
            "deflicker_percentile": (0.0, 100.0),
            "deflicker_target_level": (-18.0, 18.0),
            "compensate_exposure_bias": (0, 1),
            "compensate_hilite_pres": (0, 1),
        },
        size_bytes=28,  # 7 fields × 4 bytes (v7)
        legacy_size_bytes=(24,),  # v6 blobs shipped in official styles
        legacy_pack_format="<iffffi",  # v6: no compensate_hilite_pres
        legacy_fields=(
            "mode",
            "black",
            "exposure",
            "deflicker_percentile",
            "deflicker_target_level",
            "compensate_exposure_bias",
        ),
        blendop_cst=3,  # RGB_DISPLAY (default for exposure per src/iop/exposure.c:324)
    ),
    "filmicrgb": IOPRegistry(
        operation="filmicrgb",
        version=6,
        # 18 floats + 11 ints = 29 items, 116 bytes
        pack_format="<18fiiIIiiiIIiI",
        fields=(
            "grey_point_source",
            "black_point_source",
            "white_point_source",
            "reconstruct_threshold",
            "reconstruct_feather",
            "reconstruct_bloom_vs_details",
            "reconstruct_grey_vs_color",
            "reconstruct_structure_vs_texture",
            "security_factor",
            "grey_point_target",
            "black_point_target",
            "white_point_target",
            "output_power",
            "latitude",
            "contrast",
            "saturation",
            "balance",
            "noise_level",
            "preserve_color",
            "version",
            "auto_hardness",
            "custom_grey",
            "high_quality_reconstruction",
            "noise_distribution",
            "shadows",
            "highlights",
            "compensate_icc_black",
            "spline_version",
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
        blendop_cst=4,  # RGB_SCENE (filmicrgb is scene-referred)
    ),
    "colorbalancergb": IOPRegistry(
        operation="colorbalancergb",
        version=5,
        # 32 floats + 1 int = 33 items, 132 bytes (verified)
        pack_format="<32fi",
        fields=(
            "shadows_Y",
            "shadows_C",
            "shadows_H",
            "midtones_Y",
            "midtones_C",
            "midtones_H",
            "highlights_Y",
            "highlights_C",
            "highlights_H",
            "global_Y",
            "global_C",
            "global_H",
            "shadows_weight",
            "white_fulcrum",
            "highlights_weight",
            "chroma_shadows",
            "chroma_highlights",
            "chroma_global",
            "chroma_midtones",
            "saturation_global",
            "saturation_highlights",
            "saturation_midtones",
            "saturation_shadows",
            "hue_angle",
            "brilliance_global",
            "brilliance_highlights",
            "brilliance_midtones",
            "brilliance_shadows",
            "mask_grey_fulcrum",
            "vibrance",
            "grey_fulcrum",
            "contrast",
            "saturation_formula",
        ),
        defaults={
            "shadows_Y": 0.0,
            "shadows_C": 0.0,
            "shadows_H": 0.0,
            "midtones_Y": 0.0,
            "midtones_C": 0.0,
            "midtones_H": 0.0,
            "highlights_Y": 0.0,
            "highlights_C": 0.0,
            "highlights_H": 0.0,
            "global_Y": 0.0,
            "global_C": 0.0,
            "global_H": 0.0,
            "shadows_weight": 1.0,
            "white_fulcrum": 0.0,
            "highlights_weight": 1.0,
            "chroma_shadows": 0.0,
            "chroma_highlights": 0.0,
            "chroma_global": 0.0,
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
            "vibrance": 0.0,
            "grey_fulcrum": 0.1845,
            "contrast": 0.0,
            "saturation_formula": 1,  # DTUCS
        },
        ranges={
            "shadows_Y": (-1.0, 1.0),
            "shadows_C": (0.0, 1.0),
            "shadows_H": (0.0, 360.0),
            "midtones_Y": (-1.0, 1.0),
            "midtones_C": (0.0, 1.0),
            "midtones_H": (0.0, 360.0),
            "highlights_Y": (-1.0, 1.0),
            "highlights_C": (0.0, 1.0),
            "highlights_H": (0.0, 360.0),
            "global_Y": (-1.0, 1.0),
            "global_C": (0.0, 1.0),
            "global_H": (0.0, 360.0),
            "shadows_weight": (0.0, 3.0),
            "white_fulcrum": (-16.0, 16.0),
            "highlights_weight": (0.0, 3.0),
            "chroma_shadows": (-1.0, 1.0),
            "chroma_highlights": (-1.0, 1.0),
            "chroma_global": (-1.0, 1.0),
            "chroma_midtones": (-1.0, 1.0),
            "saturation_global": (-1.0, 1.0),
            "saturation_highlights": (-1.0, 1.0),
            "saturation_midtones": (-1.0, 1.0),
            "saturation_shadows": (-1.0, 1.0),
            "hue_angle": (-180.0, 180.0),
            "brilliance_global": (-1.0, 1.0),
            "brilliance_highlights": (-1.0, 1.0),
            "brilliance_midtones": (-1.0, 1.0),
            "brilliance_shadows": (-1.0, 1.0),
            "mask_grey_fulcrum": (0.0, 1.0),
            "vibrance": (-1.0, 1.0),
            "grey_fulcrum": (0.0, 1.0),
            "contrast": (-1.0, 1.0),
            "saturation_formula": (0, 1),
        },
        size_bytes=132,  # Verified from blob_size_calibration.md
        blendop_cst=4,  # RGB_SCENE (colorbalancergb is scene-referred)
    ),
    "sigmoid": IOPRegistry(
        operation="sigmoid",
        version=3,
        # 12 floats + 2 ints = 14 items, 56 bytes
        # Field types in order: f,f,f,f,i,f,f,f,f,f,f,f,f,i
        pack_format="<ffffiffffffffi",
        fields=(
            "middle_grey_contrast",
            "contrast_skewness",
            "display_white_target",
            "display_black_target",
            "color_processing",
            "hue_preservation",
            "red_inset",
            "red_rotation",
            "green_inset",
            "green_rotation",
            "blue_inset",
            "blue_rotation",
            "purity",
            "base_primaries",
        ),
        defaults={
            "middle_grey_contrast": 1.5,
            "contrast_skewness": 0.0,
            "display_white_target": 100.0,
            "display_black_target": 0.0152,
            "color_processing": 0,  # PER_CHANNEL
            "hue_preservation": 100.0,
            "red_inset": 0.0,
            "red_rotation": 0.0,
            "green_inset": 0.0,
            "green_rotation": 0.0,
            "blue_inset": 0.0,
            "blue_rotation": 0.0,
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
            "red_inset": (0.0, 0.99),
            "red_rotation": (-0.4, 0.4),
            "green_inset": (0.0, 0.99),
            "green_rotation": (-0.4, 0.4),
            "blue_inset": (0.0, 0.99),
            "blue_rotation": (-0.4, 0.4),
            "purity": (0.0, 1.0),
            "base_primaries": (0, 3),
        },
        size_bytes=56,  # Verified from blob_size_calibration.md
        blendop_cst=4,  # RGB_SCENE (sigmoid is scene-referred)
    ),
    "atrous": IOPRegistry(
        operation="atrous",
        version=2,
        # Verified size: 248 bytes = 62 items (from blob_size_calibration.md)
        # Use 1 int + 61 floats = 62 items = 248 bytes
        # This doesn't match the full 74-field catalog layout, but matches verified size
        #
        # Real layout (atrous.c:64-80): x[5][6], y[5][6] (5 channels × 6
        # bands) + octaves + mix.  init() (atrous.c:608-620) sets
        # x[c][k] = k/(BANDS-1) = k/5 → 0.0, 0.2, 0.4, 0.6, 0.8, 1.0 and
        # y = 0 — matching the ramp below.  A flat x=0 would make
        # ``mix < 1`` darken the image (output ≈ px × mix).
        pack_format="<i61f",
        fields=(
            "octaves",
            *(f"x_{c}_{b}" for c in range(5) for b in range(6)),  # 5x6 = 30
            *(f"y_{c}_{b}" for c in range(5) for b in range(6)),  # 5x6 = 30
            "mix",
        ),
        defaults={
            "octaves": 3,
            **{f"x_{c}_{b}": b / 5.0 for c in range(5) for b in range(6)},
            **{f"y_{c}_{b}": 0.0 for c in range(5) for b in range(6)},
            "mix": 1.0,
        },
        ranges={
            "octaves": (1, 6),
            **{f"x_{c}_{b}": (-2.0, 2.0) for c in range(5) for b in range(6)},
            **{f"y_{c}_{b}": (-2.0, 2.0) for c in range(5) for b in range(6)},
            "mix": (-2.0, 2.0),
        },
        size_bytes=248,  # Verified from blob_size_calibration.md
        blendop_cst=2,  # LAB (atrous works in Lab)
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
            "mode": (0, 1),  # 0=bilateral, 1=local_laplacian
            "sigma_r": (0.0, 100.0),  # range radius
            "sigma_s": (0.0, 100.0),  # spatial radius
            "detail": (-1.0, 4.0),  # detail boost
            "midtone": (0.001, 1.0),  # midtone range
        },
        size_bytes=20,  # Verified from blob_size_calibration.md + checked against real .dtstyle
        blendop_cst=2,  # LAB (bilat works in Lab)
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
            "exposure_fusion",  # int 0=N
            "exposure_stops",  # float 0.01-4.0
            "exposure_bias",  # float -1.0-1.0
            "preserve_colors",  # enum 0-6
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
        size_bytes=520,  # Verified from real .dtstyle files
        blendop_cst=3,  # RGB_DISPLAY (default for exposure per src/iop/exposure.c:324) (basecurve is scene-referred)
    ),
    "lowlight": IOPRegistry(
        operation="lowlight",
        version=1,  # DT_MODULE_INTROSPECTION(1), lowlight.c
        # Verified size: 52 bytes = blueness + transition_x[6] + transition_y[6]
        # (13 floats). Confirmed against the real .dtstyle blobs in data/presets/
        # ("examples_effects_day for night" and "...for twilight"), both exactly 52 B.
        #
        # Layout (lowlight.c:45-50): float blueness, transition_x[6], transition_y[6].
        # init() sets x[k] = k/5; $DEFAULT y = 0.5 for every node. commit_params()
        # builds a dt_draw_curve_new(0.0f, 1.0f) spline over the (x,y) points into
        # the LUT, and process() uses lut(L/100) as blend weight w between the
        # original pixel and a blue-shifted scotopic version — hence y in [0,1].
        pack_format="<13f",
        fields=(
            "blueness",
            *(f"transition_x_{i}" for i in range(6)),
            *(f"transition_y_{i}" for i in range(6)),
        ),
        defaults={
            "blueness": 0.0,  # $DEFAULT: no blue shift
            **{f"transition_x_{i}": i / 5.0 for i in range(6)},
            **{f"transition_y_{i}": 0.5 for i in range(6)},
        },
        ranges={
            "blueness": (0.0, 100.0),  # $MIN/$MAX annotations, lowlight.c:47
            **{f"transition_x_{i}": (0.0, 1.0) for i in range(6)},  # curve x-domain [0,1]
            **{f"transition_y_{i}": (0.0, 1.0) for i in range(6)},  # blend weight w (process())
        },
        size_bytes=52,  # Verified against real .dtstyle blobs (examples_effects_day*)
        blendop_cst=2,  # LAB — default_colorspace() returns IOP_CS_LAB
    ),
    "hazeremoval": IOPRegistry(
        operation="hazeremoval",
        version=3,  # DT_MODULE_INTROSPECTION(3), hazeremoval.c
        # v3 layout (hazeremoval.c:~50): float strength ($MIN:-1.0 $MAX:1.0
        # $DEFAULT:0.2), float distance ($MIN:0.0 $MAX:1.0 $DEFAULT:0.2),
        # gboolean compatibility_mode ($DEFAULT:FALSE), gboolean adaptive
        # ($DEFAULT:TRUE) → "<ffii" = 16 B.
        #
        # Real styles ship v2 blobs (module=2): "<ffi" = 12 B — e.g.
        # "examples_contrast and sharpness_dehaze (strong, luminance only)"
        # decodes to strength=0.5, distance=0.8, compatibility_mode=0 with
        # blendop cst=4 (RGB_SCENE).  legacy_params() maps v1 ("<ff", 8 B)
        # → v3 (compatibility_mode=TRUE, adaptive=FALSE) and v2 → v3
        # (adaptive=FALSE).
        pack_format="<ffii",
        fields=("strength", "distance", "compatibility_mode", "adaptive"),
        defaults={
            "strength": 0.2,
            "distance": 0.2,
            "compatibility_mode": 0,  # gboolean FALSE
            "adaptive": 1,  # gboolean TRUE
        },
        ranges={
            "strength": (-1.0, 1.0),
            "distance": (0.0, 1.0),
            "compatibility_mode": (0, 1),
            "adaptive": (0, 1),
        },
        size_bytes=16,  # v3 per struct.calcsize("<ffii"); real styles carry v2 (12 B)
        blendop_cst=4,  # RGB_SCENE — real style blendop cst=4; default_colorspace() = IOP_CS_RGB
        legacy_size_bytes=(12, 8),  # v2 and v1 blobs shipped in official styles
        legacy_pack_format="<ffi",  # v2: strength, distance, compatibility_mode
        legacy_fields=("strength", "distance", "compatibility_mode"),
    ),
    "highlights": IOPRegistry(
        operation="highlights",
        version=4,  # DT_MODULE_INTROSPECTION(4), highlights.c
        # v4 layout (highlights.c:~40): mode(int enum), blendL, blendC
        # (unused), strength, clip [v2], noise_level, iterations(int),
        # scales(int enum), candidating, combine, recovery(int enum)
        # [v3], solid_color [v4] → "<iffffifiiffif" = 12 × 4B = 48 B.
        #
        # VERIFIED against the real blob in "darktable_Fujifilm_X-E1"
        # (module=4, 48 B): decodes to exactly the documented defaults —
        # mode=5 (OPPOSED), blendL=1.0, blendC=0.0, strength=0.0, clip=1.0,
        # noise_level=0.0, iterations=30, scales=6 (WAVELETS_7_SCALE),
        # candidating=0.4, combine=2.0, recovery=0 (OFF), solid_color=0.0.
        # Its blendop cst=1 → DEVELOP_BLEND_CS_RAW (module works on raw
        # data at the start of the pipeline; default_colorspace() is
        # RAW-or-RGB dynamic).
        #
        # Enum values (highlights.c:57-88): mode CLIP=0, LCH=1, INPAINT=2,
        # LAPLACIAN=3, SEGMENTS=4, OPPOSED=5. scales WAVELETS_1..7 = 0..6.
        # recovery OFF=0, ADAPT=5, ADAPTF=6.
        pack_format="<i5f2i2fif",
        fields=(
            "mode",
            "blendL",
            "blendC",
            "strength",
            "clip",
            "noise_level",
            "iterations",
            "scales",
            "candidating",
            "combine",
            "recovery",
            "solid_color",
        ),
        defaults={
            "mode": 5,  # DT_IOP_HIGHLIGHTS_OPPOSED
            "blendL": 1.0,  # unused
            "blendC": 0.0,  # unused
            "strength": 0.0,
            "clip": 1.0,
            "noise_level": 0.0,
            "iterations": 30,
            "scales": 6,  # WAVELETS_7_SCALE
            "candidating": 0.4,
            "combine": 2.0,
            "recovery": 0,  # DT_RECOVERY_MODE_OFF
            "solid_color": 0.0,
        },
        ranges={
            "mode": (0, 5),
            "blendL": (0.0, 1.0),
            "blendC": (0.0, 1.0),
            "strength": (0.0, 1.0),
            "clip": (0.0, 2.0),
            "noise_level": (0.0, 0.5),
            "iterations": (1, 256),
            "scales": (0, 6),
            "candidating": (0.0, 1.0),
            "combine": (0.0, 8.0),
            "recovery": (0, 6),
            "solid_color": (0.0, 1.0),
        },
        size_bytes=48,  # Verified against real .dtstyle blob (darktable_Fujifilm_X-E1)
        blendop_cst=1,  # DEVELOP_BLEND_CS_RAW — per the real style blob
    ),
    "rgblevels": IOPRegistry(
        operation="rgblevels",
        version=1,  # DT_MODULE_INTROSPECTION(1), rgblevels.c
        # Layout (rgblevels.c:52-57): autoscale(int enum), preserve_colors
        # (int enum DT_RGB_NORM_*), levels[3][3] floats = per-channel
        # {black, middle, white} for R, G, B → "<2i9f" = 11 × 4B = 44 B.
        # Defaults (rgblevels.c:923-930): levels[c] = {0.0, 0.5, 1.0}
        # (RGBLEVELS_MIN/MID/MAX).  No real preset carries rgblevels —
        # visual loop is the only blob validation.
        pack_format="<2i9f",
        fields=(
            "autoscale",
            "preserve_colors",
            "levels_r_0",
            "levels_r_1",
            "levels_r_2",
            "levels_g_0",
            "levels_g_1",
            "levels_g_2",
            "levels_b_0",
            "levels_b_1",
            "levels_b_2",
        ),
        defaults={
            "autoscale": 0,  # DT_IOP_RGBLEVELS_LINKED_CHANNELS
            "preserve_colors": 1,  # DT_RGB_NORM_LUMINANCE (rgb_norms.h:25)
            **{
                f"levels_{c}_{i}": v
                for c in ("r", "g", "b")
                for i, v in zip((0, 1, 2), (0.0, 0.5, 1.0), strict=False)
            },
        },
        ranges={
            "autoscale": (0, 1),
            "preserve_colors": (0, 6),
            **{f"levels_{c}_{i}": (0.0, 1.0) for c in ("r", "g", "b") for i in (0, 1, 2)},
        },
        size_bytes=44,  # struct.calcsize("<2i9f"); absent from the 534-preset library
        blendop_cst=3,  # RGB_DISPLAY — default_colorspace() returns IOP_CS_RGB
    ),
    "graduatednd": IOPRegistry(
        operation="graduatednd",
        version=1,  # DT_MODULE_INTROSPECTION(1), graduatednd.c
        # Layout (graduatednd.c:~40): 6 floats → "<6f" = 24 B.
        # density (-8..8 EV, def 1.0), hardness (0..100 %, def 0.0),
        # rotation (-180..180 deg, def 0.0), offset (def 50.0, centered),
        # hue (0..1, def 0.0), saturation (0..1, def 0.0).
        # Absent from the 534-preset library — visual loop validates.
        pack_format="<6f",
        fields=("density", "hardness", "rotation", "offset", "hue", "saturation"),
        defaults={
            "density": 1.0,
            "hardness": 0.0,
            "rotation": 0.0,
            "offset": 50.0,
            "hue": 0.0,
            "saturation": 0.0,
        },
        ranges={
            "density": (-8.0, 8.0),
            "hardness": (0.0, 100.0),
            "rotation": (-180.0, 180.0),
            "offset": (0.0, 100.0),
            "hue": (0.0, 1.0),
            "saturation": (0.0, 1.0),
        },
        size_bytes=24,  # struct.calcsize("<6f"); absent from the 534-preset library
        blendop_cst=3,  # RGB_DISPLAY — default_colorspace() returns IOP_CS_RGB
    ),
    "agx": IOPRegistry(
        operation="agx",
        version=7,  # DT_MODULE_INTROSPECTION(7), agx.c
        # v7 layout (agx.c:98-155, all 4-byte fields) → 36 fields = 144 B:
        #   5f look (lift, slope, brightness, saturation, hue mix 0.6)
        #   3f log mapping (black EV -10, white EV 6.5, DR scaling 0.1)
        #   8f curve (pivot x 10/16.5, pivot y 0.18, contrast 3.0,
        #            toe/shoulder ratios 0, toe power 1.5, shoulder 3.3,
        #            gamma 2.2)
        #   i  auto_gamma FALSE
        #   2f target display black 0 / white 1
        #   2i base_primaries DT_AGX_REC2020=2, disable_primaries FALSE
        #   6f primaries inset/rotation (red/green/blue, all 0)
        #   2f master outset/unrotation ratio (1, 1)
        #   6f per-channel outset/unrotation (all 0)
        #   i  completely_reverse_primaries FALSE [v5]
        # Absent from the 534-preset library — visual loop validates.
        # base_primaries enum (agx.c:87-95): EXPORT=0, WORK=1, REC2020=2,
        # P3=3, ADOBE=4, SRGB=5.
        pack_format="<5f3f8fi2f2i6f2f6fi",
        fields=(
            "look_lift",
            "look_slope",
            "look_brightness",
            "look_saturation",
            "look_original_hue_mix_ratio",
            "range_black_relative_ev",
            "range_white_relative_ev",
            "dynamic_range_scaling",
            "curve_pivot_x",
            "curve_pivot_y_linear_output",
            "curve_contrast_around_pivot",
            "curve_linear_ratio_below_pivot",
            "curve_linear_ratio_above_pivot",
            "curve_toe_power",
            "curve_shoulder_power",
            "curve_gamma",
            "auto_gamma",
            "curve_target_display_black_ratio",
            "curve_target_display_white_ratio",
            "base_primaries",
            "disable_primaries_adjustments",
            "red_inset",
            "red_rotation",
            "green_inset",
            "green_rotation",
            "blue_inset",
            "blue_rotation",
            "master_outset_ratio",
            "master_unrotation_ratio",
            "red_outset",
            "red_unrotation",
            "green_outset",
            "green_unrotation",
            "blue_outset",
            "blue_unrotation",
            "completely_reverse_primaries",
        ),
        defaults={
            "look_lift": 0.0,
            "look_slope": 1.0,
            "look_brightness": 1.0,
            "look_saturation": 1.0,
            "look_original_hue_mix_ratio": 0.6,
            "range_black_relative_ev": -10.0,
            "range_white_relative_ev": 6.5,
            "dynamic_range_scaling": 0.1,
            "curve_pivot_x": 0.606060606061,  # 10/16.5 mid-gray position
            "curve_pivot_y_linear_output": 0.18,
            "curve_contrast_around_pivot": 3.0,
            "curve_linear_ratio_below_pivot": 0.0,
            "curve_linear_ratio_above_pivot": 0.0,
            "curve_toe_power": 1.5,
            "curve_shoulder_power": 3.3,
            "curve_gamma": 2.2,
            "auto_gamma": 0,
            "curve_target_display_black_ratio": 0.0,
            "curve_target_display_white_ratio": 1.0,
            "base_primaries": 2,  # DT_AGX_REC2020
            "disable_primaries_adjustments": 0,
            "red_inset": 0.0,
            "red_rotation": 0.0,
            "green_inset": 0.0,
            "green_rotation": 0.0,
            "blue_inset": 0.0,
            "blue_rotation": 0.0,
            "master_outset_ratio": 1.0,
            "master_unrotation_ratio": 1.0,
            "red_outset": 0.0,
            "red_unrotation": 0.0,
            "green_outset": 0.0,
            "green_unrotation": 0.0,
            "blue_outset": 0.0,
            "blue_unrotation": 0.0,
            "completely_reverse_primaries": 0,
        },
        ranges={
            "look_lift": (-1.0, 1.0),
            "look_slope": (0.0, 10.0),
            "look_brightness": (0.0, 100.0),
            "look_saturation": (0.0, 10.0),
            "look_original_hue_mix_ratio": (0.0, 1.0),
            "range_black_relative_ev": (-20.0, -0.1),
            "range_white_relative_ev": (0.1, 20.0),
            "dynamic_range_scaling": (-0.5, 2.0),
            "curve_pivot_x": (0.0, 1.0),
            "curve_pivot_y_linear_output": (0.0, 1.0),
            "curve_contrast_around_pivot": (0.1, 10.0),
            "curve_linear_ratio_below_pivot": (0.0, 1.0),
            "curve_linear_ratio_above_pivot": (0.0, 1.0),
            "curve_toe_power": (0.0, 10.0),
            "curve_shoulder_power": (0.0, 10.0),
            "curve_gamma": (0.01, 100.0),
            "auto_gamma": (0, 1),
            "curve_target_display_black_ratio": (0.0, 0.15),
            "curve_target_display_white_ratio": (0.2, 1.0),
            "base_primaries": (0, 5),
            "disable_primaries_adjustments": (0, 1),
            "red_inset": (0.0, 0.99),
            "red_rotation": (-0.5236, 0.5236),
            "green_inset": (0.0, 0.99),
            "green_rotation": (-0.5236, 0.5236),
            "blue_inset": (0.0, 0.99),
            "blue_rotation": (-0.5236, 0.5236),
            "master_outset_ratio": (0.0, 2.0),
            "master_unrotation_ratio": (0.0, 2.0),
            "red_outset": (0.0, 0.99),
            "red_unrotation": (-0.5236, 0.5236),
            "green_outset": (0.0, 0.99),
            "green_unrotation": (-0.5236, 0.5236),
            "blue_outset": (0.0, 0.99),
            "blue_unrotation": (-0.5236, 0.5236),
            "completely_reverse_primaries": (0, 1),
        },
        size_bytes=144,  # struct.calcsize("<5f3f8fi2f2i6f2f6fi"); absent from the 534-preset library
        blendop_cst=4,  # RGB_SCENE — tone-mapping module, default_colorspace() = IOP_CS_RGB
    ),
    "channelmixerrgb": IOPRegistry(
        operation="channelmixerrgb",
        version=3,  # DT_MODULE_INTROSPECTION(3), channelmixerrgb.c
        # v3 layout (channelmixerrgb.c:91-121, CHANNEL_SIZE=4):
        #   6 × float[4]: red, green, blue (mix matrix, identity default),
        #   saturation, lightness, grey (all 0) → 24 f
        #   6 × gboolean normalize_* (0)
        #   4 × int enum: illuminant (DT_ILLUMINANT_D=2), illum_fluo
        #   (DT_ILLUMINANT_FLUO_F3=2), illum_led (DT_ILLUMINANT_LED_B5=4),
        #   adaptation (DT_ADAPTATION_CAT16=1)
        #   4 × float: x (0.333), y (0.333), temperature (5003.0), gamut (1.0)
        #   2 × int: clip TRUE (1), version CHANNELMIXERRGB_V_3=2
        # → "<24f10i4f2i" = 40 fields = 160 B.
        # Absent from the 534-preset library — visual loop validates.
        pack_format="<24f10i4f2i",
        fields=(
            *(
                f"{c}_{i}"
                for c in ("red", "green", "blue", "saturation", "lightness", "grey")
                for i in range(4)
            ),
            "normalize_R",
            "normalize_G",
            "normalize_B",
            "normalize_sat",
            "normalize_light",
            "normalize_grey",
            "illuminant",
            "illum_fluo",
            "illum_led",
            "adaptation",
            "x",
            "y",
            "temperature",
            "gamut",
            "clip",
            "version",
        ),
        defaults={
            "red_0": 1.0,
            "green_1": 1.0,
            "blue_2": 1.0,  # identity mix matrix (channelmixerrgb.c:3859)
            **{
                f"{c}_{i}": 0.0
                for c in ("red", "green", "blue", "saturation", "lightness", "grey")
                for i in range(4)
                if not (c == "red" and i == 0 or c == "green" and i == 1 or c == "blue" and i == 2)
            },
            **dict.fromkeys(("normalize_R", "normalize_G", "normalize_B", "normalize_sat", "normalize_light", "normalize_grey"), 0),
            "illuminant": 2,  # DT_ILLUMINANT_D (illuminants.h:30)
            "illum_fluo": 2,  # DT_ILLUMINANT_FLUO_F3 (illuminants.h:47)
            "illum_led": 4,  # DT_ILLUMINANT_LED_B5 (illuminants.h:67)
            "adaptation": 1,  # DT_ADAPTATION_CAT16 (chromatic_adaptation.h:28)
            "x": 0.333,
            "y": 0.333,
            "temperature": 5003.0,
            "gamut": 1.0,
            "clip": 1,  # gboolean TRUE
            "version": 2,  # CHANNELMIXERRGB_V_3 (channelmixerrgb.c:88)
        },
        ranges={
            **{
                f"{c}_{i}": (-2.0, 2.0)
                for c in ("red", "green", "blue", "saturation", "lightness", "grey")
                for i in range(4)
            },
            **dict.fromkeys(("normalize_R", "normalize_G", "normalize_B", "normalize_sat", "normalize_light", "normalize_grey"), (0, 1)),
            "illuminant": (0, 10),
            "illum_fluo": (0, 12),
            "illum_led": (0, 12),
            "adaptation": (0, 4),
            "x": (0.0, 1.0),
            "y": (0.0, 1.0),
            "temperature": (1667.0, 25000.0),
            "gamut": (0.0, 12.0),
            "clip": (0, 1),
            "version": (0, 2),
        },
        size_bytes=160,  # struct.calcsize("<24f10i4f2i"); absent from the 534-preset library
        blendop_cst=4,  # RGB_SCENE — white-balance/mixing module, scene-referred
    ),
    "primaries": IOPRegistry(
        operation="primaries",
        version=1,  # DT_MODULE_INTROSPECTION(1), primaries.c
        # Layout (primaries.c): 8 floats → "<8f" = 32 B: achromatic tint
        # hue/purity, then red/green/blue hue/purity. VERIFIED against 3
        # real blobs (32 B each, e.g. "examples_colors_blue LED lighting
        # fix": blue_hue=-0.1047, blue_purity=0.95) — field order matches.
        pack_format="<8f",
        fields=(
            "achromatic_tint_hue",
            "achromatic_tint_purity",
            "red_hue",
            "red_purity",
            "green_hue",
            "green_purity",
            "blue_hue",
            "blue_purity",
        ),
        defaults={
            "achromatic_tint_hue": 0.0,
            "achromatic_tint_purity": 0.0,
            "red_hue": 0.0,
            "red_purity": 1.0,
            "green_hue": 0.0,
            "green_purity": 1.0,
            "blue_hue": 0.0,
            "blue_purity": 1.0,
        },
        ranges={
            "achromatic_tint_hue": (-3.14159, 3.14159),
            "achromatic_tint_purity": (0.0, 0.99),
            "red_hue": (-3.14159, 3.14159),
            "red_purity": (0.01, 5.0),
            "green_hue": (-3.14159, 3.14159),
            "green_purity": (0.01, 5.0),
            "blue_hue": (-3.14159, 3.14159),
            "blue_purity": (0.01, 5.0),
        },
        size_bytes=32,  # Verified against 3 real .dtstyle blobs
        blendop_cst=4,  # RGB_SCENE — per the real style blobs
    ),
    "diffuse": IOPRegistry(
        operation="diffuse",
        version=2,  # DT_MODULE_INTROSPECTION(2), diffuse.c
        # v2 layout (diffuse.c): iterations(i), sharpness(f), radius(i),
        # regularization(f), variance_threshold(f), anisotropy_first..fourth
        # (4f), threshold(f), first..fourth speed (4f) [v1 = 56 B],
        # radius_center(i) [v2] → "<ifi2f4ff4fi" = 15 fields = 60 B.
        # VERIFIED against the real blob in
        # "examples_contrast and sharpness_sharpen..." (60 B, module=2):
        # iterations=30, radius=2, regularization=1.5, variance=-0.05,
        # aniso2=3.0, speeds=(0.02, 0.04, -0.12, 0.04), radius_center=0.
        pack_format="<ifi2f4ff4fi",
        fields=(
            "iterations",
            "sharpness",
            "radius",
            "regularization",
            "variance_threshold",
            "anisotropy_first",
            "anisotropy_second",
            "anisotropy_third",
            "anisotropy_fourth",
            "threshold",
            "first",
            "second",
            "third",
            "fourth",
            "radius_center",
        ),
        defaults={
            "iterations": 1,
            "sharpness": 0.0,
            "radius": 8,
            "regularization": 0.0,
            "variance_threshold": 0.0,
            "anisotropy_first": 0.0,
            "anisotropy_second": 0.0,
            "anisotropy_third": 0.0,
            "anisotropy_fourth": 0.0,
            "threshold": 0.0,
            "first": 0.0,
            "second": 0.0,
            "third": 0.0,
            "fourth": 0.0,
            "radius_center": 0,
        },
        ranges={
            "iterations": (0, 500),
            "sharpness": (-1.0, 1.0),
            "radius": (0, 2048),
            "regularization": (0.0, 4.0),
            "variance_threshold": (-2.0, 2.0),
            "anisotropy_first": (-10.0, 10.0),
            "anisotropy_second": (-10.0, 10.0),
            "anisotropy_third": (-10.0, 10.0),
            "anisotropy_fourth": (-10.0, 10.0),
            "threshold": (0.0, 8.0),
            "first": (-1.0, 1.0),
            "second": (-1.0, 1.0),
            "third": (-1.0, 1.0),
            "fourth": (-1.0, 1.0),
            "radius_center": (0, 1024),
        },
        size_bytes=60,  # Verified against real .dtstyle blob (60 B, module=2)
        blendop_cst=4,  # RGB_SCENE — per the real style blob
    ),
    "negadoctor": IOPRegistry(
        operation="negadoctor",
        version=2,  # DT_MODULE_INTROSPECTION(2), negadoctor.c
        # Layout: film_stock(int enum NB=0/COLOR=1), Dmin[4], wb_high[4],
        # wb_low[4], D_max, offset, black, gamma, soft_clip, exposure
        # → "<i18f" = 19 fields = 76 B. Absent from the 534-preset library.
        pack_format="<i18f",
        fields=(
            "film_stock",
            "Dmin_0",
            "Dmin_1",
            "Dmin_2",
            "Dmin_3",
            "wb_high_0",
            "wb_high_1",
            "wb_high_2",
            "wb_high_3",
            "wb_low_0",
            "wb_low_1",
            "wb_low_2",
            "wb_low_3",
            "D_max",
            "offset",
            "black",
            "gamma",
            "soft_clip",
            "exposure",
        ),
        defaults={
            "film_stock": 1,  # DT_FILMSTOCK_COLOR
            **{f"Dmin_{i}": 1.0 for i in range(4)},
            **{f"wb_high_{i}": 1.0 for i in range(4)},
            **{f"wb_low_{i}": 1.0 for i in range(4)},
            "D_max": 2.046,
            "offset": -0.05,
            "black": 0.0755,
            "gamma": 4.0,
            "soft_clip": 0.75,
            "exposure": 0.9245,
        },
        ranges={
            "film_stock": (0, 1),
            **{f"Dmin_{i}": (0.00001, 1.5) for i in range(4)},
            **{f"wb_high_{i}": (0.25, 2.0) for i in range(4)},
            **{f"wb_low_{i}": (0.25, 2.0) for i in range(4)},
            "D_max": (0.1, 6.0),
            "offset": (-1.0, 1.0),
            "black": (-0.5, 0.5),
            "gamma": (1.0, 8.0),
            "soft_clip": (0.0001, 1.0),
            "exposure": (0.5, 2.0),
        },
        size_bytes=76,  # struct.calcsize("<i18f"); absent from the 534-preset library
        blendop_cst=4,  # RGB_SCENE — negative-film reconstruction, scene-referred
    ),
    "defringe": IOPRegistry(
        operation="defringe",
        version=1,  # DT_MODULE_INTROSPECTION(1), defringe.c
        # Layout: radius(f, 0.5..20, def 4.0), thresh(f, 0.5..128, def 20.0),
        # op_mode(int enum GLOBAL_AVERAGE=0/LOCAL_AVERAGE=1/STATIC=2)
        # → "<2fi" = 12 B. Absent from the 534-preset library.
        pack_format="<2fi",
        fields=("radius", "thresh", "op_mode"),
        defaults={"radius": 4.0, "thresh": 20.0, "op_mode": 0},
        ranges={"radius": (0.5, 20.0), "thresh": (0.5, 128.0), "op_mode": (0, 2)},
        size_bytes=12,  # struct.calcsize("<2fi"); absent from the 534-preset library
        blendop_cst=2,  # LAB — default_colorspace() returns IOP_CS_LAB
    ),
    "cacorrectrgb": IOPRegistry(
        operation="cacorrectrgb",
        version=1,  # DT_MODULE_INTROSPECTION(1), cacorrectrgb.c
        # Layout: guide_channel(int enum R=0/G=1/B=2, def G=1), radius(f,
        # 1..500, def 5), strength(f, 0..4, def 0.5), mode(int enum
        # STANDARD=0/DARKEN=1/BRIGHTEN=2), refine_manifolds(gboolean FALSE)
        # → "<i2f2i" = 20 B. Absent from the 534-preset library.
        pack_format="<i2f2i",
        fields=("guide_channel", "radius", "strength", "mode", "refine_manifolds"),
        defaults={
            "guide_channel": 1,
            "radius": 5.0,
            "strength": 0.5,
            "mode": 0,
            "refine_manifolds": 0,
        },
        ranges={
            "guide_channel": (0, 2),
            "radius": (1.0, 500.0),
            "strength": (0.0, 4.0),
            "mode": (0, 2),
            "refine_manifolds": (0, 1),
        },
        size_bytes=20,  # struct.calcsize("<2f3i"); absent from the 534-preset library
        blendop_cst=4,  # RGB_SCENE — CA correction early in the pipeline
    ),
    "globaltonemap": IOPRegistry(
        operation="globaltonemap",
        version=3,  # DT_MODULE_INTROSPECTION(3), globaltonemap.c
        # Layout: operator(int enum REINHARD=0/FILMIC=1/DRAGO=2, def DRAGO),
        # drago.bias(f, 0.5..1, def 0.85), drago.max_light(f, 1..500, def
        # 100.0), detail(f, -1..1, def 0.0) → "<i3f" = 16 B. Absent from
        # the 534-preset library.
        pack_format="<i3f",
        fields=("operator", "bias", "max_light", "detail"),
        defaults={"operator": 2, "bias": 0.85, "max_light": 100.0, "detail": 0.0},
        ranges={
            "operator": (0, 2),
            "bias": (0.5, 1.0),
            "max_light": (1.0, 500.0),
            "detail": (-1.0, 1.0),
        },
        size_bytes=16,  # struct.calcsize("<i3f"); absent from the 534-preset library
        blendop_cst=2,  # LAB — default_colorspace() returns IOP_CS_LAB
    ),
    "profile_gamma": IOPRegistry(
        operation="profile_gamma",
        version=2,  # DT_MODULE_INTROSPECTION(2), profile_gamma.c
        # Layout: mode(int enum LOG=0/GAMMA=1, def LOG), linear(f, 0..1,
        # def 0.1), gamma(f, 0..1, def 0.45), dynamic_range(f, 0.01..32,
        # def 10.0), grey_point(f, 0.1..100, def 18.0), shadows_range(f,
        # -16..16, def -5.0), security_factor(f, -100..100, def 0.0)
        # → "<i6f" = 28 B. Absent from the 534-preset library.
        # Operation name is "profile_gamma" (file profile_gamma.c; add_iop in iop CMakeLists).
        pack_format="<i6f",
        fields=(
            "mode",
            "linear",
            "gamma",
            "dynamic_range",
            "grey_point",
            "shadows_range",
            "security_factor",
        ),
        defaults={
            "mode": 0,
            "linear": 0.1,
            "gamma": 0.45,
            "dynamic_range": 10.0,
            "grey_point": 18.0,
            "shadows_range": -5.0,
            "security_factor": 0.0,
        },
        ranges={
            "mode": (0, 1),
            "linear": (0.0, 1.0),
            "gamma": (0.0, 1.0),
            "dynamic_range": (0.01, 32.0),
            "grey_point": (0.1, 100.0),
            "shadows_range": (-16.0, 16.0),
            "security_factor": (-100.0, 100.0),
        },
        size_bytes=28,  # struct.calcsize("<i6f"); absent from the 534-preset library
        blendop_cst=4,  # RGB_SCENE — log/scene workflow module
    ),
}
