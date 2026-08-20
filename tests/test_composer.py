"""Tests for the composer module + end-to-end integration tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from xml.etree import ElementTree as ET

import pytest

from dtstylekit.analyzer.models import HistogramStats, ImageAnalysis, LuminanceStats
from dtstylekit.codec.iop_registry import pack_params
from dtstylekit.codec.xmp_codec import encode_xmp
from dtstylekit.composer.generator import generate_dtstyle
from dtstylekit.composer.merger import merge_presets
from dtstylekit.composer.report import generate_report
from dtstylekit.composer.roundtrip import (
    validate_iop_list_consistency,
    validate_plugin_blobs,
    validate_xml_structure,
)
from dtstylekit.presets.models import PluginRef, Preset
from dtstylekit.vlm.models import Plugin, StyleSpec

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_mock_preset(
    name: str = "test",
    description: str = "",
    plugins: list[PluginRef] | None = None,
) -> Preset:
    """Create a mock Preset with op_params encoded."""
    return Preset(
        name=name,
        description=description,
        iop_list="",
        plugins=plugins or [],
        file_path=Path("/tmp/test.dtstyle"),
        xml_hash="abc",
    )


def make_plugin_ref(
    operation: str = "vibrance",
    enabled: int = 1,
    multi_name: str = "",
    op_params_blob: bytes = b"\x00\x00\x00\x00",
) -> PluginRef:
    """Create a PluginRef with encoded op_params."""
    op_params = encode_xmp(op_params_blob) if op_params_blob else ""
    return PluginRef(
        operation=operation,
        enabled=enabled,
        multi_name=multi_name,
        multi_priority=0,
        num=0,
        module=0,
        op_params=op_params,
        blendop_params="",
        blendop_version=13,
        multi_name_hand_edited=0,
    )


def _make_preset_with_real_blob(
    name: str = "test_preset",
    operation: str = "vibrance",
    params: dict | None = None,
) -> Preset:
    """Create a preset with a *real* encoded blob (not a placeholder)."""
    if params is None:
        params = {"amount": 50.0}

    blob = pack_params(operation, params)
    encoded = encode_xmp(blob)

    return Preset(
        name=name,
        description="Test preset for E2E",
        iop_list=f"{operation},0",
        plugins=[
            PluginRef(
                operation=operation,
                enabled=1,
                multi_name="",
                multi_priority=0,
                num=0,
                module=0,
                op_params=encoded,
                blendop_params="",
                blendop_version=13,
                multi_name_hand_edited=0,
            )
        ],
        file_path=Path("/tmp/test.dtstyle"),
        xml_hash="e2etest",
    )


def _make_multipreset(
    name: str = "multi_preset",
) -> Preset:
    """Create a preset with multiple real-blob plugins."""
    plugins = []
    ops = [
        (
            "exposure",
            {
                "exposure": 0.5,
                "black": 0.0,
                "mode": 0,
                "deflicker_percentile": 50.0,
                "deflicker_target_level": -4.0,
                "compensate_exposure_bias": 0,
            },
        ),
        ("vibrance", {"amount": 30.0}),
    ]
    for i, (op, params) in enumerate(ops):
        blob = pack_params(op, params)
        encoded = encode_xmp(blob)
        plugins.append(
            PluginRef(
                operation=op,
                enabled=1,
                multi_name="",
                multi_priority=0,
                num=i,
                module=0,
                op_params=encoded,
                blendop_params="",
                blendop_version=13,
                multi_name_hand_edited=0,
            )
        )

    return Preset(
        name=name,
        description="Multi-plugin test preset",
        iop_list="exposure,0,vibrance,1",
        plugins=plugins,
        file_path=Path("/tmp/multi.dtstyle"),
        xml_hash="multi_e2e",
    )


# ---------------------------------------------------------------------------
# TestMergePresets (unit tests for merge logic)
# ---------------------------------------------------------------------------


class TestMergePresets:
    def test_merge_empty(self) -> None:
        result = merge_presets([])
        assert result == []

    def test_merge_single_preset(self) -> None:
        preset = make_mock_preset(
            plugins=[
                make_plugin_ref(operation="vibrance"),
            ]
        )
        result = merge_presets([preset])
        assert len(result) == 1
        assert result[0].operation == "vibrance"

    def test_dedup_by_operation(self) -> None:
        preset = make_mock_preset(
            plugins=[
                make_plugin_ref(operation="vibrance", multi_name="a"),
                make_plugin_ref(operation="vibrance", multi_name="b"),
            ]
        )
        result = merge_presets([preset])
        assert len(result) == 2

    def test_unnamed_duplicates_are_dropped(self) -> None:
        preset_a = make_mock_preset(
            plugins=[
                make_plugin_ref(operation="vibrance"),
            ]
        )
        preset_b = make_mock_preset(
            plugins=[
                make_plugin_ref(operation="vibrance"),
                make_plugin_ref(operation="grain"),
            ]
        )
        result = merge_presets([preset_a, preset_b])
        ops = [plg.operation for plg in result]
        assert ops.count("vibrance") == 1
        assert ops.count("grain") == 1

    def test_named_instances_across_presets_first_wins(self) -> None:
        blob = pack_params("colorbalancergb", {"saturation_global": 0.1})
        preset_a = make_mock_preset(
            plugins=[
                make_plugin_ref(
                    operation="colorbalancergb",
                    multi_name="sepia",
                    op_params_blob=blob,
                ),
            ]
        )
        preset_b = make_mock_preset(
            plugins=[
                make_plugin_ref(
                    operation="colorbalancergb",
                    multi_name="faded",
                    op_params_blob=blob,
                ),
                make_plugin_ref(operation="exposure", op_params_blob=pack_params("exposure", {})),
            ]
        )
        result = merge_presets([preset_a, preset_b])
        cbrg = [p for p in result if p.operation == "colorbalancergb"]
        assert len(cbrg) == 1
        assert cbrg[0].multi_name == "sepia"
        assert [p.operation for p in result].count("exposure") == 1

    def test_multi_instance_within_one_preset_kept(self) -> None:
        blob = pack_params("colorbalancergb", {})
        preset = make_mock_preset(
            plugins=[
                make_plugin_ref(
                    operation="colorbalancergb",
                    multi_name="highlights",
                    op_params_blob=blob,
                ),
                make_plugin_ref(
                    operation="colorbalancergb",
                    multi_name="shadows",
                    op_params_blob=blob,
                ),
            ]
        )
        result = merge_presets([preset])
        names = [p.multi_name for p in result if p.operation == "colorbalancergb"]
        assert names == ["highlights", "shadows"]

    def test_adjustment_merges_onto_named_enabled_instance(self) -> None:
        blob = pack_params("colorbalancergb", {"saturation_global": 0.1})
        preset = make_mock_preset(
            plugins=[
                make_plugin_ref(
                    operation="colorbalancergb",
                    multi_name="sepia",
                    op_params_blob=blob,
                ),
            ]
        )
        result = merge_presets(
            [preset],
            adjustments={
                "colorbalancergb": {"saturation_global": 0.2},
            },
        )
        cbrg = [p for p in result if p.operation == "colorbalancergb"]
        assert len(cbrg) == 1
        assert cbrg[0].multi_name == "sepia"
        assert cbrg[0].params["saturation_global"] == 0.2

    def test_adjustment_merges_onto_disabled_placeholder_instance(self) -> None:
        blob = pack_params("filmicrgb", {"contrast": 1.0, "black_point_source": -7.65})
        preset = make_mock_preset(
            plugins=[
                make_plugin_ref(
                    operation="filmicrgb",
                    enabled=0,
                    multi_name="scene-referred default",
                    op_params_blob=blob,
                ),
            ]
        )
        result = merge_presets(
            [preset],
            adjustments={
                "filmicrgb": {"contrast": 1.4},
            },
        )
        films = [p for p in result if p.operation == "filmicrgb"]
        assert len(films) == 1
        f = films[0]
        assert f.enabled is True
        assert f.multi_name == "scene-referred default"
        assert f.params["contrast"] == 1.4
        assert f.params["black_point_source"] == pytest.approx(-7.65)

    def test_adjustments_override(self) -> None:
        blob = pack_params("exposure", {"exposure": 0.5, "compensate_hilite_pres": 0})
        preset = make_mock_preset(
            plugins=[
                make_plugin_ref(operation="exposure", op_params_blob=blob),
            ]
        )
        result = merge_presets(
            [preset],
            adjustments={
                "exposure": {"exposure": 0.75},
            },
        )
        assert len(result) == 1
        plg = result[0]
        assert plg.params["exposure"] == 0.75
        assert plg.params["compensate_hilite_pres"] == 0

    def test_adjustment_on_unverified_iop_keeps_preset_blob(self) -> None:
        preset = make_mock_preset(
            plugins=[
                make_plugin_ref(operation="vibrance"),
            ]
        )
        result = merge_presets(
            [preset],
            adjustments={
                "vibrance": {"amount": 75.0},
            },
        )
        assert len(result) == 1
        assert result[0].params == {}
        assert result[0].op_params != ""

    def test_adjustment_new_plugin(self) -> None:
        preset = make_mock_preset(
            plugins=[
                make_plugin_ref(operation="vibrance"),
            ]
        )
        result = merge_presets(
            [preset],
            adjustments={
                "filmicrgb": {"contrast": 1.4},
            },
        )
        ops = [plg.operation for plg in result]
        assert "filmicrgb" in ops
        filmic = next(plg for plg in result if plg.operation == "filmicrgb")
        assert filmic.params == {"contrast": 1.4}
        assert filmic.module == 6

    def test_fresh_filmic_skipped_on_dark_image(self) -> None:
        result = merge_presets(
            [],
            adjustments={
                "filmicrgb": {"contrast": 1.4},
            },
            dark_image=True,
        )
        assert [p for p in result if p.operation == "filmicrgb"] == []

    def test_fresh_filmic_allowed_on_dark_image_if_preset_has_it(self) -> None:
        blob = pack_params("filmicrgb", {"contrast": 1.0, "black_point_source": -7.65})
        preset = make_mock_preset(
            plugins=[
                make_plugin_ref(
                    operation="filmicrgb",
                    enabled=0,
                    multi_name="scene-referred default",
                    op_params_blob=blob,
                ),
            ]
        )
        result = merge_presets(
            [preset],
            adjustments={
                "filmicrgb": {"contrast": 1.4},
            },
            dark_image=True,
        )
        films = [p for p in result if p.operation == "filmicrgb"]
        assert len(films) == 1
        assert films[0].enabled is True
        assert films[0].params["contrast"] == 1.4
        assert films[0].params["black_point_source"] == pytest.approx(-7.65)

    def test_dark_image_non_filmic_adjustments_still_work(self) -> None:
        result = merge_presets(
            [],
            adjustments={
                "exposure": {"exposure": 0.5},
            },
            dark_image=True,
        )
        exps = [p for p in result if p.operation == "exposure"]
        assert len(exps) == 1
        assert exps[0].params["exposure"] == 0.5

    def test_with_adjustments(self) -> None:
        preset = _make_preset_with_real_blob(
            operation="exposure",
            params={
                "exposure": 0.5,
                "black": 0.0,
                "mode": 0,
                "deflicker_percentile": 50.0,
                "deflicker_target_level": -4.0,
                "compensate_exposure_bias": 0,
            },
        )
        merged = merge_presets(
            [preset],
            adjustments={"exposure": {"exposure": 0.8}},
        )
        assert len(merged) >= 1
        exp = next(p for p in merged if p.operation == "exposure")
        assert exp.params["exposure"] == 0.8
        assert exp.params["black"] == 0.0


# ---------------------------------------------------------------------------
# TestGenerateDtstyle
# ---------------------------------------------------------------------------


class TestGenerateDtstyle:
    def test_writes_valid_xml(self, tmp_path: Path) -> None:
        spec = MagicMock()
        spec.style_name = "test_style"
        spec.style_description = "Test"
        spec.iop_list = None
        spec.plugins = []

        preset = make_mock_preset()
        output = tmp_path / "test.dtstyle"

        result = generate_dtstyle(spec, [preset], output)
        assert result.exists()
        assert result.read_text().startswith("<?xml")

        root = ET.fromstring(result.read_text())
        assert root.tag == "darktable_style"
        assert root.get("version") == "1.0"

    def test_creates_output_dir(self, tmp_path: Path) -> None:
        spec = MagicMock()
        spec.style_name = "x"
        spec.style_description = ""
        spec.iop_list = None
        spec.plugins = []

        out = tmp_path / "nested" / "x.dtstyle"
        generate_dtstyle(spec, [], out)
        assert out.exists()


# ---------------------------------------------------------------------------
# TestGenerateReport
# ---------------------------------------------------------------------------


class TestGenerateReport:
    def test_writes_markdown(self, tmp_path: Path) -> None:
        spec = MagicMock()
        spec.style_name = "report_test"
        spec.style_description = "Test description"
        spec.plugins = [MagicMock(operation="filmicrgb", multi_name="", params={"contrast": 1.5})]

        analysis = MagicMock()
        analysis.to_prompt_dict.return_value = {
            "dimensions": {"w": 1024, "h": 768, "format": "JPEG"},
            "luminance": {
                "mean": 0.45,
                "std": 0.18,
                "saturation": 0.42,
                "wb_rb_ratio": 1.0,
                "tonal": [0.2, 0.5, 0.3],
            },
            "histogram": {},
            "noise": 0.05,
            "scene_tags": ["portrait", "warm"],
        }

        output = tmp_path / "report.md"
        result = generate_report(spec, [], analysis, "Test VLM rationale", output)
        assert result.exists()
        content = result.read_text()
        assert "report_test" in content
        assert "Test description" in content
        assert "Test VLM rationale" in content
        assert "filmicrgb" in content


# ---------------------------------------------------------------------------
# TestRoundtrip (XML structure and blob validation)
# ---------------------------------------------------------------------------


class TestRoundtrip:
    def test_validate_xml_structure_valid(self, tmp_path: Path) -> None:
        dtstyle = tmp_path / "test.dtstyle"
        dtstyle.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<darktable_style version="1.0">
  <info>
    <name>test</name>
    <description>test</description>
  </info>
  <style>
    <plugin>
      <num>0</num>
      <module>0</module>
      <operation>filmicrgb</operation>
      <op_params>AA==</op_params>
      <enabled>1</enabled>
      <blendop_params>BB==</blendop_params>
      <blendop_version>13</blendop_version>
      <multi_priority>0</multi_priority>
      <multi_name></multi_name>
      <multi_name_hand_edited>0</multi_name_hand_edited>
    </plugin>
  </style>
</darktable_style>""")
        errors = validate_xml_structure(dtstyle)
        assert errors == []

    def test_validate_xml_structure_invalid(self, tmp_path: Path) -> None:
        dtstyle = tmp_path / "bad.dtstyle"
        dtstyle.write_text("<invalid>")
        errors = validate_xml_structure(dtstyle)
        assert any("parse error" in e.lower() or "XML parse error" in e for e in errors)

    def test_validate_plugin_blobs(self, tmp_path: Path) -> None:
        dtstyle = tmp_path / "test.dtstyle"
        dtstyle.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<darktable_style version="1.0">
  <info><name>x</name></info>
  <style>
    <plugin>
      <operation>vibrance</operation>
      <op_params>00002041</op_params>
      <enabled>1</enabled>
      <blendop_params>gz08eJxjYGBgYAFiCQYYOOHEgAZY0QWAgBGLGANDgz0Ej1Q+dlAx68oBEMbFxwX+AwGIBgCbGCeh</blendop_params>
    </plugin>
  </style>
</darktable_style>""")
        errors = validate_plugin_blobs(dtstyle)
        assert "vibrance" not in str(errors), f"Unexpected error: {errors}"

    def test_iop_list_consistency(self, tmp_path: Path) -> None:
        dtstyle = tmp_path / "test.dtstyle"
        dtstyle.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<darktable_style version="1.0">
  <info>
    <name>x</name>
    <iop_list>filmicrgb,0</iop_list>
  </info>
  <style>
    <plugin><operation>exposure</operation><op_params>x</op_params></plugin>
  </style>
</darktable_style>""")
        errors = validate_iop_list_consistency(dtstyle)
        assert any("exposure" in e for e in errors)


# ---------------------------------------------------------------------------
# E2E: Full pipeline tests (from test_integration.py)
# ---------------------------------------------------------------------------


class TestE2EGenerateAndValidate:
    """Full pipeline from StyleSpec to .dtstyle + validation."""

    def test_single_plugin_dtstyle(self, tmp_path: Path) -> None:
        spec = StyleSpec(
            style_name="warm_vibrant",
            style_description="A warm vibrant look",
            iop_list="vibrance,0",
            plugins=[
                Plugin(operation="vibrance", params={"amount": 60.0}),
            ],
        )
        preset = _make_preset_with_real_blob()
        output = tmp_path / "warm_vibrant.dtstyle"

        generate_dtstyle(spec, [preset], output)

        assert output.exists()

        xml_errors = validate_xml_structure(output)
        assert xml_errors == [], f"XML structure errors: {xml_errors}"

        blob_errors = validate_plugin_blobs(output)
        assert blob_errors == [], f"Blob validation errors: {blob_errors}"

    def test_multipreset_merge_and_validate(self, tmp_path: Path) -> None:
        spec = StyleSpec(
            style_name="cinematic_look",
            style_description="Cinematic film look",
            iop_list="exposure,0,vibrance,1",
            plugins=[
                Plugin(operation="exposure", params={"exposure": 0.3}),
                Plugin(operation="vibrance", params={"amount": 40.0}),
            ],
        )
        preset = _make_multipreset()
        output = tmp_path / "cinematic.dtstyle"

        generate_dtstyle(spec, [preset], output)

        assert output.exists()
        xml_errors = validate_xml_structure(output)
        assert xml_errors == [], f"XML errors: {xml_errors}"

    def test_iop_list_consistency_check(self, tmp_path: Path) -> None:
        spec = StyleSpec(
            style_name="mismatch_test",
            style_description="Test iop_list mismatch",
            iop_list="vibrance,0",
            plugins=[
                Plugin(operation="exposure", params={"exposure": 1.0}),
            ],
        )
        output = tmp_path / "mismatch.dtstyle"
        generate_dtstyle(spec, [], output)

        errors = validate_iop_list_consistency(output)
        assert any(
            "exposure" in e for e in errors
        ), f"Expected iop_list mismatch error, got: {errors}"

    def test_generated_xml_roundtrip(self, tmp_path: Path) -> None:
        spec = StyleSpec(
            style_name="roundtrip_test",
            style_description="XML round-trip",
            plugins=[
                Plugin(
                    operation="exposure",
                    params={
                        "exposure": 0.0,
                        "black": 0.0,
                        "mode": 0,
                        "deflicker_percentile": 50.0,
                        "deflicker_target_level": -4.0,
                        "compensate_exposure_bias": 0,
                    },
                ),
            ],
        )
        output = tmp_path / "roundtrip.dtstyle"
        generate_dtstyle(spec, [], output)

        tree = ET.parse(output)
        root = tree.getroot()
        assert root.tag == "darktable_style"
        assert root.find("info") is not None
        assert root.find("style") is not None

        for plugin in root.find("style").findall("plugin"):
            op = plugin.findtext("operation")
            op_params_enc = plugin.findtext("op_params", "")
            if op_params_enc and op in ("exposure", "vibrance"):
                from dtstylekit.codec.iop_registry import unpack_params
                from dtstylekit.codec.xmp_codec import decode_xmp

                blob = decode_xmp(op_params_enc)
                params = unpack_params(op, blob)
                assert isinstance(params, dict)
                assert len(params) > 0


class TestE2EFullPipelineMocked:
    """Simulate the full `dtstylekit generate` pipeline with a mocked VLM."""

    def test_pipeline_produces_valid_style(self, tmp_path: Path) -> None:
        analysis = ImageAnalysis(
            width=800,
            height=600,
            mode="RGB",
            format="JPEG",
            luminance=LuminanceStats(mean=0.45, std=0.18, saturation_mean=0.3),
            histogram=HistogramStats(bins=64),
            scene_tags=["outdoor", "daylight"],
        )

        spec = StyleSpec(
            style_name="golden_hour",
            style_description="Golden hour warmth",
            iop_list="filmicrgb,0,colorbalancergb,1,exposure,2",
            plugins=[
                Plugin(
                    operation="filmicrgb",
                    params={
                        "contrast": 1.4,
                        "latitude": 25.0,
                    },
                ),
                Plugin(
                    operation="colorbalancergb",
                    params={
                        "shadows_H": 25.0,
                        "highlights_H": 35.0,
                    },
                ),
                Plugin(
                    operation="exposure",
                    params={
                        "exposure": 0.3,
                    },
                ),
            ],
        )

        dtstyle_path = tmp_path / "golden_hour.dtstyle"
        generate_dtstyle(spec, [], dtstyle_path, analysis)
        assert dtstyle_path.exists()

        report_path = tmp_path / "golden_hour.md"
        generate_report(
            spec,
            [],
            analysis,
            "Golden hour look with warm shadows and highlighted hues",
            report_path,
        )
        assert report_path.exists()
        assert "golden_hour" in report_path.read_text()

        xml_errors = validate_xml_structure(dtstyle_path)
        assert xml_errors == [], f"XML errors: {xml_errors}"

        blob_errors = validate_plugin_blobs(dtstyle_path)
        verified_errors = [e for e in blob_errors if "not in IOP_REGISTRY" not in e]
        assert verified_errors == [], f"Verified blob errors: {verified_errors}"
