# dtstylekit — AI-Powered Darktable Style Generator

> ## ⚠️ DISCLAIMERS
>
> ### 1. Experimental project
>
> **This project is TOTALLY EXPERIMENTAL.** It is built on a strong *vibe-coding* foundation: the code and binary formats have been reverse-engineered, verified, and adjusted iteratively against the darktable source code. It can **fail when creating styles**, produce unexpected results, or generate `.dtstyle` files that do not behave as expected. Use it with caution, always review the visual result, and back up your edits. Do not use it in professional workflows without validating each generated style first.
>
> ### 2. Ethical notice about photographers' styles
>
> **THIS SOFTWARE IS NOT MEANT TO COPY PHOTOGRAPHERS' STYLES. IT IS FOCUSED ON LEARNING HOW THOSE PHOTOGRAPHERS EDIT AT A TECHNICAL LEVEL. IF YOU LIKE THEM, BUY THEIR PRESETS OR THEIR PHOTOGRAPHS.**
>
> Reference photographs are used solely for educational and technical purposes: understanding which editing decisions (exposure, contrast, per-zone tonal color grading, saturation…) produce a given look. The goal is for you to learn how to edit, not to replicate anyone's commercial work.
>
> ### 3. Commitment to free software
>
> **EMPHASIS: THIS SOFTWARE WAS MADE FOR DARKTABLE, TO CONTRIBUTE TO FREE SOFTWARE AND SO THAT EVERYONE CAN EDIT THEIR RAWS FOR "FREE" AND IN AN OPEN WAY.**
>
> dtstylekit exists for the darktable community: democratizing RAW photography editing, teaching color-grading techniques, and letting anyone — without paying for licenses or commercial presets — understand and apply the techniques of great photographers. If you truly like a look, support its author by buying their work.

## Overall Goal
Build a Python CLI tool `dtstylekit` that uses a Vision Language Model (VLM) via Ollama to analyze photographs, select and compose from 534 existing Darktable `.dtstyle` presets, apply scalar adjustments on verified IOP structs (filmicrgb, colorbalancergb, sigmoid, exposure, atrous), and output valid `.dtstyle` files with explanatory markdown reports.

## Executive Summary
This project pivots from "LLM generates binary blobs" to "VLM selects/composes verified presets + applies safe scalar adjustments." The 534 presets in `data/styles/` provide a validated library of Darktable styles. The VLM (e.g., Llava, Gemma 3 4B vision) sees the image, describes the aesthetic, selects relevant presets, and proposes parameter tweaks. The Python pipeline serializes the result using verified codec/struct layouts from Darktable source (`format_analysis.md`, `blob_size_calibration.md`, `iop_modules_catalog.md`). Output: valid `.dtstyle` + markdown report. 6 phases, ~2-3 weeks.

## Project Snapshot
> See `plan.md` → `## Project Snapshot`

**Runtime**: Python 3.11+
**Language**: Python (type-hinted, dataclasses, pathlib)
**VLM Runtime**: Ollama (local) — default `gemma3:27b`; also `llava:7b`, `gemma3:4b`, `llama3.2-vision:11b` (override with `--model`)
**Database**: SQLite (preset index + semantic embeddings)
**Key Libraries**: Pillow, numpy, exifread, ollama (Python client), sqlite3, xml.etree, struct, zlib, base64, sentence-transformers (for embeddings)
**Architecture**: see `docs/architecture.md`

**Folder Structure**:
- `dtstylekit/` — package root
- `dtstylekit/codec/` — XMP codec, blendop, split IOP registry (types/verified/simple/refinement/curves)
- `dtstylekit/presets/` — preset parser, indexer, semantic search
- `dtstylekit/analyzer/` — image analysis (histogram, EXIF, scene detection)
- `dtstylekit/vlm/` — prompt builder, VLM client, response parser
- `dtstylekit/composer/` — style composer, serializer, report generator
- `dtstylekit/curves/` — curve templates + pack/unpack for curve-based IOPs (added post-plan)
- `dtstylekit/paths.py` — portable project-root path resolution (added post-plan)
- `dtstylekit/cli.py` — entry point (generate/analyze, preset, vlm, curves subcommands)
- `docs/architecture.md` — current architecture notes
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
| 1 | Project Bootstrap & Preset Symlink | Backend/Logic | REVIEWED | pyproject.toml, dtstylekit/__init__.py, .gitignore, README.md, tests/conftest.py | Package structure; Dependency versions; Symlink strategy; Type checking; Test fixtures | — | 🟡 APPROVED WITH OBSERVATIONS |
| 2 | Preset Library — Parse, Index, Embed | Backend/Logic | COMPLETED | parser.py, indexer.py, embedder.py, search.py, presets.db, preset_embeddings.npy | DB id vs. embedding row offset fix; PresetSearcher str/Path fix; Keyword search scoring | — | — |
| 3 | Codec & Registry — xmp_codec, blendop, iop_registry | Backend/Logic | COMPLETED | xmp_codec.py, blendop.py, iop_registry.py, serializer.py | verified struct layouts for 5 IOPs + simple IOPs | — | ✅ |
| 4 | Image Analyzer — Histogram, EXIF, Scene Detection | Backend/Logic | COMPLETED | analyzer/ (histogram, exif, luminance, noise, scene, pipeline) | analysis feeds VLM + composer | — | ✅ |
| 5 | VLM Integration — Prompt, Query, Parse | Backend/Logic | COMPLETED | vlm/ (client, orchestrator, parser, prompt_builder, schema_renderer, validator) | JSON-schema validation of VLM output | — | ✅ |
| 6 | Composer & Orchestrator — style_composer, report, CLI, tests | Backend/Logic | COMPLETED | composer/ (generator, merger, report, roundtrip) + cli.py | end-to-end pipeline + round-trip validation | — | ✅ |
| 7 | Curves Module — curve templates + pack/unpack (post-plan) | Backend/Logic | COMPLETED | curves/ (templates, packing, cli) | tonecurve/rgbcurve/colorzones pack/unpack | — | ✅ |
| 8 | Reference-Photo Analysis & Narrative Explanation Docs | Backend/Logic | COMPLETED | analyzer/pipeline.py (per-zone hues + bimodal detection), composer/explanation.py, cli.py `--lang` | natural-language `*_EXPLICACION.md` documents (es/en) auto-generated from the references; `--lang es` by default | — | ✅ |
| 9 | Reference Saturation Fix (global HSV) | Backend/Logic | COMPLETED | orchestrator.py `global_saturation`, prompt_builder.py HSV block, validator.py Hito 2.4 guard, tests | low-key references are no longer perceived as desaturated; the validator clamps `filmicrgb.saturation<0` to 0 when references are colorful (≥0.25 HSV) | — | ✅ |
