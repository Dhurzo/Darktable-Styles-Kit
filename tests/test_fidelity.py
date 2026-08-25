"""Tests for the minimal safety-guard fidelity module."""

from __future__ import annotations

from dataclasses import dataclass, field

from dtstylekit.vlm.fidelity import auto_fit_signature
from dtstylekit.vlm.models import Plugin, StyleSpec


@dataclass
class _Lum:
    mean: float = 0.35
    std: float = 0.114
    saturation_mean: float = 0.29
    saturation_p90: float = 0.52


@dataclass
class _Analysis:
    luminance: _Lum = field(default_factory=_Lum)


def _spec(*plugins: Plugin) -> StyleSpec:
    return StyleSpec(
        style_name="t",
        style_description="",
        rationale="",
        plugins=list(plugins),
    )


def _ref_analysis(**overrides) -> dict:
    base = {
        "global_saturation": 0.086,
        "global_luminance": 0.233,
        "shadows_hue": 14.3,
        "shadows_hue_confidence": 1.0,
        "shadows_hue_mode": "global",
        "midtones_hue": 9.7,
        "midtones_hue_confidence": 0.4,
        "midtones_hue_mode": "global",
        "highlights_hue": 16.1,
        "highlights_hue_confidence": 1.0,
        "highlights_hue_mode": "global",
    }
    base.update(overrides)
    return base


def _ref_analysis_bn(**overrides) -> dict:
    base = _ref_analysis(global_saturation=0.0, global_luminance=0.23)
    base.update(overrides)
    return base


class TestSaturationFit:
    def test_bn_refs_add_monochrome_iop(self):
        """B/N refs (sat 0.0) → monochrome IOP added (filmic sat not a desaturator)."""
        out, warns = auto_fit_signature(_spec(), _ref_analysis(global_saturation=0.0), _Analysis())
        mono = next(p for p in out.plugins if p.operation == "monochrome")
        assert mono.params["a"] == 0.0 and mono.params["b"] == 0.0
        assert any("FIDELITY monochrome" in w for w in warns)

    def test_desaturates_when_refs_are_muted(self):
        """Refs with low saturation (0.086) vs scene 0.29 → NO auto desaturation.
        The VLM decides saturation; fidelity only clamps impossible values."""
        _out, warns = auto_fit_signature(_spec(), _ref_analysis(), _Analysis())
        # No auto-desaturation — VLM decides
        assert not any("FIDELITY saturation" in w for w in warns)

    def test_boosts_vibrance_when_refs_more_saturated(self):
        """Refs more saturated than scene → NO auto vibrance boost.
        VLM decides saturation."""
        _out, warns = auto_fit_signature(
            _spec(), _ref_analysis(global_saturation=0.52), _Analysis()
        )
        assert not any("FIDELITY saturation" in w for w in warns)

    def test_no_auto_desaturation(self):
        """No automatic desaturation via filmic/colorequal — VLM decides."""
        _out, warns = auto_fit_signature(_spec(), _ref_analysis(), _Analysis())
        assert not any("FIDELITY saturation" in w for w in warns)


class TestToneFit:
    def test_darkens_when_refs_darker_than_scene(self):
        """Refs darker than scene → NO auto exposure bump."""
        exp = Plugin(operation="exposure", enabled=True, multi_name="", params={"exposure": 0.0})
        out, warns = auto_fit_signature(
            _spec(exp), _ref_analysis(global_luminance=0.15), _Analysis()
        )
        exp = next(p for p in out.plugins if p.operation == "exposure")
        assert exp.params.get("exposure", 0.0) == 0.0
        assert not any("FIDELITY tone" in w for w in warns)

    def test_brightens_when_refs_brighter(self):
        """Refs brighter than scene → NO auto exposure bump."""
        exp = Plugin(operation="exposure", enabled=True, multi_name="", params={"exposure": 0.0})
        out, warns = auto_fit_signature(
            _spec(exp), _ref_analysis(global_luminance=0.5), _Analysis()
        )
        exp = next(p for p in out.plugins if p.operation == "exposure")
        assert exp.params.get("exposure", 0.0) == 0.0
        assert not any("FIDELITY tone" in w for w in warns)

    def test_keeps_exposure_when_close(self):
        """Luminance close → no change."""
        exp = Plugin(operation="exposure", enabled=True, multi_name="", params={"exposure": 0.1})
        out, warns = auto_fit_signature(
            _spec(exp), _ref_analysis(global_luminance=0.23), _Analysis()
        )
        exp = next(p for p in out.plugins if p.operation == "exposure")
        assert exp.params.get("exposure", 0.0) == 0.1
        assert not any("FIDELITY tone" in w for w in warns)


class TestMonochromeFit:
    def test_bn_refs_add_monochrome_iop(self):
        """B/N refs (sat 0.0) → monochrome IOP added."""
        out, warns = auto_fit_signature(_spec(), _ref_analysis(global_saturation=0.0), _Analysis())
        mono = next(p for p in out.plugins if p.operation == "monochrome")
        assert mono.params["a"] == 0.0 and mono.params["b"] == 0.0
        assert any("FIDELITY monochrome" in w for w in warns)


class TestWarmthFit:
    def test_sets_missing_chroma_with_ref_hue(self):
        """Confident ref hue but no chroma in spec → NO auto chroma.
        VLM decides chroma; fidelity only clamps invalid values."""
        cb0 = Plugin(operation="colorbalancergb", enabled=True, multi_name="", params={})
        out, warns = auto_fit_signature(_spec(cb0), _ref_analysis(), _Analysis())
        cb = next(p for p in out.plugins if p.operation == "colorbalancergb")
        # No auto chroma added — VLM decides
        assert "shadows_C" not in cb.params
        assert "highlights_C" not in cb.params
        assert not any("FIDELITY warmth" in w for w in warns)
        """Chroma clamped to [0, 1] if somehow out of range."""
        cb0 = Plugin(
            operation="colorbalancergb",
            enabled=True,
            multi_name="",
            params={"shadows_C": 1.5, "highlights_C": -0.5},
        )
        out, warns = auto_fit_signature(_spec(cb0), _ref_analysis(), _Analysis())
        cb = next(p for p in out.plugins if p.operation == "colorbalancergb")
        assert cb.params["shadows_C"] == 1.0  # clamped to max 1
        assert cb.params["highlights_C"] == 0.0  # clamped to min 0
