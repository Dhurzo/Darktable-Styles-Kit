"""Build VLM prompts combining image analysis + preset candidates.

Constructs Ollama-format messages with system prompt, image analysis,
preset suggestions, and user style direction. Targets ≤6000 tokens total.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dtstylekit.analyzer.models import ImageAnalysis
    from dtstylekit.presets.models import Preset


SYSTEM_PROMPT = """You are a Darktable colorist. Your job: translate a TECHNICAL IMAGE ANALYSIS into a STRONG, OPINIONATED darktable style that MATCHES the reference look.

================================================================
MANDATORY ANALYTICAL FRAMEWORK - FOLLOW STEP BY STEP
================================================================

STEP 1 - READ THE NUMBERS (do not skip, do not guess)
  • luminance.mean:       overall brightness (0=black, 1=white)
  • luminance.std:        contrast (low=flat, high=contrasty)
  • luminance.shadows_pct: % pixels in shadows (0-1)
  • luminance.highlights_pct: % pixels in highlights (0-1)
  • luminance.saturation: color intensity (0=mono, 1=vivid)
  • luminance.wb_rb_ratio: white balance (R/B ratio, ~1=neutral)
  • histogram.mean:       per-channel means [R,G,B] - color cast?
  • histogram.p5/p50/p95: shadow/mid/highlight anchors per channel
  • noise_estimate:       sensor noise level (0=clean, >0.05=grainy)
  • scene_tags:           semantic hints (architecture, landscape, portrait...)

STEP 2 - DIAGNOSE THE LOOK (explicit reasoning, 1 sentence each)
  • TONAL:    "The image is [dark/bright/balanced] with [low/medium/high] contrast, shadows=[X%] highlights=[Y%]"
  • COLOR:    "Color cast is [neutral/warm/cool/magenta-green], saturation is [low/medium/high]"
  • MOOD:     "The feel is [moody/bright/flat/punchy/airy] - target style should [crush/lift/preserve/enhance] shadows"

STEP 3 - MAP TO MODULES WITH STRONG VALUES (use FULL ranges, not timid defaults)
  ===============================================================
  │ PIPELINE RULE: Styles target RAW files. darktable adds DEFAULT    │
  │ filmicrgb to RAW automatically.                                   │
  │   • DO NOT use sigmoid - stacks with default filmicrgb = double  │
  │     tone-mapping = crushed/blue images.                          │
  │   • USE filmicrgb for tone mapping (replaces default).           │
  │   • Use colorbalancergb for color grading (MATCH reference hues).│
  =================================================================
  ┌─────────────────────────────────────────────────────────────────────────┐
  │ FILMICRGB - PRIMARY tone-mapping for RAW (replaces default filmicrgb) │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ filmicrgb.contrast:              0.5=flat -> 2.5=punchy (default 1.0)  │
  │   -> Cinematic/moody                        -> 1.5–1.8                  │
  │   -> High contrast/punchy                   -> 1.8–2.5                  │
  │   -> Soft/film-like                         -> 0.8–1.2                  │
  │   -> Bright airy                            -> 0.7–1.0                  │
  │ filmicrgb.latitude:              0.01=hard -> 50=soft (default 0.01)   │
  │   -> Harsh shadows, need rolloff          -> 0.5–2.0                    │
  │   -> Preserve dynamic range               -> 2–4                        │
  │   -> Film-like shoulder                   -> 2–8                        │
  │ filmicrgb.saturation:            -200 to +200 (default 0)             │
  │   -> Desaturated cinematic/film           -> -30 to -60                 │
  │   -> Vibrant                                -> +15 to +40               │
  │   -> Film-like slight desat (skin tones)    -> -15 to -30               │
  │ filmicrgb.balance:               -50=shadows -> +50=highlights         │
  │   -> Shadow-weighted (moody/cinematic)    -> -3 to -8                   │
  │   -> [WARNING] balance < -10 visibly darkens the WHOLE image; avoid unless    │
  │     the target is EXPLICITLY dark/moody. For "moderate contrast" use  │
  │     -3 to +3. NEVER ≤ -15.                                           │
  │   -> Highlight-weighted (bright)          -> +5 to +15                  │
  │   -> Balanced (default for most looks)    -> -3 to +3                   │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ EXPOSURE / TONE MAPPING (scene-referred, applied FIRST)               │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ exposure.exposure:             EV shift (-4 to +4)                    │
  │   -> Dark image (mean<0.25) needing lift    -> +0.5 to +1.5             │
  │   -> Bright image (mean>0.7) needing pull   -> -0.5 to -1.0             │
  │   -> Well-exposed (0.3–0.7)                 -> -0.3 to +0.3             │
  │ exposure.black:                -1.0=lift blacks -> +1.0=crush blacks   │
  │   -> Moody/cinematic (subtle)               -> +0.05 to +0.15           │
  │   -> Lifted blacks for faded/vintage look   -> -0.2 to -0.05            │
  │   -> Preserve shadow detail (default)       -> -0.05 to 0.0             │
  │   -> NEVER use black > 0.2 (destroys shadow detail)                    │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ COLOR GRADING (scene-referred) - MATCH THE REFERENCE HUES            │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ colorbalancergb.shadows_Y:     -1.0=dark/cool -> +1.0=bright/warm      │
  │   -> Moody shadows (preserve detail)        -> -0.15 to -0.3            │
  │   -> [WARNING] NEVER < -0.3 (crushes shadow detail)                           │
  │   -> Use positive shadows_Y ONLY if reference shows lifted shadows     │
  │ colorbalancergb.shadows_C:       0=desat -> 1.0=saturate shadows       │
  │   -> Color contrast in shadows              -> 0.15–0.5                 │
  │   -> NEVER use shadows_C > 0.6 (color artifacts, monochrome look)      │
  │   -> If reference has strong cast, REDUCE chroma - style must work on varied images
  │ colorbalancergb.shadows_H:       Hue angle 0-360°                     │
  │   -> MATCH the reference's shadow hue.                                 │
  │   -> NO fixed ranges - READ the reference images and COPY their hue.   │
  │   -> If NO reference: infer from scene_tags / wb_rb_ratio             │
  │ colorbalancergb.midtones_Y:      -1.0 to +1.0 (midtones lift/crush)   │
  │   -> Slightly dark for mood                 -> -0.1 to -0.3             │
  │   -> Match reference midtone brightness     -> analyze reference        │
  │ colorbalancergb.midtones_C:      0=desat -> 1.0=saturate midtones      │
  │   -> Match reference midtone saturation     -> analyze reference        │
  │   -> CAP at 0.3 - midtones carry skin tones, high chroma = fake look
  │ colorbalancergb.midtones_H:      Hue angle 0-360°                     │
  │   -> MATCH the reference's midtone hue.                                │
  │   -> NO fixed ranges - READ the reference images and COPY their hue.   │
  │   -> 0° or 360° = NEUTRAL - use only if reference is neutral          │
  │ colorbalancergb.highlights_Y:    -1.0 to +1.0                         │
  │   -> Match reference highlight brightness     -> analyze reference      │
  │   -> NEVER negative unless reference shows dimmed highlights          │
  │ colorbalancergb.highlights_C:    0=desat -> 1.0=saturate highlights    │
  │   -> Match reference highlight saturation   -> analyze reference        │
  │   -> CAP at 0.25 - highlights clip easily, high chroma = color fringes
  │ colorbalancergb.highlights_H:    Hue angle 0-360°                     │
  │   -> MATCH the reference's highlight hue.                              │
  │   -> NO fixed ranges - READ the reference images and COPY their hue.   │
  │ colorbalancergb.global_Y:        -1.0 to +1.0 (global brightness)      │
  │   -> Moody overall (use sparingly)          -> -0.03 to -0.05           │
  │   -> [WARNING] global_Y < -0.05 darkens EVERYTHING; prefer shadows_Y for mood  │
  │   -> Neutral/preserve exposure               -> 0.0 to -0.03            │
  │ colorbalancergb.global_C:        0.0 to +1.0 - ADDITIVE color offset! │
  │   [WARNING] C-CODE REALITY (src/iop/colorbalancergb.c:1137-1143, 718-720):     │
  │   global_C>0 creates an ADDITIVE RGB OFFSET applied to EVERY pixel:    │
  │   RGB[c] += global[c]  where global[c] = gradingRGB(Ych(1, C, H)) - white + white*Y │
  │   With global_H=0 (hue 0°=RED in Yrg space, -30° shift), this tints   │
  │   the WHOLE IMAGE RED. Neutral = global_C=0.0.                         │
  │   For desaturation: use filmicrgb.saturation OR chroma_global (-0.2..-0.4). │
  │   For a deliberate color cast: use small global_C (≤0.15) with        │
  │   global_H=45 (warm) or 200 (cool). NEVER global_C>0 + global_H=0.    │
  │ colorbalancergb.global_H:        0 to 360° (hue of the global offset) │
  │   Yrg hue convention: UI 0° = Yrg -30° (CONVENTIONAL_DEG_TO_YRG_RAD). │
  │   45°=warm cast, 200°=cool cast. Only meaningful if global_C>0.       │
  │ colorbalancergb.shadows/highlights: MULTIPLICATIVE with LUMINANCE MASK │
  │   shadows: RGB *= (1-alpha) + alpha*shadows[c]  where alpha=opacity   │
  │   highlights: RGB *= (1-beta) + beta*highlights[c]  where beta=opacity│
  │   Opacity masks use luminance^0.41 centered at 0.1845 (middle grey).  │
  │   shadows_C/sH affect ONLY shadow pixels (NOT midtones/highlights).   │
  │ colorbalancergb.midtones: POWER FUNCTION (gamma-like)                 │
  │   RGB = |RGB/white_fulcrum|^midtones  -> midtones_Y shifts pivot,      │
  │   midtones_C/H rotate hue/sat around mid-grey.                        │
  │ colorbalancergb.chroma_global: TRUE GLOBAL SATURATION (multiplicative)│
  │   Ych[1] *= (1 + chroma_global + vibrance*(1-Ych[1]^|vibrance|))     │
  │   Use -0.2 to -0.4 for film-like desaturation WITHOUT color shift.   │
  │ colorbalancergb.saturation_global: DTUCS/JzAzBz formula (different)  │
  │   Separate code path - prefer chroma_global for predictable results.  │
  │ colorbalancergb.contrast: -1 to 1 -> applied AFTER grading as contrast │
  │   RGB = sign * |RGB/white_fulcrum|^(1+contrast)  (similar to midtones)│
  │   Small values (±0.2-0.3) for subtle separation boost.                │
  │ PIPELINE ORDER in process():                                          │
  │   1. RGB -> LMS -> Yrg -> Ych (colorspace)                              │
  │   2. Hue rotation (hue_angle)                                        │
  │   3. Chroma boost (chroma_* + vibrance) + gamut clip                 │
  │   4. Ych -> Yrg -> LMS -> gradingRGB (Filmlight RGB)                    │
  │   5. GLOBAL OFFSET: RGB += global          ← ADDS to EVERY PIXEL     │
  │   6. SHADOWS/HIGHLIGHTS: multiplicative with luminance masks         │
  │   7. MIDTONES: power function                                        │
  │   8. CONTRAST: power function                                        │
  │   9. Output matrix back to pipeline RGB                              │
  │   -> ORDER MATTERS: global offset applied BEFORE shadows/highlights!  │
  │ colorbalancergb.contrast:        -1.0 to +1.0 (color contrast)        │
  │   -> Boost separation                       -> +0.2 to +0.4             │
  │ colorbalancergb.vibrance:        -1.0 to +1.0 (smart saturation)      │
  │   -> Natural saturation                     -> +0.2 to +0.4             │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ REFINEMENT IOPs - fine tonal/color shaping (v0.4.0)                    │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ temperature (v4): raw WB coefficients. [WARNING] REPLACES the camera's │
  │   white balance — (1,1,1,1) = NO WB = wrong colors. ONLY use with      │
  │   intentional coefficients: warm skin red≈1.8/green≈1.0/blue≈1.2,      │
  │   cool mood red≈1.1/blue≈1.9, or D65 (2.01/1.0/1.40). Skip otherwise.  │
  │ basicadj (v2): scene-referred basics (before filmicrgb).               │
  │   black_point(-1..1) lift/crush blacks, exposure(-18..18 EV),          │
  │   hlcompr(0..500) highlight compression, contrast(-1..5),              │
  │   preserve_colors(0=none..6=power), middle_grey(0.05..100, 18.42=def), │
  │   brightness(-4..4), saturation(-1..1), vibrance(-1..1).               │
  │   -> Modest: exposure ±0.3, contrast 0.1–0.3, vibrance 0.1–0.2.        │
  │ toneequal (v2): 9-zone tonal equalizer (AFTER exposure).               │
  │   bands: noise, ultra_deep_blacks, deep_blacks, blacks, shadows,       │
  │   midtones, highlights, whites, speculars — each -2..2 (0=neutral).    │
  │   blending(0.01..100, def 5), smoothing(0.01..10, def √2),             │
  │   feathering(0.01..10000, def 1), quantization(0..2),                  │
  │   contrast_boost/exposure_boost(-16..16), iterations(1..20, def 1).    │
  │   -> Lift shadows +0.3..+0.8, warm highlights +0.2..+0.5, never >2.    │
  │ colorequal (v4): per-hue saturation/hue/brightness (8 channels: red,   │
  │   orange, yellow, green, cyan, blue, lavender, magenta) AFTER filmic.  │
  │   sat_*(0..2, 1=neutral), hue_*(-180..180°, 0=neutral),                │
  │   bright_*(0..2, 1=neutral), threshold(0..0.3, def 0.1),               │
  │   hue_shift(-23..23° global rotation).                                 │
  │   -> Boost foliage sat_green 1.2–1.5; warm skin sat_red/orange 1.1–1.3 │
  │   -> Cool shadows: hue_blue +10..+20; NEVER hue_shift > ±15 alone.     │
  │ colorharmonizer (v1): harmonic color-rule grading (RGB).               │
  │   rule(0=monochromatic..9=custom, def 3=complementary),                 │
  │   anchor_hue(0..1, def 0.1) master hue, pull_strength(0..1, def 0),     │
  │   neutral_protection(0..1, def 0.5), pull_width(0.25..4, def 1),        │
  │   smoothing(0..2, def 0).                                               │
  │   -> Gentle: pull_strength 0.1–0.3, anchor_hue from ref midtone hue;    │
  │   -> rule=3 (complementary) adds contrast; DO NOT touch custom_hue_*    │
  │     arrays or num_custom_nodes (leave defaults).                        │
  │ NOTE: relight is NOT available — deprecated in darktable, use           │
  │   toneequal to lift shadows instead.                                    │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ CURVE-BASED (Lab) - use NAMED TEMPLATES only                          │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ tonecurve.curve_preset:          "inverted_s_strong" = crushed shadows│
  │                                    "s_curve_mild" = gentle contrast   │
  │                                    "lift_shadows" = shadow detail     │
  │                                    "crush_highlights" = highlight rolloff│
  │ colorzones.curve_preset:         "muted_earth"                        │
  │                                    "cool_shadows_warm_highs"          │
  │                                    "vintage_faded"                    │
  │                                    "skin_tone_protect"                │
  │ rgbcurve.curve_preset:           "inverted_s_strong" for crushed look │
  │                                    "s_curve_mild" for gentle pop      │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ SIGMOID - ONLY for JPEGs / display-referred (NO default filmicrgb)    │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ sigmoid.middle_grey_contrast:  1.0=flat -> 3.0=punchy -> 5.0=extreme    │
  │   -> Low contrast (std<0.15) + wants punch  -> 2.0–4.0                  │
  │   -> High contrast (std>0.25)               -> 1.0–1.5 (don't overdo)   │
  │   -> Dark moody/cinematic                   -> 2.0–3.5                  │
  │   -> Bright airy/high-key                   -> 1.0–1.3                  │
  │   -> [WARNING] AVOID for RAW: darktable adds default filmicrgb; sigmoid       │
  │     stacks = double tone-mapping = crushed/blue images                    │
  │ sigmoid.contrast_skewness:     -1.0=lift shadows -> +1.0=crush shadows │
  │   -> Crushed moody shadows                  -> +0.3 to +0.8             │
  │   -> Lifted shadows for detail/airy         -> -0.3 to -0.1             │
  │   -> Preserve as-is                         -> -0.1 to +0.1             │
  └─────────────────────────────────────────────────────────────────────────┘

STEP 4 - OUTPUT FORMAT (exact JSON, no extra text)
```json
{
  "style_name": "short descriptive name",
  "style_description": "one-line summary of the look",
  "selected_presets": [],
  "adjustments": {
    "filmicrgb": {"contrast": 1.0, "latitude": 0.01, "saturation": 0, "balance": 0},
    "exposure": {"exposure": 0.0, "black": 0.0},
    "colorbalancergb": {
      "shadows_Y": 0.0, "shadows_C": 0.0, "shadows_H": 0.0,
      "midtones_Y": 0.0, "midtones_C": 0.0, "midtones_H": 0.0,
      "highlights_Y": 0.0, "highlights_C": 0.0, "highlights_H": 0.0,
      "global_Y": 0.0, "global_C": 0.0, "global_H": 0.0,
      "contrast": 0.0, "vibrance": 0.0
    },
    "tonecurve": {"curve_preset": "identity"},
    "colorzones": {"curve_preset": "identity"}
  },
  "rationale": "Technical reasoning: [1 sentence per major module choice citing numbers from analysis AND reference hues]"
}
```

==================================================================
CRITICAL RULES - VIOLATION = BROKEN STYLE
===================================================================
1. **REFERENCE OVERRIDE RULE (ABSOLUTE)**: If reference images are attached, they OVERRIDE every numeric guideline in this prompt. You MUST:
   • LOOK at the reference images FIRST - before choosing ANY parameter
   • Derive the target style EXCLUSIVELY from them: tonal character, color grade (hue in shadows/midtones/highlights, saturation), mood, texture
   • COPY the actual hues you see in the references for shadows_H, midtones_H, highlights_H - DO NOT use any fixed ranges from this prompt
   • The LAST attached image is the photo the style will be applied to. Design the style so the target photo ends up matching the reference look.
2. If NO candidate preset matches the target look -> "selected_presets": []
3. Use MODERATE values - defaults (0, 1.0, 1.5) mean "no change"; extreme values break portability
4. RAW pipeline: USE filmicrgb (replaces default), AVOID sigmoid (stacks with default filmicrgb)
5. Every module choice MUST trace back to a specific number in [IMAGE ANALYSIS] OR a visible trait in the REFERENCE IMAGES
6. The rationale MUST cite numbers: "mean=0.18 -> filmicrgb contrast 1.6", "reference shadows are teal (~195°) -> shadows_H=195", not vague words
7. Match the [STYLE DIRECTION] - if user says "bright airy", don't make it moody
8. Output JSON IMMEDIATELY - no chain-of-thought in final answer
9. highlights_Y MUST be >= 0 unless the reference shows dimmed highlights, NEVER negative by default
10. global_C is an ADDITIVE color offset: global_C>0 with global_H=0 (hue 0°=red) tints the WHOLE image red. Use global_C=0.0 (neutral) or pair it with a deliberate hue (45=warm, 200=cool) at small chroma (≤0.15). Grade with shadows_H/midtones_H/highlights_H
11. shadows_Y range: -0.15 to -0.3 for moody shadows, NEVER < -0.3 (crushes detail); use positive only if reference shows lifted shadows
12. exposure.black range: 0.0 to 0.15, NEVER > 0.2 (destroys shadow detail)
13. filmicrgb: contrast=1.0-1.8 (moderate), latitude=2-4, saturation=-30..+30, balance=-3 to +3 (NEVER ≤ -10: darkens whole image)
14. PRESERVE SHADOW DETAIL: If image analysis shows shadows_pct < 10%, keep shadows_Y > -0.2 and filmic balance >= -3
15. AVOID GLOBAL DARKENING: global_Y should be 0.0 to -0.03 unless the target is explicitly dark
16. MODULE INTERACTIONS (C-code reality):
    -> filmicrgb.balance + colorbalancergb.shadows_Y + global_Y = CUMULATIVE DARKENING
      If balance=-5 AND shadows_Y=-0.25 AND global_Y=-0.03 -> net ~-0.15 EV on shadows
    -> filmicrgb.saturation + colorbalancergb.chroma_global = CUMULATIVE DESATURATION
      Use EITHER filmic sat -20..-40 OR chroma_global -0.2..-0.4, NOT both strong
    -> exposure.exposure shifts ENTIRE image before filmicrgb (scene-referred)
    -> colorbalancergb.global offset applied BEFORE shadows/highlights masks
      -> global_Y=-0.05 darkens shadows FIRST, then shadows_Y=-0.2 darkens MORE
    -> NEVER combine: strong filmic balance (<-5) + strong shadows_Y (<-0.2) + negative global_Y
17. PORTABILITY: This style will be applied to images with varying exposure (0.25-0.7 mean luminance).
    Generate params that work ACROSS this range:
    - Prefer exposure.exposure +0.1..+0.3 (small lift) over negative shadows_Y/global_Y
    - shadows_Y max magnitude: 0.25 (at shadows_pct=50%) -> scale to 0.15 if input shadows_pct<20%
    - filmicrgb.balance: -3 to +3 for portable; ≤-5 only for explicitly dark target
    - global_Y: 0.0 (neutral) for portable styles
    - Use chroma_global -0.15..-0.25 for desaturation (portable, no hue shift)
18. COLOR DOMINANCE RULE - PREVENT MONOCHROME TINT:
    -> NEVER apply the SAME hue to shadows_H + midtones_H + highlights_H with chroma>0.05 in all three.
       That is a HIDDEN GLOBAL TINT - the image looks uniformly colored instead of graded.
    -> A real color GRADE uses DIFFERENT hues per zone (e.g. teal shadows ~200°, neutral/skin midtones,
       warm highlights ~30°). At minimum keep midtones neutral (H=0°, C=0) and grade only shadows+highlights.
    -> ONLY break this rule if the reference images are DELIBERATELY monochrome (same hue across the
       entire tonal range - rare: sepia, cyanotype). If unsure, keep midtones neutral.
    -> The Python reference analysis flags this case with hue_mode='mono' for all 3 zones AND matching
       hues - trust that explicit signal; otherwise diversify or neutralize.
19. TEMPERATURE = WB REPLACEMENT (C-code reality): the temperature module's
    coefficients REPLACE the camera's white balance. Coeffs (1,1,1,1) mean
    "no WB correction" and produce WRONG colors (e.g. red channel ~0.04 on
    a Sony RAW). NEVER emit temperature unless you have an intentional WB
    (warm skin: red≈1.8/blue≈1.2; cool mood: red≈1.1/blue≈1.9; D65:
    2.01/1.0/1.40). When in doubt, omit it entirely.
20. MODEST REFINEMENT: basicadj/toneequal/colorequal/colorharmonizer
    are fine-tuning tools. Prefer 2-3 of them over stacking all; toneequal
    bands ±0.8 max, colorequal sat_* 1.1-1.5 max, basicadj exposure ±0.3,
    colorharmonizer pull_strength 0.1-0.3. Each must be
    traceable to a reference trait.
"""


def build_prompt(
    analysis: ImageAnalysis,
    presets: list[Preset],
    direction: str,
    iop_schema: str,
    image_b64: str | None = None,
    reference_b64s: list[str] | None = None,
    reference_analysis: dict | None = None,
) -> list[dict]:
    """Build Ollama messages list.

    Args:
        analysis: ImageAnalysis from analyzer pipeline.
        presets: List of relevant Preset objects from search.
        direction: User style direction (e.g., "cinematic warm portrait").
        iop_schema: Compact markdown schema of available IOPs.
        image_b64: Optional base64-encoded image for VLM.
        reference_b64s: Optional base64-encoded *reference look* images
            (e.g. samples of a photographer's style).  When present they
            are attached to the user message and the prompt instructs the
            VLM to derive the target look from them.
        reference_analysis: Optional pre-computed hue/saturation analysis
            of reference images (from Python, not VLM vision). Contains:
            shadows_hue, midtones_hue, highlights_hue, shadows_sat,
            midtones_sat, highlights_sat.

    Returns:
        List of message dicts compatible with ollama.chat().
    """
    analysis.to_prompt_dict()
    # Compact preset list (top 5)
    from dtstylekit.presets.models import clean_description, derive_display_name

    # Exposure guardrail.  The VLM receives the image analysis JSON, but
    # gemma3:12b repeatedly stacked darkening
    # presets ("day for twilight", -1 EV) onto already-dark images,
    # crushing the output to near black.  State the rule explicitly so
    # the model has an actionable constraint instead of raw numbers.
    mean_lum = getattr(getattr(analysis, "luminance", None), "mean", None)
    if not isinstance(mean_lum, int | float) or isinstance(mean_lum, bool):
        mean_lum = None
    guard: str = ""
    if mean_lum is not None and mean_lum < 0.3:
        guard = (
            f"\n[EXPOSURE GUARD - DARK IMAGE (mean {mean_lum:.2f})]\n"
            f"• Do NOT create a NEW filmicrgb instance from scratch - it re-maps "
            f"display-referred data through the scene tone-mapper and crushes shadows. "
            f"• For contrast use SIGMOID (scene-referred, safe) with middle_grey_contrast 1.1–4.0. "
            f"• exposure.black MUST be >= 0.0 (do NOT lift shadows with negative black). "
            f"• If lifting needed: exposure.exposure +0.3..+1.5. "
            f"• colorbalancergb: shadows_Y -0.3..0 for moody shadows (NEVER < -0.3). "
            f"• NEVER dehaze/defog, NEVER negative shadows_Y/shadhi.shadows.\n"
        )
    elif mean_lum is not None and mean_lum > 0.7:
        guard = (
            f"\n[EXPOSURE GUARD]\nThe image is BRIGHT (mean luminance {mean_lum:.2f} "
            f"on 0-1). NEVER select presets that brighten the image further "
            f"(they will blow out highlights). Prefer presets that preserve "
            f"exposure or slightly darken.\n"
        )

    # ─── PRE-COMPUTED TECHNICAL DIAGNOSIS FOR VLM ───
    # This gives the VLM a head-start on Step 1-2 of the analytical framework
    lum = getattr(analysis, "luminance", None)
    hist = getattr(analysis, "histogram", None)
    diagnosis_parts = []

    if lum is not None:
        # Tonal diagnosis
        contrast_level = (
            "low" if (lum.std or 0) < 0.15 else ("high" if (lum.std or 0) > 0.25 else "medium")
        )
        brightness = (
            "dark" if (lum.mean or 0) < 0.3 else ("bright" if (lum.mean or 0) > 0.7 else "balanced")
        )
        diagnosis_parts.append(
            f"TONAL: {brightness} (mean={lum.mean:.2f}), {contrast_level} contrast (std={lum.std:.2f}), "
            f"shadows={lum.shadows_pct:.0%}, midtones={lum.midtones_pct:.0%}, highlights={lum.highlights_pct:.0%}"
        )

        # Color diagnosis
        wb = lum.white_balance_ratio_rb or 1.0
        wb_desc = "neutral" if 0.95 < wb < 1.05 else ("warm" if wb > 1.05 else "cool")
        sat_level = (
            "low"
            if (lum.saturation_mean or 0) < 0.15
            else ("high" if (lum.saturation_mean or 0) > 0.35 else "medium")
        )
        diagnosis_parts.append(
            f"COLOR: {wb_desc} cast (R/B={wb:.2f}), {sat_level} saturation (mean={lum.saturation_mean:.2f})"
        )

        # Mood diagnosis
        if (lum.mean or 0) < 0.3 and (lum.std or 0) < 0.2:
            mood = "flat/dark - needs contrast + shadow definition"
        elif (lum.mean or 0) < 0.3 and (lum.std or 0) >= 0.2:
            mood = "contrasty/dark - moody, preserve drama"
        elif (lum.mean or 0) > 0.7:
            mood = "bright - protect highlights, add depth"
        else:
            mood = "balanced - creative grading opportunity"
        diagnosis_parts.append(f"MOOD: {mood}")

    if hist is not None:
        r_mean, g_mean, b_mean = hist.mean_red, hist.mean_green, hist.mean_blue
        cast = ""
        if r_mean > g_mean * 1.1 and r_mean > b_mean * 1.1:
            cast = "red/magenta cast"
        elif b_mean > r_mean * 1.1 and b_mean > g_mean * 1.1:
            cast = "blue/cyan cast"
        elif g_mean > r_mean * 1.1 and g_mean > b_mean * 1.1:
            cast = "green cast"
        if cast:
            diagnosis_parts.append(
                f"CHANNEL CAST: {cast} (R={r_mean:.2f} G={g_mean:.2f} B={b_mean:.2f})"
            )

    tech_diagnosis = (
        "\n".join(diagnosis_parts) if diagnosis_parts else "(insufficient analysis data)"
    )

    preset_summaries = []
    for p in presets[:5]:
        ops = [plg.operation for plg in p.plugins if plg.enabled]
        # The .dtstyle filename (e.g. "examples_colors_sepia.dtstyle").
        try:
            filename = p.file_path.name if p.file_path else (getattr(p, "name", "") or "")
        except AttributeError:
            filename = getattr(p, "name", "") or ""
        # Use the cleaned display name ("sepia", "faded") when available.
        display_name = derive_display_name(getattr(p, "name", "") or "") or filename
        description = clean_description(getattr(p, "description", "") or "") or "(no description)"
        preset_summaries.append(
            {
                "filename": filename,
                "name": display_name,
                "description": description[:200],
                "operations": list(dict.fromkeys(ops))[:10],
            }
        )

    # Detect if candidates are relevant: check if any has operations matching
    # the desired style (film, color, tone). If not, add explicit guidance.
    has_relevant = any(
        any(
            op
            in (
                "filmicrgb",
                "colorbalancergb",
                "sigmoid",
                "exposure",
                "tonecurve",
                "rgbcurve",
                "colorzones",
            )
            for op in p.get("operations", [])
        )
        for p in preset_summaries
    )
    relevance_note = ""
    if not has_relevant and preset_summaries:
        relevance_note = (
            f"\n[RELEVANCE WARNING] None of the {len(preset_summaries)} candidate presets "
            f"contain the core grading IOPs (filmicrgb, colorbalancergb, sigmoid, tonecurve). "
            f"DO NOT select any of them - use selected_presets: [] and create the look "
            f"entirely via `adjustments` targeting the available IOPs.\n"
        )
    # CRITICAL: Curve template names (cinematic_teal_orange, inverted_s_strong, etc.) are NOT preset filenames.
    # They are used ONLY in adjustments.tonecurve.curve_preset or adjustments.colorzones.curve_preset.
    preset_note = (
        "\n[PRESET SELECTION RULE] Candidate presets are listed above with their filenames. "
        "Curve template names like 'cinematic_teal_orange', 'inverted_s_strong', 's_curve_mild', "
        "'lift_shadows', 'muted_earth', 'cool_shadows_warm_highs', 'vintage_faded', 'skin_tone_protect' "
        "are NOT preset files - they are ONLY valid inside adjustments.tonecurve.curve_preset or "
        "adjustments.colorzones.curve_preset. DO NOT put them in selected_presets.\n"
        "[NO PRESET RULE] For this style direction, DO NOT select any preset. Use selected_presets: [] "
        "and create the complete look via adjustments only. Presets like 'day for twilight' or 'day for night' "
        "add exposure/lowlight that CONFLICTS with teal-orange grading and produces BLUE/WHITE images."
    )
    # PIPELINE RULE: This style will be applied to RAW files via darktable-cli.
    # darktable adds a DEFAULT filmicrgb instance to RAW files automatically.
    # DO NOT use sigmoid for tone mapping - it will stack with default filmicrgb and produce broken/dark images.
    # INSTEAD: Use filmicrgb for tone mapping (it will OVERRIDE the default).
    # Use colorbalancergb for color grading (match reference hues), tonecurve/colorzones for curves.
    pipeline_note = (
        "\n[PIPELINE RULE - RAW COMPATIBILITY] This style targets RAW files. "
        "darktable-cli applies a DEFAULT filmicrgb to RAW automatically. "
        "• DO NOT use sigmoid - it stacks with default filmicrgb = double tone-mapping = crushed/blue images. "
        "• USE filmicrgb for tone mapping: contrast=1.4–1.7 (moderate cinematic), latitude=2–4, saturation=-15 to -35, balance=-3 to +3 (NEVER ≤ -10). "
        "• This filmicrgb will REPLACE the default, not stack. "
        "• Use colorbalancergb for color grading (shadows/midtones/highlights split - MATCH reference hues). "
        "• Use tonecurve.curve_preset='s_curve_mild' and colorzones.curve_preset='identity' for curves."
    )

    if reference_b64s:
        # Include pre-computed reference hues from Python analysis if available
        ref_hues_lines = []
        ref_instructions = []

        if reference_analysis:
            # Shadows
            sh = reference_analysis.get("shadows_hue")
            sh_conf = reference_analysis.get("shadows_hue_confidence", 0)
            sh_mode = reference_analysis.get("shadows_hue_mode", "neutral")
            sh_sec = reference_analysis.get("shadows_hue_secondary")
            # CONFIDENCE THRESHOLD: only apply color grading when Python analysis
            # is HIGH confidence (>=0.7). Otherwise respect the target photo's
            # original colors (hue=0°, chroma=0). This stops the system from
            # inventing a warm/cool tint when references are neutral (e.g. Alen
            # Palander). Photographers with CLEAR grading (Nolan Batman blues,
            # Blade Runner) will exceed 0.7 and apply the actual hue.
            if sh is not None and sh_conf >= 0.7:
                ref_hues_lines.append(
                    f"  shadows_hue = {sh:.1f}° (confidence={sh_conf:.2f}, mode={sh_mode})"
                )
                ref_instructions.append(
                    f"  -> SET shadows_H = {sh:.1f}° (from Python analysis, confidence={sh_conf:.2f})"
                )
                if sh_mode == "bi" and sh_sec is not None:
                    ref_instructions.append(
                        f"     NOTE: reference has bi-modal color in SHADOWS: primary {sh:.1f}°, secondary {sh_sec:.1f}° "
                        f"(e.g. teal shadows + warm accents). Apply primary {sh:.1f}° as shadows_H and keep shadows_C "
                        f"modest (<=0.10) so the secondary tone is not muted."
                    )
            else:
                ref_instructions.append(
                    "  -> SET shadows_H = 0° (NEUTRAL - reference has no clear shadow grading; respect target colors)"
                )

            # Midtones
            mh = reference_analysis.get("midtones_hue")
            mh_conf = reference_analysis.get("midtones_hue_confidence", 0)
            mh_mode = reference_analysis.get("midtones_hue_mode", "neutral")
            mh_sec = reference_analysis.get("midtones_hue_secondary")
            if mh is not None and mh_conf >= 0.7:
                ref_hues_lines.append(
                    f"  midtones_hue = {mh:.1f}° (confidence={mh_conf:.2f}, mode={mh_mode})"
                )
                ref_instructions.append(
                    f"  -> SET midtones_H = {mh:.1f}° (from Python analysis, confidence={mh_conf:.2f})"
                )
                if mh_mode == "bi" and mh_sec is not None:
                    ref_instructions.append(
                        f"     NOTE: reference has bi-modal color in MIDTONES: primary {mh:.1f}°, secondary {mh_sec:.1f}°. "
                        f"Apply primary {mh:.1f}° as midtones_H and keep midtones_C modest (<=0.08) - midtones carry skin tones."
                    )
            else:
                ref_instructions.append(
                    "  -> SET midtones_H = 0° (NEUTRAL - reference has no clear midtone grading; respect target colors)"
                )

            # Highlights
            hh = reference_analysis.get("highlights_hue")
            hh_conf = reference_analysis.get("highlights_hue_confidence", 0)
            hh_mode = reference_analysis.get("highlights_hue_mode", "neutral")
            hh_sec = reference_analysis.get("highlights_hue_secondary")
            if hh is not None and hh_conf >= 0.7:
                ref_hues_lines.append(
                    f"  highlights_hue = {hh:.1f}° (confidence={hh_conf:.2f}, mode={hh_mode})"
                )
                ref_instructions.append(
                    f"  -> SET highlights_H = {hh:.1f}° (from Python analysis, confidence={hh_conf:.2f})"
                )
                if hh_mode == "bi" and hh_sec is not None:
                    ref_instructions.append(
                        f"     NOTE: reference has bi-modal color in HIGHLIGHTS: primary {hh:.1f}°, secondary {hh_sec:.1f}°. "
                        f"Apply primary {hh:.1f}° as highlights_H and keep highlights_C modest (<=0.05) - highlights clip easily."
                    )
            else:
                ref_instructions.append(
                    "  -> SET highlights_H = 0° (NEUTRAL - reference has no clear highlight grading; respect target colors)"
                )

            # Saturation (always include)
            ss = reference_analysis.get("shadows_sat", 0)
            ms = reference_analysis.get("midtones_sat", 0)
            hs = reference_analysis.get("highlights_sat", 0)
            ref_hues_lines.append(f"  shadows_sat = {ss:.3f}")
            ref_hues_lines.append(f"  midtones_sat = {ms:.3f}")
            ref_hues_lines.append(f"  highlights_sat = {hs:.3f}")

            # Global HSV saturation (mean over references).  The per-zone
            # *_sat values above use ABSOLUTE RGB deltas averaged over ALL
            # pixels of the zone; on low-key photography (most pixels in
            # shadows) they under-report how colorful the references really
            # are (Palander: zones 0.04–0.08 vs HSV mean ~0.30).  The
            # global HSV mean is the TRUE colorfulness — saturation
            # decisions (filmicrgb.saturation / vibrance) must use it, not
            # the depressed per-zone deltas.
            gsat = reference_analysis.get("global_saturation")
            if isinstance(gsat, int | float) and not isinstance(gsat, bool):
                ref_hues_lines.append(
                    f"  global_saturation (HSV) = {gsat:.3f}  <- TRUE colorfulness of the references"
                )
                if gsat >= 0.25:
                    ref_instructions.append(
                        f"  -> References are COLORFUL (global HSV {gsat:.3f}): do NOT desaturate to "
                        f"match the low per-zone deltas. Use filmicrgb.saturation in [0, +15] (or 0) "
                        f"and colorbalancergb.vibrance +0.1..+0.3 to preserve the vivid look."
                    )
                elif gsat >= 0.15:
                    ref_instructions.append(
                        f"  -> References are moderately colorful (global HSV {gsat:.3f}): use "
                        f"filmicrgb.saturation in [-10, +5] and vibrance 0..+0.15."
                    )
                else:
                    ref_instructions.append(
                        f"  -> References are DESATURATED (global HSV {gsat:.3f}): filmicrgb.saturation "
                        f"-15..-30 is appropriate; keep vibrance 0."
                    )

            # Detect INTENTIONAL MONOCHROME reference: same hue across the 3
            # zones with hue_mode='mono' in all of them. This is the rare
            # case where a global-tint look IS the intended look (sepia,
            # cyanotype). We trust the explicit Python signal and emit a
            # portability WARNING: even deliberate mono grades should keep
            # midtones neutral so the style remains portable across photos
            # with varying content.
            modes = (sh_mode, mh_mode, hh_mode)
            hues_trio = (sh, mh, hh)
            if all(m == "mono" for m in modes) and all(h is not None for h in hues_trio):

                def _circ_diff(a: float, b: float) -> float:
                    d = abs(a - b) % 360
                    return min(d, 360 - d)

                pair_close = (
                    _circ_diff(hues_trio[0], hues_trio[1]) < 15  # type: ignore[arg-type]
                    and _circ_diff(hues_trio[1], hues_trio[2]) < 15  # type: ignore[arg-type]
                    and _circ_diff(hues_trio[0], hues_trio[2]) < 15  # type: ignore[arg-type]
                )
                if pair_close:
                    ref_instructions.append(
                        f"  [INTENTIONAL MONOCHROME REFERENCE] All 3 zones share hue ~{hues_trio[0]:.0f}° "
                        f"(hue_mode='mono' in shadows+midtones+highlights). This IS a deliberate global-tint look. "
                        f"For PORTABILITY keep midtones NEUTRAL (midtones_H=0°, midtones_C=0) and grade only "
                        f"shadows+highlights with the shared hue; the validator will let this through but warns if "
                        f"all three zones carry chroma>0.05."
                    )

            # Hito 6E — GLOBAL WARM/COOL GRADE: one coherent tint across the
            # whole tonal range (hue_mode='global' in all 3 zones, confident).
            # Unlike the rare 'mono' case this is a *graded* look with
            # per-zone hue variation (e.g. warm 15°/38°/45°): the VLM should
            # apply the three zone hues with modest chroma, never the
            # additive global offset.
            if (
                all(m == "global" for m in modes)
                and all(h is not None for h in hues_trio)
                and all(c >= 0.7 for c in (sh_conf, mh_conf, hh_conf))
            ):

                def _circ_diff(a: float, b: float) -> float:
                    d = abs(a - b) % 360
                    return min(d, 360 - d)

                def _circ_mean(hs: list[float]) -> float:
                    import math

                    s = sum(math.sin(math.radians(h)) for h in hs)
                    c = sum(math.cos(math.radians(h)) for h in hs)
                    return math.degrees(math.atan2(s, c)) % 360

                g_mean = _circ_mean(list(hues_trio))  # type: ignore[arg-type]
                # Warm: red/orange/yellow/pink band (0°–90° and 315°–360°).
                # Cool: green/cyan/blue band (90°–315°).
                warm = g_mean <= 90.0 or g_mean >= 315.0
                label = "WARM" if warm else "COOL"
                ref_instructions.append(
                    f"  [GLOBAL {label} GRADE] The references are consistently "
                    f"{label.lower()} across the tonal range (hue_mode='global', "
                    f"confidence {sh_conf:.2f}/{mh_conf:.2f}/{hh_conf:.2f}): "
                    f"shadows_H={sh:.0f}°, midtones_H={mh:.0f}°, "
                    f"highlights_H={hh:.0f}°. This IS an intentional uniform "
                    f"grade — apply these THREE zone hues with SUBTLE chroma: "
                    f"shadows_C<=0.02, midtones_C<=0.015, highlights_C<=0.012 "
                    f"(the CHROMA CAPS block below enforces these numbers). "
                    f"NEVER exceed them: a uniform tint with zone-level chroma "
                    f"over-tints the whole image red/orange. Keep global_C=0.0 "
                    f"(never use the additive global offset for this look)."
                )

        if ref_hues_lines:
            ref_hues = (
                "\n[PRE-COMPUTED REFERENCE HUES (from Python analysis)]\n"
                + "\n".join(ref_hues_lines)
                + "\n"
                "Hues with confidence>=0.7 are GROUND TRUTH - use them exactly.\n"
                "Missing/low-confidence hues: use NEUTRAL (0°) - respect target photo colors.\n"
            )

        else:
            ref_hues = "\n[No reliable pre-computed hues - use NEUTRAL: shadows=0°, midtones=0°, highlights=0° (respect target colors)]\n"

        reference_note = (
            f"{ref_hues}"
            f"\n================================================================\n"
            f"CRITICAL: USE PRE-COMPUTED HUES WHERE CONFIDENT >=0.7 - NEUTRAL (0°) WHERE NOT\n"
            f"===============================================================\n\n"
            f"The FIRST {len(reference_b64s)} attached images are REFERENCE PHOTOS.\n"
            + "\n".join(ref_instructions)
            + "\n"
            + _chroma_caps_block(reference_analysis)
            + "\n"
            "[FORBIDDEN] IGNORE THE LAST ATTACHED IMAGE (target) for hue extraction.\n"
            "[WARNING]  NEUTRALITY RULE: If reference hues are NOT confident (>=0.7), keep shadows_H/midtones_H/highlights_H = 0°.\n"
            "   Apply color grading ONLY when references show CLEAR grading (e.g. Nolan Batman blues ~200°, Blade Runner).\n"
            "   Photographers like Alen Palander have neutral references - RESPECT the target photo's original colors.\n"
            "The LAST attached image is the TARGET PHOTO. Design style so target matches reference look.\n"
            "===============================================================\n"
        )

    else:
        # No reference images provided - use empty reference note
        reference_note = ""

    user_content_parts = [
        "[STYLE DIRECTION]",
        direction,
        reference_note,
        "[TECHNICAL DIAGNOSIS]",
        tech_diagnosis,
        "",
        "[IMAGE ANALYSIS]",
        "",
        "",
        "[CANDIDATE PRESETS]",
        "",
        "",
        "[IOPs]",
        iop_schema,
        guard,
        relevance_note,
        preset_note,
        pipeline_note,
        "",
        "[WARNING] OUTPUT ONLY VALID JSON - NO TEXT, NO MARKDOWN, NO EXPLANATION. Your entire response must be a single JSON object matching the format in the system prompt.",
    ]

    user_content = "\n".join(user_content_parts)

    user_msg: dict = {"role": "user", "content": user_content}

    if image_b64:
        user_msg["images"] = [image_b64]

        if reference_b64s:
            user_msg["images"] = list(reference_b64s) + [image_b64]

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        user_msg,
    ]


# ---------------------------------------------------------------------------
# Dynamic chroma caps (coherent with validator Hito 2.1)
# ---------------------------------------------------------------------------

# Soft ceiling when confidence is below the high-confidence threshold.
# Matches validator._zone_caps_default.
_SOFT_CAPS = {"shadows": 0.10, "midtones": 0.08, "highlights": 0.05}

# Higher ceiling when reference analysis reports high confidence. Matches
# validator._zone_caps_highconf. Only the zones that clear confidence>=0.85
# get the relaxed ceiling; the others stay soft.
_HIGH_CAPS = {"shadows": 0.15, "midtones": 0.15, "highlights": 0.10}

# Hito 6F: uniform ("global") grade caps. A single coherent tint across the
# whole tonal range tints EVERYTHING — the zone caps above are tuned for
# split-tone grading and over-tint a uniform grade (r4s renders came out
# +56..+138 R-B vs +9..+29 in the references; the first 6F attempt
# 0.05/0.04/0.03 still doubled the reference warmth: +39 vs ~+19). Cap
# global grades at a SUBTLE level, and never above a QUARTER of the
# measured zone saturation. Matches validator._zone_caps_global.
_GLOBAL_CAPS = {"shadows": 0.02, "midtones": 0.015, "highlights": 0.012}

_HIGH_CONF_THRESHOLD = 0.85
_NEUTRAL_CONF_THRESHOLD = 0.70  # below this -> chroma 0 (neutral)


def _is_global_grade(reference_analysis: dict | None) -> bool:
    """True when the reference analysis declares hue_mode='global' in all
    three zones (one coherent tint across the whole tonal range)."""
    if not reference_analysis:
        return False
    return all((reference_analysis.get(f"{z}_hue_mode") or "") == "global" for z in _SOFT_CAPS)


def _chroma_caps_block(reference_analysis: dict | None) -> str:
    """Build the dynamic chroma caps instructions for the prompt.

    Mirrors the validator's Hito 2.1 logic so the prompt and the post-
    validator agree:

      - zone confidence >= 0.85  → cap = 0.15 / 0.15 / 0.10  (high-conf)
      - 0.70 <= confidence < 0.85 → cap = 0.10 / 0.08 / 0.05  (soft)
      - confidence < 0.70        → cap = 0  (neutral; respect target colors)

    The emitted caps are also clamped by the actual measured saturation in
    the reference zone (``*_sat``), since the validator clamps to the same
    min(sat, cap) value. This keeps the prompt honest: an under-saturated
    reference cannot tell the VLM to crank chroma past what the reference
    actually shows.

    Returns the multi-line instruction block (without trailing newline).
    """
    if not reference_analysis:
        # No Python analysis at all: instruct NEUTRAL everywhere.
        return (
            "[CHROMA CAPS - no reference analysis]\n"
            "  -> SET shadows_C = 0.000  (NEUTRAL - respect target colors)\n"
            "  -> SET midtones_C = 0.000  (NEUTRAL - respect target colors)\n"
            "  -> SET highlights_C = 0.000  (NEUTRAL - respect target colors)"
        )

    def _zone_cap(zone: str) -> float:
        conf = float(reference_analysis.get(f"{zone}_hue_confidence", 0) or 0)
        sat = float(reference_analysis.get(f"{zone}_sat", 0) or 0)
        if _is_global_grade(reference_analysis):
            # Hito 6F: uniform grade → subtle cap, scaled by half the
            # measured zone saturation (mirrors the validator).
            cap = _GLOBAL_CAPS[zone]
            if sat > 0.0:
                cap = min(cap, sat * 0.25)
            return cap
        if conf >= _HIGH_CONF_THRESHOLD:
            cap = _HIGH_CAPS[zone]
        elif conf >= _NEUTRAL_CONF_THRESHOLD:
            cap = _SOFT_CAPS[zone]
        else:
            return 0.0  # neutral: below threshold
        return min(sat, cap)

    def _zone_note(zone: str) -> str:
        if _is_global_grade(reference_analysis):
            sat = float(reference_analysis.get(f"{zone}_sat", 0) or 0)
            cap = _GLOBAL_CAPS[zone]
            if sat > 0.0:
                cap = min(cap, sat * 0.25)
            return (
                f"GLOBAL GRADE (uniform tint) -> cap = {cap:.2f} "
                f"(min({_GLOBAL_CAPS[zone]:.2f}, sat*0.25={sat * 0.25:.2f}))"
            )
        conf = float(reference_analysis.get(f"{zone}_hue_confidence", 0) or 0)
        if conf >= _HIGH_CONF_THRESHOLD:
            return f"high-confidence (conf={conf:.2f} >= 0.85) -> cap = {_HIGH_CAPS[zone]:.2f}"
        if conf >= _NEUTRAL_CONF_THRESHOLD:
            return f"medium-confidence (conf={conf:.2f}) -> soft cap = {_SOFT_CAPS[zone]:.2f}"
        return f"low-confidence (conf={conf:.2f} < 0.70) -> NEUTRAL (cap = 0)"

    sc = _zone_cap("shadows")
    mc = _zone_cap("midtones")
    hc = _zone_cap("highlights")
    return (
        "[CHROMA CAPS - dynamic, mirrors post-validator Hito 2.1]\n"
        f"  shadows   : {_zone_note('shadows')}\n"
        f"  midtones  : {_zone_note('midtones')}\n"
        f"  highlights: {_zone_note('highlights')}\n"
        f"  -> SET shadows_C = {sc:.3f}   (capped to min(reference_sat, ceiling))\n"
        f"  -> SET midtones_C = {mc:.3f}   (capped to min(reference_sat, ceiling))\n"
        f"  -> SET highlights_C = {hc:.3f}   (capped to min(reference_sat, ceiling))"
    )
