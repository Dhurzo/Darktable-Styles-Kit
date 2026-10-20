"""Tests for the minimal safety-guard fidelity module."""

from __future__ import annotations

from dataclasses import dataclass, field

from dtstylekit.vlm.fidelity import auto_fit_signature, compute_reference_profile
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
    def test_no_auto_chroma_added(self):
        """Confident ref hue but no chroma in spec → NO auto chroma.
        VLM decides chroma; fidelity only clamps invalid values."""
        cb0 = Plugin(operation="colorbalancergb", enabled=True, multi_name="", params={})
        out, warns = auto_fit_signature(_spec(cb0), _ref_analysis(), _Analysis())
        cb = next(p for p in out.plugins if p.operation == "colorbalancergb")
        assert "shadows_C" not in cb.params
        assert "highlights_C" not in cb.params
        assert not any("FIDELITY warmth" in w for w in warns)


class TestSafetyGuards:
    """The absolute safety clamps (the ONLY behavior of the module)."""

    def test_filmic_saturation_clamped_high(self):
        filmic = Plugin(
            operation="filmicrgb", enabled=True, multi_name="", params={"saturation": 150.0}
        )
        out, warns = auto_fit_signature(_spec(filmic), _ref_analysis(), _Analysis())
        f = next(p for p in out.plugins if p.operation == "filmicrgb")
        assert f.params["saturation"] == 100.0
        assert any("filmicrgb.saturation clamped" in w for w in warns)

    def test_filmic_saturation_clamped_low(self):
        filmic = Plugin(
            operation="filmicrgb", enabled=True, multi_name="", params={"saturation": -150.0}
        )
        out, _ = auto_fit_signature(_spec(filmic), _ref_analysis(), _Analysis())
        f = next(p for p in out.plugins if p.operation == "filmicrgb")
        assert f.params["saturation"] == -100.0

    def test_filmic_contrast_latitude_balance_clamped(self):
        filmic = Plugin(
            operation="filmicrgb",
            enabled=True,
            multi_name="",
            params={"contrast": 10.0, "latitude": 20.0, "balance": -20.0},
        )
        out, _ = auto_fit_signature(_spec(filmic), _ref_analysis(), _Analysis())
        f = next(p for p in out.plugins if p.operation == "filmicrgb")
        assert f.params["contrast"] == 5.0
        assert f.params["latitude"] == 10.0
        assert f.params["balance"] == -10.0

    def test_exposure_clamped(self):
        exp_hi = Plugin(
            operation="exposure", enabled=True, multi_name="", params={"exposure": 10.0}
        )
        out, _ = auto_fit_signature(_spec(exp_hi), _ref_analysis(), _Analysis())
        assert next(p for p in out.plugins if p.operation == "exposure").params["exposure"] == 4.0

        exp_lo = Plugin(
            operation="exposure", enabled=True, multi_name="", params={"exposure": -10.0}
        )
        out, warns = auto_fit_signature(_spec(exp_lo), _ref_analysis(), _Analysis())
        assert next(p for p in out.plugins if p.operation == "exposure").params["exposure"] == -4.0
        assert any("exposure clamped" in w for w in warns)

    def test_colorbalance_chroma_clamped(self):
        cb0 = Plugin(
            operation="colorbalancergb",
            enabled=True,
            multi_name="",
            params={"shadows_C": 1.5, "highlights_C": -0.5},
        )
        out, warns = auto_fit_signature(_spec(cb0), _ref_analysis(), _Analysis())
        cb = next(p for p in out.plugins if p.operation == "colorbalancergb")
        assert cb.params["shadows_C"] == 1.0
        assert cb.params["highlights_C"] == 0.0
        assert any("highlights_C clamped to 0" in w for w in warns)

    def test_colorbalance_hue_clamped_and_wrapped(self):
        cb0 = Plugin(
            operation="colorbalancergb",
            enabled=True,
            multi_name="",
            params={"shadows_H": -10.0, "highlights_H": 400.0},
        )
        out, warns = auto_fit_signature(_spec(cb0), _ref_analysis(), _Analysis())
        cb = next(p for p in out.plugins if p.operation == "colorbalancergb")
        assert cb.params["shadows_H"] == 0.0
        assert cb.params["highlights_H"] == 40.0  # 400 % 360
        assert any("highlights_H wrapped" in w for w in warns)

    def test_noop_without_references(self):
        exp = Plugin(operation="exposure", enabled=True, multi_name="", params={"exposure": 0.5})
        out, warns = auto_fit_signature(_spec(exp), None, _Analysis())
        exp = next(p for p in out.plugins if p.operation == "exposure")
        assert exp.params["exposure"] == 0.5
        assert warns == []


class TestReferenceProfile:
    def test_compute_reference_profile(self, tmp_path):
        """Profile computed and contains the expected keys."""
        import numpy as np
        from PIL import Image

        im = np.zeros((100, 100, 3), dtype=np.uint8)
        im[:, :, 0] = 200
        im[:, :, 1] = 100
        im[:, :, 2] = 50
        Image.fromarray(im).save(tmp_path / "ref1.jpg")
        Image.fromarray(im).save(tmp_path / "ref2.jpg")

        profile = compute_reference_profile([tmp_path / "ref1.jpg", tmp_path / "ref2.jpg"])

        assert "global_contrast" in profile
        assert "global_dynamic_range" in profile
        assert "global_saturation_p90" in profile
        assert "global_warmth_rb" in profile


class TestGentleNudge:
    """The gentle target-nudge corrects gross VLM mismatches WITHOUT
    overriding creative intent."""

    def test_nudges_desaturated_toward_vivid_ref(self):
        """Colorful reference (0.30) but VLM set saturation=-60 → nudge up."""
        filmic = Plugin(
            operation="filmicrgb", enabled=True, multi_name="", params={"saturation": -60.0}
        )
        out, warns = auto_fit_signature(
            _spec(filmic), _ref_analysis(global_saturation=0.30), _Analysis()
        )
        f = next(p for p in out.plugins if p.operation == "filmicrgb")
        # Closer to the vivid target (+5) than -60, but not a hard override.
        assert f.params["saturation"] > -60.0
        assert any("FIDELITY nudge" in w for w in warns)

    def test_nudges_vivid_toward_muted_ref(self):
        """Muted reference (0.05) but VLM set saturation=+60 → nudge down."""
        filmic = Plugin(
            operation="filmicrgb", enabled=True, multi_name="", params={"saturation": 60.0}
        )
        out, warns = auto_fit_signature(
            _spec(filmic), _ref_analysis(global_saturation=0.05), _Analysis()
        )
        f = next(p for p in out.plugins if p.operation == "filmicrgb")
        assert f.params["saturation"] < 60.0
        assert any("FIDELITY nudge" in w for w in warns)

    def test_no_nudge_when_close_to_target(self):
        """Natural reference (0.20) and mild saturation (-10) → leave alone."""
        filmic = Plugin(
            operation="filmicrgb", enabled=True, multi_name="", params={"saturation": -10.0}
        )
        out, warns = auto_fit_signature(
            _spec(filmic), _ref_analysis(global_saturation=0.20), _Analysis()
        )
        f = next(p for p in out.plugins if p.operation == "filmicrgb")
        assert f.params["saturation"] == -10.0
        assert not any("FIDELITY nudge" in w for w in warns)

    def test_chroma_nudged_toward_reference_saturation(self):
        """VLM left chroma at 0 but reference zone is colorful → gentle chroma."""
        cb = Plugin(
            operation="colorbalancergb",
            enabled=True,
            multi_name="",
            params={"shadows_C": 0.0, "midtones_C": 0.0, "highlights_C": 0.0},
        )
        ref = _ref_analysis(shadows_sat=0.5)
        out, warns = auto_fit_signature(_spec(cb), ref, _Analysis())
        c = next(p for p in out.plugins if p.operation == "colorbalancergb")
        assert c.params["shadows_C"] > 0.0
        assert any("FIDELITY nudge" in w and "shadows_C" in w for w in warns)

    def test_chroma_not_nudged_for_neutral_zone(self):
        """A neutral zone (no declared grade) must stay neutral even if a
        leftover saturation estimate exceeds the threshold; fidelity runs
        after the validator and previously re-tinted midtones at hue 0."""
        cb = Plugin(
            operation="colorbalancergb",
            enabled=True,
            multi_name="",
            params={"midtones_C": 0.0},
        )
        ref = _ref_analysis(
            midtones_sat=0.5,
            midtones_hue_mode="neutral",
            midtones_hue_confidence=0.0,
        )
        out, warns = auto_fit_signature(_spec(cb), ref, _Analysis())
        c = next(p for p in out.plugins if p.operation == "colorbalancergb")
        assert c.params["midtones_C"] == 0.0
        assert not any("FIDELITY nudge" in w and "midtones_C" in w for w in warns)

    def test_warmth_nudges_hue_toward_reference_grade(self):
        """Warm reference but VLM set a cool midtones hue → nudge warm."""
        cb = Plugin(
            operation="colorbalancergb",
            enabled=True,
            multi_name="",
            params={"midtones_C": 0.05, "midtones_H": 200.0},
        )
        ref = _ref_analysis(global_warmth_rb=0.10)
        out, warns = auto_fit_signature(_spec(cb), ref, _Analysis())
        c = next(p for p in out.plugins if p.operation == "colorbalancergb")
        # 200° (cool) nudged halfway toward 45° (warm) ≈ 122.5°
        assert 90.0 < c.params["midtones_H"] < 200.0
        assert any("FIDELITY nudge" in w and "warm reference" in w for w in warns)
