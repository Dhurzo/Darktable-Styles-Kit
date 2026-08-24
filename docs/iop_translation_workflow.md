# IOP Translation & Verification Workflow

> **Audience:** the VLM agent (Qwen 3.8 27B — recent, vision-capable) that
> reverse-engineers new darktable IOPs into `dtstylekit` and verifies them
> visually. Internal document — not user-facing.

## 1. Objective

Add new IOPs to `IOP_REGISTRY` by translating the darktable C source into a
verified Python registry entry (struct layout, defaults, ranges, blob size),
then **prove** the translation works by rendering a photo with the generated
style and comparing the result **visually** against a baseline and the
reference look.

**Hard rule: maximum 3 attempts per IOP.** After 3 failed verification
loops, stop, leave the IOP unregistered (or marked unverified), and report
what failed and why.

## 2. Where everything lives

Paths are relative to the `dtstylekit/` project root unless noted.

| Thing | Location |
|---|---|
| IOP registry | `dtstylekit/codec/iop_registry.py` (entries in `_VERIFIED_IOPS`, `_SIMPLE_IOPS`, `_REFINEMENT_IOPS`, `_CURVE_IOPS`) |
| Curve-based IOPs | `dtstylekit/curves/templates.py` + `dtstylekit/curves/packing.py` (`is_curve_iop=True` entries) |
| darktable source (to reverse-engineer) | `/home/juan/Repos/darktable/src/iop/<name>.c` (parent checkout) |
| Extraction tool | `tools/extract_iop_struct.py` — parses the C struct, prints a ready-to-paste registry block |
| Test images | `test_data/` — the user's **own** JPEGs, e.g. `thumb_*.jpg`. No images are committed; if the dir is empty, ask the user to drop photos there. |
| Reference-look images | any path (e.g. `test_data/refs/…`); passed via `--references` |
| Preset library (534 styles) | `data/presets/` (symlink to `../../data/styles`) |
| Generated styles + reports | `generated_styles/` (default output of the pipeline) |
| Search index DB + embeddings | `outputs/` (`presets.db`, `preset_embeddings.npy`) |
| Render scratch (verification) | `generated_styles/iop_verify/<iop>/` (create per IOP) |
| Registry tests | `tests/test_registry.py`, `tests/test_real_presets.py` |
| IOP discovery ledger | `docs/reversed_iops.md` — every IOP ever attempted, with its outcome |

Environment overrides exist for most paths (`DTSTYLEKIT_PRESETS_DIR`,
`DTSTYLEKIT_OUTPUTS_DIR`, `DTSTYLEKIT_GENERATED_DIR`).

## 3. How to translate a new IOP (reverse-engineering)

1. **Read the C source** `src/iop/<name>.c` in the darktable checkout:
   - `dt_iop_<name>_params_t` struct — field order **is** the blob layout
     (little-endian).
   - `$MIN:$MAX:$DEFAULT` annotations on each field.
   - `DT_MODULE_INTROSPECTION(<version>)` — the struct version.
   - `get_colorspace()` → blendop: 2 = LAB, 3 = RGB_DISPLAY, 4 = RGB_SCENE.
   - Older shipped versions (`legacy_*`) if darktable bumped the struct and
     official styles still carry the old blobs.
2. **Run the extractor** for a draft:
   ```bash
   python tools/extract_iop_struct.py /home/juan/Repos/darktable/src/iop/<name>.c --blendop 2|3|4
   ```
   The output is best-effort: **arrays, nested structs and enum members need
   your manual review against the C source** before trusting the block.
3. **Add the entry** to the appropriate dict in `iop_registry.py`:
   - fully understood + verified → `_VERIFIED_IOPS`
   - plausible but not blob-verified → `_SIMPLE_IOPS` / `_REFINEMENT_IOPS`
   - curve-based (colorzones/rgbcurve/tonecurve family) → `_CURVE_IOPS` with
     `is_curve_iop=True` and a template in `curves/templates.py`
   - `size_bytes` must equal `struct.calcsize(pack_format)`.
4. **Static checks**:
   ```bash
   python -m pytest tests/test_registry.py -q          # pack/unpack/size invariants
   python -m pytest tests/test_real_presets.py -q      # round-trip against the 534 real presets
   ```
   Note: some IOPs appear in **zero** real presets (temperature, basicadj,
   toneequal, colorharmonizer) — for those, the visual loop in §4 is the
   only validation available.
5. If any real preset uses the IOP, `unpack_params` its real blob and
   confirm the fields decode sanely and `verify_size` passes.

## 4. Verification loop (render + vision) — max 3 attempts

For each attempt, produce **hard evidence**: rendered image + written
observations. Loop:

1. **Build a minimal .dtstyle** that enables *only* this IOP with its
   defaults (or a clearly labeled test value, e.g. `exposure=+1.0`), packed
   with `pack_params`.
2. **Render** the test image with darktable-cli using an **isolated
   library** (exact pattern from `dtstylekit/vlm/iterative_refiner.py`,
   `render_with_style`):
   ```bash
   # work dir: generated_styles/iop_verify/<iop>/
   env HOME=<work> XDG_CONFIG_HOME=<work>/cfg XDG_DATA_HOME=<work>/data \
     darktable-cli <test_data/thumb_*.jpg> <work>/baseline_init.jpg --width 1200
   ```
   - first run creates the isolated library DB (baseline = the IOP *off*);
   - import the .dtstyle into that library (styles + style_items tables,
     style payload = decoded XMP, see `_import_style_into_library`);
   - render again:
   ```bash
   env HOME=<work> XDG_CONFIG_HOME=<work>/cfg XDG_DATA_HOME=<work>/data \
     darktable-cli <test_data/thumb_*.jpg> <work>/render_<iop>.jpg --width 1200
   ```
   A render that fails to produce an output file is an automatic FAIL.
3. **Look at the images** (you have vision — this is the point of the loop):
   - `render_<iop>.jpg` vs `baseline_init.jpg`: is the expected effect
     present and in the right direction?
   - vs the reference-look images when the IOP defines a look: do colors,
     contrast, temperature and style match?
   - check concretely per IOP family: exposure/basicadj → brightness shift
     & black point; temperature → white balance direction (red/blue);
     curves → shape of tonal response; saturation ops → chroma change.
   - watch for artifacts: clipping, banding, wrong-color casts, crashes.
4. **Decide**:
   - **PASS** — effect present, plausible magnitude, no artifacts. On PASS,
     also write a per-IOP doc `docs/reversed_iops/<iop>.md` capturing the
     registry entry (struct layout, fields, defaults, ranges, version,
     blendop) and the visual evidence. This doc is the input for implementing
     the IOP in `dtstylekit` in future steps, to generate better presets.
   - **FAIL** — no effect, wrong direction, wrong magnitude, artifacts, or
     render failure. Diagnose: re-read the C struct (offsets, field order,
     version, blendop, enum values), fix the entry, and retry.
5. **Max 3 attempts.** After the 3rd failure: keep the entry only if it
   passes pack/unpack round-trips, but mark it as unverified in your report
   (or remove it), and move on to the next IOP. Never silently pass a
   failed IOP.

## 5. IOP ledger (`docs/reversed_iops.md`)

Every IOP you attempt — whether it ends PASS or FAIL — **must** be recorded
in `docs/reversed_iops.md` before moving on:

- **Before starting a discovery session (or when starting from scratch):
  read the ledger first.** Only work on IOPs that are not listed, or are
  listed as FAIL/UNVERIFIED. Never re-do an IOP already marked PASS.
- Each entry: IOP name, status (`PASS` / `FAIL` / `UNVERIFIED`), date,
  pack_format/size/version, and a one-line note (evidence or failure
  diagnosis).
- If you retry an IOP that previously FAILED, update its existing entry —
  do not create a duplicate.

```markdown
| IOP | Status | Version | pack_format / size | Notes |
|-----|--------|---------|--------------------|-------|
| temperature | FAIL (3/3) | v4 | `<4fi` / 20B | blob decodes but render shows no color shift; blendop suspect |
```

## 6. What "verified" means (exit criteria)

- `pack_params → unpack_params` round-trip is lossless (covered by
  `tests/test_registry.py`).
- `size_bytes` matches real blobs when the IOP exists in the 534-preset
  library (covered by `tests/test_real_presets.py`).
- The visual loop §4 passed: the render shows the IOP doing what the C
  source says it does.
- `blendop_cst`, version and `legacy_*` fields are correct per the C
  source.

## 7. Reporting

After each IOP, append a short report (e.g.
`generated_styles/iop_verify/REPORT.md`) **and update the ledger**
(`docs/reversed_iops.md`, see §5):

```markdown
## <iop>
- status: PASS | FAIL (attempt n/3)
- pack_format / size / version / blendop
- evidence: <work>/render_<iop>.jpg vs <work>/baseline_init.jpg
- visual notes: <what you saw, concrete>
- failure diagnosis (if FAIL): <what was wrong and what you changed>
```

On **PASS**, also write `docs/reversed_iops/<iop>.md` (see §4 step 4) —
the implementation reference for future `dtstylekit` preset generation.

## 8. Rules of engagement

- Never modify unrelated registry entries while working on an IOP.
- Never invent field values: every field must trace to the C source.
- Prefer the extraction tool output as a draft, but always review arrays,
  enums, nested structs and `gboolean` vs `int` yourself.
- If the source is ambiguous (e.g. union fields, dynamic size), stop and
  ask the user instead of guessing — a wrong blob corrupts the style.
- The visual decision must be grounded in what you actually see in the
  images, not in what you expect the IOP to do.
