# Style Report: Moody Palm

*Generated: 2026-08-09T23:18:10.086061*

**Description**: Dark, cinematic look emphasizing the palm fronds with a cool teal/orange color contrast and crushed shadows.

## Image Analysis

- **Dimensions**: 819 × 1024 (JPEG)
- **Mean luminance**: 0.10
- **Std luminance**: 0.08
- **Saturation**: 0.50
- **Tonal distribution**: shadows=87.57%, midtones=12.42%, highlights=0.00%
- **Scene tags**: low-key, cool-cast
- **Noise estimate**: 0.013148123398423195

## Base Presets

- (no base presets — pure from-scratch)

## Adjustments Applied

### `sigmoid`

| Field | Value |
|-------|-------|
| middle_grey_contrast | 3.2 |
| contrast_skewness | 0.6 |
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
| black | 0.4 |
| exposure | 0.8 |
| deflicker_percentile | 50.0 |
| deflicker_target_level | -4.0 |
| compensate_exposure_bias | 0 |
| compensate_hilite_pres | 1 |

### `colorbalancergb`

| Field | Value |
|-------|-------|
| shadows_Y | -0.5 |
| shadows_C | 0.6 |
| shadows_H | 195.0 |
| midtones_Y | -0.2 |
| midtones_C | 0.0 |
| midtones_H | 0.0 |
| highlights_Y | -0.15 |
| highlights_C | 0.0 |
| highlights_H | 0.0 |
| global_Y | -0.1 |
| global_C | 0.3 |
| global_H | 210.0 |
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
| vibrance | 0.4 |
| grey_fulcrum | 0.1845 |
| contrast | 0.3 |
| saturation_formula | 1 |

## VLM Rationale

The image is dark (mean=0.10) with low contrast (std=0.08), requiring a sigmoid to add punch and definition. The shadows occupy 88% of the image, necessitating a crushed shadow look via contrast_skewness = +0.6.  Exposure was increased by +0.8 EV due to the dark nature of the scene (mean=0.10). Black point was lifted slightly (+0.4) to avoid crushing shadows further and preserve some detail. Color cast is cool, so shadows_Y is set to -0.5 for a teal/blue tone with hue 195.  A global Y shift of -0.1 darkens the overall image slightly while maintaining contrast. Global saturation increased to +0.3 to enhance color richness. The 'inverted_s_strong' curve preset was selected to further crush shadows and add a cinematic feel.

## How to Import

1. Open Darktable
2. Go to **Modules → Styles → Import**
3. Select the generated `.dtstyle` file
4. Apply from the styles sidebar
