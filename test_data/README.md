# dtstylekit Test Data & Test Runner

This directory hosts the end-to-end test runner for the dtstylekit style
generation pipeline. `test_outputs/` is gitignored (generated at runtime).

> **⚠️ No images are committed.** The test fixtures are real photographs and
> are **not redistributed** (photographers retain their copyright). Drop your
> **own** JPEG photos here to run the test suite — see "Adding your own test
> images" below.

## Directory Structure

```
dtstylekit/
├── test_data/          # YOUR OWN test images (not committed)
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

## Adding your own test images

Place your own JPEG photos in `test_data/` (or anywhere else). The runner
skips any test case whose image is missing, so a partial set works fine:

```bash
mkdir -p test_data
cp /path/to/my_own_photos/photo1.jpg test_data/
```

Test case names that match are:

| Image | Direction | Expected Modules |
|-------|-----------|------------------|
| thumb_A14I7406.jpg | dark moody cinematic architectural | sigmoid, exposure, colorbalancergb |
| thumb_AE7A8477.jpg | high contrast night photography cool tones moody | sigmoid, exposure, colorbalancergb |
| thumb_UPBUNDLE.jpg | landscape photography vibrant natural colors | sigmoid, colorbalancergb |
| thumb_AE7A8490-2.jpg | portrait warm golden hour skin tones | sigmoid, colorbalancergb |
| thumb_Oct1042.jpg | vintage film look faded muted colors | sigmoid, colorbalancergb, tonecurve |
| thumb_Photo202012.jpg | black and white high contrast fine art | sigmoid, exposure, colorbalancergb |

> Rename your photos to match (e.g. `thumb_UPBUNDLE.jpg`), or add new
> entries to `TEST_CASES` in `test_runner.py` for your own directions.

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
python3 test_runner.py            # uses test_data/
python3 test_runner.py --dir /path/to/my/own/photos
```

Cases whose images are missing are skipped (exit code 0 as long as no
run failed).

## Output

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
| `No test image directory found` | Add your own JPEGs to `test_data/` or pass `--dir` |
| `fts5: syntax error near ","` | Avoid commas in `--direction`; use space-separated words |
| `VLM call failed: Failed to load image` | Use JPEG images (not WebP); use absolute paths |
| `Empty style spec` | Retry — the orchestrator retries once at higher temperature automatically |
| `Timeout` | CPU inference takes 2-5 min per image; increase timeout if needed |

## Cleaning Up

```bash
# Remove all generated outputs
rm -rf test_outputs/
```