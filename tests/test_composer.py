"""Tests for the composer module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from xml.etree import ElementTree as ET

import pytest

from dtstylekit.codec.iop_registry import pack_params
from dtstylekit.codec.xmp_codec import encode_xmp
from dtstylekit.composer.generator import generate_dtstyle
from dtstylekit.composer.merger import merge_presets
from dtstylekit.composer.report import generate_report
from dtstylekit.presets.models import PluginRef, Preset


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


class TestMergePresets:
    def test_merge_empty(self) -> None:
        result = merge_presets([])
        assert result == []

    def test_merge_single_preset(self) -> None:
        preset = make_mock_preset(plugins=[
            make_plugin_ref(operation="vibrance"),
        ])
        result = merge_presets([preset])
        assert len(result) == 1
        assert result[0].operation == "vibrance"

    def test_dedup_by_operation(self) -> None:
        preset = make_mock_preset(plugins=[
            make_plugin_ref(operation="vibrance", multi_name="a"),
            make_plugin_ref(operation="vibrance", multi_name="b"),
        ])
        result = merge_presets([preset])
        # Different multi_names → keep both
        assert len(result) == 2

    def test_unnamed_duplicates_are_dropped(self) -> None:
        """Two presets sharing an unnamed operation → only one instance."""
        preset_a = make_mock_preset(plugins=[
            make_plugin_ref(operation="vibrance"),
        ])
        preset_b = make_mock_preset(plugins=[
            make_plugin_ref(operation="vibrance"),
            make_plugin_ref(operation="grain"),
        ])
        result = merge_presets([preset_a, preset_b])
        ops = [plg.operation for plg in result]
        assert ops.count("vibrance") == 1
        # The non-duplicate plugin of the second preset is still merged.
        assert ops.count("grain") == 1

    def test_named_instances_across_presets_first_wins(self) -> None:
        """Same op with *different* multi_names from two presets: only the
        first preset's instance survives (official styles name their
        instances, e.g. colorbalancergb "sepia" / "faded")."""
        blob = pack_params("colorbalancergb", {"saturation_global": 0.1})
        preset_a = make_mock_preset(plugins=[
            make_plugin_ref(
                operation="colorbalancergb", multi_name="sepia",
                op_params_blob=blob,
            ),
        ])
        preset_b = make_mock_preset(plugins=[
            make_plugin_ref(
                operation="colorbalancergb", multi_name="faded",
                op_params_blob=blob,
            ),
            make_plugin_ref(operation="exposure", op_params_blob=pack_params("exposure", {})),
        ])
        result = merge_presets([preset_a, preset_b])
        cbrg = [p for p in result if p.operation == "colorbalancergb"]
        assert len(cbrg) == 1
        assert cbrg[0].multi_name == "sepia"  # first preset wins
        # The second preset's non-colliding plugin is kept.
        assert [p.operation for p in result].count("exposure") == 1

    def test_multi_instance_within_one_preset_kept(self) -> None:
        """Intentional named multi-instances *inside* a single preset are
        all preserved (e.g. camera styles with separate highlights/
        shadows instances)."""
        blob = pack_params("colorbalancergb", {})
        preset = make_mock_preset(plugins=[
            make_plugin_ref(
                operation="colorbalancergb", multi_name="highlights",
                op_params_blob=blob,
            ),
            make_plugin_ref(
                operation="colorbalancergb", multi_name="shadows",
                op_params_blob=blob,
            ),
        ])
        result = merge_presets([preset])
        names = [p.multi_name for p in result if p.operation == "colorbalancergb"]
        assert names == ["highlights", "shadows"]

    def test_adjustment_merges_onto_named_enabled_instance(self) -> None:
        """Adjustment merges onto the preset's enabled named instance,
        preserving its multi_name."""
        blob = pack_params("colorbalancergb", {"saturation_global": 0.1})
        preset = make_mock_preset(plugins=[
            make_plugin_ref(
                operation="colorbalancergb", multi_name="sepia",
                op_params_blob=blob,
            ),
        ])
        result = merge_presets([preset], adjustments={
            "colorbalancergb": {"saturation_global": 0.2},
        })
        cbrg = [p for p in result if p.operation == "colorbalancergb"]
        assert len(cbrg) == 1
        assert cbrg[0].multi_name == "sepia"
        assert cbrg[0].params["saturation_global"] == 0.2

    def test_adjustment_merges_onto_disabled_placeholder_instance(self) -> None:
        """Presets embed darktable's disabled 'scene-referred default'
        filmicrgb placeholder, which carries the preset's *custom* values
        (NOT the registry defaults).  An adjustment must merge onto it
        and enable it, preserving the preset look."""
        blob = pack_params("filmicrgb", {"contrast": 1.0, "black_point_source": -7.65})
        preset = make_mock_preset(plugins=[
            make_plugin_ref(
                operation="filmicrgb", enabled=0,
                multi_name="scene-referred default",
                op_params_blob=blob,
            ),
        ])
        result = merge_presets([preset], adjustments={
            "filmicrgb": {"contrast": 1.4},
        })
        films = [p for p in result if p.operation == "filmicrgb"]
        assert len(films) == 1
        f = films[0]
        assert f.enabled is True
        assert f.multi_name == "scene-referred default"
        assert f.params["contrast"] == 1.4
        # The preset's custom values survive the merge (not defaults).
        assert f.params["black_point_source"] == pytest.approx(-7.65)

    def test_adjustments_override(self) -> None:
        """Adjustment on a preset plugin merges onto the preset's values.

        exposure is a verified IOP (28-byte v7 blob), so the preset blob
        is decoded, the adjustment applied on top, and re-packed.
        ``compensate_hilite_pres=0`` is set in the preset blob while the
        registry default is 1 — if the merge started from defaults the
        final params would show 1, not 0.
        """
        blob = pack_params("exposure", {"exposure": 0.5, "compensate_hilite_pres": 0})
        preset = make_mock_preset(plugins=[
            make_plugin_ref(operation="exposure", op_params_blob=blob),
        ])
        result = merge_presets([preset], adjustments={
            "exposure": {"exposure": 0.75},
        })
        assert len(result) == 1
        plg = result[0]
        # Preset value preserved...
        assert plg.params["exposure"] == 0.75
        # ...and the rest of the preset's fields survived (not defaults).
        assert plg.params["compensate_hilite_pres"] == 0  # from the blob, not default 1

    def test_adjustment_on_unverified_iop_keeps_preset_blob(self) -> None:
        """Unverified IOPs cannot be re-packed → blob kept, adjustment skipped."""
        preset = make_mock_preset(plugins=[
            make_plugin_ref(operation="vibrance"),
        ])
        result = merge_presets([preset], adjustments={
            "vibrance": {"amount": 75.0},
        })
        assert len(result) == 1
        assert result[0].params == {}  # untouched
        assert result[0].op_params != ""  # preset blob still present

    def test_adjustment_new_plugin(self) -> None:
        """Adjustment for an operation not in the presets → new plugin."""
        preset = make_mock_preset(plugins=[
            make_plugin_ref(operation="vibrance"),
        ])
        result = merge_presets([preset], adjustments={
            "filmicrgb": {"contrast": 1.4},
        })
        ops = [plg.operation for plg in result]
        assert "filmicrgb" in ops
        filmic = next(plg for plg in result if plg.operation == "filmicrgb")
        assert filmic.params == {"contrast": 1.4}
        assert filmic.module == 6  # registry version

    def test_fresh_filmic_skipped_on_dark_image(self) -> None:
        """A fresh filmicrgb is never created for a dark image (it would
        crush shadows on display-referred data)."""
        result = merge_presets([], adjustments={
            "filmicrgb": {"contrast": 1.4},
        }, dark_image=True)
        assert [p for p in result if p.operation == "filmicrgb"] == []

    def test_fresh_filmic_allowed_on_dark_image_if_preset_has_it(self) -> None:
        """dark_image only blocks the *fresh* path; merging onto a preset's
        filmicrgb still works."""
        blob = pack_params("filmicrgb", {"contrast": 1.0, "black_point_source": -7.65})
        preset = make_mock_preset(plugins=[
            make_plugin_ref(
                operation="filmicrgb", enabled=0,
                multi_name="scene-referred default",
                op_params_blob=blob,
            ),
        ])
        result = merge_presets([preset], adjustments={
            "filmicrgb": {"contrast": 1.4},
        }, dark_image=True)
        films = [p for p in result if p.operation == "filmicrgb"]
        assert len(films) == 1
        assert films[0].enabled is True
        assert films[0].params["contrast"] == 1.4
        assert films[0].params["black_point_source"] == pytest.approx(-7.65)

    def test_dark_image_non_filmic_adjustments_still_work(self) -> None:
        """dark_image only blocks fresh filmicrgb, not other ops."""
        result = merge_presets([], adjustments={
            "exposure": {"exposure": 0.5},
        }, dark_image=True)
        exps = [p for p in result if p.operation == "exposure"]
        assert len(exps) == 1
        assert exps[0].params["exposure"] == 0.5


class TestGenerateDtstyle:
    def test_writes_valid_xml(self, tmp_path: Path) -> None:
        # Build a mock spec
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

        # Parse and verify structure
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


class TestGenerateReport:
    def test_writes_markdown(self, tmp_path: Path) -> None:
        spec = MagicMock()
        spec.style_name = "report_test"
        spec.style_description = "Test description"
        spec.plugins = [MagicMock(operation="filmicrgb", multi_name="", params={"contrast": 1.5})]

        analysis = MagicMock()
        analysis.to_prompt_dict.return_value = {
            "dimensions": {"w": 1024, "h": 768, "format": "JPEG"},
            "luminance": {"mean": 0.45, "std": 0.18, "saturation": 0.42, "wb_rb_ratio": 1.0, "tonal": [0.2, 0.5, 0.3]},
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


class TestRoundtrip:
    def test_validate_xml_structure_valid(self, tmp_path: Path) -> None:
        from dtstylekit.composer.roundtrip import validate_xml_structure
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
        from dtstylekit.composer.roundtrip import validate_xml_structure
        dtstyle = tmp_path / "bad.dtstyle"
        dtstyle.write_text("<invalid>")
        errors = validate_xml_structure(dtstyle)
        assert any("parse error" in e.lower() or "XML parse error" in e for e in errors)

    def test_validate_plugin_blobs(self, tmp_path: Path) -> None:
        from dtstylekit.composer.roundtrip import validate_plugin_blobs
        # Use a fixture that matches a known preset
        # (We can't easily test real blob validation without real presets)
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
        # vibrance op_params should be 4 bytes (one float)
        assert "vibrance" not in str(errors), f"Unexpected error: {errors}"

    def test_iop_list_consistency(self, tmp_path: Path) -> None:
        from dtstylekit.composer.roundtrip import validate_iop_list_consistency
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
