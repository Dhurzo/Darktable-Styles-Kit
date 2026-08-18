# Advanced Usage Guide

This guide covers advanced features and workflows for dtstylekit beyond the basic quickstart.

## Table of Contents

1. [Iterative Refinement](#iterative-refinement)
2. [Reference Image Analysis](#reference-image-analysis)
3. [Curve Templates](#curve-templates)
4. [Custom VLM Models](#custom-vlm-models)
5. [Batch Processing](#batch-processing)
6. [Exporting and Sharing Styles](#exporting-and-sharing-styles)
7. [Troubleshooting Advanced Issues](#troubleshooting-advanced-issues)

---

## Iterative Refinement

Iterative refinement closes the loop between generation and visual feedback. It renders the generated style, measures visual metrics, and feeds corrections back to the VLM.

### Basic Usage

```bash
# Requires a RAW file for test rendering
dtstylekit generate photo.jpg \
  --refine-iterations 3 \
  --refine-raw photo.ARW \
  -o refined_style.dtstyle
```

### How It Works

1. **Generate** initial style spec from image + direction
2. **Render** style through `darktable-cli` on the RAW file
3. **Evaluate** rendered result (luminance, saturation, color balance)
4. **Refine** prompt with visual feedback, re-query VLM
5. **Repeat** for N iterations

### Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `--refine-iterations` | 0 | Number of refinement loops (0 = disabled) |
| `--refine-raw` | required | Path to RAW file for test rendering |
| `--temperature` | 0.4 | VLM sampling temperature |

### Example Workflow

```bash
# 1. Analyze reference images to understand the target look
dtstylekit generate photo.jpg \
  --references "refs/*.jpg" \
  --direction "warm cinematic portrait" \
  --refine-iterations 3 \
  --refine-raw photo.ARW \
  -o final_style.dtstyle

# 2. Check the generated explanation
cat generated_styles/final_style_EXPLICACION.md
```

### Visual Feedback Metrics

The refinement loop evaluates:
- **Mean luminance** (target: 0.15-0.7, avoid crushed/blown)
- **Mean saturation** (target: >0.1, avoid desaturated)
- **Red cast detection** (R/G channel ratio)
- **Highlight/shadow clipping**

---

## Reference Image Analysis

When you provide reference images with `--references`, dtstylekit performs deep analysis to extract the "look DNA":

### What Gets Analyzed

1. **Tonal key** (low/mid/high key from mean luminance)
2. **Contrast band** (low/mid/high from std deviation)
3. **Saturation band** (low/mid/high)
4. **White balance** (warm/cool/neutral from R/B ratio)
5. **Per-zone hue analysis** (shadows/midtones/highlights)
   - Hue mode: neutral / mono / bi / global
   - Confidence scores
   - Secondary hues for bimodal grades

### Reference Selection Tips

- Use **3-5 reference images** for best results
- References should share the **same aesthetic direction**
- Mix of **lighting conditions** helps VLM generalize
- Include **at least one portrait** if targeting skin tones

### Interpretation Guide

The generated `*_EXPLICACION.md` explains:

```markdown
## 2. Cómo están editadas las referencias

### Sombras
- **Matiz dominante**: Teal (200°), saturación media 0.045 (confianza 0.85)

### Medios
- **Neutras** (confianza 0.32): no hay gradación de color clara; se respeta el color original.

### Altas
- **Matiz dominante**: Naranja (30°), saturación media 0.038 (confianza 0.78)
```

### Advanced: Custom Reference Analysis

For programmatic access:

```python
from dtstylekit.analyzer.pipeline import analyze_reference_hues
from pathlib import Path

refs = [Path("ref1.jpg"), Path("ref2.jpg")]
analysis = analyze_reference_hues(refs)

# Access per-zone data
print(analysis["shadows_hue"])           # Primary hue
print(analysis["shadows_hue_secondary"]) # Secondary hue (if bimodal)
print(analysis["shadows_hue_mode"])      # "mono", "bi", "global", or "neutral"
print(analysis["shadows_hue_confidence"]) # 0.0 - 1.0
```

---

## Curve Templates

dtstylekit includes 30+ built-in curve templates for `colorzones`, `rgbcurve`, and `tonecurve`.

### Built-in Categories

| Category | Templates | Use Case |
|----------|-----------|----------|
| `tone` | `identity`, `low_key`, `high_key` | Overall brightness |
| `contrast` | `s_soft`, `s_strong`, `crush_subtle`, `crush_strong` | S-curve contrast |
| `vintage` | `inverted_s_soft`, `inverted_s_strong`, `lift_subtle`, `lift_medium` | Faded/film look |
| `filmic` | `highlights_soft`, `bleach_bypass`, `matte_film` | Film emulation |
| `color` | `shadow_cool`, `shadow_warm`, `sepia_warm`, `sepia_cool`, `cross_process_warm` | Color grading |

### Listing Templates

```bash
# List all templates
dtstylekit curves list

# Filter by category
dtstylekit curves list --category filmic

# Show template details
dtstylekit curves info s_strong
```

### Using in Styles

```json
{
  "operation": "tonecurve",
  "params": {
    "curve_preset": "bleach_bypass"
  }
}
```

### Custom Curve Templates

You can extend the registry programmatically:

```python
from dtstylekit.curves.templates import REGISTRY, CurveTemplate

# Add a custom template
custom = CurveTemplate(
    name="my_custom_s",
    title="My Custom S-Curve",
    category="contrast",
    description="Aggressive S-curve for high contrast",
    channels=["all"],
    nodes_per_channel={"all": [(0.0, 0.0), (0.25, 0.15), (0.5, 0.5), (0.75, 0.85), (1.0, 1.0)]}
)
REGISTRY.append(custom)
```

---

## Custom VLM Models

dtstylekit works with any vision model in Ollama. The default is `gemma3:27b`.

### Recommended Models

| Model | VRAM | Quality | Speed | Best For |
|-------|------|---------|-------|----------|
| `gemma3:27b` | ~16 GB | High | Medium | General purpose (default) |
| `llama3.2-vision:11b` | ~8 GB | Very High | Medium | Photos, fine detail |
| `gemma3:4b` | ~4 GB | Good | Fast | Low VRAM systems |
| `llava:7b` | ~6 GB | Good | Medium | Legacy compatibility |

### Switching Models

```bash
# One-time override
dtstylekit generate photo.jpg --model llama3.2-vision:11b -o style.dtstyle

# Persistent override
export DTSTYLEKIT_DEFAULT_MODEL=llama3.2-vision:11b
```

### Model-Specific Tuning

Different models respond differently to temperature:

```bash
# Higher temperature for creative models
dtstylekit generate photo.jpg --model gemma3:4b --temperature 0.6 -o style.dtstyle

# Lower temperature for precise models
dtstylekit generate photo.jpg --model llama3.2-vision:11b --temperature 0.2 -o style.dtstyle
```

---

## Batch Processing

Process multiple images with the same direction.

### CLI Batch (Single Direction)

```bash
# Generate styles for all JPGs in a directory
for img in photos/*.jpg; do
  dtstylekit generate "$img" \
    --direction "warm cinematic" \
    -o "styles/$(basename "$img" .jpg).dtstyle"
done
```

### Python Batch API

```python
from dtstylekit.vlm.orchestrator import generate_style_spec
from dtstylekit.analyzer.pipeline import analyze_image
from dtstylekit.presets.search import PresetSearcher
from dtstylekit.codec.iop_registry import IOP_REGISTRY
from pathlib import Path

searcher = PresetSearcher("outputs/presets.db", "outputs/preset_embeddings.npy")

images = list(Path("photos").glob("*.jpg"))
for img in images:
    spec, report, warnings, analysis = generate_style_spec(
        image_path=img,
        direction="warm cinematic",
        searcher=searcher,
        analyzer=analyze_image,
        registry=IOP_REGISTRY,
    )
    # Save spec...
```

### Parallel Processing

For large batches, use GNU parallel:

```bash
# Process 4 images at a time
ls photos/*.jpg | parallel -j 4 dtstylekit generate {} --direction "warm cinematic" -o styles/{/.}.dtstyle
```

---

## Exporting and Sharing Styles

### Style File Structure

Generated `.dtstyle` files are valid Darktable style files:

```xml
<style version="1.0">
  <info>
    <name>My Generated Style</name>
    <description>Warm cinematic portrait</description>
  </info>
  <style>
    <plugin>
      <operation>exposure</operation>
      <op_params>...</op_params>
      <enabled>1</enabled>
      <blendop_params>...</blendop_params>
    </plugin>
    ...
  </style>
  <iop_list>exposure,filmcrgb,colorbalancergb</iop_list>
</style>
```

### Installing in Darktable

1. **GUI**: Modules → Styles → Import → Select `.dtstyle` file
2. **CLI**: `darktable-cli image.ARW output.jpg --style "My Style"`
3. **Batch**: `darktable-cli *.ARW /output/dir --style "My Style"`

### Sharing Styles

The `.dtstyle` file is portable. Share it directly or:

```bash
# Package multiple styles
tar -czf my_style_pack.tar.gz styles/*.dtstyle

# Include explanation documents
tar -czf my_style_pack.tar.gz generated_styles/*.dtstyle generated_styles/*_EXPLICACION.md
```

### Version Compatibility

Styles are tied to the Darktable version used for generation. Check compatibility:

```bash
# Verify style works with current Darktable
darktable-cli --import-style my_style.dtstyle

# Test round-trip
dtstylekit curves info --verify my_style.dtstyle
```

---

## Troubleshooting Advanced Issues

### Common Issues

| Symptom | Cause | Solution |
|---------|-------|----------|
| "No .dtstyle files found" | Preset library not linked | Run `./setup.sh` |
| "VLM call failed: timeout" | Model too slow | Use smaller model (`gemma3:4b`) |
| "Style import fails in DT" | Version mismatch | Regenerate with matching DT version |
| "Iterative refinement hangs" | darktable-cli not found | Install Darktable with CLI |
| "Reference analysis empty" | Refs not JPEG | Convert to JPEG: `magick ref.webp ref.jpg` |

### Debug Mode

```bash
# Verbose logging
dtstylekit generate photo.jpg -v

# Debug VLM prompt
dtstylekit vlm generate photo.jpg --output /tmp/spec.json
cat /tmp/spec.json

# Test preset search
dtstylekit preset search "warm cinematic" --limit 10
```

### Performance Tuning

| Setting | Impact | Recommendation |
|---------|--------|----------------|
| `--model` | VRAM vs Quality | `gemma3:4b` for <8GB VRAM |
| `--temperature` | Determinism | 0.2 for consistent, 0.6 for creative |
| `--refine-iterations` | Time vs Quality | 2-3 for most cases |
| Embedding model | Search quality | `all-MiniLM-L6-v2` (default) |

### Getting Help

- **GitHub Issues**: Bug reports and feature requests
- **Discussions**: Usage questions and workflow sharing
- **Matrix**: `#dtstylekit:matrix.org` for real-time help

---

## Appendix: Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DTSTYLEKIT_PRESETS_DIR` | Auto | Force preset library path |
| `DTSTYLEKIT_OUTPUTS_DIR` | `./outputs` | Output directory |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server |
| `DTSTYLEKIT_DEFAULT_MODEL` | `gemma3:27b` | Default VLM model |

---

*For basic usage, see [README.md](../README.md) and [SETUP.md](../SETUP.md).*
