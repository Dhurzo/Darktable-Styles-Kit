# primaries, diffuse, negadoctor, defringe, cacorrectrgb, globaltonemap, profile_gamma

Status: all **PASS** (visual loop; blobs verified against real presets
where available).

## primaries (v1, 32 B, `<8f`) — blob-verified

- 8 floats: achromatic tint hue/purity + red/green/blue hue/purity.
- **3 real blobs** (32 B each) decode with exact field order — e.g.
  "blue LED lighting fix": blue_hue=-0.1047, blue_purity=0.95.
- Visual: blue_purity 1→0.3 desaturates blues (sat -0.031, MAE 1.9 on a
  low-blue image). blendop_cst=4 (RGB_SCENE, per real blobs).

## diffuse (v2, 60 B, `<ifi2f4ff4fi`) — blob-verified

- iterations(i), sharpness(f), radius(i), regularization(f),
  variance_threshold(f), 4×anisotropy(f), threshold(f), 4×speed(f),
  radius_center(i)[v2].
- **Real blob** ("examples_contrast and sharpness_sharpen...", 60 B,
  module=2): iterations=30, radius=2, regularization=1.5, variance=-0.05,
  aniso2=3.0, speeds=(0.02, 0.04, -0.12, 0.04) — decodes cleanly.
- Visual: those real-preset values raise local contrast +10.9 % — the
  anisotropic-diffusion solver sharpens as well as smooths depending on
  the speed/anisotropy signs. blendop_cst=4.

## negadoctor (v2, 76 B, `<i18f`)

- film_stock(enum NB=0/COLOR=1) + Dmin[4] + wb_high[4] + wb_low[4] +
  D_max, offset, black, gamma, soft_clip, exposure.
- Visual: defaults on a positive image → massive tonal remap
  (MAE 125.5/255, lum +0.412) — the module treats the input as a film
  negative, exactly its documented purpose. blendop_cst=4.

## defringe (v1, 12 B, `<2fi`)

- radius(f 0.5..20, def 4), thresh(f 0.5..128, def 20), op_mode(enum
  GLOBAL_AVERAGE=0/LOCAL=1/STATIC=2).
- Visual on synthetic CA (R channel shifted 3 px): CA edge metric
  1.481 → 1.208 (-18 %). Conditional module: no-CA input passes through
  unchanged (correct behavior). blendop_cst=2 (LAB).

## cacorrectrgb (v1, 20 B, `<i2f2i`)

- guide_channel(enum R=0/G=1/B=2, def G=1), radius(f 1..500, def 5),
  strength(f 0..4, def 0.5), mode(enum STANDARD=0/DARKEN=1/BRIGHTEN=2),
  refine_manifolds(gboolean).
- Visual on synthetic CA: CA metric 1.481 → 0.643 (-57 %) with
  strength=2.5, radius=12. blendop_cst=4.

## globaltonemap (v3, 16 B, `<i3f`)

- operator(enum REINHARD=0/FILMIC=1/DRAGO=2, def DRAGO), drago.bias
  (0.5..1, def 0.85), drago.max_light(1..500, def 100), detail(-1..1).
- Visual: Drago defaults → lum +0.085, local contrast +17.4 %, MAE 21.7
  (highlight compression). blendop_cst=2 (LAB).

## profile_gamma (v2, 28 B, `<i6f`) — NAME GOTCHA

- mode(enum LOG=0/GAMMA=1), linear(0..1, def 0.1), gamma(0..1, def
  0.45), dynamic_range(0.01..32, def 10), grey_point(0.1..100, def 18),
  shadows_range(-16..16, def -5), security_factor(-100..100, def 0).
- **Attempt 1 FAIL: operation name is `profile_gamma` (with underscore,
  per `add_iop(profile_gamma ...)` in src/iop/CMakeLists.txt) — the
  style silently no-ops with any other name.** Attempt 2 with the right
  name + mode=GAMMA/gamma=0.9/DR=32: MAE 8.17 (strong tonal remap).
- blendop_cst=4 (RGB_SCENE).

## Usage notes

- primaries: per-channel hue shifts ±0.1 rad + purity 0.8–1.2 for
  creative grading (see the blue-LED-fix presets).
- diffuse: positive `third` speed smooths; the real-preset combo
  sharpens. Start from the real blob values.
- negadoctor: only meaningful on scanned negatives — do not emit for
  normal photos unless the user asks for the film-negative look.
- defringe/cacorrectrgb: correction modules; only emit when the user
  reports CA.
- globaltonemap: DRAGO is the sensible default; bias 0.8–0.9.
- profile_gamma: niche (log workflows); remember the underscore.
