# rgblevels, graduatednd, agx, channelmixerrgb — IOP references

Status: all **PASS** (visual loop, attempt 1–2/3; none appear in the
534-preset library, so the visual loop is the only blob validation).

## rgblevels (v1, 44 B, `<2i9f`)

- `autoscale` (int: LINKED=0, INDEPENDENT=1, def 0), `preserve_colors`
  (int DT_RGB_NORM_*, def LUMINANCE=1), `levels[3][3]` floats = per
  channel R/G/B `{black, middle, white}` defaults {0.0, 0.5, 1.0}
  (RGBLEVELS_MIN/MID/MAX, rgblevels.c:923-930).
- Mapping (rgblevels.c:1298+): `out = ((in-black)/(white-black))^inv_gamma`
  with inv_gamma anchored so middle → 0.5 (commit_params).
- **Visual evidence**: white 1.0→0.72 (all channels) → luminance
  -0.173 with strong structural change. NOTE: the naive expectation
  "lower white ⇒ brighter" is WRONG: the auto-gamma anchors mid=0.5 and
  with white=0.72 the mid sits above the range centre, so the power
  curve (≈1.9) darkens the midtones. Direction is consistent with the
  C source; first attempt flagged as unexpected, diagnosed and PASS.
- blendop_cst=3 (RGB_DISPLAY).

## graduatednd (v1, 24 B, `<6f`)

- density (-8..8 EV, def 1.0), hardness (0..100, def 0), rotation
  (-180..180, def 0), offset (def 50), hue (0..1, def 0), saturation
  (0..1, def 0).
- **Visual evidence**: density=3, hue=0.55 (blue), saturation=0.6 →
  saturation +0.167, R-B -0.073, top-vs-bottom luminance delta -0.114
  (blue ND gradient applied from the top). blendop_cst=3.

## agx (v7, 144 B, `<5f3f8fi2f2i6f2f6fi`, 36 fields)

- Full AgX/Filmic-like tone mapping: look (5f), log range (3f), curve
  (8f), auto_gamma, target display black/white (2f), base primaries
  (enum, REC2020=2) + disable flag, primaries inset/rotation (6f),
  master outset/unrotation ratios (2f), per-channel outset/unrotation
  (6f), completely_reverse_primaries [v5].
- **Visual evidence**: defaults (full tone map active) → global tone
  shift, highlight compression, saturation +0.034. blendop_cst=4
  (RGB_SCENE).

## channelmixerrgb (v3, 160 B, `<24f10i4f2i`, 40 fields)

- 6 × float[4] (red, green, blue mix matrix — identity default;
  saturation, lightness, grey — zeros), 6 × gboolean normalize_*,
  illuminant (D=2), illum_fluo (F3=2), illum_led (B5=4), adaptation
  (CAT16=1), x/y (0.333), temperature (5003.0), gamut (1.0), clip
  (TRUE), version (V3=2).
- **Visual evidence**: temperature 5003→7500 → R-B +0.081 (warmer),
  saturation +0.249. SEMANTICS: the temperature slider is the scene
  *illuminant* temperature — raising it makes the module add more red
  to neutralize a bluer light. Direction correct per module semantics.
  blendop_cst=4 (RGB_SCENE).

## Usage notes for style generation

- rgblevels: prefer small moves of black/white (±0.1) — the auto-gamma
  amplifies midtone shifts.
- graduatednd: density 1–4, hue 0.5–0.65 (blue) for sky gradients.
- agx: defaults are a complete look; use look_saturation/look_slope for
  styling.
- channelmixerrgb: use temperature/gamut sparingly; the mix matrix
  (red/green/blue rows) is the powerful part for creative grading.
