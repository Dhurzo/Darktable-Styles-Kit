# Future IOPs — documented but not exposed

This document records IOPs whose binary layouts have been **derived from
the darktable C sources** but are deliberately **NOT implemented** in the
dtstylekit registry/prompt yet. They stay here so the work is not lost
and the activation conditions are explicit.

## Why keep IOPs out of the prompt?

The VLM (gemma3:27b) proposes parameters from a prompt. Every exposed
IOP adds prompt tokens and — more importantly — degrees of freedom the
model can misuse. The current policy (rule #20, MODEST REFINEMENT) caps
each style at 2–3 refinement modules with conservative ranges. Exposing
IOPs that require the model to propose **dozens of numbers at once** (or
that cannot be verified against real blobs) creates broken styles with
no quality upside.

An IOP is promoted to the registry when **both** hold:

1. The struct layout is verified against a real blob (official preset,
   benchmark XMP, or an E2E darktable-cli render round-trip).
2. The VLM can reasonably propose its parameters (few, meaningful,
   bounded numbers).

---

## channelmixerrgb (v3) — most powerful grading matrix, not exposed

The single most powerful color-grading IOP in darktable (a full 3×3 RGB
matrix + saturation/lightness/grey rows + chromatic adaptation), yet the
hardest to drive from a VLM.

### C source (checkout master, `src/iop/channelmixerrgb.c`)

```
DT_MODULE_INTROSPECTION(3, dt_iop_channelmixer_rgb_params_t)
#define CHANNEL_SIZE 4
#define COLOR_MIN -2.0
#define COLOR_MAX 2.0
#define TEMP_MIN 1667.
#define TEMP_MAX 25000.
```

```
struct dt_iop_channelmixer_rgb_params_t {
  float red[4], green[4], blue[4];          // $MIN: -2.0 $MAX: 2.0
  float saturation[4], lightness[4], grey[4]; // $MIN: -2.0 $MAX: 2.0
  gboolean normalize_R, normalize_G, normalize_B,
           normalize_sat, normalize_light, normalize_grey;
  dt_illuminant_t illuminant;               // $DEFAULT: DT_ILLUMINANT_D
  dt_illuminant_fluo_t illum_fluo;          // $DEFAULT: DT_ILLUMINANT_FLUO_F3
  dt_illuminant_led_t illum_led;            // $DEFAULT: DT_ILLUMINANT_LED_B5
  dt_adaptation_t adaptation;               // $DEFAULT: DT_ADAPTATION_CAT16
  float x, y;                               // $DEFAULT: 0.333
  float temperature;                        // $MIN: 1667 $MAX: 25000 $DEFAULT: 5003
  float gamut;                              // $MIN: 0.0 $MAX: 12.0 $DEFAULT: 1.0
  gboolean clip;                            // $DEFAULT: TRUE
  dt_iop_channelmixer_rgb_version_t version; // $DEFAULT: CHANNELMIXERRGB_V_3 (2)
};
```

### Derived layout

| Field group | Count | C type | pack |
|---|---|---|---|
| `red`/`green`/`blue`/`saturation`/`lightness`/`grey` | 6 × 4 | float | `24f` |
| `normalize_*` | 6 | gboolean | `6i` |
| `illuminant`, `illum_fluo`, `illum_led`, `adaptation` | 4 | enum | `4i` |
| `x`, `y` | 2 | float | `2f` |
| `temperature` | 1 | float | `1f` |
| `gamut` | 1 | float | `1f` |
| `clip` | 1 | gboolean | `1i` |
| `version` | 1 | enum | `1i` |

**pack_format**: `<24f12i2f2fi` … `struct.calcsize` = **160 bytes**,
version 3, blendop_cst = **4 (RGB_SCENE)** — verify against the C before
committing anything.

### Why not now

- **24 matrix coefficients + 6 booleans + 4 enums** — the VLM would have
  to emit ~35 numbers in a single JSON; gemma3:27b cannot do this
  reliably and any partial/absurd matrix breaks the grade.
- **No real blobs to verify against**: absent from the 534 official
  presets and from the benchmark XMPs (only the legacy `channelmixer`
  88B IOP appears there). Size verification would rely on
  `struct.calcsize` alone until an E2E darktable-cli render round-trip
  is done.

### Activation condition

Revisit when **either** applies:

- A more capable VLM (larger or better-instructed model) that can emit
  the full matrix in one shot — then expose only the *diagonal
  normalization* pattern (`red=[1,0,0,0]`, etc.) plus `temperature` /
  `gamut` / `adaptation` presets, keeping the matrix rows at defaults.
- A real channelmixerrgb blob becomes available (user-contributed
  preset) to pin `size_bytes` and validate the pack round-trip.

---

## Other deferred IOPs (from the discovery sweep)

| IOP | Why deferred |
|---|---|
| `equalizer` | 2D matrices `equalizer_x/y[3][BANDS]` + nested `drag_params` struct + GUI-only draw arrays — layout risk high, no blobs |
| `zonesystem` | Arrays + nested structs + `MAX_ZONE_SYSTEM_SIZE` constant — same risk class |
| `retouch`, `liquify`, `spots` | Local editing tools — not a “style” concern, complex blobs |
| raw-prep (`demosaic`, `rawprepare`, `rawdenoise`, …) | Auto-pipeline modules; exposing them would fight darktable's own defaults |
| geometric (`crop`, `flip`, `rotatepixels`, …) | Not style-related |
| `hazeremoval` | Explicitly rejected by the dark-image guard (crushes shadows) |
| `useless`, `watermark` | Non-photographic |

---

## relight — DEPRECATED, do not register

`relight` was implemented end-to-end (registry entry `<3f` 12B, tests,
prompt section, E2E) and then **removed again**. It is deprecated in
darktable — the C source carries `"this module is deprecated. please use
the tone equalizer module instead"` (`src/iop/relight.c:91-93`) — and it
is **not compiled into the released 5.6.0 binary**: `darktable-cli`
silently ignores the module when applying a style (verified: renders with
every `ev` value, including defaults, are pixel-identical to the
baseline).

Lessons recorded:

- A struct layout can be correct and verified against benchmark blobs
  (relight's 12B blob exists in `darktable-bench-3.4legacy.xmp`) and the
  module can still be dead at runtime.
- **Always E2E-render before exposing an IOP**, even with a real blob in
  hand — `tools/benchmark_probe.py` proves the layout, only a render
  proves the module is alive in the target darktable binary.
- The replacement for shadow-lifting is `toneequal` (registered, v2,
  verified 72B) — its `shadows`/`blacks` bands cover relight's use case
  with more control.

If a future darktable release re-enables relight, re-register it from
the draft in git history (`git show <commit>:dtstylekit/codec/iop_registry.py`).

---

## How new IOPs get discovered (the process)

1. **Extract**: `python tools/extract_iop_struct.py src/iop/<op>.c
   --blendop <2|3|4>` → draft `IOPRegistry` entry (fields, defaults,
   ranges, pack_format, size_bytes) straight from the C annotations.
2. **Verify size**: `python tools/benchmark_probe.py <darktable-checkout>`
   — compares every real blob in the 6 benchmark XMPs (≈283 blobs,
   ≈66 ops) against the registry; `MISMATCH` means the layout is wrong.
   Official presets (`test_real_presets.py`) are a second source.
3. **Round-trip tests**: pack/unpack + real-blob fixture (commit the
   XMP/style into `tests/fixtures/`).
4. **E2E**: if no real blob exists (e.g. colorharmonizer), render via
   `darktable-cli` with an isolated library — neutrals must equal the
   baseline, values must produce a sane effect.
5. **Expose**: only then add to `schema_renderer` refinement list and
   the SYSTEM_PROMPT block, with conservative ranges and a MODEST
   REFINEMENT note.
</content>
