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


class TestSchemaRenderer:
    def test_renders_iop_schema(self) -> None:
        from dtstylekit.vlm.schema_renderer import render_iop_schema
        schema = render_iop_schema(IOP_REGISTRY, max_iops=5)
        assert "filmicrgb" in schema.lower() or "colorbalancergb" in schema.lower()


class TestPromptBuilder:
    def test_build_prompt_messages(self) -> None:
        from dtstylekit.vlm.prompt_builder import build_prompt

        analysis = MagicMock()
        analysis.to_prompt_dict.return_value = {"test": "data"}

        presets = []
        messages = build_prompt(analysis, presets, "warm cinematic", iop_schema="### filmicrgb", image_b64=None)
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "warm cinematic" in messages[1]["content"]

    def test_dark_image_gets_exposure_guard(self) -> None:
        """A dark image must trigger the EXPOSURE GUARD in the prompt."""
        from dtstylekit.vlm.prompt_builder import build_prompt

        analysis = MagicMock()
        analysis.to_prompt_dict.return_value = {"luminance": {"mean": 0.15}}
        analysis.luminance.mean = 0.15

        messages = build_prompt(analysis, [], "night", iop_schema="### filmicrgb")
        content = messages[1]["content"]
        assert "[EXPOSURE GUARD]" in content
        assert "DARK" in content
        assert "'day for twilight'" in content

    def test_bright_image_gets_exposure_guard(self) -> None:
        from dtstylekit.vlm.prompt_builder import build_prompt

        analysis = MagicMock()
        analysis.to_prompt_dict.return_value = {"luminance": {"mean": 0.85}}
        analysis.luminance.mean = 0.85

        messages = build_prompt(analysis, [], "sunny", iop_schema="### filmicrgb")
        content = messages[1]["content"]
        assert "[EXPOSURE GUARD]" in content
        assert "BRIGHT" in content

    def test_mid_image_no_guard(self) -> None:
        from dtstylekit.vlm.prompt_builder import build_prompt

        analysis = MagicMock()
        analysis.to_prompt_dict.return_value = {"luminance": {"mean": 0.5}}
        analysis.luminance.mean = 0.5

        messages = build_prompt(analysis, [], "neutral", iop_schema="### filmicrgb")
        assert "[EXPOSURE GUARD]" not in messages[1]["content"]


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
