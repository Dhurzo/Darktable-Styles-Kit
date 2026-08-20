# dtstylekit Test Data & Test Runner

This directory contains test images and automated tests for the dtstylekit style generation pipeline.
**The thumbnail images are committed** as fixtures for `test_runner.py`; `test_outputs/` is gitignored (generated at runtime).

## Directory Structure

```
dtstylekit/
├── test_data/          # Input test images (committed fixtures)
│   ├── thumb_A14I7406.jpg
│   ├── thumb_AE7A8477.jpg
│   ├── thumb_AE7A8490-2.jpg
│   ├── thumb_Oct1042.jpg
│   ├── thumb_Photo202012.jpg
│   └── thumb_UPBUNDLE.jpg
├── test_outputs/       # Generated styles & reports (gitignored, created at runtime)
│   ├── test_1_.../
│   ├── test_2_.../
│   └── test_results.json
├── test_runner.py      # Automated test script
└── README.md           # This file
```

## Prerequisites

1. **Ollama running** with `gemma3:12b` model:
   ```bash
   ollama pull gemma3:12b
   ollama serve
   ```

2. **dtstylekit installed** in development mode:
   ```bash
   cd <DTSTYLEKIT_ROOT>
   pip install -e .
   ```

3. **Preset index built** (one-time):
   ```bash
   dtstylekit preset index
   ```

## Quick Start: Single Test

Run generation on one image (~2-3 minutes on CPU):

```bash
cd <DTSTYLEKIT_ROOT>

# Dark moody cinematic (Palander-style)
python3 -m dtstylekit.cli generate test_data/thumb_A14I7406.jpg \
  --direction "dark moody cinematic architectural" \
  --model gemma3:12b \
  --output test_outputs/single_test

# Bright vibrant landscape
python3 -m dtstylekit.cli generate test_data/thumb_UPBUNDLE.jpg \
  --direction "landscape photography vibrant natural colors" \
  --model gemma3:12b \
  --output test_outputs/landscape_test
```

**Output:**
- `test_outputs/<name>/<Style_Name>.dtstyle` — importable Darktable style
- `test_outputs/<name>/<Style_Name>.md` — detailed report with analysis, module settings, rationale

## Full Test Suite

Run all 6 test cases (~15-20 minutes on CPU):

```bash
cd <DTSTYLEKIT_ROOT>
python3 test_runner.py
```

### Test Cases

| # | Image | Direction | Expected Modules |
|---|-------|-----------|------------------|
| 1 | thumb_A14I7406.jpg | dark moody cinematic architectural | sigmoid, exposure, colorbalancergb |
| 2 | thumb_AE7A8477.jpg | high contrast night photography cool tones moody | sigmoid, exposure, colorbalancergb |
| 3 | thumb_UPBUNDLE.jpg | landscape photography vibrant natural colors | sigmoid, colorbalancergb |
| 4 | thumb_AE7A8490-2.jpg | portrait warm golden hour skin tones | sigmoid, colorbalancergb |
| 5 | thumb_Oct1042.jpg | vintage film look faded muted colors | sigmoid, colorbalancergb, tonecurve |
| 6 | thumb_Photo202012.jpg | black and white high contrast fine art | sigmoid, exposure, colorbalancergb |

### Output

Generates `test_outputs/test_results.json`:
```json
[
  {
    "test": 1,
    "image": "thumb_A14I7406.jpg",
    "direction": "dark moody cinematic architectural",
    "success": true,
    "modules_ok": true,
    "issues": [],
    "dtstyle": "test_outputs/test_1_thumb_A14I7406/Dark_Cinematic_Palm.dtstyle"
  },
  ...
]
```

## Interpreting Results

- **success: true** — VLM returned valid style spec, .dtstyle generated
- **modules_ok: true** — All expected modules present in generated style
- **issues** — Any missing/unexpected modules or warnings

## Common Issues

| Issue | Fix |
|-------|-----|
| `fts5: syntax error near ","` | Avoid commas in `--direction`; use space-separated words |
| `VLM call failed: Failed to load image` | Use JPEG thumbnails (not WebP); thumbnails in test_data/ are JPEG |
| `Empty style spec` | Retry — the orchestrator retries once at higher temperature automatically |
| `Timeout` | CPU inference takes 2-5 min per image; increase timeout if needed |

## Adding New Test Images

1. Place JPEG images in `test_data/`
2. Add a test case to `TEST_CASES` in `test_runner.py`
3. Run the test suite

## Cleaning Up

```bash
# Remove all generated outputs
rm -rf test_outputs/

# Recreate fresh
mkdir test_outputs
```
