# dtstylekit — AI-Powered Darktable Style Generator

A Python CLI tool that uses Vision Language Models (VLM) via Ollama to analyze photographs, select and compose from 534 existing Darktable presets, apply safe scalar adjustments on verified IOP structs, and output valid `.dtstyle` files with explanatory markdown reports.

## Overview

This project pivots from "LLM generates binary blobs" to "VLM selects/composes verified presets + applies safe scalar adjustments." The 534 presets in `data/styles/` provide a validated library of Darktable styles. The VLM (default: `qwen3-vl:8b`, customizable via `--model`) sees the image, describes the aesthetic, selects relevant presets, and proposes parameter tweaks. The Python pipeline serializes the result using verified codec/struct layouts from Darktable source.

**Output:** Valid `.dtstyle` file + markdown report explaining the choices.

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
ollama pull qwen3-vl:8b
```

Verify it's working:

```bash
ollama run qwen3-vl:8b "Describe this image" --image /path/to/a/photo.jpg
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

### Usage

```bash
# Analyze an image and generate a style (uses default model: qwen3-vl:8b)
dtstylekit generate path/to/photo.jpg -o my_style.dtstyle

# Use a different VLM model
dtstylekit generate path/to/photo.jpg --model llama3.2-vision:11b -o my_style.dtstyle

# List available presets
dtstylekit presets list

# Search presets semantically
dtstylekit presets search "warm cinematic look"

# Generate a curve-based preset adjustment (e.g. tone curve, rgb curve, color zones)
dtstylekit curves --help
```

> **Model customization:** The `--model` flag accepts any vision model available in Ollama. The default is `qwen3-vl:8b` (good balance of quality and VRAM). Other good options: `llama3.2-vision:11b` (best for photos, ~8 GB VRAM), `gemma3:4b` (lightweight, ~4 GB), `llava:7b` (classic, ~6 GB).

### Development

```bash
# Run tests
pytest

# Type check
mypy dtstylekit

# Lint
ruff check .
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

The default VLM is `qwen3-vl:8b` (override with `--model`). Preset library,
`outputs/` (SQLite index + embeddings) and `generated_styles/` are resolved
relative to the project root via `dtstylekit/paths.py` and can be overridden
with the `DTSTYLEKIT_PRESETS_DIR` / `DTSTYLEKIT_OUTPUTS_DIR` environment
variables, so the CLI works from any working directory.

## Preset Library

The 534 presets in `data/styles/` cover camera-specific styles (Canon, Nikon, Sony, Fujifilm, etc.), film simulations, creative looks, and technical corrections. Each preset is a valid Darktable `.dtstyle` file with verified XMP structure.

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
- **Markdown report** — Explains preset selection, parameter choices, and expected visual effect

## License

MIT License — see LICENSE file for details.