# Phase 1: Project Bootstrap & Preset Symlink
**Type:** Backend/Logic

## Objective
Scaffold the `dtstylekit` Python package structure, install dependencies, create symlink to the 534 Darktable presets in `data/styles/`, and establish the project foundation.

## Project Snapshot
> See `plan.md` → `## Project Snapshot`

## Required Context
- The 534 `.dtstyle` presets exist at `/home/juan/Repos/darktable/data/styles/` (relative: `../../data/styles/` from dtstylekit root)
- Darktable source files for reference are in `../src/`, `../data/styles/`
- Research artifacts in `../glm5Generated/` provide all format specs, struct layouts, and codec algorithms
- This is a greenfield Python project — no existing Python files in `dtstylekit/`

## Related Files (for context)
- `../../data/styles/`: 534 `.dtstyle` files to symlink (source of truth for preset library)
- `../glm5Generated/format_analysis.md`: `.dtstyle` XML structure, XMP codec algorithm
- `../glm5Generated/iop_modules_catalog.md`: 27 IOPs with struct layouts, pack formats, ranges
- `../glm5Generated/blob_size_calibration.md`: Verified blob sizes, default blendop (420 bytes)
- `../glm5Generated/darktable_source_map.md`: Key Darktable source files for reference
- `../src/common/exif.cc:3092-3274`: Canonical `dt_exif_xmp_encode/decode` implementation
- `../src/develop/blend.h:180-222`: `dt_develop_blend_params_t` struct definition

## Inputs
- None (first phase)

## Tasks
- [ ] Create Python package structure: `dtstylekit/`, `dtstylekit/codec/`, `dtstylekit/presets/`, `dtstylekit/analyzer/`, `dtstylekit/vlm/`, `dtstylekit/composer/`, `tests/`
- [ ] Create `pyproject.toml` with dependencies: `pillow`, `numpy`, `exifread`, `ollama`, `sentence-transformers`, `pytest`, `ruff`, `mypy`
- [ ] Create `dtstylekit/__init__.py` with version and exports
- [ ] Create symlink `dtstylekit/data/presets` → `../../data/styles` (534 presets)
- [ ] Create `.gitignore` for Python (`__pycache__`, `.pytest_cache`, `*.pyc`, `.mypy_cache`, `dist/`, `build/`, `.env`)
- [ ] Create `README.md` with project overview and quickstart
- [ ] Create `tests/__init__.py` and `tests/conftest.py` for pytest fixtures
- [ ] Verify symlink works: list 534 `.dtstyle` files from Python

## Expected Outputs
- `dtstylekit/__init__.py`: Package init with `__version__ = "0.1.0"`
- `dtstylekit/codec/__init__.py`, `dtstylekit/presets/__init__.py`, `dtstylekit/analyzer/__init__.py`, `dtstylekit/vlm/__init__.py`, `dtstylekit/composer/__init__.py`
- `pyproject.toml`: Project config with dependencies and tool config (ruff, mypy, pytest)
- `dtstylekit/data/presets/`: Symlink to `../../data/styles/` (534 `.dtstyle` files accessible)
- `.gitignore`: Standard Python ignores
- `README.md`: Project documentation
- `tests/conftest.py`: Pytest fixtures (sample image paths, preset loader)

## Dependencies
None

## Completion Criteria
- [ ] `pip install -e .` succeeds without errors
- [ ] `python -c "from dtstylekit.data import presets; print(len(list(presets.glob('*.dtstyle'))))"` prints `534`
- [ ] `ruff check .` and `mypy dtstylekit` pass (no code yet, but config valid)
- [ ] Symlink is relative and works from any CWD