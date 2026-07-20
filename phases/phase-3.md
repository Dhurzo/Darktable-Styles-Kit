# Phase 3: Codec & Registry — xmp_codec, blendop, iop_registry
**Type:** Backend/Logic

## Objective
Implement the binary codec (XMP encode/decode), default blendop handling, and IOP registry with verified struct layouts for the 5 key IOPs (filmicrgb, colorbalancergb, sigmoid, exposure, atrous) plus simple IOPs.

## Project Snapshot
> See `plan.md` → `## Project Snapshot`

## Required Context
- XMP codec algorithm per `format_analysis.md` §3: hex for ≤100 bytes, gz+factor+base64 for >100 bytes
- `encode_xmp(data: bytes) -> str` and `decode_xmp(s: str) -> bytes` per `format_analysis.md` §9 Python recipe
- Default blendop: 420 bytes, verified in `blob_size_calibration.md` §3
  - `DEFAULT_BLENDOP_DISPLAY = "gz08eJxjYGBgYAFiCQYYOOHEgAZY0QWAgBGLGANDgz0Ej1Q+dlAx68oBEMbFxwX+AwGIBgCbGCeh"` (blend_cst=4, blend_mode=24, opacity=100.0)
  - `DEFAULT_BLENDOP_SCENE = "gz10eJxjYGBgYAJiCQYYOOHEgAZY0QWAgBGLGANDgz0Ej1Q+dcF/IADRAG2yHQc="` (blend_cst=2)
  - Patch opacity at offset 16 (float32, percentage 0-100)
- IOP Registry: Verified struct sizes from `blob_size_calibration.md` §1:
  - `filmicrgb` v6: 116 bytes (18 floats + 11 ints/gbooleans)
  - `colorbalancergb` v5: 132 bytes (32 floats + 1 int)
  - `sigmoid` v3: 56 bytes (12 floats + 2 ints)
  - `exposure` v6: 24 bytes (mode, black, exposure, deflicker_pct, deflicker_target, compensate_bias)
  - `atrous` v2: 248 bytes (octaves + x[6][6] + y[6][6] + mix)
- Simple IOPs (Tier 1 from `iop_modules_catalog.md`): vibrance, velvia, grain, colorcontrast, splittoning, bloom, soften, vignette, colorbalance, shadhi, colorize, monochrome, colisa, lowpass, highpass, sharpen, levels — pack formats defined but sizes need verification
- `struct.pack` format strings use little-endian `<` (Darktable is little-endian)

## Related Files (for context)
- `../glm5Generated/format_analysis.md`: §3 (codec), §4 (blendop), §5 (op_params), §9 (Python recipes), §10 (generate_dtstyle)
- `../glm5Generated/blob_size_calibration.md`: §1 (verified sizes), §3 (blendop structure), §4 (implementation consequences)
- `../glm5Generated/iop_modules_catalog.md`: All 27 IOPs with pack formats, fields, ranges, defaults
- `../src/common/exif.cc:3092-3274`: Canonical `dt_exif_xmp_encode/decode` C++ implementation
- `../src/develop/blend.h:180-222`: `dt_develop_blend_params_t` struct definition
- `../src/iop/filmicrgb.c`, `../src/iop/colorbalancergb.c`, `../src/iop/sigmoid.c`, `../src/iop/exposure.c`, `../src/iop/atrous.c`: Struct definitions for verified IOPs

## Inputs
- None (pure library code)

## Tasks
- [ ] Create `dtstylekit/codec/xmp_codec.py`:
  - `encode_xmp(data: bytes, compress_threshold: int = 100) -> str`
  - `decode_xmp(s: str) -> bytes`
  - Unit tests: round-trip hex, round-trip gz+base64, edge cases (empty, exactly 100 bytes)
- [ ] Create `dtstylekit/codec/blendop.py`:
  - Constants: `DEFAULT_BLENDOP_DISPLAY`, `DEFAULT_BLENDOP_SCENE` (strings from calibration)
  - `patch_opacity(encoded: str, opacity_pct: float) -> str` — decodes, patches offset 16, re-encodes
  - `patch_blend_mode(encoded: str, mode: int) -> str` — patches offset 8 (uint32)
  - `patch_blend_cst(encoded: str, cst: int) -> str` — patches offset 4 (int32)
  - `create_blendop(opacity: float = 100.0, mode: int = 24, cst: int = 4) -> str` — builds from template
- [ ] Create `dtstylekit/codec/iop_registry.py`:
  - `IOPRegistry` dataclass with: `operation`, `version`, `pack_format`, `fields`, `defaults`, `ranges`, `size_bytes`, `blendop_cst` (2=scene, 4=display)
  - Pre-populated `IOP_REGISTRY: dict[str, IOPRegistry]` with 5 verified IOPs + simple IOPs (use pack formats from catalog, sizes as `None` for unverified)
  - `get_registry(op: str) -> IOPRegistry | None`
  - `pack_params(op: str, params: dict) -> bytes` — merges defaults, validates ranges, `struct.pack`
  - `unpack_params(op: str, blob: bytes) -> dict` — `struct.unpack` → dict with field names
  - `verify_size(op: str, blob: bytes) -> bool` — compares `len(blob)` to expected size
- [ ] Create `dtstylekit/codec/serializer.py`:
  - `encode_plugin(plugin_dict: dict) -> dict` — takes `{operation, enabled, multi_name, params, blendop_override?}` returns XML-ready dict with `op_params_encoded`, `blendop_encoded`
  - `build_dtstyle_xml(name: str, description: str, plugins: list[dict], iop_list: str | None = None) -> str`
- [ ] Write tests: codec round-trip, blendop patching, registry pack/unpack for verified IOPs, XML generation

## Expected Outputs
- `dtstylekit/codec/xmp_codec.py`: XMP encode/decode with tests
- `dtstylekit/codec/blendop.py`: Blendop template + patching functions
- `dtstylekit/codec/iop_registry.py`: Registry with 5 verified + ~18 simple IOPs, pack/unpack/verify
- `dtstylekit/codec/serializer.py`: Plugin encoding + XML builder
- `dtstylekit/codec/__init__.py`: Exports all public APIs
- `tests/test_codec.py`: Round-trip tests for all codec functions
- `tests/test_registry.py`: Pack/unpack/verify for each registered IOP

## Dependencies
- Phase 1 (package structure)

## Completion Criteria
- [ ] `encode_xmp(decode_xmp(s)) == s` for both hex and gz formats (test vectors from calibration)
- [ ] `patch_opacity(DEFAULT_BLENDOP_DISPLAY, 50.0)` produces blob with opacity=50.0 at offset 16
- [ ] `pack_params("filmicrgb", {"contrast": 1.5, "latitude": 25.0})` → 116-byte blob
- [ ] `unpack_params("filmicrgb", pack_params(...))` recovers input values (within float precision)
- [ ] `build_dtstyle_xml(...)` produces valid XML matching `format_analysis.md` §2 structure
- [ ] All tests pass: `pytest tests/test_codec.py tests/test_registry.py -v`