# dtstylekit Architecture

`dtstylekit` is an experimental pipeline that turns a photograph plus optional
reference photographs into a Darktable `.dtstyle` file.

The project deliberately avoids asking a VLM to invent binary blobs. The model
selects/composes from verified presets and proposes scalar adjustments. Python
owns validation, clamping, serialization, rendering, and export.

## High-Level Data Flow

```text
image + optional references
        -> analyzer
        -> preset index/search
        -> prompt/schema build
        -> VLM JSON
        -> validator + fidelity + safety bake
        -> .dtstyle + report
```

## CLI Entry Points

- `generate` / `analyze`: full style generation path.
- `apply`: render/export style to images with per-image exposure normalization.
- `preset index` / `preset search`: preset library tooling.
- `vlm generate`: VLM/spec generation without final composer path.
- `curves list` / `curves info`: curve-template inspection.

## Package Boundaries

- `dtstylekit/codec/`: XMP/blob codec, verified IOP registry, serialization.
- `dtstylekit/presets/`: preset parsing, indexing, embeddings, and search.
- `dtstylekit/analyzer/`: image analysis: histogram, EXIF, luminance, saturation,
  scene classification, reference filtering, and reference signatures.
- `dtstylekit/vlm/`: prompt building, model client, response parsing, style
  contracts, validation, fidelity, orchestration, and refinement.
- `dtstylekit/composer/`: style assembly, reports, explanations, safety baking.
- `dtstylekit/render.py`: darktable rendering helpers, generated style path
  sanitization, and render metrics.
- `dtstylekit/export/`: apply-style export and exposure normalization.
- `dtstylekit/eval/`: look-fidelity scoring and safety predicates.

## Registry Contract

`dtstylekit/codec/registry_types.py` defines the frozen `IOPRegistry` entry
shape used by packers, serializers, prompts, and validators.

Current invariants enforced:

- non-empty `operation`
- unique declared `fields`
- `defaults` and `ranges` only refer to declared fields
- range tuples have two bounds
- positive byte sizes when present
- legacy blob metadata is complete when present
- curve IOPs carry a curve pack size

## VLM Style Contract

`dtstylekit/vlm/models.py` defines the strongly typed handoff from the model:

- `StyleSpec.plugins` contains only `Plugin` instances.
- `Plugin.operation` is non-empty.
- `Plugin.multi_priority` is non-negative.
- `Plugin.params` values are numeric or scalar strings such as curve-template
  names.
- `StyleSpec` preserves structural immutability for plugin tuples and selected
  preset tuples.

## Shared Visual Thresholds

Color metric helpers live in `dtstylekit/color.py` and are shared by render,
eval, analyzer, and prompt/fidelity paths:

- BT.709 luminance helper
- HSV saturation helper
- red-cast predicate
- crushed-shadow predicate
- blown-highlight predicate

Keeping these thresholds central prevents safety logic from drifting across
layers.

## Safety Model

The pipeline separates three concerns:

1. **Schema safety**: registry contracts, validation, clamping, and
   serialization invariants.
2. **Visual safety**: render metrics, red-cast/crush/blow-out predicates, and
   safety bake.
3. **Look fidelity**: optional reference-driven comparison against rendered
   output.

The style is expected to be conservative. Per-image normalization happens at
apply/export time; generated styles should not bake target-specific exposure
unless an explicit safety decision requires it.

## Testing Entrypoints

The current test suite covers:

- codec/blob round-trips and corrupt decompression behavior
- preset parsing/indexing/search
- registry contracts
- analyzer/reference filters
- VLM parsing, validation, fidelity, and contracts
- render helpers and safe style-name sanitization
- eval look metrics
- CLI parser and command dispatch paths

Tests use `python3 -m pytest -q -p no:cacheprovider`.
