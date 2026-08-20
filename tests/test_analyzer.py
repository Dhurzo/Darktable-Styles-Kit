"""Unit tests for the image analyzer modules."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from dtstylekit.analyzer.histogram import compute_histogram
from dtstylekit.analyzer.luminance import compute_luminance_stats
from dtstylekit.analyzer.models import HistogramStats, ImageAnalysis, LuminanceStats
from dtstylekit.analyzer.pipeline import (
    _circular_dispersion,
    _circular_mean,
    _consensus_vote,
    _detect_bimodal,
    analyze_image,
    analyze_reference_hues,
)
from dtstylekit.analyzer.scene import detect_scene


def make_image(
    mode: str = "RGB",
    size: tuple[int, int] = (64, 64),
    color: tuple[int, int, int] = (128, 128, 128),
) -> Image.Image:
    return Image.new(mode, size, color)


@pytest.fixture
def tmp_image(tmp_path: Path) -> Path:
    img = make_image()
    path = tmp_path / "test.jpg"
    img.save(path, format="JPEG")
    return path


class TestHistogram:
    def test_compute_histogram_rgb_returns_64_bins(self) -> None:
        img = make_image()
        result: HistogramStats = compute_histogram(img, bins=64)
        assert len(result.red) == 64
        assert len(result.green) == 64
        assert len(result.blue) == 64

    def test_compute_histogram_rgb_default_bins(self) -> None:
        img = make_image()
        result: HistogramStats = compute_histogram(img)
        assert len(result.red) == 64

    def test_compute_histogram_normalized_stats(self) -> None:
        img = make_image()
        result: HistogramStats = compute_histogram(img)
        assert 0.0 <= result.mean_red <= 1.0
        assert 0.0 <= result.std_red <= 1.0


class TestLuminance:
    def test_tonal_distribution_sums_to_one(self) -> None:
        img = make_image()
        result: LuminanceStats = compute_luminance_stats(img)
        total = result.shadows_pct + result.midtones_pct + result.highlights_pct
        # Values are fractions that sum to ~1.0 (=100%)
        assert 0.95 <= total <= 1.05

    def test_luminance_returns_positive_mean(self) -> None:
        img = make_image()
        result: LuminanceStats = compute_luminance_stats(img)
        assert result.mean >= 0.0


class TestScene:
    def test_detect_scene_returns_list(self) -> None:
        analysis = ImageAnalysis()
        tags = detect_scene(analysis)
        assert isinstance(tags, list)


class TestPipeline:
    def test_analyze_image_returns_analysis(self, tmp_image: Path) -> None:
        result: ImageAnalysis = analyze_image(str(tmp_image))
        assert isinstance(result, ImageAnalysis)
        assert result.width > 0
        assert result.height > 0

    def test_analyze_image_handles_missing_file(self) -> None:
        # Should not crash, should populate errors list
        result = analyze_image("/nonexistent/path/to/image.jpg")
        assert isinstance(result, ImageAnalysis)
        assert len(result.errors) > 0

    def test_to_prompt_dict_returns_compact(self, tmp_image: Path) -> None:
        result = analyze_image(str(tmp_image))
        prompt_dict = result.to_prompt_dict()
        assert "dimensions" in prompt_dict
        assert "histogram" in prompt_dict
        assert "luminance" in prompt_dict


# ---------------------------------------------------------------------------
# Helpers for reference-hue tests
# ---------------------------------------------------------------------------


def _solid_color_image(
    path: Path, size: tuple[int, int] = (128, 128), color: tuple[int, int, int] = (128, 128, 128)
) -> Path:
    """Write a solid-color JPEG. Luminance is derived from BT.709; the tonal
    zone (shadows/midtones/highlights) depends on the color."""
    Image.new("RGB", size, color).save(path, format="JPEG")
    return path


def _gradient_image(
    path: Path,
    top_color: tuple[int, int, int],
    bottom_color: tuple[int, int, int],
    size: tuple[int, int] = (128, 512),
) -> Path:
    """Vertical gradient JPEG. Top row = top_color, bottom row = bottom_color.
    Useful for placing saturated pixels in a specific tonal zone."""
    w, h = size
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    for y in range(h):
        t = y / max(h - 1, 1)
        arr[y, :, :] = [int(top_color[c] * (1 - t) + bottom_color[c] * t) for c in range(3)]
    Image.fromarray(arr, "RGB").save(path, format="JPEG")
    return path


def _hue_to_rgb(hue_deg: float, sat: float = 1.0, lum: float = 0.5) -> tuple[int, int, int]:
    """Convert HSV to 0-255 RGB. lum here is HSV value, not luminance."""
    import colorsys

    r, g, b = colorsys.hsv_to_rgb((hue_deg % 360) / 360.0, sat, lum)
    return int(r * 255), int(g * 255), int(b * 255)


def _dark_saturated_color(hue_deg: float, scale: float = 0.2) -> tuple[int, int, int]:
    """Produce a dark but saturated color so luminance < 0.25 AND delta > 0.15.

    Uses HSV(hue, 1.0, 1.0) = a fully saturated pure hue, then scales the RGB
    down to keep luminance below the shadows mask threshold (0.25).
    """
    pure = _hue_to_rgb(hue_deg, sat=1.0, lum=1.0)
    return tuple(int(c * scale) for c in pure)


class TestCircularStats:
    """Hito 1: circular statistics helpers."""

    def test_circular_mean_handles_wraparound(self) -> None:
        # 350° + 10° should mean 0°, NOT 180° (arithmetic mean pitfall)
        m = _circular_mean([350, 10], [1, 1])
        assert min(abs(m - 0), abs(m - 360)) < 1.0

    def test_circular_mean_single_value(self) -> None:
        assert abs(_circular_mean([180.0]) - 180.0) < 1e-3
        assert abs(_circular_mean([0.0]) - 0.0) < 1e-3

    def test_circular_mean_empty(self) -> None:
        assert _circular_mean([]) == 0.0

    def test_circular_dispersion_identical_high(self) -> None:
        # All same hue → dispersion ~1.0
        assert _circular_dispersion([200, 200, 200]) > 0.99

    def test_circular_dispersion_opposite_low(self) -> None:
        # Opposite hues → dispersion ~0
        assert _circular_dispersion([0, 180]) < 0.05
        assert _circular_dispersion([45, 225]) < 0.05

    def test_circular_dispersion_four_cardinals_zero(self) -> None:
        # 4 hues 90° apart cancel out exactly
        assert _circular_dispersion([0, 90, 180, 270]) < 0.05

    def test_circular_dispersion_weighted(self) -> None:
        # 90% at 0°, 10% at 180° → still high dispersion
        assert _circular_dispersion([0, 180], [0.9, 0.1]) > 0.7


class TestBimodalDetection:
    """Hito 1: bimodal hue detection."""

    def test_bimodal_detected_two_distinct_peaks(self) -> None:
        # Two clear groups: 200° (teal-ish) and 30° (orange/warm), 50/50
        hues = [200.0] * 100 + [30.0] * 100
        weights = [1.0] * 200
        result = _detect_bimodal(hues, weights)
        assert result is not None
        primary, secondary, share = result
        assert share > 0.4  # primary holds a meaningful share
        # Primary/secondary should be near 200 or 30 (within ±20°)
        peaks = sorted([primary % 360, secondary % 360])
        assert any(abs(p - 30) < 25 for p in peaks)
        assert any(abs(p - 200) < 25 for p in peaks)

    def test_bimodal_not_detected_when_single_peak(self) -> None:
        # All same hue
        hues = [180.0] * 100
        weights = [1.0] * 100
        assert _detect_bimodal(hues, weights) is None

    def test_bimodal_not_detected_when_adjacent_bins(self) -> None:
        # 10° and 25° are in adjacent 30° bins → same mode
        hues = [10.0] * 100 + [25.0] * 100
        weights = [1.0] * 200
        assert _detect_bimodal(hues, weights) is None

    def test_bimodal_not_detected_when_uniform(self) -> None:
        # Hues spread everywhere → no two dominant peaks
        hues = list(range(0, 360, 10))
        weights = [1.0] * len(hues)
        assert _detect_bimodal(hues, weights) is None

    def test_bimodal_empty(self) -> None:
        assert _detect_bimodal([], []) is None


class TestAnalyzeReferenceHues:
    """Hito 1: end-to-end reference hue analysis with circular + bimodal logic."""

    def test_empty_input_returns_neutral(self) -> None:
        result = analyze_reference_hues([])
        assert result["shadows_hue"] is None
        assert result["midtones_hue"] is None
        assert result["highlights_hue"] is None
        assert result["shadows_hue_confidence"] == 0.0
        assert result["shadows_hue_mode"] == "neutral"
        assert result["midtones_hue_mode"] == "neutral"
        assert result["highlights_hue_mode"] == "neutral"

    def test_low_saturation_gray_is_neutral(self, tmp_path: Path) -> None:
        # Pure gray image — no saturation anywhere → neutral in all zones
        p = _solid_color_image(tmp_path / "gray.jpg", color=(128, 128, 128))
        result = analyze_reference_hues([p])
        for zone in ("shadows", "midtones", "highlights"):
            assert result[f"{zone}_hue"] is None, f"{zone} should be neutral"
            assert result[f"{zone}_hue_mode"] == "neutral"
            assert result[f"{zone}_hue_confidence"] == 0.0

    def test_solid_color_single_zone_uses_circular_mean(self, tmp_path: Path) -> None:
        # Pure red image (hue 0°) in shadows (low luminance) - expect mono mode
        # Use dark saturated red so luminance<0.25 but delta>0.15.
        dark_red = _dark_saturated_color(0, scale=0.2)
        p = _solid_color_image(tmp_path / "dark_red.jpg", color=dark_red)
        result = analyze_reference_hues([p])
        # All pixels are in shadows (lum ~0.2 < 0.25). Hue 0 should be detected.
        assert result["shadows_hue_mode"] == "mono"
        # Hue near 0 (or 360 — both are red)
        sh = result["shadows_hue"]
        assert sh is not None
        assert min(abs(sh - 0), abs(sh - 360)) < 20.0
        assert result["shadows_hue_confidence"] > 0.0

    def test_wraparound_hues_combine_to_zero(self, tmp_path: Path) -> None:
        # Two references: one very slightly orange-red (hue ~5°), one slightly
        # pink-red (hue ~355°). Arithmetic mean would be 180° (catastrophic).
        # Circular mean should land near 0°.
        c1 = _dark_saturated_color(5, scale=0.2)  # near-red, slightly orange
        c2 = _dark_saturated_color(355, scale=0.2)  # near-red, slightly pink
        p1 = _solid_color_image(tmp_path / "red1.jpg", color=c1)
        p2 = _solid_color_image(tmp_path / "red2.jpg", color=c2)
        result = analyze_reference_hues([p1, p2])
        sh = result["shadows_hue"]
        assert sh is not None
        # Should be near 0° (or 360°), NOT near 180°
        assert min(abs(sh - 0), abs(sh - 360)) < 15.0, f"expected hue near 0/360, got {sh}"

    def test_dispersion_lowers_confidence_for_disagreeing_refs(self, tmp_path: Path) -> None:
        # Two refs with strongly different hues in shadows: 0° and 120°
        # Dispersion will be low → confidence drops to 0 → neutral mode
        c1 = _dark_saturated_color(0, scale=0.2)
        c2 = _dark_saturated_color(120, scale=0.2)
        p1 = _solid_color_image(tmp_path / "red.jpg", color=c1)
        p2 = _solid_color_image(tmp_path / "green.jpg", color=c2)
        result = analyze_reference_hues([p1, p2])
        # Two opposite hues → dispersion low → forced neutral
        assert result["shadows_hue_mode"] == "neutral"
        assert result["shadows_hue"] is None
        assert result["shadows_hue_confidence"] == 0.0

    def test_bimodal_reference_emits_secondary_hue(self, tmp_path: Path) -> None:
        # Build a single image with two tonal populations of distinct hues
        # in the same zone: 50% of pixels at hue 200° (teal) + 50% at hue 30°
        # (warm), all at lum<0.25 so both go to shadows.
        h, w = 256, 256
        arr = np.zeros((h, w, 3), dtype=np.uint8)
        # Top half: teal at low luminance (sat delta high enough)
        # bottom half: warm at low luminance
        for y in range(h):
            hue = 200.0 if y < h / 2 else 30.0
            # Use HSV→RGB then scale down to keep luminance < 0.25
            import colorsys

            r, g, b = colorsys.hsv_to_rgb((hue % 360) / 360.0, 0.9, 0.4)
            # Scale to a luminance just below 0.25 threshold in BT.709
            # RGB ~ (0.1, 0.18, 0.27) for teal at V=0.4 -> luminance ~0.18
            arr[y, :, 0] = int(r * 255 * 0.5)
            arr[y, :, 1] = int(g * 255 * 0.5)
            arr[y, :, 2] = int(b * 255 * 0.5)
        Image.fromarray(arr, "RGB").save(tmp_path / "bimodal.jpg", format="JPEG")
        result = analyze_reference_hues([tmp_path / "bimodal.jpg"])
        # Shadows should be bimodal with primary near 200 and secondary near 30
        # OR vice versa
        assert result["shadows_hue_mode"] == "bi"
        primary = result["shadows_hue"]
        secondary = result["shadows_hue_secondary"]
        assert primary is not None
        assert secondary is not None
        peaks = sorted([primary % 360, secondary % 360])
        # Each peak should be within 25° of one of the inputs (30, 200)
        assert any(abs(p - 30) < 30 for p in peaks)
        assert any(abs(p - 200) < 30 for p in peaks)

    def test_returns_hue_mode_field_for_each_zone(self, tmp_path: Path) -> None:
        # All zones present in the dict
        p = _solid_color_image(tmp_path / "gray.jpg", color=(128, 128, 128))
        result = analyze_reference_hues([p])
        for zone in ("shadows", "midtones", "highlights"):
            assert f"{zone}_hue_mode" in result
            assert result[f"{zone}_hue_mode"] in ("neutral", "mono", "bi")

    def test_secondary_hue_field_present(self, tmp_path: Path) -> None:
        p = _solid_color_image(tmp_path / "gray.jpg", color=(128, 128, 128))
        result = analyze_reference_hues([p])
        # Sanity: secondary hue fields exist; None for neutral
        for zone in ("shadows", "midtones", "highlights"):
            assert f"{zone}_hue_secondary" in result
            assert result[f"{zone}_hue_secondary"] is None

    def test_nonexistent_file_skipped_gracefully(self, tmp_path: Path) -> None:
        # A nonexistent path + a valid gray image should not crash
        p = _solid_color_image(tmp_path / "gray.jpg", color=(128, 128, 128))
        result = analyze_reference_hues([tmp_path / "nope.jpg", p])
        # Should return whatever the gray image gives (neutral everywhere)
        assert result["shadows_hue_mode"] == "neutral"


def _triple_zone_image(
    path: Path,
    sh_hue: float,
    mt_hue: float,
    hi_hue: float,
    size: tuple[int, int] = (128, 384),
) -> Path:
    """Three vertical bands with the given hues, one per tonal zone.

    Shadows band: hue ``sh_hue`` at low value (luma < 0.25).
    Midtones band: hue ``mt_hue`` at mid value (luma 0.25–0.75).
    Highlights band: hue ``hi_hue`` at high value (luma >= 0.75).

    Saturation is fixed at 0.9. Returns the written JPEG path.  Used by
    the Hito 6C global-grade tests: one coherent tint across the whole
    tonal range (all zone hues within ±45°).
    """
    import colorsys

    w, h = size
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    band = h // 3

    def fill(y0: int, y1: int, hue: float, v0: float, v1: float) -> None:
        for y in range(y0, y1):
            t = (y - y0) / max(y1 - y0 - 1, 1)
            v = v0 + (v1 - v0) * t
            r, g, b = colorsys.hsv_to_rgb((hue % 360) / 360.0, 0.9, v)
            arr[y, :, :] = (int(r * 255), int(g * 255), int(b * 255))

    # hue 15°: luma ≈ 0.40*V → V 0.25–0.55 keeps luma < 0.25 (shadows).
    fill(0, band, sh_hue, 0.25, 0.55)
    # hue 38°: luma ≈ 0.78*V → V 0.60–0.85 keeps luma in 0.47–0.66 (midtones).
    fill(band, 2 * band, mt_hue, 0.60, 0.85)
    # hue 45°: luma ≈ 0.83*V → V 0.95–1.00 keeps luma >= 0.79 (highlights).
    fill(2 * band, h, hi_hue, 0.95, 1.00)

    Image.fromarray(arr, "RGB").save(path, format="JPEG")
    return path


class TestConsensusVote:
    """Hito 6A: majority-consensus circular vote over per-reference hues."""

    def test_disagreeing_minority_does_not_veto_majority(self) -> None:
        # 4 refs at 200° + 1 at 90° → consensus must be ~200°, not neutral.
        consensus, agree_flat, agree_weighted = _consensus_vote(
            [200.0, 200.0, 200.0, 200.0, 90.0], [1.0] * 5
        )
        assert abs(consensus - 200.0) < 1e-6
        assert agree_flat == 0.8
        assert agree_weighted == 0.8

    def test_minority_reference_becomes_neutral(self) -> None:
        # 2 refs at 200° + 3 at 90° → the vote finds the 90° camp (3/5).
        # The *gate* (`agree_weighted > 0.6` in `_zone_combine`) then
        # rejects it: 0.6 is not a strict majority, so the zone goes
        # neutral instead of inventing a tint. Here we only assert the
        # vote itself reports the majority camp.
        consensus, agree_flat, agree_weighted = _consensus_vote(
            [200.0, 200.0, 90.0, 90.0, 90.0], [1.0] * 5
        )
        assert agree_flat == 0.6
        assert agree_weighted == 0.6
        assert abs(consensus - 90.0) < 1e-3

    def test_weights_give_saturated_refs_more_say(self) -> None:
        # 2 nearly-gray refs at 200° (low conf) + 3 saturated refs at 90°:
        # weighted support favours the 90° camp (0.882 vs 0.118).
        consensus, agree_flat, agree_weighted = _consensus_vote(
            [200.0, 200.0, 90.0, 90.0, 90.0],
            [0.2, 0.2, 1.0, 1.0, 1.0],
        )
        assert agree_flat == 0.6
        assert abs(agree_weighted - 0.882) < 0.01
        assert abs(consensus - 90.0) < 1e-3

    def test_wraparound_consensus(self) -> None:
        consensus, agree_flat, _ = _consensus_vote([350.0, 10.0, 5.0])
        assert abs(consensus - 1.7) < 2.0
        assert agree_flat == 1.0


class TestGlobalGradeDetection:
    """Hito 6C: 'global' hue_mode — one coherent tint across tonal zones."""

    def test_coherent_warm_grade_is_global(self, tmp_path: Path) -> None:
        # 3 refs, each with a warm grade across all 3 zones (hues within
        # ±45° of their joint mean): 15/38/45, 10/35/42, 20/40/48.
        refs = [
            _triple_zone_image(tmp_path / f"warm{i}.jpg", sh, mt, hi)
            for i, (sh, mt, hi) in enumerate([(15, 38, 45), (10, 35, 42), (20, 40, 48)])
        ]
        result = analyze_reference_hues(refs)
        for zone in ("shadows", "midtones", "highlights"):
            assert result[f"{zone}_hue_mode"] == "global", zone
            assert result[f"{zone}_hue"] is not None, zone
            assert result[f"{zone}_hue_confidence"] >= 0.7, zone
        # Consensus hues per zone ≈ the band inputs
        assert abs(result["shadows_hue"] - 15.0) < 10.0
        assert abs(result["midtones_hue"] - 38.0) < 10.0
        assert abs(result["highlights_hue"] - 45.0) < 10.0

    def test_split_grade_is_not_global(self, tmp_path: Path) -> None:
        # One ref: teal shadows (200°) only; another: warm highlights (30°)
        # only. No ref has a coherent tint across ALL zones → not global.
        teal = _dark_saturated_color(200, scale=0.2)  # shadows-only
        warm_hi = _hue_to_rgb(30, sat=0.9, lum=0.9)  # highlights-only
        p1 = _solid_color_image(tmp_path / "teal.jpg", color=teal)
        p2 = _solid_color_image(tmp_path / "warmhi.jpg", color=warm_hi)
        result = analyze_reference_hues([p1, p2])
        for zone in ("shadows", "midtones", "highlights"):
            assert result[f"{zone}_hue_mode"] != "global", zone
        # Shadows still resolve to the teal hue (mono, one ref with data)
        assert result["shadows_hue_mode"] == "mono"
        assert abs(result["shadows_hue"] - 200.0) < 15.0


class TestReferenceVoteAggregation:
    """Hito 6A end-to-end: one disagreeing reference no longer vetoes."""

    def test_one_disagreeing_ref_keeps_majority_hue(self, tmp_path: Path) -> None:
        # 4 teal refs (200°) + 1 green ref (90°), all in shadows.
        refs = []
        for i in range(4):
            refs.append(
                _solid_color_image(
                    tmp_path / f"teal{i}.jpg",
                    color=_dark_saturated_color(200, scale=0.2),
                )
            )
        refs.append(
            _solid_color_image(
                tmp_path / "green.jpg",
                color=_dark_saturated_color(90, scale=0.2),
            )
        )
        result = analyze_reference_hues(refs)
        sh = result["shadows_hue"]
        assert sh is not None
        assert abs(sh - 200.0) < 15.0, f"expected ~200, got {sh}"
        assert result["shadows_hue_confidence"] >= 0.6
        assert result["shadows_hue_mode"] in ("mono", "global")

    def test_minority_majority_split_stays_neutral(self, tmp_path: Path) -> None:
        # 2 teal + 3 green → 40% agreement → neutral (no tint invented).
        refs = []
        for i in range(2):
            refs.append(
                _solid_color_image(
                    tmp_path / f"teal{i}.jpg",
                    color=_dark_saturated_color(200, scale=0.2),
                )
            )
        for i in range(3):
            refs.append(
                _solid_color_image(
                    tmp_path / f"green{i}.jpg",
                    color=_dark_saturated_color(90, scale=0.2),
                )
            )
        result = analyze_reference_hues(refs)
        assert result["shadows_hue_mode"] == "neutral"
        assert result["shadows_hue"] is None
        assert result["shadows_hue_confidence"] == 0.0


class TestVolumeSaturationRule:
    """Hito 6B: volume rule — low mean saturation with real pixel volume."""

    def test_low_sat_zone_with_volume_emits_hue(self, tmp_path: Path) -> None:
        # 70% gray + 30% dark red in shadows: mean_sat ≈ 0.075 < 0.10 but
        # ~4900 px with delta > 0.05 → hue must be analyzed (old gate 0.15
        # discarded it).
        h, w = 128, 128
        arr = np.zeros((h, w, 3), dtype=np.uint8)
        arr[:, :, :] = (60, 60, 60)  # gray, luma 0.06 < 0.25 (shadows)
        red = _dark_saturated_color(0, scale=0.25)  # (64, 0, 0), luma 0.053
        arr[: int(h * 0.3), :, :] = red
        Image.fromarray(arr, "RGB").save(tmp_path / "vol.jpg", format="JPEG")

        result = analyze_reference_hues([tmp_path / "vol.jpg"])
        sh = result["shadows_hue"]
        assert sh is not None, "volume rule must recover the hue"
        assert min(abs(sh - 0), abs(sh - 360)) < 20.0
        assert result["shadows_hue_mode"] == "mono"
        assert result["shadows_hue_confidence"] > 0.0
