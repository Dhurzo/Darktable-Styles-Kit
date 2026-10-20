"""Tests for exposure-normalized style export."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from PIL import Image

from dtstylekit.codec.serializer import build_dtstyle_xml
from dtstylekit.export import (
    reference_target_luminance,
    style_exposure,
    style_with_exposure,
)
from dtstylekit.vlm.iterative_refiner import compute_render_metrics


def _style(tmp_path, plugins):
    path = tmp_path / "style.dtstyle"
    path.write_text(build_dtstyle_xml("test", "", plugins), encoding="utf-8")
    return path


def test_style_exposure_reads_first_exposure_module(tmp_path):
    style = _style(
        tmp_path,
        [{"operation": "exposure", "params": {"exposure": 0.5, "black": 0.0}}],
    )
    assert style_exposure(style) == pytest.approx((0.5, 0.0))


def test_style_with_exposure_updates_existing_plugin(tmp_path):
    style = _style(
        tmp_path,
        [{"operation": "exposure", "params": {"exposure": 0.5, "black": 0.0}}],
    )
    out = style_with_exposure(style, -0.75, tmp_path / "out.dtstyle")
    assert style_exposure(out) == pytest.approx((-0.75, 0.0))


def test_style_with_exposure_adds_missing_plugin(tmp_path):
    style = _style(
        tmp_path,
        [{"operation": "vibrance", "params": {"amount": 10.0}}],
    )
    assert style_exposure(style) == pytest.approx((0.0, 0.0))
    out = style_with_exposure(style, 0.4, tmp_path / "out.dtstyle")
    assert style_exposure(out) == pytest.approx((0.4, 0.0))


def test_clipped_pct_measures_hard_highlights(tmp_path):
    image = Image.new("RGB", (10, 10), (0, 0, 0))
    image.putpixel((0, 0), (255, 255, 255))
    path = tmp_path / "clip.png"
    image.save(path)
    metrics = compute_render_metrics(path)
    assert metrics.clipped_pct == pytest.approx(0.01)


def test_reference_target_luminance_uses_filtered_paths(tmp_path):
    dark = tmp_path / "dark.png"
    bright = tmp_path / "bright.png"
    Image.new("RGB", (16, 16), (20, 20, 20)).save(dark)
    Image.new("RGB", (16, 16), (235, 235, 235)).save(bright)

    unfiltered = reference_target_luminance([dark, bright])
    filtered = reference_target_luminance(
        [dark, bright],
        filter_result=SimpleNamespace(kept=[dark]),
    )

    assert unfiltered > filtered
    assert filtered == pytest.approx(reference_target_luminance([dark]))
