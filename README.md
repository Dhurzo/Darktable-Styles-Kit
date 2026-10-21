<p align="center">
  <img src="assets/logo.svg" alt="dtstylekit logo" width="560">
</p>

# dtstylekit — AI-Powered Darktable Style Generator

## Overview

This project pivots from "LLM generates binary blobs" to "VLM selects/composes verified presets + applies safe scalar adjustments." The VLM (default: `gemma3:27b`, customizable via `--model`) sees the image, describes the aesthetic, selects relevant presets from the **official darktable style library** (indexed locally via `setup.sh` — not vendored in this repository), and proposes parameter tweaks. The Python pipeline serializes the result using verified codec/struct layouts from Darktable source.

**Output:** Valid `.dtstyle` file + markdown report explaining the choices.


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


## Quickstart

### Prerequisites

- Python 3.11+
- [Ollama](https://ollama.ai/) installed and running locally
- Darktable installed (for testing round-trips)

### Setting up Ollama

If you don't have Ollama yet, install it:

- **Linux:**
  ```bash
  curl -fsSL https://ollama.ai/install.sh | sh
  ```
- **macOS:** Download from [ollama.ai](https://ollama.ai/) or `brew install ollama`
- **Windows:** Download from [ollama.ai](https://ollama.ai/)

Start the Ollama service (it runs in the background):

```bash
ollama serve  # starts the server (usually auto-starts after install)
```

Pull the default vision model:

```bash
ollama pull gemma3:27b
```

Verify it's working:

```bash
ollama run gemma3:27b "Describe this image" --image /path/to/a/photo.jpg
```

> Other compatible models: `llama3.2-vision:11b` (best for photos, ~8 GB VRAM), `gemma3:4b` (lightweight, ~4 GB), `llava:7b` (classic, ~6 GB). Switch with `--model` when running dtstylekit.

### Installation

```bash
# From the dtstylekit project root
pip install -e .[dev]
```

> **Note:** `pip install -e .[dev]` registers the `dtstylekit` CLI command via the `[project.scripts]` entry point. If `dtstylekit` is not found after installing, make sure the virtual environment is activated:
> ```bash
> source .venv/bin/activate
> # or if you use a different venv path:
> source /path/to/venv/bin/activate
> ```

### Preset library setup

dtstylekit indexes the **534 official darktable styles** (the `.dtstyle`
files in `data/styles/` of the darktable source tree) to build its
semantic search index. Those styles are *not* vendored into this
repository — you need a darktable checkout (or any directory containing
`.dtstyle` files) on your machine.

**What is `data/presets`?** It is a *symlink* (created by `./setup.sh`)
that points at your darktable checkout's `data/styles` directory — the
official style library dtstylekit indexes for semantic search. It is a
machine-specific pointer, not a directory of files: the styles themselves
live in your darktable checkout, so the symlink is gitignored and never
committed. Filling it is the first step of the setup below; if you prefer
no symlink at all, use the `DTSTYLEKIT_PRESETS_DIR` option (Option C).

**Option A — automatic (recommended):**

```bash
./setup.sh
```

The script locates the preset library (via `DTSTYLEKIT_PRESETS_DIR`, or a
darktable checkout containing `data/styles`, or an interactive prompt),
creates/repairs the `data/presets` symlink, verifies the files are
reachable, and builds the search index. It is idempotent — safe to run
again any time.

**Option B — manual:**

```bash
# 1. Clone darktable (or point at an existing checkout)
git clone https://github.com/darktable-org/darktable /path/to/darktable

# 2. Symlink the official styles into the expected location
ln -s /path/to/darktable/data/styles data/presets

# 3. Build the search index
dtstylekit preset index
```

**Option C — no symlink at all:** keep the library anywhere and point the
tool at it with the `DTSTYLEKIT_PRESETS_DIR` environment variable (or
`dtstylekit preset index --preset-dir <dir>`):

```bash
export DTSTYLEKIT_PRESETS_DIR=/path/to/darktable/data/styles
```

> The `data/presets` symlink in this repository points at
> `../../data/styles`, which only resolves when dtstylekit lives *inside*
> a darktable checkout (the layout this project was developed in). Use
> `./setup.sh` or `DTSTYLEKIT_PRESETS_DIR` for any other layout.

### Usage

```bash
# Analyze an image and generate a style (uses default model: gemma3:27b)
dtstylekit generate path/to/photo.jpg -o my_style.dtstyle

# RAW input is supported: a JPEG preview is rendered automatically for the
# VLM, while the style is tested against the RAW itself
dtstylekit generate path/to/photo.ARW -o my_style.dtstyle

# Apply the style to a whole set: exposure is normalized per image to the
# references (or --target-luminance) and highlights are kept below --max-clip
dtstylekit apply my_style.dtstyle 'photos/*.ARW' \
    --references 'refs/*.jpeg' -o outputs/

# Use a different VLM model
dtstylekit generate path/to/photo.jpg --model llama3.2-vision:11b -o my_style.dtstyle

# List available presets
dtstylekit preset list

# Search presets semantically
dtstylekit preset search "warm cinematic look"

# Generate a curve-based preset adjustment (e.g. tone curve, rgb curve, color zones)
dtstylekit curves --help

# Generate with reference-look images + a Spanish explanation document
dtstylekit generate photo.jpg --references 'refs/*.jpg' --direction "cinematic warm portrait" --lang es

# Keep only references that share the same edit (default: auto, min 2).
# Use --reference-filter warn to inspect decisions without dropping anything.
dtstylekit generate photo.jpg --references 'refs/*.jpg' --reference-filter auto
```

Styles are exposure-neutral: `generate` saves the look, and `apply` computes
an exposure offset for each photo. This keeps a style generated from one
frame from blowing out brighter frames in the same set.

> **Model customization:** The `--model` flag accepts any vision model available in Ollama. The default is `gemma3:27b` (good balance of quality and VRAM). Other good options: `llama3.2-vision:11b` (best for photos, ~8 GB VRAM), `gemma3:4b` (lightweight, ~4 GB), `llava:7b` (classic, ~6 GB).

### Supported darktable version

The binary layouts (IOP struct versions, blendop version, `module` fields)
are tightly coupled to a specific darktable build. This checkout targets
the darktable master that contains `dtstylekit/` — if you update
darktable, re-run the test suite first:

```bash
pytest tests/test_version_drift.py tests/test_real_presets.py
```

`test_version_drift.py` parses `DT_MODULE_INTROSPECTION` from
`src/iop/*.c` of the enclosing checkout and fails when the registry drifts
from the C sources (silently dropped modules are the classic symptom).
`test_real_presets.py` re-verifies blob sizes against the official styles
in `data/styles/`.

### Visual smoke check

Structural validation (XMP, blob sizes) proves a style *imports*, not
that it *renders*. After generating a style, run:

```bash
python tools/visual_check.py --style generated_styles/my_style.dtstyle
```

It renders a deterministic synthetic image through `darktable-cli` with
and without the style and fails on near-black/near-white/flat outputs.
Requires `darktable-cli` on `PATH` (skipped automatically in tests when
absent).

### Development

```bash
# Run tests
pytest

# Lint (must stay clean — CI enforces it)
ruff check .

# Type check (best-effort — the codebase has pre-existing typing debt;
# do not expect a fully clean run yet)
mypy dtstylekit --follow-imports=skip --ignore-missing-imports
```

## Architecture

```
dtstylekit/
├── cli.py                 # CLI entry point (generate/analyze, preset, vlm, curves)
├── paths.py               # Portable project-root path resolution
├── codec/                 # XMP codec, blendop blob, IOP registry, XML serializer
├── presets/               # Preset parser, SQLite indexer, embeddings, semantic search
├── analyzer/              # Image analysis (histogram, EXIF, luminance, noise, scene)
├── vlm/                   # Prompt builder, VLM client, orchestrator, validator, parser
├── composer/              # Style generator, merger, report, round-trip validator
├── curves/                # Curve templates + pack/unpack for curve-based IOPs
└── data/presets/          # Symlink to 534 .dtstyle files (darktable style library)
```

The default VLM is `gemma3:27b` (override with `--model`). Preset library,
`outputs/` (SQLite index + embeddings) and `generated_styles/` are resolved
relative to the project root via `dtstylekit/paths.py` and can be overridden
with the `DTSTYLEKIT_PRESETS_DIR` / `DTSTYLEKIT_OUTPUTS_DIR` environment
variables, so the CLI works from any working directory.

## Preset Library

dtstylekit indexes the **534 official darktable styles** (camera-specific styles for Canon, Nikon, Sony, Fujifilm, etc., film simulations, creative looks, and technical corrections). The library is **not vendored in this repository**: `./setup.sh` locates your darktable checkout and builds the search index (see [Preset library setup](#preset-library-setup)). Each preset is a valid Darktable `.dtstyle` file with verified XMP structure.

## VLM Integration

The VLM analyzes the input image and:
1. Describes the aesthetic (lighting, mood, color palette)
2. Selects 1-3 relevant presets from the library
3. Proposes scalar parameter adjustments on verified IOPs:
   - `filmicrgb` (tone mapping)
   - `colorbalancergb` (color grading)
   - `sigmoid` (contrast)
   - `exposure` (brightness)
   - `atrous` (sharpening/denoising)

## Output

Each run produces:
- **`.dtstyle` file** — Ready to import into Darktable
- **Markdown report** — Explains preset selection, parameter choices, expected visual effect, and the reference consistency decision when references are used
- **`*_EXPLICACION.md` explanation document** — When `--references` are given, a natural-language narrative companion is auto-generated: it analyses the reference photographs (tonal key, contrast, saturation, white balance, per-zone hue grading) and explains in plain language how they are edited and why every module/parameter of the generated style was chosen. Language: `--lang es` (default) or `--lang en`.

## Example results (before → after)

Below is a real end-to-end run: a RAW file rendered through `darktable-cli`
**without** any style (left) vs. the same RAW rendered with a style generated
by `dtstylekit` from reference-look images via the VLM pipeline (right).

| Before — no style | After — `Night_Market_Moody` (generated from references) |
|---|---|
| ![Before: RAW with no style applied](assets/result_before.jpg) | ![After: RAW with dtstylekit-generated Night_Market_Moody style](assets/result_after.jpg) |

The generated style was produced with:

```bash
dtstylekit generate photo.jpg \
  --references 'refs/*.jpg' \
  --direction "night market moody" --lang es
```

The VLM selected presets from the indexed library, applied safe scalar
adjustments on verified IOP structs, and the composer serialized a valid
`.dtstyle` (here it swapped `filmicrgb` → `sigmoid` for the dark target to
avoid crushing shadows). The rendered look matches the references' tonal key
and color grading.

## Contributing / Release flow

This repository is the **release channel** for dtstylekit. Day-to-day
development happens in a private working copy that lives *inside* a
darktable checkout (that layout gives the dev tools direct access to the
darktable C sources for IOP-struct verification). Changes are synced here
as clean, reviewed commits — so:

- **Bug reports and feature requests**: open an [Issue](https://github.com/Dhurzo/Darktable-Styles-Kit/issues) — very welcome.
- **Small PRs** (typo fixes, docs) are fine too; larger changes are best
  discussed in an issue first, then integrated upstream and released here.
- CI runs the full test suite (with a sparse darktable checkout) on every
  push and PR, so the `main` branch is always usable standalone.

## License

MIT License — see LICENSE file for details.

## Acknowledgements & legal

- Built for and around [darktable](https://www.darktable.org/) — this
  project is **not affiliated with, endorsed by, or connected to** the
  darktable project or its maintainers. "darktable" is used
  descriptively to denote interoperability.
- The official darktable style library (534 `.dtstyle` files) is **not
  redistributed**: users link their own darktable checkout via
  `data/presets`. All credit for those styles belongs to the darktable
  contributors.
- No photographer photographs are included in this repository.
- Binary layouts (IOP struct versions, blendop format) were
  reverse-engineered from darktable's open source code solely for
  interoperability, under the terms of its GPLv3 license.
