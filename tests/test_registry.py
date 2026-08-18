"""Tests for IOP Registry: pack_params, unpack_params, verify_size."""

from pathlib import Path

import pytest

from dtstylekit.codec import (
    IOP_REGISTRY,
    IOPRegistry,
    get_registry,
    list_registered,
    list_unverified,
    list_verified,
    pack_params,
    unpack_params,
    verify_size,
)


class TestRegistryAccess:
    """Tests for registry lookup and listing functions."""

    def test_get_registry_existing(self):
        """get_registry returns IOPRegistry for known operations."""
        for op in ["exposure", "filmicrgb", "colorbalancergb", "sigmoid", "atrous"]:
            reg = get_registry(op)
            assert reg is not None
            assert reg.operation == op
            assert isinstance(reg, IOPRegistry)

    def test_get_registry_unknown(self):
        """get_registry returns None for unknown operations."""
        assert get_registry("nonexistent") is None
        assert get_registry("") is None

    def test_list_registered(self):
        """list_registered returns all registered operations."""
        registered = list_registered()
        assert len(registered) > 0
        assert "exposure" in registered
        assert "filmicrgb" in registered
        assert registered == sorted(registered)  # Should be sorted

    def test_list_verified(self):
        """list_verified returns only operations with verified sizes."""
        verified = list_verified()
        assert "filmicrgb" in verified
        assert "colorbalancergb" in verified
        assert "sigmoid" in verified
        assert "exposure" in verified
        assert "atrous" in verified
        # Curve IOPs now also have verified sizes
        assert "colorzones" in verified
        assert "rgbcurve" in verified
        assert "tonecurve" in verified
        # Simple IOPs should NOT be in verified
        assert "vibrance" not in verified
        # Now includes bilat (20B), basecurve (520B), plus the originals
        # and the refinement IOPs (temperature, basicadj, toneequal,
        # colorequal, colorharmonizer) — all with verified sizes.
        # (relight is deprecated in darktable and not registered.)
        assert len(verified) == 15

    def test_list_unverified(self):
        """list_unverified returns operations without verified sizes."""
        unverified = list_unverified()
        assert "vibrance" in unverified
        assert "velvia" in unverified
        assert "filmicrgb" not in unverified
        assert len(unverified) > 0

    def test_all_verified_have_size(self):
        """All verified IOPs should have size_bytes set."""
        for op in list_verified():
            reg = get_registry(op)
            assert reg.size_bytes is not None, f"{op} is verified but has no size_bytes"
            assert reg.size_bytes > 0, f"{op} has invalid size_bytes"

    def test_all_unverified_have_none_size(self):
        """All unverified IOPs should have size_bytes = None."""
        for op in list_unverified():
            reg = get_registry(op)
            assert reg.size_bytes is None, f"{op} is unverified but has size_bytes={reg.size_bytes}"


class TestPackParams:
    """Tests for pack_params function."""

    def test_pack_exposure_defaults(self):
        """Pack exposure with defaults produces correct size."""
        blob = pack_params("exposure", {})
        assert len(blob) == 28
        assert verify_size("exposure", blob)

    def test_pack_exposure_custom(self):
        """Pack exposure with custom values."""
        blob = pack_params(
            "exposure",
            {
                "mode": 1,
                "black": 0.1,
                "exposure": 2.5,
                "deflicker_percentile": 75.0,
                "deflicker_target_level": -2.0,
                "compensate_exposure_bias": 1,
            },
        )
        assert len(blob) == 28
        assert verify_size("exposure", blob)

    def test_pack_filmicrgb_defaults(self):
        """Pack filmicrgb with defaults produces 116 bytes."""
        blob = pack_params("filmicrgb", {})
        assert len(blob) == 116
        assert verify_size("filmicrgb", blob)

    def test_pack_filmicrgb_custom(self):
        """Pack filmicrgb with custom values."""
        blob = pack_params(
            "filmicrgb",
            {
                "contrast": 1.5,
                "latitude": 25.0,
                "saturation": 10.0,
            },
        )
        assert len(blob) == 116
        assert verify_size("filmicrgb", blob)

    def test_pack_colorbalancergb_defaults(self):
        """Pack colorbalancergb with defaults produces 132 bytes."""
        blob = pack_params("colorbalancergb", {})
        assert len(blob) == 132
        assert verify_size("colorbalancergb", blob)

    def test_pack_colorbalancergb_custom(self):
        """Pack colorbalancergb with custom values."""
        blob = pack_params(
            "colorbalancergb",
            {
                "global_Y": 0.1,
                "global_C": 0.2,
                "saturation_global": 0.3,
            },
        )
        assert len(blob) == 132
        assert verify_size("colorbalancergb", blob)

    def test_pack_sigmoid_defaults(self):
        """Pack sigmoid with defaults produces 56 bytes."""
        blob = pack_params("sigmoid", {})
        assert len(blob) == 56
        assert verify_size("sigmoid", blob)

    def test_pack_sigmoid_custom(self):
        """Pack sigmoid with custom values."""
        blob = pack_params(
            "sigmoid",
            {
                "middle_grey_contrast": 2.0,
                "contrast_skewness": 0.1,
            },
        )
        assert len(blob) == 56
        assert verify_size("sigmoid", blob)

    def test_pack_atrous_defaults(self):
        """Pack atrous with defaults produces 248 bytes."""
        blob = pack_params("atrous", {})
        assert len(blob) == 248
        assert verify_size("atrous", blob)

    def test_pack_atrous_custom(self):
        """Pack atrous with custom values."""
        blob = pack_params(
            "atrous",
            {
                "octaves": 4,
                "mix": 0.5,
            },
        )
        assert len(blob) == 248
        assert verify_size("atrous", blob)

    def test_pack_simple_iops(self):
        """Pack simple IOPs (unverified sizes)."""
        for op in list_unverified():
            blob = pack_params(op, {})
            # Should not raise, size just not verified
            assert isinstance(blob, bytes)
            # verify_size returns True for unverified
            assert verify_size(op, blob)

    def test_pack_unknown_operation(self):
        """Pack unknown operation raises ValueError."""
        with pytest.raises(ValueError, match="Unknown operation"):
            pack_params("nonexistent", {})

    def test_pack_invalid_range(self):
        """Pack with out-of-range value raises ValueError."""
        with pytest.raises(ValueError, match="out of range"):
            pack_params("exposure", {"exposure": 100.0})  # max is 18.0

        with pytest.raises(ValueError, match="out of range"):
            pack_params("filmicrgb", {"contrast": 10.0})  # max is 5.0

    def test_pack_merges_defaults(self):
        """Pack merges provided params with defaults."""
        blob = pack_params("vibrance", {"amount": 50.0})
        unpacked = unpack_params("vibrance", blob)
        assert unpacked["amount"] == 50.0
        # Other defaults should be present
        assert "amount" in unpacked


class TestUnpackParams:
    """Tests for unpack_params function."""

    def test_unpack_exposure(self):
        """Unpack exposure blob recovers values."""
        original = {
            "mode": 1,
            "black": 0.1,
            "exposure": 2.5,
            "deflicker_percentile": 75.0,
            "deflicker_target_level": -2.0,
            "compensate_exposure_bias": 1,
        }
        blob = pack_params("exposure", original)
        unpacked = unpack_params("exposure", blob)

        for key, val in original.items():
            if isinstance(val, float):
                assert abs(unpacked[key] - val) < 1e-6, f"{key}: {unpacked[key]} != {val}"
            else:
                assert unpacked[key] == val, f"{key}: {unpacked[key]} != {val}"

    def test_unpack_filmicrgb(self):
        """Unpack filmicrgb blob recovers values."""
        original = {
            "contrast": 1.5,
            "latitude": 25.0,
            "saturation": 10.0,
            "grey_point_target": 20.0,
        }
        blob = pack_params("filmicrgb", original)
        unpacked = unpack_params("filmicrgb", blob)

        for key, val in original.items():
            if isinstance(val, float):
                assert abs(unpacked[key] - val) < 1e-6, f"{key}: {unpacked[key]} != {val}"
            else:
                assert unpacked[key] == val

    def test_unpack_colorbalancergb(self):
        """Unpack colorbalancergb blob recovers values."""
        original = {
            "global_Y": 0.1,
            "global_C": 0.2,
            "saturation_global": 0.3,
            "vibrance": 0.5,
        }
        blob = pack_params("colorbalancergb", original)
        unpacked = unpack_params("colorbalancergb", blob)

        for key, val in original.items():
            if isinstance(val, float):
                assert abs(unpacked[key] - val) < 1e-6, f"{key}: {unpacked[key]} != {val}"
            else:
                assert unpacked[key] == val

    def test_unpack_sigmoid(self):
        """Unpack sigmoid blob recovers values."""
        original = {
            "middle_grey_contrast": 2.0,
            "contrast_skewness": 0.1,
            "display_white_target": 200.0,
        }
        blob = pack_params("sigmoid", original)
        unpacked = unpack_params("sigmoid", blob)

        for key, val in original.items():
            if isinstance(val, float):
                assert abs(unpacked[key] - val) < 1e-6, f"{key}: {unpacked[key]} != {val}"
            else:
                assert unpacked[key] == val

    def test_unpack_atrous(self):
        """Unpack atrous blob recovers values."""
        original = {
            "octaves": 5,
            "mix": 0.75,
            "x_0_0": 0.1,
            "y_1_2": -0.2,
        }
        blob = pack_params("atrous", original)
        unpacked = unpack_params("atrous", blob)

        for key, val in original.items():
            if isinstance(val, float):
                assert abs(unpacked[key] - val) < 1e-6, f"{key}: {unpacked[key]} != {val}"
            else:
                assert unpacked[key] == val

    def test_unpack_simple_iops(self):
        """Unpack simple IOPs."""
        for op in list_unverified():
            blob = pack_params(op, {})
            unpacked = unpack_params(op, blob)
            # Should contain all fields
            reg = get_registry(op)
            for field in reg.fields:
                assert field in unpacked

    def test_unpack_unknown_operation(self):
        """Unpack unknown operation raises ValueError."""
        with pytest.raises(ValueError, match="Unknown operation"):
            unpack_params("nonexistent", b"data")

    def test_unpack_size_mismatch(self):
        """Unpack with wrong blob size raises ValueError (for verified IOPs)."""
        # exposure expects 24 bytes
        with pytest.raises(ValueError, match="Blob size mismatch"):
            unpack_params("exposure", b"x" * 20)

        with pytest.raises(ValueError, match="Blob size mismatch"):
            unpack_params("exposure", b"x" * 30)

    def test_unpack_no_size_check_unverified(self):
        """Unpack unverified IOP doesn't check size against registry."""
        # Should not raise size mismatch error since vibrance.size_bytes is None
        # But struct.unpack still requires correct format size (4 bytes for <f)
        blob = b"x" * 4
        result = unpack_params("vibrance", blob)
        assert isinstance(result, dict)


class TestRoundTrip:
    """Round-trip tests: pack -> unpack should recover original values."""

    @pytest.mark.parametrize(
        "op",
        [
            op
            for op in list_verified()
            if get_registry(op).pack_format != "<basecurve>"
            and get_registry(op).pack_format != "<pass_through>"
        ],
    )
    def test_roundtrip_verified_iops(self, op):
        """Round-trip for all verified IOPs with defaults."""
        # Curve-based IOPs require a template; skip the no-params path
        reg = get_registry(op)
        params = {} if not getattr(reg, "is_curve_iop", False) else {"curve_preset": "identity"}
        blob = pack_params(op, params)
        unpacked = unpack_params(op, blob)

        # Skip curve_preset field — it's a synthetic marker, not a real field
        for field in reg.fields:
            if getattr(reg, "is_curve_iop", False) and field == "curve_preset":
                continue
            original_val = reg.defaults[field]
            unpacked_val = unpacked[field]
            if isinstance(original_val, float):
                assert (
                    abs(unpacked_val - original_val) < 1e-6
                ), f"{op}.{field}: {unpacked_val} != {original_val}"
            else:
                assert (
                    unpacked_val == original_val
                ), f"{op}.{field}: {unpacked_val} != {original_val}"

    @pytest.mark.parametrize("op", list_unverified())
    def test_roundtrip_unverified_iops(self, op):
        """Round-trip for all unverified IOPs with defaults."""
        blob = pack_params(op, {})
        unpacked = unpack_params(op, blob)
        reg = get_registry(op)

        for field in reg.fields:
            original_val = reg.defaults[field]
            unpacked_val = unpacked[field]
            if isinstance(original_val, float):
                assert (
                    abs(unpacked_val - original_val) < 1e-6
                ), f"{op}.{field}: {unpacked_val} != {original_val}"
            else:
                assert (
                    unpacked_val == original_val
                ), f"{op}.{field}: {unpacked_val} != {original_val}"

    def test_roundtrip_filmicrgb_specific(self):
        """Specific test for filmicrgb with values from completion criteria."""
        # Completion criteria: pack_params("filmicrgb", {"contrast": 1.5, "latitude": 25.0})
        # → 116-byte blob, unpack recovers input
        blob = pack_params("filmicrgb", {"contrast": 1.5, "latitude": 25.0})
        assert len(blob) == 116

        unpacked = unpack_params("filmicrgb", blob)
        assert abs(unpacked["contrast"] - 1.5) < 1e-6
        assert abs(unpacked["latitude"] - 25.0) < 1e-6

    def test_roundtrip_exposure_specific(self):
        """Specific test for exposure."""
        blob = pack_params("exposure", {"exposure": 1.5, "black": 0.1})
        assert len(blob) == 28

        unpacked = unpack_params("exposure", blob)
        assert abs(unpacked["exposure"] - 1.5) < 1e-6
        assert abs(unpacked["black"] - 0.1) < 1e-6


class TestVerifySize:
    """Tests for verify_size function."""

    def test_verify_correct_size(self):
        """verify_size returns True for correct blob sizes."""
        for op in list_verified():
            reg = get_registry(op)
            # Skip read-only IOPs (basecurve has curve data that can't be packed)
            if reg.pack_format in ("<basecurve>", "<pass_through>"):
                continue
            params = {} if not getattr(reg, "is_curve_iop", False) else {"curve_preset": "identity"}
            blob = pack_params(op, params)
            assert verify_size(op, blob), f"verify_size failed for {op}"

    def test_verify_wrong_size(self):
        """verify_size returns False for incorrect blob sizes."""
        for op in list_verified():
            reg = get_registry(op)
            wrong_blob = b"x" * (reg.size_bytes + 1)
            assert not verify_size(op, wrong_blob), f"verify_size should fail for wrong size {op}"

    def test_verify_unverified_returns_true(self):
        """verify_size returns True for unverified IOPs (can't verify)."""
        for op in list_unverified():
            assert verify_size(op, b"any size")
            assert verify_size(op, b"")


class TestRegistryStructure:
    """Tests for registry entry structure and consistency."""

    def test_all_have_pack_format(self):
        """All registry entries should have pack_format."""
        for _op, reg in IOP_REGISTRY.items():
            assert reg.pack_format
            assert reg.pack_format.startswith("<")

    def test_all_have_fields(self):
        """All registry entries should have fields tuple."""
        for _op, reg in IOP_REGISTRY.items():
            assert isinstance(reg.fields, tuple)
            assert len(reg.fields) > 0

    def test_all_have_defaults(self):
        """All registry entries should have defaults dict."""
        for _op, reg in IOP_REGISTRY.items():
            assert isinstance(reg.defaults, dict)
            assert set(reg.defaults.keys()) == set(reg.fields)

    def test_all_have_ranges(self):
        """All registry entries should have ranges dict."""
        for _op, reg in IOP_REGISTRY.items():
            assert isinstance(reg.ranges, dict)
            assert set(reg.ranges.keys()) == set(reg.fields)

    def test_all_have_blendop_cst(self):
        """All registry entries should have blendop_cst (2, 3, or 4)."""
        for op, reg in IOP_REGISTRY.items():
            assert reg.blendop_cst in (2, 3, 4), f"{op} has invalid blendop_cst: {reg.blendop_cst}"

    def test_verified_iops_blendop_cst(self):
        """Verified IOPs should have correct blendop_cst (per blend.h:
        2 = LAB, 3 = RGB_DISPLAY, 4 = RGB_SCENE)."""
        # Scene-referred RGB (blendop_cst=4)
        for op in ["filmicrgb", "colorbalancergb", "sigmoid"]:
            reg = get_registry(op)
            assert reg.blendop_cst == 4, f"{op} should be scene-referred (4)"

        # Display-referred RGB (blendop_cst=3)
        # exposure uses RGB_DISPLAY per src/iop/exposure.c:324
        reg = get_registry("exposure")
        assert reg.blendop_cst == 3, "exposure should be display-referred (3)"

        # Lab-based (blendop_cst=2)
        for op in ["atrous", "bilat"]:
            reg = get_registry(op)
            assert reg.blendop_cst == 2, f"{op} should be Lab-based (2)"

    def test_version_numbers(self):
        """Version numbers should match known versions."""
        assert get_registry("exposure").version == 7
        assert get_registry("filmicrgb").version == 6
        assert get_registry("colorbalancergb").version == 5
        assert get_registry("sigmoid").version == 3
        assert get_registry("atrous").version == 2


class TestEdgeCases:
    """Edge case and error handling tests."""

    def test_pack_with_extra_params_ignored(self):
        """Extra params not in fields should be ignored (merged but not packed)."""
        # This should not raise - extra params are filtered by field order
        blob = pack_params("vibrance", {"amount": 50.0, "extra_field": 123})
        unpacked = unpack_params("vibrance", blob)
        assert "extra_field" not in unpacked
        assert unpacked["amount"] == 50.0

    def test_unpack_returns_all_fields(self):
        """Unpack should return all fields defined in registry."""
        for op in list_registered():
            reg = get_registry(op)
            # Skip read-only IOPs that can't be packed
            if reg.pack_format == "<basecurve>":
                continue
            params = {} if not getattr(reg, "is_curve_iop", False) else {"curve_preset": "identity"}
            blob = pack_params(op, params)
            unpacked = unpack_params(op, blob)
            assert set(unpacked.keys()) == set(reg.fields)

    def test_int_fields_packed_correctly(self):
        """Integer fields should pack as integers, not floats."""
        blob = pack_params("exposure", {"mode": 1, "compensate_exposure_bias": 1})
        unpacked = unpack_params("exposure", blob)
        assert isinstance(unpacked["mode"], int)
        assert isinstance(unpacked["compensate_exposure_bias"], int)
        assert unpacked["mode"] == 1
        assert unpacked["compensate_exposure_bias"] == 1

    def test_gboolean_fields(self):
        """gboolean fields (0/1 ints) should pack correctly."""
        blob = pack_params("filmicrgb", {"auto_hardness": 1, "custom_grey": 0})
        unpacked = unpack_params("filmicrgb", blob)
        assert unpacked["auto_hardness"] == 1
        assert unpacked["custom_grey"] == 0


# ---------------------------------------------------------------------------
# Refinement IOPs (v0.4.0): temperature, basicadj, toneequal, colorequal
# ---------------------------------------------------------------------------


class TestRefinementIops:
    """Round-trip pack/unpack for the refinement IOPs."""

    REFINEMENT_OPS = [
        ("temperature", 20, "<4fi", 5),
        ("basicadj", 44, "<5fi5f", 11),
        ("toneequal", 72, "<15f3i", 18),
        ("colorequal", 128, "<6fi24ff", 32),
        ("colorharmonizer", 60, "<i4f4fi4ff", 15),
    ]

    @pytest.mark.parametrize("op,size,fmt,nfields", REFINEMENT_OPS)
    def test_registered_with_verified_size(self, op, size, fmt, nfields):
        reg = get_registry(op)
        assert reg is not None
        assert reg.size_bytes == size
        assert reg.pack_format == fmt
        assert len(reg.fields) == nfields
        assert len(reg.ranges) == nfields
        assert len(reg.defaults) == nfields

    @pytest.mark.parametrize("op,size,_fmt,_nfields", REFINEMENT_OPS)
    def test_pack_defaults_roundtrip(self, op, size, _fmt, _nfields):
        blob = pack_params(op, {})
        assert len(blob) == size
        unpacked = unpack_params(op, blob)
        assert set(unpacked.keys()) == set(get_registry(op).fields)
        for field, default in get_registry(op).defaults.items():
            assert abs(float(unpacked[field]) - float(default)) < 1e-4, field

    def test_temperature_custom_values(self):
        blob = pack_params("temperature", {"red": 1.5, "green": 0.9, "preset": 2})
        p = unpack_params("temperature", blob)
        assert abs(p["red"] - 1.5) < 1e-5
        assert abs(p["green"] - 0.9) < 1e-5
        assert p["preset"] == 2
        assert isinstance(p["preset"], int)

    def test_basicadj_enum_mid_struct(self):
        """preserve_colors is an int enum sitting mid-struct (<5fi5f)."""
        blob = pack_params("basicadj", {"preserve_colors": 3, "exposure": 1.0})
        p = unpack_params("basicadj", blob)
        assert p["preserve_colors"] == 3
        assert isinstance(p["preserve_colors"], int)
        assert abs(p["exposure"] - 1.0) < 1e-5
        # Fields after the enum must still decode in order
        assert abs(p["middle_grey"] - 18.42) < 1e-2

    def test_toneequal_bands_and_enums(self):
        blob = pack_params(
            "toneequal",
            {
                "midtones": 0.8,
                "blacks": -0.5,
                "feathering": 100.0,
                "iterations": 3,
                "details": 2,
                "method": 1,
            },
        )
        p = unpack_params("toneequal", blob)
        assert abs(p["midtones"] - 0.8) < 1e-5
        assert abs(p["blacks"] + 0.5) < 1e-5
        assert abs(p["feathering"] - 100.0) < 1e-3
        assert p["iterations"] == 3
        assert p["details"] == 2
        assert p["method"] == 1

    def test_colorequal_custom_values(self):
        blob = pack_params(
            "colorequal",
            {
                "hue_blue": 45.0,
                "sat_red": 1.5,
                "threshold": 0.2,
                "hue_shift": 12.0,
                "use_filter": 0,
            },
        )
        p = unpack_params("colorequal", blob)
        assert abs(p["hue_blue"] - 45.0) < 1e-5
        assert abs(p["sat_red"] - 1.5) < 1e-5
        assert abs(p["threshold"] - 0.2) < 1e-5
        assert abs(p["hue_shift"] - 12.0) < 1e-5
        assert p["use_filter"] == 0
        assert isinstance(p["use_filter"], int)

    def test_clamps_out_of_range(self):
        """Ranges are enforced by pack_params."""
        with pytest.raises(ValueError):
            pack_params("colorequal", {"threshold": 0.9})  # max 0.3
        with pytest.raises(ValueError):
            pack_params("toneequal", {"iterations": 0})  # min 1

    def test_colorharmonizer_defaults(self):
        """colorharmonizer: <i4f4fi4ff 60B with rule enum first."""
        blob = pack_params("colorharmonizer", {})
        assert len(blob) == 60
        p = unpack_params("colorharmonizer", blob)
        assert p["rule"] == 3  # COMPLEMENTARY
        assert isinstance(p["rule"], int)
        assert abs(p["anchor_hue"] - 0.1) < 1e-5
        assert abs(p["neutral_protection"] - 0.5) < 1e-5
        assert p["num_custom_nodes"] == 4
        assert isinstance(p["num_custom_nodes"], int)
        assert len(p) == 15

    def test_colorharmonizer_custom_values_and_clamp(self):
        blob = pack_params(
            "colorharmonizer",
            {
                "rule": 9,
                "anchor_hue": 0.6,
                "pull_strength": 0.8,
                "custom_hue_0": 0.25,
                "custom_hue_3": 0.9,
                "node_saturation_1": 1.5,
                "smoothing": 1.5,
            },
        )
        p = unpack_params("colorharmonizer", blob)
        assert p["rule"] == 9
        assert abs(p["anchor_hue"] - 0.6) < 1e-5
        assert abs(p["pull_strength"] - 0.8) < 1e-5
        assert abs(p["custom_hue_0"] - 0.25) < 1e-5
        assert abs(p["custom_hue_3"] - 0.9) < 1e-5
        assert abs(p["node_saturation_1"] - 1.5) < 1e-5
        assert abs(p["smoothing"] - 1.5) < 1e-5
        with pytest.raises(ValueError):
            pack_params("colorharmonizer", {"anchor_hue": 1.5})  # max 1.0
        with pytest.raises(ValueError):
            pack_params("colorharmonizer", {"num_custom_nodes": 1})  # min 2


class TestColorequalRealBlobs:
    """Verify our colorequal layout against REAL blobs from official
    darktable styles (committed as fixtures so CI can verify without
    the 534-preset library)."""

    FIXTURES = Path(__file__).parent / "fixtures"

    def _first_colorequal_blob(self, path: Path) -> bytes:
        import xml.etree.ElementTree as ET

        from dtstylekit.codec.xmp_codec import decode_xmp

        root = ET.parse(path).getroot()
        for plugin in root.findall("style/plugin"):
            if plugin.findtext("operation") == "colorequal":
                return decode_xmp(plugin.findtext("op_params", "") or "")
        raise AssertionError(f"no colorequal plugin in {path}")

    @pytest.mark.parametrize(
        "fixture_name",
        [
            "examples_colors_autumn.dtstyle",
            "examples_spot color_blue.dtstyle",
            "examples_spot color_red.dtstyle",
        ],
    )
    def test_real_blob_size_and_unpack(self, fixture_name):
        fixture = self.FIXTURES / fixture_name
        assert fixture.exists(), f"missing fixture {fixture_name}"
        blob = self._first_colorequal_blob(fixture)
        assert len(blob) == 128
        assert verify_size("colorequal", blob)
        unpacked = unpack_params("colorequal", blob)
        assert len(unpacked) == 32

    def test_autumn_blob_semantics(self):
        """examples_colors_autumn: shifts greens to yellow and yellows to
        orange — green/yellow saturation up, green hue rotated negative
        (toward yellow)."""
        fixture = self.FIXTURES / "examples_colors_autumn.dtstyle"
        p = unpack_params("colorequal", self._first_colorequal_blob(fixture))
        # Defaults preserved
        assert abs(p["threshold"] - 0.1) < 1e-5
        assert abs(p["smoothing_hue"] - 1.0) < 1e-5
        assert p["use_filter"] == 1
        # Green/yellow boosted (autumn foliage)
        assert p["sat_green"] > 1.2
        assert p["sat_yellow"] > 1.2
        # Green hue rotated negative → toward yellow
        assert p["hue_green"] < -30.0
        assert p["hue_yellow"] < -30.0
        # Node placement neutral
        assert abs(p["hue_shift"]) < 1e-4


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
