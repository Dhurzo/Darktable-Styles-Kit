# hazeremoval — IOP reverse-engineering reference

> Implementation reference produced by the verification workflow
> (`docs/iop_translation_workflow.md`). Status: **PASS** (visual loop,
> attempt 1/3).

## Identity

| Field | Value | Source |
|---|---|---|
| operation | `hazeremoval` | src/iop/hazeremoval.c |
| module version (current) | **3** | `DT_MODULE_INTROSPECTION(3, dt_iop_vibrance_params_t)` |
| colorspace | `IOP_CS_RGB` | `default_colorspace()` |
| blendop_cst | **4 (RGB_SCENE)** | real style blob ("examples_contrast and sharpness_dehaze (strong, luminance only)") has cst=4 |
| flags | INCLUDE_IN_STYLES, SUPPORTS_BLENDING, ALLOW_TILING | `int flags()` |

## Struct layout

### v3 (current, 16 bytes, `<ffii`)

```c
typedef struct dt_iop_hazeremoval_params_t
{
  float strength;              // $MIN: -1.0 $MAX: 1.0 $DEFAULT: 0.2
  float distance;              // $MIN:  0.0 $MAX: 1.0 $DEFAULT: 0.2
  gboolean compatibility_mode; // $DEFAULT: FALSE
  gboolean adaptive;           // $DEFAULT: TRUE
} dt_iop_hazeremoval_params_t;
```

### Legacy versions shipped in official styles

- **v2** (12 B, `<ffi`): `strength, distance, compatibility_mode`.
  `legacy_params(2→3)` sets `adaptive = FALSE`.
  Real blob: `examples_contrast and sharpness_dehaze (strong, luminance only)`
  → module=2, `00 00 00 3f cb cc 4c 3f 00 00 00 00`
  = strength=0.5, distance=0.8, compatibility_mode=0.
- **v1** (8 B, `<ff`): `strength, distance`.
  `legacy_params(1→3)` sets `compatibility_mode = TRUE, adaptive = FALSE`.

## Registry entry

`_VERIFIED_IOPS["hazeremoval"]` in `dtstylekit/codec/iop_registry.py`:

- `version=3`, `pack_format="<ffii"`, `size_bytes=16`
- defaults: strength=0.2, distance=0.2, compatibility_mode=0, adaptive=1
- ranges: strength (-1,1), distance (0,1), compatibility_mode (0,1), adaptive (0,1)
- `blendop_cst=4`
- `legacy_size_bytes=(12, 8)`, `legacy_pack_format="<ffi"`,
  `legacy_fields=("strength", "distance", "compatibility_mode")`

## Verification evidence

Static: pack/unpack round-trip lossless; `verify_size` passes on the real
v2 blob; `tests/test_registry.py` + `tests/test_real_presets.py` green
(127 passed).

Visual loop (isolated library, `generated_styles/iop_verify/hazeremoval/`):
minimal style with only hazeremoval at test values
strength=0.8, distance=0.8 (defaults 0.2 are too subtle to judge), rendered
at 1200 px against baseline (IOP off). Quantitative pixel analysis
(this environment has no image viewer; metrics are objective):

| Image | Δ luminance | Δ saturation | Δ local contrast (16px blocks) |
|---|---|---|---|
| ref_01 (dark night shot) | -0.076 | **+34.8 %** | +2.2 % |
| ref_03 (bright scene) | -0.108 | **+122.1 %** | **+16.3 %** |

Direction and magnitude match the C source (veil removal: darker, more
chromatic, more local contrast). No blob-corruption artifacts (no noise
explosion, no color garbage, no clipping blow-up; MAE 19.5/255 structural
change). The elevated shadow clipping is the expected consequence of a
strong test value (0.8/0.8), not a layout error.

## Usage notes for style generation

- Sensible style values: strength 0.1–0.5, distance 0.2–0.8.
- `adaptive=TRUE` (v3 default) is the modern behavior; keep it unless
  reproducing a legacy look.
- The module is scene-referred (blendop_cst=4) — place accordingly in the
  pipeline order.
