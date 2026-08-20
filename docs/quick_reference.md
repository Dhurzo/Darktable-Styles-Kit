# Quick Reference Card

## Common Commands

```bash
# Generate style from single image
dtstylekit generate photo.jpg -o style.dtstyle

# Generate with reference images
dtstylekit generate photo.jpg \
  --references "refs/*.jpg" \
  --direction "warm cinematic" \
  -o style.dtstyle

# Generate with Spanish explanation (default)
dtstylekit generate photo.jpg --lang es -o style.dtstyle

# Generate with English explanation
dtstylekit generate photo.jpg --lang en -o style.dtstyle

# Iterative refinement
dtstylekit generate photo.jpg \
  --refine-iterations 3 \
  --refine-raw photo.ARW \
  -o refined.dtstyle

# List curve templates
dtstylekit curves list
dtstylekit curves list --category filmic
dtstylekit curves info s_strong

# Search presets
dtstylekit preset search "warm cinematic"
dtstylekit preset list

# Rebuild preset index
dtstylekit preset index --force
```

## VLM Models

| Model | Command | VRAM |
|-------|---------|------|
| Gemma 3 27B (default) | `dtstylekit generate photo.jpg` | 16 GB |
| Llama 3.2 Vision 11B | `--model llama3.2-vision:11b` | 8 GB |
| Gemma 3 4B | `--model gemma3:4b` | 4 GB |
| LLaVA 7B | `--model llava:7b` | 6 GB |

## Direction Keywords

### Tonal
- `low_key`, `high_key`, `dark`, `bright`, `moody`, `airy`

### Contrast
- `high contrast`, `low contrast`, `crushed blacks`, `lifted shadows`

### Color
- `warm`, `cool`, `teal & orange`, `golden hour`, `blue hour`
- `sepia`, `cross-process`, `bleach bypass`, `vintage`

### Filmic
- `cinematic`, `film look`, `kodak portra`, `fuji velvia`
- `matte film`, `grainy`, `soft highlights`

## Environment Variables

```bash
# Force preset library path
export DTSTYLEKIT_PRESETS_DIR=/path/to/darktable/data/styles

# Custom output directory
export DTSTYLEKIT_OUTPUTS_DIR=/path/to/outputs

# Remote Ollama
export OLLAMA_HOST=http://192.168.1.50:11434

# Default model
export DTSTYLEKIT_DEFAULT_MODEL=llama3.2-vision:11b
```

## Curve Template Names

```
# Contrast
s_soft, s_strong

# Vintage
inverted_s_soft, inverted_s_strong
lift_subtle, lift_medium
crush_subtle, crush_strong

# Filmic
highlights_soft
bleach_bypass
matte_film

# Tonal
low_key, high_key

# Color
shadow_cool, shadow_warm
sepia_warm, sepia_cool
cross_process_warm
```

## File Outputs

Each generation produces:
- `style.dtstyle` - Darktable style file
- `style.md` - Technical report
- `style_EXPLICACION.md` - Narrative explanation (Spanish)
- `style_EXPLANATION.md` - Narrative explanation (English, with `--lang en`)

## Troubleshooting Quick Fixes

| Error | Fix |
|-------|-----|
| `No .dtstyle files found` | Run `./setup.sh` |
| `VLM timeout` | Use smaller model (`--model gemma3:4b`) |
| `Ollama connection refused` | `ollama serve &` |
| `dtstylekit not found` | `source .venv/bin/activate && pip install -e .[dev]` |
| `Style import fails` | Check Darktable version matches |
| `Reference analysis empty` | Use JPEG, not WebP |
