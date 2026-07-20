"""Unit tests for the image analyzer modules."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from dtstylekit.analyzer.models import HistogramStats, ImageAnalysis, LuminanceStats
from dtstylekit.analyzer.histogram import compute_histogram
from dtstylekit.analyzer.luminance import compute_luminance_stats
from dtstylekit.analyzer.exif import extract_exif
from dtstylekit.analyzer.scene import detect_scene
from dtstylekit.analyzer.noise import estimate_noise
from dtstylekit.analyzer.pipeline import analyze_image


def make_image(mode: str = "RGB", size: tuple[int, int] = (64, 64),
               color: tuple[int, int, int] = (128, 128, 128)) -> Image.Image:
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
        result: ImageAnalysis = analyze_image(str(tmp_image))
        prompt_dict = result.to_prompt_dict()
        assert "dimensions" in prompt_dict
        assert "histogram" in prompt_dict
        assert "luminance" in prompt_dict
