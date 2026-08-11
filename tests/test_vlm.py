"""Tests for the VLM integration module (with mocked VLM)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

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
        spec = StyleSpec(style_name="test", plugins=[
            Plugin(operation="vibrance", params={"amount": 50.0}),
        ])
        validated, warnings = validate_style(spec, IOP_REGISTRY)
        assert len(validated.plugins) == 1
        assert validated.plugins[0].params["amount"] == 50.0

    def test_clamps_out_of_range(self) -> None:
        spec = StyleSpec(style_name="test", plugins=[
            Plugin(operation="vibrance", params={"amount": 999.0}),
        ])
        validated, warnings = validate_style(spec, IOP_REGISTRY)
        # vibrance range is 0..100, so 999 should be clamped to 100
        assert validated.plugins[0].params["amount"] == 100.0
        assert any("out of range" in w for w in warnings)

    def test_merges_defaults(self) -> None:
        spec = StyleSpec(style_name="test", plugins=[
            Plugin(operation="filmicrgb", params={"contrast": 1.5}),
        ])
        validated, _ = validate_style(spec, IOP_REGISTRY)
        # Defaults for filmicrgb should be merged
        assert validated.plugins[0].params["contrast"] == 1.5
        assert "grey_point_source" in validated.plugins[0].params  # default

    def test_skips_unknown_iop(self) -> None:
        spec = StyleSpec(style_name="test", plugins=[
            Plugin(operation="nonexistent_iop", params={"x": 1.0}),
        ])
        validated, warnings = validate_style(spec, IOP_REGISTRY)
        assert len(validated.plugins) == 0
        assert any("Unknown IOP" in w for w in warnings)

    def test_validates_curve_preset(self) -> None:
        """Curve-based IOPs accept ``curve_preset`` as a string."""
        spec = StyleSpec(style_name="test", plugins=[
            Plugin(
                operation="colorzones",
                params={"curve_preset": "s_strong", "strength": 50.0},
            ),
        ])
        validated, warnings = validate_style(spec, IOP_REGISTRY)
        assert len(validated.plugins) == 1
        cp = validated.plugins[0].params.get("curve_preset")
        assert cp == "s_strong"
        # A known template should *not* produce an "unknown" warning
        assert not any("not a known" in w for w in warnings)
        # And the strength scalar should still be present and clamped
        assert validated.plugins[0].params.get("strength") == 50.0

    def test_rejects_unknown_curve_template(self) -> None:
        spec = StyleSpec(style_name="test", plugins=[
            Plugin(
                operation="rgbcurve",
                params={"curve_preset": "doesnt_exist"},
            ),
        ])
        # If curve_preset is unknown the validator should emit a
        # *warning* but still keep the plugin (the LLM can recover).
        validated, warnings = validate_style(spec, IOP_REGISTRY)
        assert any("not a known curve template" in w for w in warnings)
        assert validated.plugins[0].params.get("curve_preset") is None or \
            validated.plugins[0].params.get("curve_preset") == "doesnt_exist"


class TestValidateAntiTintGuards:
    """Hitos 2.1, 2.2, 2.3: anti-tint-dominance semantic guards."""

    def _colorbalance_plugin(self, **params) -> Plugin:
        return Plugin(operation="colorbalancergb", params=params)

    # ---- 2.1: dynamic chroma ceiling -----------------------------------
    def test_default_chroma_ceiling_without_reference(self) -> None:
        """No reference_analysis → shadows_C caps at 0.10 (default)."""
        spec = StyleSpec(style_name="t", plugins=[
            self._colorbalance_plugin(shadows_C=0.4, shadows_H=200.0,
                                       midtones_C=0.4, midtones_H=200.0,
                                       highlights_C=0.4, highlights_H=200.0),
        ])
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
        spec = StyleSpec(style_name="t", plugins=[
            self._colorbalance_plugin(shadows_C=0.15, shadows_H=200.0,
                                       midtones_C=0.15, midtones_H=200.0,
                                       highlights_C=0.10, highlights_H=200.0),
        ])
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
        spec = StyleSpec(style_name="t", plugins=[
            self._colorbalance_plugin(shadows_C=0.15, shadows_H=200.0),
        ])
        ref = {"shadows_hue_confidence": 0.72}
        validated, warnings = validate_style(spec, IOP_REGISTRY, reference_analysis=ref)
        # 0.15 > default cap 0.10 → clamped down
        assert validated.plugins[0].params["shadows_C"] == 0.10
        assert any("dynamic cap" in w for w in warnings)

    # ---- 2.2: midtones protection on likely-portrait target -------------
    def test_midtones_chroma_protected_on_skin_tone_target(self) -> None:
        """Target histogram R≈G>B (skin signature) → midtones_C capped to 0.05."""
        from dtstylekit.analyzer.models import HistogramStats, ImageAnalysis

        spec = StyleSpec(style_name="t", plugins=[
            self._colorbalance_plugin(midtones_C=0.20, midtones_H=30.0),
        ])
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

        spec = StyleSpec(style_name="t", plugins=[
            self._colorbalance_plugin(midtones_C=0.08, midtones_H=30.0),
        ])
        target = ImageAnalysis(
            histogram=HistogramStats(mean_red=0.5, mean_green=0.5, mean_blue=0.5),
        )
        validated, _ = validate_style(spec, IOP_REGISTRY, target_analysis=target)
        # 0.08 is within the default ceiling, no clamp expected; definitely no skin protection
        assert validated.plugins[0].params["midtones_C"] == 0.08

    def test_midtones_not_protected_when_blue_dominant(self) -> None:
        """Target histogram with B>>R,G (cool/landscape) → no skin protection."""
        from dtstylekit.analyzer.models import HistogramStats, ImageAnalysis

        spec = StyleSpec(style_name="t", plugins=[
            self._colorbalance_plugin(midtones_C=0.08, midtones_H=200.0),
        ])
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
        spec = StyleSpec(style_name="t", plugins=[
            self._colorbalance_plugin(
                shadows_C=0.15, shadows_H=200.0,
                midtones_C=0.12, midtones_H=200.0,
                highlights_C=0.10, highlights_H=200.0,
            ),
        ])
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
        spec = StyleSpec(style_name="t", plugins=[
            self._colorbalance_plugin(
                shadows_C=0.10, shadows_H=200.0,
                midtones_C=0.08, midtones_H=200.0,
                highlights_C=0.05, highlights_H=200.0,
            ),
        ])
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
        spec = StyleSpec(style_name="t", plugins=[
            self._colorbalance_plugin(
                shadows_C=0.10, shadows_H=200.0,    # teal shadows
                midtones_C=0.08, midtones_H=0.0,    # neutral midtones (skin protected)
                highlights_C=0.05, highlights_H=30.0,  # warm highlights
            ),
        ])
        validated, warnings = validate_style(spec, IOP_REGISTRY)
        assert not any("monochrome-dominance" in w for w in warnings)

    def test_monochrome_dominance_requires_all_three_zones_chroma(self) -> None:
        """Same hue but chroma=0 in one zone → not a global tint yet."""
        spec = StyleSpec(style_name="t", plugins=[
            self._colorbalance_plugin(
                shadows_C=0.10, shadows_H=200.0,
                midtones_C=0.00, midtones_H=200.0,   # midtones neutral
                highlights_C=0.05, highlights_H=200.0,
            ),
        ])
        validated, warnings = validate_style(spec, IOP_REGISTRY)
        assert not any("monochrome-dominance" in w for w in warnings)
        # midtones stays neutral, the other two keep their chroma (already capped)

    def test_wrapped_hues_treated_as_same_for_dominance(self) -> None:
        """Hues 358°, 1°, 2° must count as the same hue (circular)."""
        spec = StyleSpec(style_name="t", plugins=[
            self._colorbalance_plugin(
                shadows_C=0.15, shadows_H=358.0,
                midtones_C=0.12, midtones_H=1.0,
                highlights_C=0.10, highlights_H=2.0,
            ),
        ])
        # Confident reference (lifts ceiling) but 'neutral' hue_mode (not mono)
        ref = {
            "shadows_hue_confidence": 0.90,
            "midtones_hue_confidence": 0.90,
            "highlights_hue_confidence": 0.90,
            "shadows_hue_mode": "neutral",
            "midtones_hue_mode": "neutral",
            "highlights_hue_mode": "neutral",
        }
        validated, warnings = validate_style(spec, IOP_REGISTRY, reference_analysis=ref)
        assert any("monochrome-dominance" in w for w in warnings)


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
        messages = build_prompt(analysis, presets, "warm cinematic", iop_schema="### filmicrgb", image_b64=None)
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
            analysis, [], "test", "schema",
            image_b64=None, reference_b64s=["fake"], reference_analysis=ref,
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
            "shadows_hue": 200.0, "shadows_hue_confidence": 0.90,
            "shadows_hue_mode": "mono", "shadows_sat": 0.50,
            "midtones_hue": 200.0, "midtones_hue_confidence": 0.90,
            "midtones_hue_mode": "mono", "midtones_sat": 0.50,
            "highlights_hue": 200.0, "highlights_hue_confidence": 0.90,
            "highlights_hue_mode": "mono", "highlights_sat": 0.50,
        }
        msgs = build_prompt(
            analysis, [], "test", "schema",
            image_b64=None, reference_b64s=["fake"], reference_analysis=ref,
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
            "shadows_hue_confidence": 0.72,   # medium → soft cap 0.10
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
            analysis, [], "test", "schema",
            image_b64=None, reference_b64s=["fake"], reference_analysis=ref,
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
            "shadows_hue": None, "shadows_hue_confidence": 0.2,
            "shadows_hue_mode": "neutral", "shadows_sat": 0.0,
            "midtones_hue": None, "midtones_hue_confidence": 0.2,
            "midtones_hue_mode": "neutral", "midtones_sat": 0.0,
            "highlights_hue": None, "highlights_hue_confidence": 0.2,
            "highlights_hue_mode": "neutral", "highlights_sat": 0.0,
        }
        msgs = build_prompt(
            analysis, [], "test", "schema",
            image_b64=None, reference_b64s=["fake"], reference_analysis=ref,
        )
        content = msgs[1]["content"]
        assert "INTENTIONAL MONOCHROME" not in content
        # All zones below 0.70 → all neutral
        assert "SET shadows_C = 0.000" in content
        assert "SET midtones_C = 0.000" in content
        assert "SET highlights_C = 0.000" in content


class TestPresetExposureFilter:
    """Luminance-suitability filter for candidate presets."""

    def _preset(self, plugins: list) -> Preset:
        from pathlib import Path

        return Preset(
            name="test", description="", iop_list="", plugins=plugins,
            file_path=Path("/tmp/x.dtstyle"), xml_hash="h",
        )

    def _exposure_ref(self, ev: float, enabled: int = 1) -> PluginRef:
        from dtstylekit.codec.iop_registry import pack_params
        from dtstylekit.codec.xmp_codec import encode_xmp

        blob = pack_params("exposure", {"exposure": ev})
        return PluginRef(
            operation="exposure", enabled=enabled, multi_name="",
            multi_priority=0, num=0, module=7, op_params=encode_xmp(blob),
            blendop_params="", blendop_version=13, multi_name_hand_edited=0,
        )

    def test_net_ev_summed_only_enabled(self) -> None:
        from dtstylekit.vlm.orchestrator import _preset_net_ev

        p = self._preset([self._exposure_ref(-1.0), self._exposure_ref(0.5, enabled=0)])
        assert _preset_net_ev(p) == -1.0

    def test_darkening_preset_rejected_for_dark_image(self) -> None:
        from dtstylekit.vlm.orchestrator import _preset_ev_fits

        p = self._preset([self._exposure_ref(-1.0)])
        assert _preset_ev_fits(p, 0.15) is False   # dark image + -1 EV → crushed
        assert _preset_ev_fits(p, 0.5) is True     # mid image → fine
        assert _preset_ev_fits(p, 0.85) is True    # bright image → fine

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
            name="dehaze strong luminance only", description="",
            iop_list="", plugins=[], file_path=Path("/tmp/x.dtstyle"),
            xml_hash="h",
        )
        assert _preset_ev_fits(p, 0.15) is False   # dark image → dropped
        assert _preset_ev_fits(p, 0.5) is True     # mid image → fine
        assert _preset_ev_fits(p, 0.85) is True    # bright image → fine
