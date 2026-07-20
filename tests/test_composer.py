"""Tests for the composer module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from xml.etree import ElementTree as ET

import pytest

from dtstylekit.codec.iop_registry import IOP_REGISTRY
from dtstylekit.codec.xmp_codec import decode_xmp, encode_xmp
from dtstylekit.composer.merger import merge_presets
from dtstylekit.composer.generator import generate_dtstyle
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

    def test_adjustments_override(self) -> None:
        preset = make_mock_preset(plugins=[
            make_plugin_ref(operation="vibrance"),
        ])
        result = merge_presets([preset], adjustments={
            "vibrance": {"amount": 75.0},
        })
        assert len(result) >= 1
        # Find the vibrance plugin
        for plg in result:
            if plg.operation == "vibrance":
                assert plg.params == {"amount": 75.0}


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
