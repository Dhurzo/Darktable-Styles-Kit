"""Tests for the signature-fidelity auto-fit (dtstylekit/vlm/fidelity.py)."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from dtstylekit.vlm.fidelity import auto_fit_signature
from dtstylekit.vlm.models import Plugin, StyleSpec


@dataclass
class _Lum:
    mean: float = 0.35
    saturation_mean: float = 0.29


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
        "midtones_hue_confidence": 0.55,
        "midtones_hue_mode": "global",
        "highlights_hue": 16.1,
        "highlights_hue_confidence": 1.0,
        "highlights_hue_mode": "global",
    }
    base.update(overrides)
    return base


class TestSaturationFit:
    def test_desaturates_when_refs_are_muted(self):
        """Refs sat 0.086 vs scene 0.29 (ratio 0.30) → colorequal desaturation
        sat_* ≈ 1-(1-0.30)/1.44 = 0.51 (measured render calibration)."""
        spec = _spec()
        out, warns = auto_fit_signature(spec, _ref_analysis(), _Analysis())
        ce = next(p for p in out.plugins if p.operation == "colorequal")
        assert ce.params["sat_red"] == pytest.approx(0.51, abs=0.02)
        assert ce.params["sat_blue"] == pytest.approx(0.51, abs=0.02)
        assert any("FIDELITY saturation" in w for w in warns)

    def test_no_change_when_saturation_close(self):
        """ratio ~0.9 → no desaturation added."""
        spec = _spec()
        out, warns = auto_fit_signature(spec, _ref_analysis(global_saturation=0.26), _Analysis())
        assert not any(p.operation == "filmicrgb" for p in out.plugins)
        assert not any("FIDELITY saturation" in w for w in warns)

    def test_boosts_vibrance_when_refs_more_saturated(self):
        """ratio 1.8 → positive vibrance."""
        spec = _spec()
        out, _warns = auto_fit_signature(spec, _ref_analysis(global_saturation=0.52), _Analysis())
        cb = next(p for p in out.plugins if p.operation == "colorbalancergb")
        assert cb.params["vibrance"] > 0.1

    def test_never_weakens_existing_desaturation(self):
        """If the VLM already set filmicrgb.saturation=-80 (stronger than
        the fitted target), the fit must not soften it back toward 0."""
        filmic = Plugin(
            operation="filmicrgb", enabled=True, multi_name="", params={"saturation": -80.0}
        )
        out, _ = auto_fit_signature(_spec(filmic), _ref_analysis(), _Analysis())
        filmic2 = next(p for p in out.plugins if p.operation == "filmicrgb")
        assert filmic2.params["saturation"] == -80.0

    def test_strengthens_insufficient_desaturation(self):
        """If the VLM set sat_*=0.8 but the refs demand ≈0.51, reinforce."""
        ce0 = Plugin(
            operation="colorequal",
            enabled=True,
            multi_name="",
            params={"sat_red": 0.8, "sat_green": 0.8, "sat_blue": 0.8},
        )
        out, _ = auto_fit_signature(_spec(ce0), _ref_analysis(), _Analysis())
        ce = next(p for p in out.plugins if p.operation == "colorequal")
        assert ce.params["sat_red"] == pytest.approx(0.51, abs=0.02)


class TestToneFit:
    def test_darkens_when_refs_darker_than_scene(self):
        """refs lum 0.233 vs scene 0.35 → EV ≈ -0.59 → exposure set negative
        (this is the cafe-look failure mode: the VLM had set +0.3)."""
        exposure = Plugin(
            operation="exposure", enabled=True, multi_name="", params={"exposure": 0.3}
        )
        out, warns = auto_fit_signature(_spec(exposure), _ref_analysis(), _Analysis())
        exp = next(p for p in out.plugins if p.operation == "exposure")
        assert exp.params["exposure"] < 0
        assert any("FIDELITY tone" in w for w in warns)

    def test_brightens_when_refs_brighter(self):
        """refs lum 0.5 vs scene 0.3 → EV ≈ +0.74 → exposure positive."""
        out, _ = auto_fit_signature(_spec(), _ref_analysis(global_luminance=0.5), _Analysis())
        exp = next(p for p in out.plugins if p.operation == "exposure")
        assert exp.params["exposure"] > 0.3

    def test_keeps_exposure_when_close(self):
        """EV target within ±0.3 of the spec → untouched."""
        exposure = Plugin(
            operation="exposure", enabled=True, multi_name="", params={"exposure": 0.0}
        )
        out, warns = auto_fit_signature(
            _spec(exposure), _ref_analysis(global_luminance=0.30), _Analysis()
        )
        exp = next(p for p in out.plugins if p.operation == "exposure")
        assert exp.params["exposure"] == 0.0
        assert not any("FIDELITY tone" in w for w in warns)


class TestWarmthFit:
    def test_sets_missing_chroma_with_ref_hue(self):
        """Confident ref hue but no chroma in the spec → hue + subtle chroma."""
        out, warns = auto_fit_signature(_spec(), _ref_analysis(), _Analysis())
        cb = next(p for p in out.plugins if p.operation == "colorbalancergb")
        # shadows: conf 1.0, mode global → cap 0.02
        assert cb.params["shadows_H"] == pytest.approx(14.3)
        assert cb.params["shadows_C"] == pytest.approx(0.02)
        # highlights: conf 1.0, mode global → cap 0.012
        assert cb.params["highlights_C"] == pytest.approx(0.012)
        # midtones: conf 0.55 < 0.7 → untouched
        assert "midtones_C" not in cb.params
        assert any("FIDELITY warmth" in w for w in warns)

    def test_global_mode_respects_caps(self):
        """mode='global' chroma must never exceed the 6F caps."""
        out, _ = auto_fit_signature(_spec(), _ref_analysis(), _Analysis())
        cb = next(p for p in out.plugins if p.operation == "colorbalancergb")
        assert cb.params["shadows_C"] <= 0.02
        assert cb.params["highlights_C"] <= 0.012

    def test_bidirectional_gets_subtle_chroma(self):
        """mode='bi' with high confidence → chroma 0.05."""
        out, _ = auto_fit_signature(
            _spec(),
            _ref_analysis(
                shadows_hue_mode="bi", midtones_hue_confidence=0.9, midtones_hue_mode="bi"
            ),
            _Analysis(),
        )
        cb = next(p for p in out.plugins if p.operation == "colorbalancergb")
        assert cb.params["midtones_C"] == pytest.approx(0.05)
        assert cb.params["midtones_H"] == pytest.approx(9.7)

    def test_keeps_existing_visible_chroma(self):
        """If the spec already carries chroma ≥ 0.02 in a zone, don't touch it."""
        cb0 = Plugin(
            operation="colorbalancergb",
            enabled=True,
            multi_name="",
            params={"shadows_C": 0.08, "shadows_H": 200.0},
        )
        out, warns = auto_fit_signature(_spec(cb0), _ref_analysis(), _Analysis())
        cb = next(p for p in out.plugins if p.operation == "colorbalancergb")
        assert cb.params["shadows_H"] == 200.0
        assert cb.params["shadows_C"] == 0.08
        # only the highlights zone gets fitted
        assert not any("shadows" in w for w in warns if "FIDELITY warmth" in w)


class TestNoop:
    def test_noop_without_references(self):
        spec = _spec(
            Plugin(operation="exposure", enabled=True, multi_name="", params={"exposure": 0.5})
        )
        out, warns = auto_fit_signature(spec, None, _Analysis())
        exp = next(p for p in out.plugins if p.operation == "exposure")
        assert exp.params["exposure"] == 0.5
        assert warns == []


class TestWarmthCap:
    def test_caps_chroma_proportional_to_ref_saturation(self):
        """Nishimura regression: midtones_sat 0.38 → C cap 0.115; a spec
        with C=0.15 (full-image blue tint) gets clamped."""
        cb0 = Plugin(
            operation="colorbalancergb",
            enabled=True,
            multi_name="",
            params={"midtones_C": 0.15, "midtones_H": 195.7, "shadows_C": 0.15, "shadows_H": 191.3},
        )
        ref = _ref_analysis(
            midtones_hue=195.7,
            midtones_hue_confidence=1.0,
            midtones_hue_mode="bi",
            shadows_hue=191.3,
            shadows_hue_confidence=1.0,
            shadows_hue_mode="mono",
        )
        ref["midtones_sat"] = 0.383
        ref["shadows_sat"] = 0.158
        out, warns = auto_fit_signature(_spec(cb0), ref, _Analysis())
        cb = next(p for p in out.plugins if p.operation == "colorbalancergb")
        assert cb.params["midtones_C"] == pytest.approx(0.057, abs=0.002)
        assert cb.params["shadows_C"] == pytest.approx(0.024, abs=0.002)
        assert any("FIDELITY warmth cap" in w for w in warns)

    def test_keeps_chroma_below_cap(self):
        """C already under the cap → untouched."""
        cb0 = Plugin(
            operation="colorbalancergb",
            enabled=True,
            multi_name="",
            params={"midtones_C": 0.05, "midtones_H": 195.7},
        )
        ref = _ref_analysis(midtones_hue_confidence=1.0, midtones_hue_mode="bi")
        ref["midtones_sat"] = 0.383
        out, warns = auto_fit_signature(_spec(cb0), ref, _Analysis())
        cb = next(p for p in out.plugins if p.operation == "colorbalancergb")
        assert cb.params["midtones_C"] == 0.05
        assert not any("warmth cap" in w for w in warns)


class TestSaturationFitBN:
    def test_bn_references_demand_full_desaturation(self):
        """B/N refs (sat 0.0) vs colorful scene → monochrome IOP +
        colorequal floor (filmic saturation is not a desaturator)."""
        out, _warns = auto_fit_signature(_spec(), _ref_analysis(global_saturation=0.0), _Analysis())
        assert any(p.operation == "monochrome" for p in out.plugins)
        ce = next(p for p in out.plugins if p.operation == "colorequal")
        assert ce.params["sat_red"] == pytest.approx(0.15)


class TestMonochromeFit:
    def test_bn_refs_add_monochrome_iop(self):
        """B/N refs (sat 0.0) → the monochrome IOP is added (filmic sat
        cannot reach zero — measured -100 still leaves 35%)."""
        out, warns = auto_fit_signature(_spec(), _ref_analysis(global_saturation=0.0), _Analysis())
        mono = next(p for p in out.plugins if p.operation == "monochrome")
        assert mono.params["a"] == 0.0 and mono.params["b"] == 0.0
        ce = next(p for p in out.plugins if p.operation == "colorequal")
        assert ce.params["sat_red"] == pytest.approx(0.15)
        assert any("FIDELITY monochrome" in w for w in warns)
