# dtstylekit Test Outputs

**This directory is gitignored** — generated test outputs are not committed.

## Contents

Generated at runtime by `test_runner.py` or individual `dtstylekit generate` calls:

```
test_outputs/
├── single_test/           # Single test run output
│   ├── Moody_Palm.dtstyle
│   └── Moody_Palm.md
├── test_1_thumb_A14I7406/ # Test suite run #1
│   ├── Dark_Cinematic_Palm.dtstyle
│   └── Dark_Cinematic_Palm.md
├── test_2_thumb_AE7A8477/ # Test suite run #2
│   ├── Moody_Night_Photography.dtstyle
│   └── Moody_Night_Photography.md
├── ...
└── test_results.json      # Summary JSON from test_runner.py
```

## File Types

### `.dtstyle` — Importable Darktable Style
XML file compatible with Darktable's style system. Import via:
1. Darktable → Modules → Styles → Import
2. Select the `.dtstyle` file
3. Apply from Styles sidebar

### `.md` — Generation Report
Markdown report containing:
- Image analysis (luminance, histogram, scene tags, noise)
- Base presets used (if any)
- Module-by-module parameter tables
- VLM rationale with technical reasoning citing specific numbers
- Import instructions

### `test_results.json` — Test Suite Summary
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
  }
]
```

## Cleaning

```bash
# Remove all test outputs
rm -rf /home/juan/Repos/darktable/dtstylekit/test_outputs/*

# Or recreate the directory
rm -rf /home/juan/Repos/darktable/dtstylekit/test_outputs
mkdir /home/juan/Repos/darktable/dtstylekit/test_outputs
```