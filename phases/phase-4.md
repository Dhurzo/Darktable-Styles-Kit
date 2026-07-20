# Phase 4: Image Analyzer — Histogram, EXIF, Scene Detection
**Type:** Backend/Logic

## Objective
Extract visual signals from input images (JPEG/TIFF) to complement VLM analysis: per-channel histograms, luminance statistics, EXIF metadata, and heuristic scene classification.

## Project Snapshot
> See `plan.md` → `## Project Snapshot`

## Required Context
- Input: JPEG/TIFF files (RAW not supported in MVP — user must export to TIFF first)
- Output: `ImageAnalysis` dataclass with compact JSON-serializable fields for VLM prompt
- Histogram: 256 bins × 3 channels (R,G,B) using Pillow/numpy — downsample to 64 bins for token efficiency
- Statistics per channel: mean, std, percentiles (5, 50, 95)
- Luminance: 0.299R + 0.587G + 0.114B → mean, std, tonal distribution (shadows <0.18, midtones 0.18-0.75, highlights >0.75)
- Saturation: HSV conversion → mean S
- White balance: R/B channel ratio
- Noise estimate: variance in central 32×32 tile (after downsampling)
- EXIF: ISO, focal length, aperture, shutter speed, white balance mode, camera make/model (via `exifread`)
- Scene detection: heuristic rules based on histogram + EXIF (e.g., high-key, low-key, golden-hour, overcast, backlit, indoor, night, portrait, landscape)
- Output size target: ~200 tokens for VLM context (per `architecture_proposal.md` §9.1)

## Related Files (for context)
- `../glm5Generated/architecture_proposal.md`: §2.1 (Image Analyzer signals), §9.1 (optimization)
- `../glm5Generated/ai_integration_notes.md`: §9.1 (image analysis JSON format)
- `../glm5Generated/format_analysis.md`: §10 (analysis output example)

## Inputs
- Image file path (JPEG/TIFF)

## Tasks
- [ ] Create `dtstylekit/analyzer/models.py`: `ImageAnalysis` dataclass with all fields above + `to_json()` / `to_prompt_dict()` (compact version for VLM)
- [ ] Create `dtstylekit/analyzer/histogram.py`: `compute_histogram(image: Image.Image, bins: int = 64) -> dict` returns per-channel arrays + stats
- [ ] Create `dtstylekit/analyzer/luminance.py`: `compute_luminance_stats(rgb_arrays) -> dict` with mean, std, tonal distribution
- [ ] Create `dtstylekit/analyzer/exif.py`: `extract_exif(path: str) -> dict` using `exifread` — handle missing tags gracefully
- [ ] Create `dtstylekit/analyzer/scene.py`: `detect_scene(analysis: ImageAnalysis) -> list[str]` — heuristic rules returning tags
- [ ] Create `dtstylekit/analyzer/noise.py`: `estimate_noise(image: Image.Image) -> float` — central tile variance
- [ ] Create `dtstylekit/analyzer/pipeline.py`: `analyze_image(path: str) -> ImageAnalysis` — orchestrates all extractors
- [ ] Create `dtstylekit/analyzer/cli.py`: Subcommand `dtstylekit analyze <image>` → prints JSON
- [ ] Write tests: known test images with expected analysis ranges

## Expected Outputs
- `dtstylekit/analyzer/models.py`: `ImageAnalysis` dataclass + prompt dict conversion
- `dtstylekit/analyzer/histogram.py`: Histogram computation (64 bins default)
- `dtstylekit/analyzer/luminance.py`: Luminance stats + tonal distribution
- `dtstylekit/analyzer/exif.py`: EXIF extraction with fallbacks
- `dtstylekit/analyzer/scene.py`: Scene detection heuristics
- `dtstylekit/analyzer/noise.py`: Noise estimation
- `dtstylekit/analyzer/pipeline.py`: Main `analyze_image()` function
- `dtstylekit/analyzer/cli.py`: `analyze` subcommand
- `tests/test_analyzer.py`: Unit tests with sample images
- `tests/fixtures/`: Sample test images (small JPEGs: portrait, landscape, low-key, high-key)

## Dependencies
- Phase 1 (package structure)

## Completion Criteria
- [ ] `dtstylekit analyze tests/fixtures/portrait.jpg` outputs valid JSON with all fields populated
- [ ] Histogram arrays length 64 per channel, sum ≈ pixel count
- [ ] Luminance tonal distribution sums to ~100%
- [ ] EXIF extraction returns ISO, focal, aperture for test images with EXIF
- [ ] Scene detection returns at least 1 tag for each test fixture
- [ ] Noise estimate is a positive float
- [ ] `ImageAnalysis.to_prompt_dict()` output is <500 tokens when JSON-serialized
- [ ] All tests pass: `pytest tests/test_analyzer.py -v`