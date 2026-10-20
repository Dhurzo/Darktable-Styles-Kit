"""Regression tests for the clipping-only safety bake."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from dtstylekit.vlm.models import Plugin, StyleSpec
from dtstylekit.vlm.orchestrator import _safety_bake


def _metrics(*, lum: float, clipped: float):
    from dtstylekit.vlm.iterative_refiner import RenderMetrics

    return RenderMetrics(
        mean_luminance=lum,
        std_luminance=0.2,
        mean_saturation=0.1,
        r_mean=0.1,
        g_mean=0.1,
        b_mean=0.1,
        r_over_g=1.0,
        shadows_pct=0.1,
        highlights_pct=0.1,
        mean_hsv_saturation=0.2,
        clipped_pct=clipped,
    )


class TestSafetyBake:
    def test_dark_render_is_not_lifted_to_reference(self, tmp_path: Path) -> None:
        """A dark style must stay dark: exposure normalization is per image."""
        spec = StyleSpec(
            style_name="t",
            plugins=[Plugin(operation="exposure", params={"exposure": 0.3})],
        )
        with (
            patch("dtstylekit.composer.generator.generate_dtstyle"),
            patch(
                "dtstylekit.render.render_with_style",
                return_value=tmp_path / "r.jpg",
            ),
            patch(
                "dtstylekit.render.compute_render_metrics",
                return_value=_metrics(lum=0.03, clipped=0.0),
            ),
        ):
            out = _safety_bake(spec, [], tmp_path / "target.arw", tmp_path)
        assert out.plugins[0].params["exposure"] == pytest.approx(0.3)

    def test_clipped_render_lowers_exposure(self, tmp_path: Path) -> None:
        spec = StyleSpec(
            style_name="t",
            plugins=[Plugin(operation="exposure", params={"exposure": 0.3})],
        )
        metrics = [_metrics(lum=0.9, clipped=0.5), _metrics(lum=0.2, clipped=0.0)]
        with (
            patch("dtstylekit.composer.generator.generate_dtstyle"),
            patch(
                "dtstylekit.render.render_with_style",
                return_value=tmp_path / "r.jpg",
            ),
            patch(
                "dtstylekit.render.compute_render_metrics",
                side_effect=metrics,
            ),
        ):
            out = _safety_bake(spec, [], tmp_path / "target.arw", tmp_path)
        assert out.plugins[0].params["exposure"] < 0.3
