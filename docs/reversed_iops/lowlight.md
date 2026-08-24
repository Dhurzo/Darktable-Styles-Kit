# Reversed IOP: lowlight

Status: **PASS** (v1) — verified 2026-08-20 via live `darktable-cli` render.

## Registry entry

- operation: `lowlight`
- version: `1`
- pack_format: `<13f`
- size_bytes: `52`
- blendop_cst: `2` (LAB)

## Struct layout (from `src/iop/lowlight.c`)

`dt_iop_lowlight_params_t` (v1):

| offset | field | type | meaning |
|--------|-------|------|---------|
| 0 | `blueness` | f32 | scotopic white saturation (blue shift) |
| 1..6 | `transition_x[6]` | f32×6 | curve control points, x (luminance 0..1) |
| 7..12 | `transition_y[6]` | f32×6 | curve control points, y (blend weight 0..1) |

`DT_IOP_LOWLIGHT_BANDS = 6`.

## Defaults & ranges

| field | default | range | notes |
|-------|---------|-------|-------|
| `blueness` | 0.0 | 0.0..100.0 | $DEFAULT: 0.0, $MAX: 100.0 |
| `transition_x[k]` | k/5 | 0.0..1.0 | i.e. `[0, .2, .4, .6, .8, 1]` |
| `transition_y[k]` | 0.5 | 0.0..1.0 | flat 0.5 default |

## Algorithm semantics (how the params drive the output)

1. `commit_params` builds a draw-curve from `(transition_x[k], transition_y[k])`
   (with extrapolation sentinels `(tx[4]-1, ty[0])` and `(tx[1]+1, ty[5])`),
   then samples it into a 256-entry LUT over the domain `[0,1]`.
2. Per pixel (Lab input):
   - scotopic white `Lab_sw = (100, 0, -blueness)` → `XYZ_sw`.
   - scotopic luminance `V = CLIP(0.5 * Y * (1.33*(1+(Y+Z)/X) - 1.68))`.
   - blend weight `w = lut(L/100)`.
   - output `XYZ = w*XYZ + (1-w) * V * XYZ_sw`.

Net effect: midtones/highlights shift toward cool blue, true shadows darken
(`V` is tiny there). Higher `blueness` = stronger saturation of the scotopic
point; `transition_y` at a given luminance = weight toward the scotopic point.

## Verification evidence

- Round-trip: packed blob decodes to the exact test params
  (`blueness=50.0`, `transition_x=[0,.2,.4,.6,.8,1]`,
  `transition_y=[0,.2,.5,.7,.9,1]`); XMP hex encode/decode round-trips.
- Real preset match: both `examples_effects_day for night.dtstyle` and
  `examples_effects_day for twilight.dtstyle` blobs (52 B) decode with this
  struct; `night` = `blueness 40, x=[0,.15,.4,.6,.8,1], y=[0,.02,.05,.2,.55,1]`.
- Visual loop (attempt 2/3, after fixing `<module>` to 1):
  `darktable-cli --style lowlight_verify` on a 1200×1500 WebP export.
  Baseline vs styled render: 70% of pixels changed (mean |Δ| 12.4/255,
  p95 26/255). Per Lab band: L<10 → darkening, L 10-70 → strong blue shift
  (dB +19..+25), L>70 → mild cool shift (dB +12). Direction and magnitude
  match the algorithm; no artifacts.

## Implementation notes for dtstylekit preset generation

- `blueness` is the primary creative knob (0 = no color effect).
- `transition_y` controls *where* the effect lands on the luminance axis:
  high `y` at low luminance = shadows strongly shifted to scotopic; the
  shipped day-for-night preset keeps `y` near 0 for most of the curve and
  ramps to 1 at the top, giving a full-frame blue cast.
- Module placement in a `.dtstyle`: use `<module>1</module>` +
  `blendop_version=13` (copy the blendop block from a real preset blob).
