# Troubleshooting Guide

## Installation Issues

### `dtstylekit: command not found`

**Cause**: Virtual environment not activated or package not installed.

```bash
# Fix
source .venv/bin/activate
pip install -e .[dev]
```

### `externally-managed-environment` error

**Cause**: System Python blocks pip install.

```bash
# Fix - use virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

### `ollama: connection refused`

**Cause**: Ollama service not running.

```bash
# Fix
ollama serve &  # Run in background

# Verify
ollama list
curl http://localhost:11434/api/tags
```

### `No .dtstyle files found` / `Found 0 preset(s)`

**Cause**: Preset library not linked.

```bash
# Fix - automatic
./setup.sh

# Fix - manual
export DTSTYLEKIT_PRESETS_DIR=/path/to/darktable/data/styles
dtstylekit preset index --force
```

### Python version mismatch

**Cause**: dtstylekit requires Python 3.11+.

```bash
# Check
python3 --version

# Fix - install Python 3.11+
# Ubuntu/Debian: sudo apt install python3.11 python3.11-venv
# Fedora: sudo dnf install python3.11
# macOS: brew install python@3.11
```

---

## Runtime Issues

### `VLM call failed: Failed to load image`

**Cause**: Image format not supported or path issues.

```bash
# Fix - use JPEG
magick photo.webp photo.jpg
magick photo.heic photo.jpg

# Fix - use absolute path
dtstylekit generate /full/path/to/photo.jpg ...

# Fix - check file exists
ls -la photo.jpg
```

### `VLM call failed: timeout` / Generation takes too long

**Cause**: Model too large for hardware.

```bash
# Fix - use smaller model
dtstylekit generate photo.jpg --model gemma3:4b -o style.dtstyle

# Fix - reduce temperature for faster convergence
dtstylekit generate photo.jpg --temperature 0.2 -o style.dtstyle

# Fix - disable iterative refinement
dtstylekit generate photo.jpg --refine-iterations 0 -o style.dtstyle
```

### `VLM call failed: CUDA out of memory` / GPU OOM

**Cause**: Model exceeds VRAM.

```bash
# Fix - use CPU-only model
dtstylekit generate photo.jpg --model gemma3:4b -o style.dtstyle

# Fix - reduce batch/parallelism
export OLLAMA_NUM_PARALLEL=1
```

### `darktable-cli not found` / Iterative refinement fails

**Cause**: Darktable CLI not in PATH.

```bash
# Fix - install Darktable with CLI
# Ubuntu: sudo apt install darktable
# Fedora: sudo dnf install darktable
# macOS: brew install darktable

# Verify
darktable-cli --version

# Fix - specify path
dtstylekit generate photo.jpg --refine-raw photo.ARW --darktable-cli /usr/bin/darktable-cli
```

### Generated style fails to import in Darktable

**Cause**: Version mismatch between dtstylekit and Darktable.

```bash
# Fix - regenerate with matching versions
# 1. Check Darktable version
darktable --version

# 2. Rebuild dtstylekit against same DT source
cd /path/to/darktable
./build.sh --prefix /opt/darktable --build-type Release

# 3. Regenerate style
dtstylekit generate photo.jpg -o style.dtstyle
```

### Style looks wrong / nothing like reference

**Cause**: VLM misinterpreted direction or references.

```bash
# Fix - be more specific in direction
dtstylekit generate photo.jpg \
  --direction "warm cinematic portrait, teal shadows, golden highlights, film grain" \
  --references "refs/*.jpg" \
  -o style.dtstyle

# Fix - add more reference images (3-5)
dtstylekit generate photo.jpg --references "ref1.jpg ref2.jpg ref3.jpg" ...

# Fix - use iterative refinement
dtstylekit generate photo.jpg --refine-iterations 3 --refine-raw photo.ARW ...

# Fix - check explanation document
cat generated_styles/style_EXPLICACION.md
```

### Preset search returns wrong/camera profiles

**Cause**: Semantic search matched camera baseline profiles.

```bash
# Fix - rebuild index
dtstylekit preset index --force

# Fix - use more specific search
dtstylekit preset search "warm cinematic portrait" --limit 5

# Fix - check preset library has 534 styles
dtstylekit preset list | wc -l  # should be 534
```

---

## Reference Image Issues

### References not analyzed / empty analysis

**Cause**: References not in supported format.

```bash
# Fix - convert to JPEG
for f in refs/*; do magick "$f" "${f%.*}.jpg"; done

# Fix - check file permissions
chmod 644 refs/*.jpg

# Fix - verify Ollama can read images
ollama run gemma3:27b "Describe this image" --image refs/ref1.jpg
```

### Reference analysis shows "neutral" for all zones

**Cause**: References lack strong color grading.

```bash
# Fix - use references with strong grading
# Fix - increase reference count (3-5 images)
# Fix - check reference quality (not thumbnails)
```

---

## Output Issues

### No output files generated

**Cause**: Output directory permissions or path issues.

```bash
# Fix - check output directory
ls -la outputs/

# Fix - specify output explicitly
dtstylekit generate photo.jpg -o /full/path/to/style.dtstyle

# Fix - check disk space
df -h .
```

### Explanation document not generated

**Cause**: `--references` not provided (required for explanation).

```bash
# Fix - add references
dtstylekit generate photo.jpg --references "refs/*.jpg" ...

# Fix - check language
dtstylekit generate photo.jpg --references "refs/*.jpg" --lang en -o style.dtstyle
```

---

## Performance Issues

### Slow preset indexing

**Cause**: Large preset library or slow disk.

```bash
# Expected: 1-3 minutes for 534 presets
# Fix - use SSD for outputs directory
export DTSTYLEKIT_OUTPUTS_DIR=/fast/ssd/outputs

# Fix - skip embedding generation (not recommended)
# No current option, but can use smaller embedding model
```

### Slow VLM inference

**Cause**: Large model, CPU-only, or high temperature.

```bash
# Fix - use GPU-accelerated Ollama
# NVIDIA: ollama run gemma3:27b (auto-detects CUDA)
# AMD: ollama run gemma3:27b (ROCM)
# Apple Silicon: ollama run gemma3:27b (CoreML)

# Fix - reduce temperature
dtstylekit generate photo.jpg --temperature 0.2 ...

# Fix - use smaller model
dtstylekit generate photo.jpg --model gemma3:4b ...
```

---

## Advanced Debugging

### Enable debug logging

```bash
# Verbose output
dtstylekit generate photo.jpg -v

# Debug specific modules
DTSTYLEKIT_DEBUG=1 dtstylekit generate photo.jpg
```

### Inspect VLM prompt/response

```bash
# Generate spec without assembly
dtstylekit vlm generate photo.jpg --direction "warm" --output /tmp/spec.json
cat /tmp/spec.json | jq .
```

### Test preset search

```bash
# Search with debug
dtstylekit preset search "warm cinematic" --limit 10

# Check index stats
sqlite3 outputs/presets.db "SELECT COUNT(*) FROM presets;"
```

### Test round-trip validation

```bash
# Validate generated style
dtstylekit curves info --verify generated_styles/style.dtstyle

# Full round-trip
python -m dtstylekit.tools.visual_check --style generated_styles/style.dtstyle
```

### Check Darktable compatibility

```bash
# Verify DT version
darktable --version

# Check module versions
darktable -d iop 2>&1 | grep -E "version|module"
```

---

## Getting Help

### Before Reporting

1. Run with `-v` flag and capture output
2. Note Python version: `python3 --version`
3. Note Darktable version: `darktable --version`
4. Note Ollama model: `ollama list`
5. Include relevant log/error output

### Where to Report

- **GitHub Issues**: Bugs and feature requests
- **GitHub Discussions**: Usage questions
- **Matrix**: `#dtstylekit:matrix.org` (real-time)

### Useful Debug Commands

```bash
# Full environment info
dtstylekit generate photo.jpg -v 2>&1 | head -50

# Check all dependencies
pip list | grep -E "ollama|sentence|numpy|pillow|exifread"

# Verify preset library
dtstylekit preset list | head -20
dtstylekit preset search "test" --limit 5
```
