"""XMP codec for Darktable blob encoding/decoding.

Replicates dt_exif_xmp_encode / dt_exif_xmp_decode from darktable source.
See format_analysis.md §3 and §9 for algorithm details.
"""

import base64
import zlib


def encode_xmp(data: bytes, compress_threshold: int = 100) -> str:
    """Encode binary data to XMP string format.

    Args:
        data: Raw binary data (struct.pack output)
        compress_threshold: Use gz+base64 if len(data) > threshold (default 100)

    Returns:
        Hex string (if <= threshold) or gzXX<base64> string (if > threshold)

    Per format_analysis.md §3:
    - Hex: no prefix, each byte -> 2 hex chars
    - gz+base64: prefix "gz" + 2-digit factor + base64(zlib.compress(data))
    """
    if len(data) > compress_threshold:
        compressed = zlib.compress(data)
        factor = min(len(data) // len(compressed) + 1, 99)
        b64 = base64.b64encode(compressed).decode("ascii")
        return f"gz{factor // 10}{factor % 10}{b64}"
    else:
        return data.hex()


def decode_xmp(s: str) -> bytes:
    """Decode XMP string back to binary data.

    Args:
        s: Encoded string (hex or gzXX<base64>)

    Returns:
        Decoded binary data

    Per format_analysis.md §3 and §9:
    - If starts with "gz": extract factor (2 digits), base64 decode, zlib decompress
    - Else: hex decode

    Raises:
        ValueError: If input format is invalid
    """
    if s.startswith("gz"):
        if len(s) < 4:
            raise ValueError(f"Invalid gz format: too short: {s!r}")
        # Extract compression factor (2 digits)
        try:
            factor = 10 * (ord(s[2]) - ord("0")) + (ord(s[3]) - ord("0"))
        except (ValueError, IndexError):
            raise ValueError(f"Invalid gz factor in: {s!r}") from None
        b64_data = s[4:]
        if not b64_data:
            raise ValueError(f"Missing base64 data in: {s!r}")
        try:
            compressed = base64.b64decode(b64_data)
        except Exception as e:
            raise ValueError(f"Invalid base64 data in: {s!r}") from e
        buf_len = factor * len(compressed)
        while True:
            try:
                return zlib.decompress(compressed, bufsize=buf_len)
            except zlib.error:
                buf_len *= 2
    else:
        try:
            return bytes.fromhex(s)
        except ValueError as e:
            raise ValueError(f"Invalid hex data: {s!r}") from e


def verify_roundtrip(data: bytes, compress_threshold: int = 100) -> bool:
    """Verify encode/decode round-trip preserves data."""
    encoded = encode_xmp(data, compress_threshold)
    decoded = decode_xmp(encoded)
    return decoded == data


# Test vectors from blob_size_calibration.md §3
# DEFAULT_BLENDOP_DISPLAY = "gz08eJxjYGBgYAFiCQYYOOHEgAZY0QWAgBGLGANDgz0Ej1Q+dlAx68oBEMbFxwX+AwGIBgCbGCeh"
# DEFAULT_BLENDOP_SCENE = "gz10eJxjYGBgYAJiCQYYOOHEgAZY0QWAgBGLGANDgz0Ej1Q+dcF/IADRAG2yHQc="

# Expected decoded sizes (from blob_size_calibration.md §1):
# filmicrgb v6: 116 bytes
# colorbalancergb v5: 132 bytes
# sigmoid v3: 56 bytes
# exposure v6: 24 bytes
# atrous v2: 248 bytes
