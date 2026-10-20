"""GenerationService orchestration and safety-bake preset matching."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dtstylekit.analyzer.models import ImageAnalysis
from dtstylekit.composer.safety import safety_bake
from dtstylekit.generation import GenerationRequest, GenerationService
from dtstylekit.presets.models import Preset
from dtstylekit.render import RenderMetrics
from dtstylekit.vlm.models import Plugin, StyleSpec


class _FakeResolver:
    def __init__(self, presets: list[Preset]) -> None:
        self.presets = presets
        self.names: list[str] = []

    def load_many(self, names: list[str], _warnings: list[str]) -> list[Preset]:
        self.names = names
        return self.presets


def _preset(tmp_path: Path) -> Preset:
    return Preset(
        name="_l10n_darktable|_l10n_examples|_l10n_colors|_l10n_sepia",
        description="",
        iop_list="",
        plugins=[],
        file_path=tmp_path / "examples_colors_sepia.dtstyle",
        xml_hash="abc",
    )


def _metrics(clipped: float = 0.0) -> RenderMetrics:
    return RenderMetrics(
        mean_luminance=0.5,
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


def test_service_resolves_selected_presets(tmp_path: Path) -> None:
    spec = StyleSpec(style_name="sepia", selected_preset_names=["sepia"])
    resolved = [_preset(tmp_path)]
    service = GenerationService(
        MagicMock(), analyzer=lambda _path: ImageAnalysis(), resolver=_FakeResolver(resolved)
    )
    with patch(
        "dtstylekit.generation.generate_style_spec",
        return_value=(spec, "report", [], ImageAnalysis()),
    ):
        result = service.generate(GenerationRequest(image_path=tmp_path / "in.jpg"))
    assert result.presets == resolved


def test_service_rejects_empty_style(tmp_path: Path) -> None:
    service = GenerationService(MagicMock(), analyzer=lambda _path: ImageAnalysis())
    with patch(
        "dtstylekit.generation.generate_style_spec",
        return_value=(StyleSpec(style_name="empty"), "report", [], ImageAnalysis()),
    ):
        with pytest.raises(ValueError, match="no selected presets"):
            service.generate(GenerationRequest(image_path=tmp_path / "in.jpg"))


def test_service_writes_style_and_report(tmp_path: Path) -> None:
    spec = StyleSpec(
        style_name="look", plugins=[Plugin(operation="exposure", params={"exposure": 0.1})]
    )
    service = GenerationService(MagicMock(), analyzer=lambda _path: ImageAnalysis())
    with patch(
        "dtstylekit.generation.generate_style_spec",
        return_value=(spec, "report", [], ImageAnalysis()),
    ):
        result = service.generate(GenerationRequest(image_path=tmp_path / "in.jpg"))

    def _write_style(_spec, _presets, path, _analysis):
        Path(path).write_text(
            "<darktable_style><style><plugin><enabled>1</enabled></plugin></style></darktable_style>"
        )

    with (
        patch("dtstylekit.composer.generator.generate_dtstyle", side_effect=_write_style),
        patch("dtstylekit.composer.report.generate_report"),
    ):
        output = service.write(result, tmp_path / "out")

    assert output.dtstyle_path == tmp_path / "out" / "look.dtstyle"
    assert output.report_path == tmp_path / "out" / "look.md"
    assert output.dtstyle_path.exists()


def test_safety_bake_matches_display_name(tmp_path: Path) -> None:
    preset = _preset(tmp_path)
    spec = StyleSpec(style_name="sepia", selected_preset_names=["sepia"])
    with (
        patch("dtstylekit.composer.generator.generate_dtstyle") as generate,
        patch("dtstylekit.render.render_with_style", return_value=tmp_path / "r.jpg"),
        patch("dtstylekit.render.compute_render_metrics", return_value=_metrics()),
    ):
        safety_bake(spec, [preset], tmp_path / "target.arw", tmp_path)
    assert generate.call_args.args[1] == [preset]
