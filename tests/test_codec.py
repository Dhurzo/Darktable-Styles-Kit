"""Round-trip tests for XMP codec and blendop functions."""

import pytest

from dtstylekit.codec import (
    DEFAULT_BLENDOP_DISPLAY,
    DEFAULT_BLENDOP_LAB,
    DEFAULT_BLENDOP_SCENE,
    create_blendop,
    create_blendop_scene,
    decode_xmp,
    encode_xmp,
    get_blend_cst,
    get_blend_mode,
    get_opacity,
    patch_blend_cst,
    patch_blend_mode,
    patch_opacity,
    verify_blendop_size,
    verify_roundtrip,
)


class TestXMPCodec:
    """Tests for encode_xmp / decode_xmp round-trips."""

    def test_roundtrip_hex_small(self):
        """Round-trip for data <= 100 bytes (hex encoding)."""
        # Various sizes under threshold
        for size in [0, 1, 50, 99, 100]:
            data = bytes(range(size))
            assert verify_roundtrip(data), f"Round-trip failed for size {size}"

    def test_roundtrip_gz_large(self):
        """Round-trip for data > 100 bytes (gz+base64 encoding)."""
        for size in [101, 200, 420, 1000, 5000]:
            data = bytes([i % 256 for i in range(size)])
            assert verify_roundtrip(data), f"Round-trip failed for size {size}"

    def test_roundtrip_exact_threshold(self):
        """Test exactly at threshold boundary (100 bytes)."""
        data = b"x" * 100
        encoded = encode_xmp(data, compress_threshold=100)
        assert not encoded.startswith("gz"), "Should use hex at exactly 100 bytes"
        assert verify_roundtrip(data, compress_threshold=100)

        data = b"x" * 101
        encoded = encode_xmp(data, compress_threshold=100)
        assert encoded.startswith("gz"), "Should use gz at 101 bytes"
        assert verify_roundtrip(data, compress_threshold=100)

    def test_empty_bytes(self):
        """Empty bytes encode to empty hex string."""
        encoded = encode_xmp(b"")
        assert encoded == ""
        assert decode_xmp("") == b""

    def test_known_vectors_display(self):
        """Test vectors from blob_size_calibration.md §3."""
        # DEFAULT_BLENDOP_DISPLAY decodes to 420 bytes
        blob = decode_xmp(DEFAULT_BLENDOP_DISPLAY)
        assert len(blob) == 420

        # Re-encode should produce equivalent (may differ in factor digits)
        re_encoded = encode_xmp(blob)
        re_decoded = decode_xmp(re_encoded)
        assert re_decoded == blob

    def test_known_vectors_scene(self):
        """Test vectors for scene blendop."""
        blob = decode_xmp(DEFAULT_BLENDOP_SCENE)
        assert len(blob) == 420

        re_encoded = encode_xmp(blob)
        re_decoded = decode_xmp(re_encoded)
        assert re_decoded == blob

    def test_decode_hex(self):
        """Direct hex decode test."""
        data = b"hello world"
        encoded = data.hex()
        decoded = decode_xmp(encoded)
        assert decoded == data

    def test_decode_gz(self):
        """Direct gz+base64 decode test."""
        data = b"x" * 200
        encoded = encode_xmp(data, compress_threshold=100)
        assert encoded.startswith("gz")
        decoded = decode_xmp(encoded)
        assert decoded == data

    def test_invalid_input(self):
        """Invalid inputs should raise appropriate errors."""
        with pytest.raises(ValueError):
            decode_xmp("not_hex_or_gz")

        with pytest.raises(ValueError):
            decode_xmp("gz")  # too short

        with pytest.raises(ValueError):
            decode_xmp("gz00")  # no base64 data


class TestBlendop:
    """Tests for blendop constants and patching functions."""

    def test_default_constants_exist(self):
        """Default blendop constants should be defined."""
        assert DEFAULT_BLENDOP_DISPLAY.startswith("gz")
        assert DEFAULT_BLENDOP_SCENE.startswith("gz")
        assert DEFAULT_BLENDOP_LAB.startswith("gz")

    def test_default_sizes(self):
        """Default blendops should decode to 420 bytes."""
        assert verify_blendop_size(DEFAULT_BLENDOP_DISPLAY)
        assert verify_blendop_size(DEFAULT_BLENDOP_SCENE)
        assert verify_blendop_size(DEFAULT_BLENDOP_LAB)

    def test_default_color_spaces(self):
        """Color spaces per blend.h: 2=LAB, 3=RGB_DISPLAY, 4=RGB_SCENE."""
        assert get_blend_cst(DEFAULT_BLENDOP_DISPLAY) == 3
        assert get_blend_cst(DEFAULT_BLENDOP_SCENE) == 4
        assert get_blend_cst(DEFAULT_BLENDOP_LAB) == 2

    def test_patch_opacity(self):
        """Patch opacity at offset 16 (float32, 0-100%)."""
        # Default opacity is 100.0
        assert get_opacity(DEFAULT_BLENDOP_DISPLAY) == 100.0

        # Patch to 50%
        patched = patch_opacity(DEFAULT_BLENDOP_DISPLAY, 50.0)
        assert get_opacity(patched) == 50.0

        # Patch to 0%
        patched = patch_opacity(DEFAULT_BLENDOP_DISPLAY, 0.0)
        assert get_opacity(patched) == 0.0

        # Patch to 75.5%
        patched = patch_opacity(DEFAULT_BLENDOP_DISPLAY, 75.5)
        assert abs(get_opacity(patched) - 75.5) < 0.01

    def test_patch_blend_mode(self):
        """Patch blend_mode at offset 8 (uint32)."""
        assert get_blend_mode(DEFAULT_BLENDOP_DISPLAY) == 24

        patched = patch_blend_mode(DEFAULT_BLENDOP_DISPLAY, 0)
        assert get_blend_mode(patched) == 0

        patched = patch_blend_mode(DEFAULT_BLENDOP_DISPLAY, 15)
        assert get_blend_mode(patched) == 15

    def test_patch_blend_cst(self):
        """Patch blend_cst at offset 4 (int32)."""
        assert get_blend_cst(DEFAULT_BLENDOP_DISPLAY) == 3

        patched = patch_blend_cst(DEFAULT_BLENDOP_DISPLAY, 2)
        assert get_blend_cst(patched) == 2

        patched = patch_blend_cst(DEFAULT_BLENDOP_SCENE, 3)
        assert get_blend_cst(patched) == 3

    def test_create_blendop_display(self):
        """Create custom blendop from display template."""
        # Default params
        blendop = create_blendop()
        assert get_opacity(blendop) == 100.0
        assert get_blend_mode(blendop) == 24
        assert get_blend_cst(blendop) == 3

        # Custom opacity
        blendop = create_blendop(opacity=50.0)
        assert get_opacity(blendop) == 50.0

        # Custom mode
        blendop = create_blendop(mode=15)
        assert get_blend_mode(blendop) == 15

        # Custom cst
        blendop = create_blendop(cst=2)
        assert get_blend_cst(blendop) == 2

        # All custom
        blendop = create_blendop(opacity=75.0, mode=10, cst=2)
        assert get_opacity(blendop) == 75.0
        assert get_blend_mode(blendop) == 10
        assert get_blend_cst(blendop) == 2

    def test_create_blendop_scene(self):
        """Create custom blendop from scene template."""
        blendop = create_blendop_scene()
        assert get_blend_cst(blendop) == 4
        assert get_opacity(blendop) == 100.0
        assert get_blend_mode(blendop) == 24

        blendop = create_blendop_scene(opacity=25.0, mode=5)
        assert get_opacity(blendop) == 25.0
        assert get_blend_mode(blendop) == 5
        assert get_blend_cst(blendop) == 4

    def test_patch_order_independence(self):
        """Patching in different orders should give same result."""
        # Order: cst, mode, opacity
        a = create_blendop(opacity=50.0, mode=10, cst=2)
        # Manual order
        b = DEFAULT_BLENDOP_DISPLAY
        b = patch_blend_cst(b, 2)
        b = patch_blend_mode(b, 10)
        b = patch_opacity(b, 50.0)

        assert get_opacity(a) == get_opacity(b)
        assert get_blend_mode(a) == get_blend_mode(b)
        assert get_blend_cst(a) == get_blend_cst(b)

    def test_patch_preserves_size(self):
        """Patching should not change blob size."""
        for func, val in [
            (patch_opacity, 50.0),
            (patch_blend_mode, 10),
            (patch_blend_cst, 2),
        ]:
            patched = func(DEFAULT_BLENDOP_DISPLAY, val)
            assert verify_blendop_size(patched), f"{func.__name__} changed size"


class TestBlendopEdgeCases:
    """Edge case tests for blendop functions."""

    def test_opacity_float_precision(self):
        """Opacity should handle float values correctly."""
        patched = patch_opacity(DEFAULT_BLENDOP_DISPLAY, 33.333)
        assert abs(get_opacity(patched) - 33.333) < 0.001

    def test_blend_mode_uint32(self):
        """Blend mode should accept full uint32 range."""
        patched = patch_blend_mode(DEFAULT_BLENDOP_DISPLAY, 0xFFFFFFFF)
        assert get_blend_mode(patched) == 0xFFFFFFFF

    def test_blend_cst_int32(self):
        """Blend cst should accept int32 range."""
        patched = patch_blend_cst(DEFAULT_BLENDOP_DISPLAY, -1)
        assert get_blend_cst(patched) == -1

        patched = patch_blend_cst(DEFAULT_BLENDOP_DISPLAY, 0x7FFFFFFF)
        assert get_blend_cst(patched) == 0x7FFFFFFF

    def test_roundtrip_patched(self):
        """Patched blendops should still round-trip through encode/decode."""
        patched = patch_opacity(DEFAULT_BLENDOP_DISPLAY, 50.0)
        blob = decode_xmp(patched)
        re_encoded = encode_xmp(blob)
        re_decoded = decode_xmp(re_encoded)
        assert re_decoded == blob


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
