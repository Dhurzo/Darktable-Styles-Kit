# dtstylekit — AI-Powered Darktable Style Generator

## Overall Goal
Build a Python CLI tool `dtstylekit` that uses a Vision Language Model (VLM) via Ollama to analyze photographs, select and compose from 534 existing Darktable `.dtstyle` presets, apply scalar adjustments on verified IOP structs (filmicrgb, colorbalancergb, sigmoid, exposure, atrous), and output valid `.dtstyle` files with explanatory markdown reports.

## Executive Summary
This project pivots from "LLM generates binary blobs" to "VLM selects/composes verified presets + applies safe scalar adjustments." The 534 presets in `data/styles/` provide a validated library of Darktable styles. The VLM (e.g., Llava, Gemma 3 4B vision) sees the image, describes the aesthetic, selects relevant presets, and proposes parameter tweaks. The Python pipeline serializes the result using verified codec/struct layouts from Darktable source (`format_analysis.md`, `blob_size_calibration.md`, `iop_modules_catalog.md`). Output: valid `.dtstyle` + markdown report. 6 phases, ~2-3 weeks.

## Project Snapshot
> See `plan.md` → `## Project Snapshot`

**Runtime**: Python 3.11+  
**Language**: Python (type-hinted, dataclasses, pathlib)  
**VLM Runtime**: Ollama (local) — default `qwen3-vl:8b`; also `llava:7b`, `gemma3:4b`, `llama3.2-vision:11b` (override with `--model`)  
**Database**: SQLite (preset index + semantic embeddings)  
**Key Libraries**: Pillow, numpy, exifread, ollama (Python client), sqlite3, xml.etree, struct, zlib, base64, sentence-transformers (for embeddings)  
**Folder Structure**:  
- `dtstylekit/` — package root  
- `dtstylekit/codec/` — XMP codec, blendop, IOP registry  
- `dtstylekit/presets/` — preset parser, indexer, semantic search  
- `dtstylekit/analyzer/` — image analysis (histogram, EXIF, scene detection)  
- `dtstylekit/vlm/` — prompt builder, VLM client, response parser  
- `dtstylekit/composer/` — style composer, serializer, report generator  
- `dtstylekit/curves/` — curve templates + pack/unpack for curve-based IOPs (added post-plan)  
- `dtstylekit/paths.py` — portable project-root path resolution (added post-plan)  
- `dtstylekit/cli.py` — entry point (generate/analyze, preset, vlm, curves subcommands)  
- `tests/` — round-trip tests with real darktable  
- `data/presets/` — symlink to `../../data/styles/` (534 .dtstyle files) 

**Conventions**:  
- Type hints everywhere, `dataclass` for data structures  
- `struct.pack` format strings per IOP (little-endian `<`)  
- Default blendop blob stored as constant (420 bytes, verified)  
- JSON schema for VLM output validation  
- Embeddings: `sentence-transformers/all-MiniLM-L6-v2` (384-dim) for semantic search  

## Phases

| # | Name | Type | State | Key Outputs | Key Decisions | File | Result |
|---|------|------|-------|-------------|---------------|------|--------|
| 1 | Project Bootstrap & Preset Symlink | Backend/Logic | REVIEWED | pyproject.toml, dtstylekit/__init__.py, .gitignore, README.md, tests/conftest.py | Package structure; Dependency versions; Symlink strategy; Type checking; Test fixtures | phases/phase-1.md | 🟡 APPROVED WITH OBSERVATIONS |
| 2 | Preset Library — Parse, Index, Embed | Backend/Logic | COMPLETED | parser.py, indexer.py, embedder.py, search.py, presets.db, preset_embeddings.npy | DB id vs. embedding row offset fix; PresetSearcher str/Path fix; Keyword search scoring | phases/phase-2.md | — |
| 3 | Codec & Registry — xmp_codec, blendop, iop_registry | Backend/Logic | COMPLETED | xmp_codec.py, blendop.py, iop_registry.py, serializer.py | verified struct layouts for 5 IOPs + simple IOPs | phases/phase-3.md | ✅ |
| 4 | Image Analyzer — Histogram, EXIF, Scene Detection | Backend/Logic | COMPLETED | analyzer/ (histogram, exif, luminance, noise, scene, pipeline) | analysis feeds VLM + composer | phases/phase-4.md | ✅ |
| 5 | VLM Integration — Prompt, Query, Parse | Backend/Logic | COMPLETED | vlm/ (client, orchestrator, parser, prompt_builder, schema_renderer, validator) | JSON-schema validation of VLM output | phases/phase-5.md | ✅ |
| 6 | Composer & Orchestrator — style_composer, report, CLI, tests | Backend/Logic | COMPLETED | composer/ (generator, merger, report, roundtrip) + cli.py | end-to-end pipeline + round-trip validation | phases/phase-6.md | ✅ |
| 7 | Curves Module — curve templates + pack/unpack (post-plan) | Backend/Logic | COMPLETED | curves/ (templates, packing, cli) | tonecurve/rgbcurve/colorzones pack/unpack | — | ✅ |