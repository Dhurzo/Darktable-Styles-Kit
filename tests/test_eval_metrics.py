"""Tests for look-fidelity metrics."""

from dtstylekit.eval.metrics import LookFidelity, LookProfile, compare_looks


def test_look_profile_red_cast() -> None:
    profile = LookProfile(r_over_g=2.0, r_mean=0.2, b_mean=0.1)
    assert profile.has_red_cast
    assert not profile.safety_ok


def test_look_profile_crushed() -> None:
    profile = LookProfile(mean_luminance=0.05)
    assert profile.is_crushed
    assert not profile.safety_ok


def test_look_profile_blown() -> None:
    profile = LookProfile(mean_luminance=0.95, highlights_pct=0.1)
    assert profile.is_blown
    assert not profile.safety_ok


def test_look_profile_safe_defaults() -> None:
    profile = LookProfile(mean_luminance=0.5)
    assert profile.safety_ok


def test_compare_looks_identical_passes() -> None:
    profile = LookProfile(mean_luminance=0.5)
    result = compare_looks(profile, profile)
    assert isinstance(result, LookFidelity)
    assert result.passed
