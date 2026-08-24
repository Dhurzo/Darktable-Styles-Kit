# highlights — IOP reverse-engineering reference

Status: **PASS** (blob-verified + visual loop, attempt 1/3).

## Identity

| Field | Value | Source |
|---|---|---|
| operation | `highlights` | src/iop/highlights.c |
| module version | **4** | `DT_MODULE_INTROSPECTION(4)` |
| colorspace | RAW-or-RGB (dynamic) | `default_colorspace()` comment |
| blendop_cst | **1 (DEVELOP_BLEND_CS_RAW)** | real blob `darktable_Fujifilm_X-E1` |
| flags | INCLUDE_IN_STYLES, SUPPORTS_BLENDING, ALLOW_TILING | `int flags()` |

## Struct layout (v4, 48 B, `<i5f2i2fif`)

```c
typedef struct dt_iop_highlights_params_t
{
  dt_iop_highlights_mode_t mode;  // $DEFAULT: DT_IOP_HIGHLIGHTS_OPPOSED (=5)
  float blendL;                   // unused, default 1.0
  float blendC;                   // unused, default 0.0
  float strength;                 // $MIN: 0.0 $MAX: 1.0 $DEFAULT: 0.0
  float clip;                     // $MIN: 0.0 $MAX: 2.0 $DEFAULT: 1.0   [v2]
  float noise_level;              // $MIN: 0. $MAX: 0.5 $DEFAULT: 0.0    [v3]
  int iterations;                 // $MIN: 1 $MAX: 256 $DEFAULT: 30
  dt_atrous_wavelets_scales_t scales; // $DEFAULT: WAVELES_7_SCALE (=6)
  float candidating;              // $MIN: 0.0 $MAX: 1.0 $DEFAULT: 0.4
  float combine;                  // $MIN: 0.0 $MAX: 8.0 $DEFAULT: 2.0
  dt_recovery_mode_t recovery;    // $DEFAULT: DT_RECOVERY_MODE_OFF (=0)
  float solid_color;              // $MIN: 0.0 $MAX: 1.0 $DEFAULT: 0.0   [v4]
} dt_iop_highlights_params_t;
```

Enums: mode CLIP=0, LCH=1, INPAINT=2, LAPLACIAN=3, SEGMENTS=4, OPPOSED=5;
scales WAVELETS_1..7 = 0..6; recovery OFF=0, ADAPT=5, ADAPTF=6.

## Verification

- **Blob real**: `darktable_Fujifilm_X-E1` (module=4, 48 B) decodes to
  EXACTLY the documented defaults (mode=5, blendL=1.0, strength=0.0,
  clip=1.0, iterations=30, scales=6, candidating=0.4, combine=2.0).
- **Visual loop**: blown test image (ref_03 ×2.2, 16.8 % clipped pixels);
  style with strength=1.0, clip=0.5, mode=OPPOSED → clipped pixels
  **16.82 % → 0.00 %** (full reconstruction), luminance -0.15 (expected:
  recovered highlights are darker than pure white).

## Usage notes

- For style generation: strength 0.3–1.0 with clip 0.5–1.0; keep
  mode=OPPOSED (5) and scales=6 unless matching a legacy look.
- recovery (rebuild) adds guided-laplacian inpainting on top; OFF is the
  safe default for styles.
