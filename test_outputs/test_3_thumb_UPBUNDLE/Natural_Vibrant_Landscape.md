# Style Report: Natural Vibrant Landscape

*Generated: 2026-08-09T23:25:03.040943*

**Description**: Enhances natural colors and adds subtle depth to a bright landscape photograph.

## Image Analysis

- **Dimensions**: 1024 × 1024 (JPEG)
- **Mean luminance**: 0.75
- **Std luminance**: 0.38
- **Saturation**: 0.08
- **Tonal distribution**: shadows=19.26%, midtones=11.33%, highlights=69.41%
- **Scene tags**: high-key, high-contrast, desaturated, backlit, high-iso
- **Noise estimate**: 0.0943179652094841

## Base Presets

- (no base presets — pure from-scratch)

## Adjustments Applied

### `sigmoid`

| Field | Value |
|-------|-------|
| middle_grey_contrast | 1.2 |
| contrast_skewness | -0.1 |
| display_white_target | 100.0 |
| display_black_target | 0.0152 |
| color_processing | 0 |
| hue_preservation | 100.0 |
| red_inset | 0.0 |
| red_rotation | 0.0 |
| green_inset | 0.0 |
| green_rotation | 0.0 |
| blue_inset | 0.0 |
| blue_rotation | 0.0 |
| purity | 0.0 |
| base_primaries | 0 |

### `exposure`

| Field | Value |
|-------|-------|
| mode | 0 |
| black | 0.0 |
| exposure | -0.3 |
| deflicker_percentile | 50.0 |
| deflicker_target_level | -4.0 |
| compensate_exposure_bias | 0 |
| compensate_hilite_pres | 1 |

### `colorbalancergb`

| Field | Value |
|-------|-------|
| shadows_Y | 0.1 |
| shadows_C | 0.3 |
| shadows_H | 0.0 |
| midtones_Y | 0.0 |
| midtones_C | 0.0 |
| midtones_H | 0.0 |
| highlights_Y | -0.1 |
| highlights_C | 0.0 |
| highlights_H | 0.0 |
| global_Y | 0.1 |
| global_C | 0.3 |
| global_H | 0.0 |
| shadows_weight | 1.0 |
| white_fulcrum | 0.0 |
| highlights_weight | 1.0 |
| chroma_shadows | 0.0 |
| chroma_highlights | 0.0 |
| chroma_global | 0.0 |
| chroma_midtones | 0.0 |
| saturation_global | 0.0 |
| saturation_highlights | 0.0 |
| saturation_midtones | 0.0 |
| saturation_shadows | 0.0 |
| hue_angle | 0.0 |
| brilliance_global | 0.0 |
| brilliance_highlights | 0.0 |
| brilliance_midtones | 0.0 |
| brilliance_shadows | 0.0 |
| mask_grey_fulcrum | 0.1845 |
| vibrance | 0.0 |
| grey_fulcrum | 0.1845 |
| contrast | 0.0 |
| saturation_formula | 1 |

## VLM Rationale

Technical reasoning: Sigmoid middle_grey_contrast=1.2 to retain punch while protecting highlights; exposure=-0.3 to avoid clipping due to high mean (0.75); colorbalancergb shadows_Y=+0.1 for warmth, shadows_C=0.3 for contrast in shadows, global_Y=+0.1 for subtle lift; tonecurve 's_soft' preset for gentle contrast and vintage feel.

## How to Import

1. Open Darktable
2. Go to **Modules → Styles → Import**
3. Select the generated `.dtstyle` file
4. Apply from the styles sidebar
