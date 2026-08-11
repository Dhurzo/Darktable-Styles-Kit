# Style Report: Moody Night Photography

*Generated: 2026-08-09T23:20:54.500123*

**Description**: A high-contrast, cool-toned look emphasizing drama and shadows, suitable for night photography.

## Image Analysis

- **Dimensions**: 819 × 1024 (JPEG)
- **Mean luminance**: 0.24
- **Std luminance**: 0.24
- **Saturation**: 0.32
- **Tonal distribution**: shadows=56.51%, midtones=38.65%, highlights=4.84%
- **Scene tags**: low-key, high-contrast, cool-cast, night, high-iso
- **Noise estimate**: 0.05130843445658684

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
| black | 0.0 |
| exposure | 0.8 |
| deflicker_percentile | 50.0 |
| deflicker_target_level | -4.0 |
| compensate_exposure_bias | 0 |
| compensate_hilite_pres | 1 |

### `colorbalancergb`

| Field | Value |
|-------|-------|
| shadows_Y | -0.5 |
| shadows_C | 0.4 |
| shadows_H | 195.0 |
| midtones_Y | -0.1 |
| midtones_C | 0.0 |
| midtones_H | 0.0 |
| highlights_Y | -0.2 |
| highlights_C | 0.0 |
| highlights_H | 0.0 |
| global_Y | -0.1 |
| global_C | 0.2 |
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

The image is dark (mean=0.24) with medium contrast (std=0.24), shadows=57%, highlights=5%. To achieve the desired high-contrast and moody look, a sigmoid curve is used with middle_grey_contrast set to 3.2 for punchy contrast, and contrast_skewness at 0.6 to crush shadows slightly. The exposure is lifted by 0.8 EV as the image is dark (mean<0.3) needing brightening. Black point is preserved at 0.0 to avoid lifting shadows further. Color cast is cool (R/B=0.83), so shadows_Y is set to -0.5 for a cooler shadow tone, with color contrast boosted via shadows_C = 0.4 and hue angle 195 degrees for teal-like shadows. Global Y is slightly lowered (-0.1) to maintain darkness while keeping the overall brightness in check. Vibrance is increased by 0.4 to enhance saturation without affecting skin tones. An inverted s curve preset is used to further emphasize contrast, crushing shadows and lifting highlights.

## How to Import

1. Open Darktable
2. Go to **Modules → Styles → Import**
3. Select the generated `.dtstyle` file
4. Apply from the styles sidebar
