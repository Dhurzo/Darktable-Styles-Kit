"""Tests for the VLM integration module (with mocked VLM)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from dtstylekit.analyzer.models import HistogramStats, ImageAnalysis
from dtstylekit.codec.iop_registry import IOP_REGISTRY
from dtstylekit.presets.models import PluginRef, Preset
from dtstylekit.vlm.models import Plugin, StyleSpec
from dtstylekit.vlm.parser import parse_response
from dtstylekit.vlm.validator import validate_style

MOCK_VLM_RESPONSE_OK = """Here's my analysis:

```json
{
  "style_name": "warm cinematic portrait",
  "style_description": "Warm soft-light cinematic look",
  "selected_presets": ["examples_colors_extreme saturation.dtstyle"],
  "adjustments": {
    "filmicrgb": {"contrast": 1.4, "latitude": 25.0},
    "colorbalancergb": {"shadows_H": 25.0, "highlights_H": 35.0}
  },
  "rationale": "Boost contrast and shift hues warm"
}
```

---REPORT---
This style increases filmic contrast and shifts shadows/highlights warm for a cinematic portrait look. It's based on the existing extreme-saturation example preset.
"""


class TestParseResponse:
    def test_parses_json_in_fence(self) -> None:
        spec, report = parse_response(MOCK_VLM_RESPONSE_OK)
        assert spec.style_name == "warm cinematic portrait"
        assert "filmicrgb" in spec.operations
        assert "colorbalancergb" in spec.operations
        assert "cinematic portrait" in report.lower()

    def test_extracts_report_section(self) -> None:
        _, report = parse_response(MOCK_VLM_RESPONSE_OK)
        assert "filmic contrast" in report

    def test_handles_raw_json_no_fence(self) -> None:
        raw = '{"style_name": "raw", "plugins": [{"operation": "vibrance", "params": {"amount": 50}}]}'
        spec, _ = parse_response(raw)
        assert spec.style_name == "raw"
        assert spec.operations == ["vibrance"]

    def test_raises_on_no_json(self) -> None:
        with pytest.raises(ValueError, match="No JSON"):
            parse_response("just some text without JSON")


class TestValidateStyle:
    def test_validates_known_iop(self) -> None:
        spec = StyleSpec(
            style_name="test",
            plugins=[
                Plugin(operation="vibrance", params={"amount": 50.0}),
            ],
        )
        validated, _warnings = validate_style(spec, IOP_REGISTRY)
        assert len(validated.plugins) == 1
        assert validated.plugins[0].params["amount"] == 50.0

    def test_clamps_out_of_range(self) -> None:
        spec = StyleSpec(
            style_name="test",
            plugins=[
                Plugin(operation="vibrance", params={"amount": 999.0}),
            ],
        )
        validated, warnings = validate_style(spec, IOP_REGISTRY)
        # vibrance range is 0..100, so 999 should be clamped to 100
        assert validated.plugins[0].params["amount"] == 100.0
        assert any("out of range" in w for w in warnings)

    def test_merges_defaults(self) -> None:
        spec = StyleSpec(
            style_name="test",
            plugins=[
                Plugin(operation="filmicrgb", params={"contrast": 1.5}),
            ],
        )
        validated, _ = validate_style(spec, IOP_REGISTRY)
        # Defaults for filmicrgb should be merged
        assert validated.plugins[0].params["contrast"] == 1.5
        assert "grey_point_source" in validated.plugins[0].params  # default

    def test_colorful_references_block_negative_filmic_saturation(self) -> None:
        """Hito 2.4: references with global HSV saturation >= 0.25 are
        colorful — a negative filmicrgb.saturation contradicts the look
        and must be clamped to 0.0 (the VLM ignored the prompt hint and
        chose -25 for the colorful Palander references)."""
        spec = StyleSpec(
            style_name="test",
            plugins=[
                Plugin(operation="filmicrgb", params={"contrast": 1.4, "saturation": -25.0}),
            ],
        )
        ref = {
            # per-zone deltas look desaturated (low-key refs)...
            "shadows_sat": 0.040,
            "midtones_sat": 0.083,
            "highlights_sat": 0.058,
            "shadows_hue_confidence": 0.0,
            "midtones_hue_confidence": 0.0,
            "highlights_hue_confidence": 0.0,
            # ...but the global HSV mean says they are colorful
            "global_saturation": 0.304,
        }
        validated, warnings = validate_style(
            spec,
            IOP_REGISTRY,
            reference_analysis=ref,
        )
        assert validated.plugins[0].params["saturation"] == 0.0
        assert any("contradicts colorful references" in w for w in warnings)

    def test_desaturated_references_allow_negative_filmic_saturation(self) -> None:
        """Global HSV < 0.15 → references genuinely desaturated: a negative
        filmicrgb.saturation stays as-is."""
        spec = StyleSpec(
            style_name="test",
            plugins=[
                Plugin(operation="filmicrgb", params={"saturation": -25.0}),
            ],
        )
        ref = {"global_saturation": 0.10}
        validated, _ = validate_style(spec, IOP_REGISTRY, reference_analysis=ref)
        assert validated.plugins[0].params["saturation"] == -25.0

    def test_skips_unknown_iop(self) -> None:
        spec = StyleSpec(
            style_name="test",
            plugins=[
                Plugin(operation="nonexistent_iop", params={"x": 1.0}),
            ],
        )
        validated, warnings = validate_style(spec, IOP_REGISTRY)
        assert len(validated.plugins) == 0
        assert any("Unknown IOP" in w for w in warnings)

    def test_validates_curve_preset(self) -> None:
        """Curve-based IOPs accept ``curve_preset`` as a string."""
        spec = StyleSpec(
            style_name="test",
            plugins=[
                Plugin(
                    operation="colorzones",
                    params={"curve_preset": "s_strong", "strength": 50.0},
                ),
            ],
        )
        validated, warnings = validate_style(spec, IOP_REGISTRY)
        assert len(validated.plugins) == 1
        cp = validated.plugins[0].params.get("curve_preset")
        assert cp == "s_strong"
        # A known template should *not* produce an "unknown" warning
        assert not any("not a known" in w for w in warnings)
        # And the strength scalar should still be present and clamped
        assert validated.plugins[0].params.get("strength") == 50.0

    def test_rejects_unknown_curve_template(self) -> None:
        spec = StyleSpec(
            style_name="test",
            plugins=[
                Plugin(
                    operation="rgbcurve",
                    params={"curve_preset": "doesnt_exist"},
                ),
            ],
        )
        # If curve_preset is unknown the validator should emit a
        # *warning* but still keep the plugin (the LLM can recover).
        validated, warnings = validate_style(spec, IOP_REGISTRY)
        assert any("not a known curve template" in w for w in warnings)
        assert (
            validated.plugins[0].params.get("curve_preset") is None
            or validated.plugins[0].params.get("curve_preset") == "doesnt_exist"
        )


class TestValidateAntiTintGuards:
    """Hitos 2.1, 2.2, 2.3: anti-tint-dominance semantic guards."""

    def _colorbalance_plugin(self, **params) -> Plugin:
        return Plugin(operation="colorbalancergb", params=params)

    # ---- 2.1: dynamic chroma ceiling -----------------------------------
    def test_default_chroma_ceiling_without_reference(self) -> None:
        """No reference_analysis → shadows_C caps at 0.10 (default)."""
        spec = StyleSpec(
            style_name="t",
            plugins=[
                self._colorbalance_plugin(
                    shadows_C=0.4,
                    shadows_H=200.0,
                    midtones_C=0.4,
                    midtones_H=200.0,
                    highlights_C=0.4,
                    highlights_H=200.0,
                ),
            ],
        )
        validated, warnings = validate_style(spec, IOP_REGISTRY)
        params = validated.plugins[0].params
        assert params["shadows_C"] == 0.10
        assert params["midtones_C"] == 0.08
        assert params["highlights_C"] == 0.05
        assert any("dynamic cap" in w for w in warnings)

    def test_high_confidence_relaxes_ceiling(self) -> None:
        """reference_analysis with confidence>=0.85 allows the larger cap.

        Because we declare both the same hue AND hue_mode='mono' in the
        three zones, the reference is marking this as an intentional
        monochrome grade — the dominance guard (2.3) won't fire, only 2.1.
        """
        spec = StyleSpec(
            style_name="t",
            plugins=[
                self._colorbalance_plugin(
                    shadows_C=0.15,
                    shadows_H=200.0,
                    midtones_C=0.15,
                    midtones_H=200.0,
                    highlights_C=0.10,
                    highlights_H=200.0,
                ),
            ],
        )
        ref = {
            "shadows_hue_confidence": 0.90,
            "midtones_hue_confidence": 0.90,
            "highlights_hue_confidence": 0.90,
            "shadows_hue_mode": "mono",
            "midtones_hue_mode": "mono",
            "highlights_hue_mode": "mono",
            "shadows_hue": 200.0,
            "midtones_hue": 200.0,
            "highlights_hue": 200.0,
        }
        validated, warnings = validate_style(spec, IOP_REGISTRY, reference_analysis=ref)
        params = validated.plugins[0].params
        # 0.15 / 0.15 / 0.10 are the high-confidence caps — within them, no clamp
        assert params["shadows_C"] == 0.15
        assert params["midtones_C"] == 0.15
        assert params["highlights_C"] == 0.10
        assert not any("dynamic cap" in w for w in warnings)

    def test_medium_confidence_keeps_default_ceiling(self) -> None:
        """Confidence 0.72 (>=0.7 but <0.85) → still the conservative cap."""
        spec = StyleSpec(
            style_name="t",
            plugins=[
                self._colorbalance_plugin(shadows_C=0.15, shadows_H=200.0),
            ],
        )
        ref = {"shadows_hue_confidence": 0.72}
        validated, warnings = validate_style(spec, IOP_REGISTRY, reference_analysis=ref)
        # 0.15 > default cap 0.10 → clamped down
        assert validated.plugins[0].params["shadows_C"] == 0.10
        assert any("dynamic cap" in w for w in warnings)

    # ---- 2.2: midtones protection on likely-portrait target -------------
    def test_midtones_chroma_protected_on_skin_tone_target(self) -> None:
        """Target histogram R≈G>B (skin signature) → midtones_C capped to 0.05."""
        from dtstylekit.analyzer.models import HistogramStats, ImageAnalysis

        spec = StyleSpec(
            style_name="t",
            plugins=[
                self._colorbalance_plugin(midtones_C=0.20, midtones_H=30.0),
            ],
        )
        # Simulate portrait histogram: R≈G>B
        target = ImageAnalysis(
            histogram=HistogramStats(mean_red=0.55, mean_green=0.50, mean_blue=0.35),
        )
        validated, warnings = validate_style(spec, IOP_REGISTRY, target_analysis=target)
        assert validated.plugins[0].params["midtones_C"] == 0.05
        assert any("likely-portrait" in w or "skin" in w for w in warnings)

    def test_midtones_not_protected_when_target_is_neutral(self) -> None:
        """Neutral target histogram (R=G=B) → protection doesn't trigger."""
        from dtstylekit.analyzer.models import HistogramStats, ImageAnalysis

        spec = StyleSpec(
            style_name="t",
            plugins=[
                self._colorbalance_plugin(midtones_C=0.08, midtones_H=30.0),
            ],
        )
        target = ImageAnalysis(
            histogram=HistogramStats(mean_red=0.5, mean_green=0.5, mean_blue=0.5),
        )
        validated, _ = validate_style(spec, IOP_REGISTRY, target_analysis=target)
        # 0.08 is within the default ceiling, no clamp expected; definitely no skin protection
        assert validated.plugins[0].params["midtones_C"] == 0.08

    def test_midtones_not_protected_when_blue_dominant(self) -> None:
        """Target histogram with B>>R,G (cool/landscape) → no skin protection."""
        from dtstylekit.analyzer.models import HistogramStats, ImageAnalysis

        spec = StyleSpec(
            style_name="t",
            plugins=[
                self._colorbalance_plugin(midtones_C=0.08, midtones_H=200.0),
            ],
        )
        target = ImageAnalysis(
            histogram=HistogramStats(mean_red=0.3, mean_green=0.4, mean_blue=0.6),
        )
        validated, warnings = validate_style(spec, IOP_REGISTRY, target_analysis=target)
        assert validated.plugins[0].params["midtones_C"] == 0.08
        assert not any("skin" in w for w in warnings)

    # ---- 2.3: monochrome-dominance check --------------------------------
    def test_monochrome_dominance_halved_when_reference_not_mono(self) -> None:
        """Same hue in the 3 zones + confident reference in 'neutral' mode
        (reference didn't actually call for this hue) → chromas halved.

        Setup: confidence 0.90 (lifts the 2.1 cap to 0.15/0.15/0.10) so the
        VLM's 0.15/0.12/0.10 survives 2.1 unchanged. Then 2.3 fires because
        the reference hue_modes are 'neutral' (NOT an intentional mono grade)
        → halves them.
        """
        spec = StyleSpec(
            style_name="t",
            plugins=[
                self._colorbalance_plugin(
                    shadows_C=0.15,
                    shadows_H=200.0,
                    midtones_C=0.12,
                    midtones_H=200.0,
                    highlights_C=0.10,
                    highlights_H=200.0,
                ),
            ],
        )
        ref = {
            "shadows_hue_confidence": 0.90,
            "midtones_hue_confidence": 0.90,
            "highlights_hue_confidence": 0.90,
            "shadows_hue_mode": "neutral",
            "midtones_hue_mode": "neutral",
            "highlights_hue_mode": "neutral",
        }
        validated, warnings = validate_style(spec, IOP_REGISTRY, reference_analysis=ref)
        params = validated.plugins[0].params
        # All chroma > 0.05 and same hue → 2.3 halves them
        assert params["shadows_C"] == 0.075
        assert params["midtones_C"] == 0.06
        assert params["highlights_C"] == 0.05
        assert any("monochrome-dominance" in w for w in warnings)

    def test_monochrome_dominance_allows_intentional_mono_reference(self) -> None:
        """Reference declares hue_mode=mono with same hue in all 3 zones → allowed."""
        spec = StyleSpec(
            style_name="t",
            plugins=[
                self._colorbalance_plugin(
                    shadows_C=0.10,
                    shadows_H=200.0,
                    midtones_C=0.08,
                    midtones_H=200.0,
                    highlights_C=0.05,
                    highlights_H=200.0,
                ),
            ],
        )
        ref = {
            "shadows_hue_mode": "mono",
            "midtones_hue_mode": "mono",
            "highlights_hue_mode": "mono",
            "shadows_hue": 200.0,
            "midtones_hue": 200.0,
            "highlights_hue": 200.0,
        }
        validated, warnings = validate_style(spec, IOP_REGISTRY, reference_analysis=ref)
        # No mono-dominance halving should occur (intent = real monochrome grade)
        assert not any("monochrome-dominance" in w for w in warnings)
        params = validated.plugins[0].params
        assert params["shadows_C"] == 0.10  # within default cap, untouched
        assert params["midtones_C"] == 0.08
        assert params["highlights_C"] == 0.05

    def test_monochrome_dominance_ignored_when_hues_differ(self) -> None:
        """Different hues per zone (classic orange-teal) → no dominance tripped."""
        spec = StyleSpec(
            style_name="t",
            plugins=[
                self._colorbalance_plugin(
                    shadows_C=0.10,
                    shadows_H=200.0,  # teal shadows
                    midtones_C=0.08,
                    midtones_H=0.0,  # neutral midtones (skin protected)
                    highlights_C=0.05,
                    highlights_H=30.0,  # warm highlights
                ),
            ],
        )
        _, warnings = validate_style(spec, IOP_REGISTRY)
        assert not any("monochrome-dominance" in w for w in warnings)

    def test_monochrome_dominance_requires_all_three_zones_chroma(self) -> None:
        """Same hue but chroma=0 in one zone → not a global tint yet."""
        spec = StyleSpec(
            style_name="t",
            plugins=[
                self._colorbalance_plugin(
                    shadows_C=0.10,
                    shadows_H=200.0,
                    midtones_C=0.00,
                    midtones_H=200.0,  # midtones neutral
                    highlights_C=0.05,
                    highlights_H=200.0,
                ),
            ],
        )
        _, warnings = validate_style(spec, IOP_REGISTRY)
        assert not any("monochrome-dominance" in w for w in warnings)
        # midtones stays neutral, the other two keep their chroma (already capped)

    def test_wrapped_hues_treated_as_same_for_dominance(self) -> None:
        """Hues 358°, 1°, 2° must count as the same hue (circular)."""
        spec = StyleSpec(
            style_name="t",
            plugins=[
                self._colorbalance_plugin(
                    shadows_C=0.15,
                    shadows_H=358.0,
                    midtones_C=0.12,
                    midtones_H=1.0,
                    highlights_C=0.10,
                    highlights_H=2.0,
                ),
            ],
        )
        # Confident reference (lifts ceiling) but 'neutral' hue_mode (not mono)
        ref = {
            "shadows_hue_confidence": 0.90,
            "midtones_hue_confidence": 0.90,
            "highlights_hue_confidence": 0.90,
            "shadows_hue_mode": "neutral",
            "midtones_hue_mode": "neutral",
            "highlights_hue_mode": "neutral",
        }
        _, warnings = validate_style(spec, IOP_REGISTRY, reference_analysis=ref)
        assert any("monochrome-dominance" in w for w in warnings)


class TestValidateGlobalGrade:
    """Hito 6D + 6F: global-grade references and their chroma caps.

    A 'global' reference (one coherent tint across the tonal range, zone
    hues spread up to ±45° — e.g. warm 15°/38°/45°) marks a uniform
    VLM hue as *intentional*; the validator must NOT halve it (6D).

    Hito 6F: a uniform tint with zone-level chroma over-tints the whole
    image (r4s renders came out +56..+138 R-B vs +9..+29 in the refs).
    So for 'global' references the dynamic ceiling (2.1) drops to a
    SUBTLE cap — min(0.02/0.015/0.012, sat*0.25) per zone — before the
    dominance check ever runs.  A wrong-hue spec (teal 200° on a warm
    reference) is thus capped to a subtle tint instead of halved.
    """

    def _warm_global_ref(self) -> dict:
        return {
            "shadows_hue": 15.0,
            "shadows_hue_confidence": 0.90,
            "shadows_hue_mode": "global",
            "midtones_hue": 38.0,
            "midtones_hue_confidence": 0.90,
            "midtones_hue_mode": "global",
            "highlights_hue": 45.0,
            "highlights_hue_confidence": 0.90,
            "highlights_hue_mode": "global",
            "shadows_sat": 0.30,
            "midtones_sat": 0.30,
            "highlights_sat": 0.30,
        }

    def test_global_ref_allows_uniform_warm_spec(self) -> None:
        """Warm-global reference + uniform warm spec (15/20/25, spread
        within ±15° so 2.3 would fire) → the 'global' exception allows it
        and the 6F global caps clamp chroma to a subtle level
        (min(0.02/0.015/0.012, sat*0.25=0.075) → 0.02/0.015/0.012)."""
        spec = StyleSpec(
            style_name="t",
            plugins=[
                Plugin(
                    operation="colorbalancergb",
                    params={
                        "shadows_C": 0.12,
                        "shadows_H": 15.0,
                        "midtones_C": 0.10,
                        "midtones_H": 20.0,
                        "highlights_C": 0.08,
                        "highlights_H": 25.0,
                    },
                ),
            ],
        )
        validated, warnings = validate_style(
            spec,
            IOP_REGISTRY,
            reference_analysis=self._warm_global_ref(),
        )
        assert not any("monochrome-dominance" in w for w in warnings)
        params = validated.plugins[0].params
        assert params["shadows_C"] == 0.02
        assert params["midtones_C"] == 0.015
        assert params["highlights_C"] == 0.012
        assert any("GLOBAL-GRADE cap" in w for w in warnings)

    def test_global_ref_wrong_hue_spec_capped_to_subtle(self) -> None:
        """Warm-global reference but the VLM applies teal 200° uniformly →
        NOT an intentional match.  The 6F global cap still clamps the
        chroma to the subtle level (a wrong-hue uniform tint must not be
        strong either); no halving happens because highlights_C=0.03 no
        longer trips the strict >0.05 gate."""
        spec = StyleSpec(
            style_name="t",
            plugins=[
                Plugin(
                    operation="colorbalancergb",
                    params={
                        "shadows_C": 0.12,
                        "shadows_H": 200.0,
                        "midtones_C": 0.10,
                        "midtones_H": 200.0,
                        "highlights_C": 0.08,
                        "highlights_H": 200.0,
                    },
                ),
            ],
        )
        validated, warnings = validate_style(
            spec,
            IOP_REGISTRY,
            reference_analysis=self._warm_global_ref(),
        )
        params = validated.plugins[0].params
        assert params["shadows_C"] == 0.02
        assert params["midtones_C"] == 0.015
        assert params["highlights_C"] == 0.012
        # The cap (not the dominance halving) did the clamping
        assert any("GLOBAL-GRADE cap" in w for w in warnings)

    def test_global_ref_spread_beyond_15_degrees_allowed(self) -> None:
        """The reference's own zone hues may spread up to ±45° (warm grade
        15°/38°/45° = 30° spread) — the OLD ±15° exception would have
        rejected this warm-global reference and halved the spec."""
        spec = StyleSpec(
            style_name="t",
            plugins=[
                Plugin(
                    operation="colorbalancergb",
                    params={
                        "shadows_C": 0.05,
                        "shadows_H": 30.0,
                        "midtones_C": 0.04,
                        "midtones_H": 30.0,
                        "highlights_C": 0.03,
                        "highlights_H": 30.0,
                    },
                ),
            ],
        )
        validated, warnings = validate_style(
            spec,
            IOP_REGISTRY,
            reference_analysis=self._warm_global_ref(),
        )
        # spec_mean = 30°, ref_mean ≈ 32.7° → within 45° → allowed
        assert not any("monochrome-dominance" in w for w in warnings)
        params = validated.plugins[0].params
        # Within the global caps already → untouched
        assert params["shadows_C"] == 0.02
        assert params["midtones_C"] == 0.015
        assert params["highlights_C"] == 0.012

    def test_global_ref_cap_scaled_by_half_zone_saturation(self) -> None:
        """When the measured zone saturation is below the global cap, the
        cap tightens further: cap = min(0.02, sat*0.25).  sat=0.06 →
        cap 0.015 for shadows."""
        ref = dict(self._warm_global_ref())
        ref["shadows_sat"] = 0.06
        spec = StyleSpec(
            style_name="t",
            plugins=[
                Plugin(
                    operation="colorbalancergb",
                    params={
                        "shadows_C": 0.08,
                        "shadows_H": 20.0,
                    },
                ),
            ],
        )
        validated, warnings = validate_style(
            spec,
            IOP_REGISTRY,
            reference_analysis=ref,
        )
        assert validated.plugins[0].params["shadows_C"] == 0.015
        assert any("GLOBAL-GRADE cap" in w for w in warnings)


class TestSchemaRenderer:
    def test_renders_iop_schema(self) -> None:
        from dtstylekit.vlm.schema_renderer import render_iop_schema

        schema = render_iop_schema(IOP_REGISTRY, max_iops=5)
        assert "filmicrgb" in schema.lower() or "colorbalancergb" in schema.lower()


class TestPromptBuilder:
    def _make_analysis(self, mean: float, std: float = 0.2, sat: float = 0.3) -> MagicMock:
        """Create a properly mocked analysis with luminance and histogram attributes."""
        analysis = MagicMock()
        analysis.to_prompt_dict.return_value = {"luminance": {"mean": mean}}

        # Create a proper mock for luminance with all needed attributes
        luminance = MagicMock()
        luminance.mean = mean
        luminance.std = std
        luminance.saturation_mean = sat
        luminance.white_balance_ratio_rb = 1.0
        luminance.shadows_pct = 0.2
        luminance.midtones_pct = 0.6
        luminance.highlights_pct = 0.2
        analysis.luminance = luminance

        # Create a proper mock for histogram with all needed attributes
        histogram = MagicMock()
        histogram.mean_red = mean * 0.9
        histogram.mean_green = mean
        histogram.mean_blue = mean * 1.1
        analysis.histogram = histogram

        return analysis

    def test_build_prompt_messages(self) -> None:
        from dtstylekit.vlm.prompt_builder import build_prompt

        analysis = self._make_analysis(mean=0.5)
        presets = []
        messages = build_prompt(
            analysis, presets, "warm cinematic", iop_schema="### filmicrgb", image_b64=None
        )
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "warm cinematic" in messages[1]["content"]

    def test_dark_image_gets_exposure_guard(self) -> None:
        """A dark image must trigger the EXPOSURE GUARD in the prompt."""
        from dtstylekit.vlm.prompt_builder import build_prompt

        analysis = self._make_analysis(mean=0.15, std=0.1)

        messages = build_prompt(analysis, [], "night", iop_schema="### filmicrgb")
        content = messages[1]["content"]
        assert "EXPOSURE GUARD" in content
        assert "DARK" in content
        assert "'day for twilight'" in content

    def test_bright_image_gets_exposure_guard(self) -> None:
        from dtstylekit.vlm.prompt_builder import build_prompt

        analysis = self._make_analysis(mean=0.85, std=0.15)

        messages = build_prompt(analysis, [], "sunny", iop_schema="### filmicrgb")
        content = messages[1]["content"]
        assert "[EXPOSURE GUARD]" in content
        assert "BRIGHT" in content

    def test_mid_image_no_guard(self) -> None:
        from dtstylekit.vlm.prompt_builder import build_prompt

        analysis = self._make_analysis(mean=0.5, std=0.2)

        messages = build_prompt(analysis, [], "neutral", iop_schema="### filmicrgb")
        assert "[EXPOSURE GUARD]" not in messages[1]["content"]


class TestPromptAntiTintRules:
    """Hito 3: prompt-level anti-tint instructions and dynamic chroma caps."""

    def _make_analysis(self, mean: float = 0.5) -> MagicMock:
        """Minimal analysis mock with luminance + histogram attributes."""
        analysis = MagicMock()
        analysis.to_prompt_dict.return_value = {"luminance": {"mean": mean}}
        luminance = MagicMock()
        luminance.mean = mean
        luminance.std = 0.2
        luminance.saturation_mean = 0.3
        luminance.white_balance_ratio_rb = 1.0
        luminance.shadows_pct = 0.2
        luminance.midtones_pct = 0.6
        luminance.highlights_pct = 0.2
        analysis.luminance = luminance
        histogram = MagicMock()
        histogram.mean_red = mean * 0.9
        histogram.mean_green = mean
        histogram.mean_blue = mean * 1.1
        analysis.histogram = histogram
        return analysis

    def test_prompt_has_color_dominance_rule(self) -> None:
        """SYSTEM_PROMPT must carry rule #18 COLOR DOMINANCE RULE."""
        from dtstylekit.vlm.prompt_builder import SYSTEM_PROMPT

        assert "18. COLOR DOMINANCE RULE" in SYSTEM_PROMPT
        assert "HIDDEN GLOBAL TINT" in SYSTEM_PROMPT
        # Must warn against same hue in all 3 zones
        assert "shadows_H + midtones_H + highlights_H" in SYSTEM_PROMPT
        # Must mention the chroma>0.05 threshold (matches validator 2.3)
        assert "chroma>0.05" in SYSTEM_PROMPT

    def test_prompt_emits_bimodal_instruction(self) -> None:
        """Reference with hue_mode='bi' for a zone → prompt injects a NOTE
        describing primary+secondary hue for that zone."""
        from dtstylekit.vlm.prompt_builder import build_prompt

        analysis = self._make_analysis(0.5)
        ref = {
            "shadows_hue": 200.0,
            "shadows_hue_confidence": 0.90,
            "shadows_hue_mode": "bi",
            "shadows_hue_secondary": 30.0,
            "shadows_sat": 0.50,
            "midtones_hue": None,
            "midtones_hue_confidence": 0.40,
            "midtones_hue_mode": "neutral",
            "midtones_hue_secondary": None,
            "midtones_sat": 0.0,
            "highlights_hue": 30.0,
            "highlights_hue_confidence": 0.90,
            "highlights_hue_mode": "mono",
            "highlights_hue_secondary": None,
            "highlights_sat": 0.30,
        }
        msgs = build_prompt(
            analysis,
            [],
            "test",
            "schema",
            image_b64=None,
            reference_b64s=["fake"],
            reference_analysis=ref,
        )
        content = msgs[1]["content"]
        assert "bi-modal color in SHADOWS" in content
        assert "primary 200.0" in content
        assert "secondary 30.0" in content
        # The instructions still drive the SET directive with the primary
        assert "SET shadows_H = 200.0" in content

    def test_prompt_dynamic_chroma_caps_high_confidence(self) -> None:
        """All 3 zones with confidence >= 0.85 → caps at 0.15/0.15/0.10
        (mirrors validator high-confidence ceiling)."""
        from dtstylekit.vlm.prompt_builder import build_prompt

        analysis = self._make_analysis(0.5)
        ref = {
            "shadows_hue": 200.0,
            "shadows_hue_confidence": 0.90,
            "shadows_hue_mode": "mono",
            "shadows_sat": 0.50,
            "midtones_hue": 200.0,
            "midtones_hue_confidence": 0.90,
            "midtones_hue_mode": "mono",
            "midtones_sat": 0.50,
            "highlights_hue": 200.0,
            "highlights_hue_confidence": 0.90,
            "highlights_hue_mode": "mono",
            "highlights_sat": 0.50,
        }
        msgs = build_prompt(
            analysis,
            [],
            "test",
            "schema",
            image_b64=None,
            reference_b64s=["fake"],
            reference_analysis=ref,
        )
        content = msgs[1]["content"]
        # High-confidence cap echoed in the prompt
        assert "high-confidence (conf=0.90 >= 0.85)" in content
        assert "SET shadows_C = 0.150" in content
        assert "SET midtones_C = 0.150" in content
        assert "SET highlights_C = 0.100" in content
        # Even though all zones are mono with same hue, this prompts the
        # intentional-monochrome WARNING block (the SETs themselves don't
        # promote the hidden-tint problem; the warning tells the model to
        # keep midtones neutral for portability).
        assert "INTENTIONAL MONOCHROME REFERENCE" in content

    def test_prompt_dynamic_chroma_caps_medium_confidence(self) -> None:
        """Confidence in [0.70, 0.85) → soft caps 0.10/0.08/0.05.
        Below 0.70 → 0 (neutral)."""
        from dtstylekit.vlm.prompt_builder import build_prompt

        analysis = self._make_analysis(0.5)
        ref = {
            "shadows_hue": 200.0,
            "shadows_hue_confidence": 0.72,  # medium → soft cap 0.10
            "shadows_hue_mode": "mono",
            "shadows_sat": 0.50,
            "midtones_hue": None,
            "midtones_hue_confidence": 0.60,  # low → neutral 0
            "midtones_hue_mode": "neutral",
            "midtones_sat": 0.0,
            "highlights_hue": None,
            "highlights_hue_confidence": 0.0,  # low → neutral 0
            "highlights_hue_mode": "neutral",
            "highlights_sat": 0.0,
        }
        msgs = build_prompt(
            analysis,
            [],
            "test",
            "schema",
            image_b64=None,
            reference_b64s=["fake"],
            reference_analysis=ref,
        )
        content = msgs[1]["content"]
        # Shadow: medium conf -> soft cap 0.10 (sat 0.50, so 0.10 wins)
        assert "shadows   : medium-confidence (conf=0.72)" in content
        assert "SET shadows_C = 0.100" in content
        # Midtones: conf 0.60 < 0.70 → neutral 0
        assert "midtones  : low-confidence (conf=0.60 < 0.70) -> NEUTRAL" in content
        assert "SET midtones_C = 0.000" in content
        # Highlights: conf 0.0 < 0.70 → neutral 0
        assert "highlights: low-confidence (conf=0.00 < 0.70) -> NEUTRAL" in content
        assert "SET highlights_C = 0.000" in content

    def test_prompt_neutral_reference_tints_no_intentional_mono(self) -> None:
        """A neutral reference (no clear hues) must NOT emit the intentional
        monochrome warning (which is reserved for hue_mode='mono' across all
        3 zones with matching hues)."""
        from dtstylekit.vlm.prompt_builder import build_prompt

        analysis = self._make_analysis(0.5)
        ref = {
            "shadows_hue": None,
            "shadows_hue_confidence": 0.2,
            "shadows_hue_mode": "neutral",
            "shadows_sat": 0.0,
            "midtones_hue": None,
            "midtones_hue_confidence": 0.2,
            "midtones_hue_mode": "neutral",
            "midtones_sat": 0.0,
            "highlights_hue": None,
            "highlights_hue_confidence": 0.2,
            "highlights_hue_mode": "neutral",
            "highlights_sat": 0.0,
        }
        msgs = build_prompt(
            analysis,
            [],
            "test",
            "schema",
            image_b64=None,
            reference_b64s=["fake"],
            reference_analysis=ref,
        )
        content = msgs[1]["content"]
        assert "INTENTIONAL MONOCHROME" not in content
        # All zones below 0.70 → all neutral
        assert "SET shadows_C = 0.000" in content
        assert "SET midtones_C = 0.000" in content
        assert "SET highlights_C = 0.000" in content

    def test_prompt_global_saturation_colorful_references(self) -> None:
        """High global HSV saturation (>= 0.25) must override the depressed
        per-zone deltas: do NOT desaturate, use filmicrgb.saturation
        [0, +15] and vibrance +0.1..+0.3."""
        from dtstylekit.vlm.prompt_builder import build_prompt

        analysis = self._make_analysis(0.5)
        ref = {
            # Low-key references: per-zone deltas look nearly desaturated...
            "shadows_sat": 0.040,
            "midtones_sat": 0.083,
            "highlights_sat": 0.058,
            "shadows_hue": None,
            "shadows_hue_confidence": 0.0,
            "shadows_hue_mode": "neutral",
            "midtones_hue": None,
            "midtones_hue_confidence": 0.0,
            "midtones_hue_mode": "neutral",
            "highlights_hue": None,
            "highlights_hue_confidence": 0.0,
            "highlights_hue_mode": "neutral",
            # ...but the global HSV mean says they are colorful
            "global_saturation": 0.30,
        }
        msgs = build_prompt(
            analysis,
            [],
            "editorial",
            "schema",
            image_b64=None,
            reference_b64s=["fake"],
            reference_analysis=ref,
        )
        content = msgs[1]["content"]
        assert "global_saturation (HSV) = 0.300" in content
        assert "TRUE colorfulness" in content
        assert "COLORFUL" in content
        assert "filmicrgb.saturation in [0, +15]" in content
        assert "vibrance +0.1..+0.3" in content

    def test_prompt_global_saturation_desaturated_references(self) -> None:
        """Low global HSV saturation (< 0.15) allows filmicrgb.saturation
        -15..-30 with vibrance 0."""
        from dtstylekit.vlm.prompt_builder import build_prompt

        analysis = self._make_analysis(0.5)
        ref = {
            "shadows_sat": 0.02,
            "midtones_sat": 0.04,
            "highlights_sat": 0.03,
            "shadows_hue": None,
            "shadows_hue_confidence": 0.0,
            "shadows_hue_mode": "neutral",
            "midtones_hue": None,
            "midtones_hue_confidence": 0.0,
            "midtones_hue_mode": "neutral",
            "highlights_hue": None,
            "highlights_hue_confidence": 0.0,
            "highlights_hue_mode": "neutral",
            "global_saturation": 0.10,
        }
        msgs = build_prompt(
            analysis,
            [],
            "editorial",
            "schema",
            image_b64=None,
            reference_b64s=["fake"],
            reference_analysis=ref,
        )
        content = msgs[1]["content"]
        assert "DESATURATED" in content
        assert "filmicrgb.saturation -15..-30" in content
        assert "keep vibrance 0" in content

    def test_prompt_no_global_saturation_no_block(self) -> None:
        """Without global_saturation in the analysis the prompt must not
        reference it (backwards compatible)."""
        from dtstylekit.vlm.prompt_builder import build_prompt

        analysis = self._make_analysis(0.5)
        ref = {
            "shadows_sat": 0.04,
            "midtones_sat": 0.08,
            "highlights_sat": 0.06,
            "shadows_hue": None,
            "shadows_hue_confidence": 0.0,
            "shadows_hue_mode": "neutral",
            "midtones_hue": None,
            "midtones_hue_confidence": 0.0,
            "midtones_hue_mode": "neutral",
            "highlights_hue": None,
            "highlights_hue_confidence": 0.0,
            "highlights_hue_mode": "neutral",
        }
        msgs = build_prompt(
            analysis,
            [],
            "editorial",
            "schema",
            image_b64=None,
            reference_b64s=["fake"],
            reference_analysis=ref,
        )
        assert "global_saturation" not in msgs[1]["content"]

    def test_prompt_emits_global_warm_grade(self) -> None:
        """hue_mode='global' in all 3 zones with conf >= 0.7 → the prompt
        emits a [GLOBAL WARM GRADE] instruction with the three zone hues
        (Hito 6E)."""
        from dtstylekit.vlm.prompt_builder import build_prompt

        analysis = self._make_analysis(0.5)
        ref = {
            "shadows_hue": 15.0,
            "shadows_hue_confidence": 0.80,
            "shadows_hue_mode": "global",
            "shadows_sat": 0.30,
            "midtones_hue": 38.0,
            "midtones_hue_confidence": 0.86,
            "midtones_hue_mode": "global",
            "midtones_sat": 0.30,
            "highlights_hue": 45.0,
            "highlights_hue_confidence": 1.00,
            "highlights_hue_mode": "global",
            "highlights_sat": 0.30,
        }
        msgs = build_prompt(
            analysis,
            [],
            "test",
            "schema",
            image_b64=None,
            reference_b64s=["fake"],
            reference_analysis=ref,
        )
        content = msgs[1]["content"]
        assert "[GLOBAL WARM GRADE]" in content
        assert "shadows_H=15°" in content
        assert "midtones_H=38°" in content
        assert "highlights_H=45°" in content
        assert "global_C=0.0" in content
        # Hito 6F: the instruction must carry the SUBTLE global caps and the
        # caps block must echo the same numbers (sat 0.30 → min(cap, 0.15)).
        assert "shadows_C<=0.02" in content
        assert "midtones_C<=0.015" in content
        assert "highlights_C<=0.012" in content
        assert "SET shadows_C = 0.020" in content
        assert "SET midtones_C = 0.015" in content
        assert "SET highlights_C = 0.012" in content
        assert "GLOBAL GRADE (uniform tint)" in content

    def test_prompt_emits_global_cool_grade(self) -> None:
        """A blue global grade must be labelled COOL, not WARM."""
        from dtstylekit.vlm.prompt_builder import build_prompt

        analysis = self._make_analysis(0.5)
        ref = {
            "shadows_hue": 200.0,
            "shadows_hue_confidence": 0.90,
            "shadows_hue_mode": "global",
            "shadows_sat": 0.30,
            "midtones_hue": 205.0,
            "midtones_hue_confidence": 0.90,
            "midtones_hue_mode": "global",
            "midtones_sat": 0.30,
            "highlights_hue": 210.0,
            "highlights_hue_confidence": 0.90,
            "highlights_hue_mode": "global",
            "highlights_sat": 0.30,
        }
        msgs = build_prompt(
            analysis,
            [],
            "test",
            "schema",
            image_b64=None,
            reference_b64s=["fake"],
            reference_analysis=ref,
        )
        content = msgs[1]["content"]
        assert "[GLOBAL COOL GRADE]" in content
        assert "shadows_H=200°" in content

    def test_prompt_no_global_grade_for_neutral_refs(self) -> None:
        """Neutral or low-confidence references must NOT emit the global
        grade instruction."""
        from dtstylekit.vlm.prompt_builder import build_prompt

        analysis = self._make_analysis(0.5)
        ref = {
            "shadows_hue": None,
            "shadows_hue_confidence": 0.2,
            "shadows_hue_mode": "neutral",
            "shadows_sat": 0.0,
            "midtones_hue": None,
            "midtones_hue_confidence": 0.2,
            "midtones_hue_mode": "neutral",
            "midtones_sat": 0.0,
            "highlights_hue": None,
            "highlights_hue_confidence": 0.2,
            "highlights_hue_mode": "neutral",
            "highlights_sat": 0.0,
        }
        msgs = build_prompt(
            analysis,
            [],
            "test",
            "schema",
            image_b64=None,
            reference_b64s=["fake"],
            reference_analysis=ref,
        )
        content = msgs[1]["content"]
        assert "[GLOBAL" not in content

    def test_prompt_no_global_grade_when_confidence_low(self) -> None:
        """hue_mode='global' but conf < 0.7 → no global grade instruction
        (the model must stay neutral)."""
        from dtstylekit.vlm.prompt_builder import build_prompt

        analysis = self._make_analysis(0.5)
        ref = {
            "shadows_hue": 15.0,
            "shadows_hue_confidence": 0.60,
            "shadows_hue_mode": "global",
            "shadows_sat": 0.30,
            "midtones_hue": 38.0,
            "midtones_hue_confidence": 0.55,
            "midtones_hue_mode": "global",
            "midtones_sat": 0.30,
            "highlights_hue": 45.0,
            "highlights_hue_confidence": 0.50,
            "highlights_hue_mode": "global",
            "highlights_sat": 0.30,
        }
        msgs = build_prompt(
            analysis,
            [],
            "test",
            "schema",
            image_b64=None,
            reference_b64s=["fake"],
            reference_analysis=ref,
        )
        assert "[GLOBAL" not in msgs[1]["content"]


class TestPresetExposureFilter:
    """Luminance-suitability filter for candidate presets."""

    def _preset(self, plugins: list) -> Preset:
        from pathlib import Path

        return Preset(
            name="test",
            description="",
            iop_list="",
            plugins=plugins,
            file_path=Path("/tmp/x.dtstyle"),
            xml_hash="h",
        )

    def _exposure_ref(self, ev: float, enabled: int = 1) -> PluginRef:
        from dtstylekit.codec.iop_registry import pack_params
        from dtstylekit.codec.xmp_codec import encode_xmp

        blob = pack_params("exposure", {"exposure": ev})
        return PluginRef(
            operation="exposure",
            enabled=enabled,
            multi_name="",
            multi_priority=0,
            num=0,
            module=7,
            op_params=encode_xmp(blob),
            blendop_params="",
            blendop_version=13,
            multi_name_hand_edited=0,
        )

    def test_net_ev_summed_only_enabled(self) -> None:
        from dtstylekit.vlm.orchestrator import _preset_net_ev

        p = self._preset([self._exposure_ref(-1.0), self._exposure_ref(0.5, enabled=0)])
        assert _preset_net_ev(p) == -1.0

    def test_darkening_preset_rejected_for_dark_image(self) -> None:
        from dtstylekit.vlm.orchestrator import _preset_ev_fits

        p = self._preset([self._exposure_ref(-1.0)])
        assert _preset_ev_fits(p, 0.15) is False  # dark image + -1 EV → crushed
        assert _preset_ev_fits(p, 0.5) is True  # mid image → fine
        assert _preset_ev_fits(p, 0.85) is True  # bright image → fine

    def test_brightening_preset_rejected_for_bright_image(self) -> None:
        from dtstylekit.vlm.orchestrator import _preset_ev_fits

        p = self._preset([self._exposure_ref(0.8)])
        assert _preset_ev_fits(p, 0.85) is False
        assert _preset_ev_fits(p, 0.15) is True

    def test_preset_without_exposure_always_fits(self) -> None:
        from dtstylekit.vlm.orchestrator import _preset_ev_fits

        p = self._preset([])
        assert _preset_ev_fits(p, 0.1) is True
        assert _preset_ev_fits(p, 0.9) is True

    def test_dehaze_preset_rejected_for_dark_image_by_name(self) -> None:
        """hazeremoval is not in the IOP registry (no blob decode), but
        dehaze crushes dark images — reject by name for mean_lum < 0.3."""
        from pathlib import Path

        from dtstylekit.vlm.orchestrator import _preset_ev_fits

        p = Preset(
            name="dehaze strong luminance only",
            description="",
            iop_list="",
            plugins=[],
            file_path=Path("/tmp/x.dtstyle"),
            xml_hash="h",
        )
        assert _preset_ev_fits(p, 0.15) is False  # dark image → dropped
        assert _preset_ev_fits(p, 0.5) is True  # mid image → fine
        assert _preset_ev_fits(p, 0.85) is True  # bright image → fine


class TestE2EValidatorGuardsWithVLMResponse:
    """Hito 5: structural E2E of the post-validator anti-tint safeguards.

    These tests feed a *simulated VLM JSON response* (the raw string the
    VLM would return) through ``parse_response`` → ``validate_style``,
    with a populated ``reference_analysis`` and a ``target_analysis``
    carrying a portrait-like histogram.  They verify that even when a
    VLM tries to apply a uniform tint across all three zones, the Hito 2
    validator salvages the result at the pipeline boundary:

      * monochrome-intent reference + portrait target → midtones protected
        (Hito 2.2 skin-tone guard caps ``midtones_C`` to 0.05).
      * neutral reference + uniform-hue VLM attempt → monochrome-dominance
        halves every zone chroma (Hito 2.3).

    Both tests cover the full pipeline path actually exercised by the
    orchestrator: VLM text → parser → validator(reference_analysis=…,
    target_analysis=…).  No live Ollama call is performed.
    """

    # Simulated VLM responses — the JSON shape the orchestrator passes
    # through ``parse_response``.  We mirror the structure the SYSTEM_PROMPT
    # asks the model to emit, including the colorbalancergb module with the
    # offending uniform-tint values.

    _AGGRESSIVE_SLOT = """```json
{{
  "style_name": "uniform tint attack",
  "style_description": "VLM wrongly applies same hue everywhere",
  "selected_presets": [],
  "adjustments": {{
    "colorbalancergb": {{
      "shadows_H": 200.0, "shadows_C": {shc:.3f},
      "midtones_H": 200.0, "midtones_C": {mc:.3f},
      "highlights_H": 200.0, "highlights_C": {hc:.3f}
    }}
  }},
  "rationale": "intentional wrong uniform tint"
}}
```"""

    def _mono_ref(self) -> dict:
        """Intentional-monochrome reference: mono hue in all 3 zones,
        same hue, high confidence.  Validator 2.3 must NOT halve here
        (the reference explicitly calls for a global tint look)."""
        return {
            "shadows_hue": 200.0,
            "shadows_hue_confidence": 0.90,
            "shadows_hue_mode": "mono",
            "shadows_hue_secondary": None,
            "midtones_hue": 200.0,
            "midtones_hue_confidence": 0.90,
            "midtones_hue_mode": "mono",
            "midtones_hue_secondary": None,
            "highlights_hue": 200.0,
            "highlights_hue_confidence": 0.90,
            "highlights_hue_mode": "mono",
            "highlights_hue_secondary": None,
            "shadows_sat": 0.50,
            "midtones_sat": 0.50,
            "highlights_sat": 0.50,
        }

    def _neutral_ref(self) -> dict:
        """Neutral reference: hue_modes 'neutral' (no clear grade).  The
        validator's 2.3 dominance guard will then *halve* an aggressive
        uniform-hue VLM attempt."""
        return {
            "shadows_hue": None,
            "shadows_hue_confidence": 0.20,
            "shadows_hue_mode": "neutral",
            "midtones_hue": None,
            "midtones_hue_confidence": 0.20,
            "midtones_hue_mode": "neutral",
            "highlights_hue": None,
            "highlights_hue_confidence": 0.20,
            "highlights_hue_mode": "neutral",
            "shadows_sat": 0.0,
            "midtones_sat": 0.0,
            "highlights_sat": 0.0,
        }

    def _portrait_target(self) -> ImageAnalysis:
        return ImageAnalysis(
            histogram=HistogramStats(mean_red=0.55, mean_green=0.50, mean_blue=0.35),
        )

    def _parse_and_validate(
        self,
        vlm_json: str,
        ref: dict,
        target: ImageAnalysis | None = None,
    ) -> tuple[StyleSpec, list[str]]:
        spec, _report = parse_response(vlm_json)
        return validate_style(
            spec,
            IOP_REGISTRY,
            reference_analysis=ref,
            target_analysis=target,
        )

    def test_mono_ref_skintone_target_keeps_midtones_neutral(self) -> None:
        """VLM tries uniform tint 200° in all zones with chroma 0.15/0.15/0.10.
        Reference_analysis says hue_mode='mono' (intentional) and target is a
        portrait.  Outcome path:
          * 2.1 relaxes caps to high-conf (0.15/0.15/0.10) - values pass.
          * 2.3 sees same hue + all chroma>0.05 BUT reference_analysis
            declares mono intent → no halving (intentional exception).
          * 2.2 sees portrait target R≈G>B with midtones_C=0.15 > 0.05 →
            clamps midtones_C to 0.05 (skin protection).
        Final: shadows_C=0.15, midtones_C=0.05, highlights_C=0.10.
        """
        vlm = self._AGGRESSIVE_SLOT.format(shc=0.15, mc=0.15, hc=0.10)
        spec, warnings = self._parse_and_validate(
            vlm,
            self._mono_ref(),
            self._portrait_target(),
        )
        cb = next(p for p in spec.plugins if p.operation == "colorbalancergb")
        params = cb.params
        assert params["shadows_C"] == 0.15
        assert (
            params["midtones_C"] == 0.05
        ), f"midtones_C must be clamped to 0.05 on portrait target; got {params['midtones_C']}"
        assert params["highlights_C"] == 0.10
        # Skin warning must appear
        assert any("likely-portrait" in w or "skin" in w for w in warnings)
        # No dominance halving (mono intent allowed)
        assert not any("monochrome-dominance" in w for w in warnings)

    def test_neutral_ref_aggressive_vlm_triggers_dominance_halving(self) -> None:
        """VLM tries uniform tint 200° with chroma 0.15/0.12/0.10.  All 3
        reference zones report high confidence (0.90) but hue_mode='neutral'
        (the extractor found colour but doesn't call this an intentional
        monochrome grade).  Outcome path:
          * 2.1: conf 0.90 >= 0.85 in all 3 zones → relaxed caps
            (0.15/0.15/0.10) so the aggressive values (0.15/0.12/0.10)
            survive unchanged.
          * 2.3: same_hue (all 200°) + all chroma > 0.05 → fires.
            reference_analysis hue_modes are 'neutral' (NOT 'mono') in
            the 3 zones → ``allow`` is False → halve each chroma.
        Final: shadows_C=0.075, midtones_C=0.06, highlights_C=0.05.
        """
        ref = {
            "shadows_hue": 200.0,
            "shadows_hue_confidence": 0.90,
            "shadows_hue_mode": "neutral",  # not intentionally mono
            "midtones_hue": None,
            "midtones_hue_confidence": 0.90,
            "midtones_hue_mode": "neutral",
            "highlights_hue": None,
            "highlights_hue_confidence": 0.90,
            "highlights_hue_mode": "neutral",
            "shadows_sat": 0.50,
            "midtones_sat": 0.50,
            "highlights_sat": 0.50,
        }
        # 0.15/0.12/0.10 - all within high-conf caps (0.15/0.15/0.10)
        vlm = self._AGGRESSIVE_SLOT.format(shc=0.15, mc=0.12, hc=0.10)
        spec, warnings = self._parse_and_validate(vlm, ref)
        cb = next(p for p in spec.plugins if p.operation == "colorbalancergb")
        params = cb.params
        # 2.3 halves all three chromas (same hue 200° + all chroma > 0.05)
        assert params["shadows_C"] == 0.075, params["shadows_C"]
        assert params["midtones_C"] == 0.06, params["midtones_C"]
        assert params["highlights_C"] == 0.05, params["highlights_C"]
        assert any("monochrome-dominance" in w for w in warnings)

    def test_prompt_and_validator_agree_on_neutral_reference(self) -> None:
        """Cross-check: when reference_analysis = neutral everywhere, the
        prompt's dynamic chroma caps emit 0.000 for all three zones AND the
        validator's default caps also clamp any non-zero chroma the VLM
        tries to emit.  This guarantees prompt guidance and post-validator
        are coherent (Hito 2.1 ↔ Hito 3 chroma caps block).
        """
        from dtstylekit.vlm.prompt_builder import _chroma_caps_block

        ref = {
            "shadows_hue": None,
            "shadows_hue_confidence": 0.20,
            "shadows_hue_mode": "neutral",
            "shadows_sat": 0.0,
            "midtones_hue": None,
            "midtones_hue_confidence": 0.20,
            "midtones_hue_mode": "neutral",
            "midtones_sat": 0.0,
            "highlights_hue": None,
            "highlights_hue_confidence": 0.20,
            "highlights_hue_mode": "neutral",
            "highlights_sat": 0.0,
        }
        # Prompt block: all neutral → caps 0.000
        block = _chroma_caps_block(ref)
        assert "SET shadows_C = 0.000" in block
        assert "SET midtones_C = 0.000" in block
        assert "SET highlights_C = 0.000" in block

        # Validator: the VLM tries chroma 0.20 everywhere with non-neutral
        # hue → 2.1 default caps clamp each *_C to the soft ceiling (0.10 /
        # 0.08 / 0.05), and 2.3 sees "all chroma > 0.05" → halves them.
        vlm = self._AGGRESSIVE_SLOT.format(shc=0.20, mc=0.20, hc=0.20)
        spec, _ = self._parse_and_validate(vlm, ref)
        # With ref_conf < 0.7, the default caps clamp 0.20 → 0.10/0.08/0.05.
        # highlights cap 0.05 is NOT > 0.05 strict, so 2.3 does not fire on
        # the strict gate and values keep the default-cap clamps.
        cb = next(p for p in spec.plugins if p.operation == "colorbalancergb")
        params = cb.params
        assert params["shadows_C"] == 0.10
        assert params["midtones_C"] == 0.08
        assert params["highlights_C"] == 0.05
