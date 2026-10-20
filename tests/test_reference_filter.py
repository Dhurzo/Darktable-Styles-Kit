"""Tests for the reference consistency filter."""

from __future__ import annotations

import colorsys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from dtstylekit.analyzer.reference_filter import (
    ReferenceFilterConfig,
    extract_reference_features,
    filter_references,
    format_reference_filter_report,
)


def _make_reference(
    path: Path,
    *,
    hue: float = 30.0,
    saturation: float = 0.35,
    contrast: float = 1.0,
    brightness: float = 1.0,
    monochrome: bool = False,
) -> Path:
    """Create a small synthetic reference with controllable look.

    The image is a textured vertical luminance ramp tinted with a single
    hue, which is enough to exercise tone, colour and texture proxies
    without external fixtures.
    """
    height, width = 96, 128
    y = np.linspace(0.0, 1.0, height)[:, None]
    x = np.linspace(0.0, 1.0, width)[None, :]
    luminance = (0.05 + 0.80 * y) * (0.90 + 0.20 * np.sin(x * 6.0 * np.pi))
    luminance = np.clip((luminance - 0.5) * contrast + 0.5, 0.0, 1.0)
    luminance = np.clip(luminance * brightness, 0.0, 1.0)
    red, green, blue = colorsys.hsv_to_rgb((hue % 360.0) / 360.0, saturation, 1.0)
    if monochrome:
        rgb = np.stack([luminance, luminance, luminance], axis=-1)
    else:
        rgb = np.stack([luminance * red, luminance * green, luminance * blue], axis=-1)
    Image.fromarray((rgb * 255.0).astype(np.uint8)).save(path, quality=90)
    return path


@pytest.fixture
def clean_refs(tmp_path: Path) -> list[Path]:
    return [
        _make_reference(tmp_path / "a.jpg", hue=30.0, saturation=0.35),
        _make_reference(
            tmp_path / "b.jpg",
            hue=34.0,
            saturation=0.37,
            contrast=1.03,
            brightness=1.02,
        ),
        _make_reference(
            tmp_path / "c.jpg",
            hue=27.0,
            saturation=0.33,
            contrast=0.98,
            brightness=0.98,
        ),
    ]


def test_clean_set_is_kept(clean_refs: list[Path]) -> None:
    result = filter_references(clean_refs)

    assert set(result.kept) == set(clean_refs)
    assert result.dropped == []
    assert result.outliers == []
    assert result.error is None
    assert result.medoid in clean_refs
    assert "all 3 reference(s) consistent" in result.summary


@pytest.mark.parametrize(
    "outlier_kwargs",
    [
        {"hue": 350.0, "saturation": 0.90, "contrast": 1.8},
        {"monochrome": True},
        {"contrast": 0.15},
        {"contrast": 2.5},
        {"brightness": 0.35},
        {"brightness": 1.8},
        {"hue": 350.0, "saturation": 0.75},
    ],
)
def test_outlier_is_dropped(
    clean_refs: list[Path],
    tmp_path: Path,
    outlier_kwargs: dict,
) -> None:
    outlier = _make_reference(tmp_path / "outlier.jpg", **outlier_kwargs)

    result = filter_references([*clean_refs, outlier])

    assert set(result.kept) == set(clean_refs)
    assert result.dropped == [outlier]
    assert outlier in result.outliers
    assert result.error is None
    assert any("dropped outlier.jpg" in warning for warning in result.warnings)


def test_warn_mode_reports_without_dropping(
    clean_refs: list[Path],
    tmp_path: Path,
) -> None:
    outlier = _make_reference(tmp_path / "outlier.jpg", saturation=0.9, hue=350.0)

    result = filter_references(
        [*clean_refs, outlier],
        ReferenceFilterConfig(mode="warn"),
    )

    assert set(result.kept) == {*clean_refs, outlier}
    assert result.dropped == []
    assert result.outliers == [outlier]
    assert any("would drop" in warning for warning in result.warnings)


def test_off_mode_preserves_legacy_behaviour(
    clean_refs: list[Path],
    tmp_path: Path,
) -> None:
    outlier = _make_reference(tmp_path / "outlier.jpg", monochrome=True)

    result = filter_references(
        [*clean_refs, outlier],
        ReferenceFilterConfig(mode="off"),
    )

    assert set(result.kept) == {*clean_refs, outlier}
    assert result.dropped == []
    assert result.features == {}
    assert result.summary == ""
    assert format_reference_filter_report(result) == []


def test_invalid_reference_is_skipped(
    clean_refs: list[Path],
    tmp_path: Path,
) -> None:
    invalid = tmp_path / "broken.jpg"
    invalid.write_bytes(b"not an image")

    result = filter_references([*clean_refs, invalid])

    assert set(result.kept) == set(clean_refs)
    assert invalid in result.dropped
    assert any("skipped unreadable" in warning for warning in result.warnings)


def test_two_references_are_not_filtered(tmp_path: Path) -> None:
    refs = [
        _make_reference(tmp_path / "warm.jpg", hue=30.0),
        _make_reference(tmp_path / "mono.jpg", monochrome=True),
    ]

    result = filter_references(refs)

    assert set(result.kept) == set(refs)
    assert result.dropped == []
    assert any("fewer than 3" in note for note in result.notes)


def test_order_does_not_change_selection(clean_refs: list[Path], tmp_path: Path) -> None:
    outlier = _make_reference(tmp_path / "outlier.jpg", monochrome=True)
    refs = [*clean_refs, outlier]

    forward = filter_references(refs)
    backward = filter_references(list(reversed(refs)))

    assert forward.kept == backward.kept
    assert forward.dropped == backward.dropped
    assert forward.medoid == backward.medoid


def test_strict_mode_errors_when_no_group_is_consistent(tmp_path: Path) -> None:
    refs = [
        _make_reference(tmp_path / "warm.jpg", hue=30.0),
        _make_reference(tmp_path / "vivid.jpg", hue=350.0, saturation=0.9),
        _make_reference(tmp_path / "mono.jpg", monochrome=True, contrast=2.0),
        _make_reference(tmp_path / "bright.jpg", brightness=1.9),
    ]

    result = filter_references(refs, ReferenceFilterConfig(mode="strict"))

    assert result.error is not None
    assert "No consistent reference group" in result.error
    assert set(result.kept) == set(refs)


def test_strict_mode_errors_when_group_is_smaller_than_min_refs(
    clean_refs: list[Path],
    tmp_path: Path,
) -> None:
    outlier = _make_reference(tmp_path / "outlier.jpg", monochrome=True)
    config = ReferenceFilterConfig(mode="strict", min_refs=4)

    result = filter_references([*clean_refs, outlier], config)

    assert result.error is not None
    assert "No consistent reference group" in result.error
    assert set(result.kept) == {*clean_refs, outlier}


def test_match_both_still_drops_outlier(
    clean_refs: list[Path],
    tmp_path: Path,
) -> None:
    outlier = _make_reference(tmp_path / "outlier.jpg", brightness=1.9)
    config = ReferenceFilterConfig(mode="auto", match="both")

    result = filter_references([*clean_refs, outlier], config)

    assert outlier in result.dropped
    assert len(result.kept) == 3


def test_report_contains_decision_table(clean_refs: list[Path], tmp_path: Path) -> None:
    outlier = _make_reference(tmp_path / "outlier.jpg", monochrome=True)

    result = filter_references([*clean_refs, outlier])
    report = format_reference_filter_report(result)

    assert report[0] == "## Reference Consistency"
    assert any("Tone distance" in line for line in report)
    assert any("`outlier.jpg` | dropped" in line for line in report)
    assert any("`a.jpg` | kept" in line for line in report)


def test_features_are_serialisable(clean_refs: list[Path]) -> None:
    feature = extract_reference_features(clean_refs[0])
    payload = feature.to_dict()

    assert payload["path"] == str(clean_refs[0])
    assert payload["monochrome"] is False
    assert set(payload["zones"]) == {"shadows", "midtones", "highlights"}


def test_invalid_config_is_rejected() -> None:
    with pytest.raises(ValueError, match="min_refs"):
        ReferenceFilterConfig(min_refs=1)
    with pytest.raises(ValueError, match="thresholds"):
        ReferenceFilterConfig(edit_threshold=0)
    with pytest.raises(ValueError, match="thresholds"):
        ReferenceFilterConfig(tone_threshold=0)
