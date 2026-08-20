"""Pytest configuration and fixtures for dtstylekit tests."""

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def preset_dir() -> Path:
    """Path to the preset directory (symlink to ../../data/styles)."""
    return Path(__file__).parent.parent / "dtstylekit" / "data" / "presets"


@pytest.fixture(scope="session")
def sample_preset(preset_dir: Path) -> Path:
    """Return path to a sample .dtstyle preset file."""
    presets = list(preset_dir.glob("*.dtstyle"))
    if not presets:
        pytest.skip(f"No .dtstyle files found in {preset_dir} (darktable style library not available)")
    return presets[0]


@pytest.fixture(scope="session")
def all_presets(preset_dir: Path) -> list[Path]:
    """Return list of all .dtstyle preset files."""
    presets = list(preset_dir.glob("*.dtstyle"))
    if not presets:
        pytest.skip(f"No .dtstyle files found in {preset_dir} (darktable style library not available)")
    return presets


@pytest.fixture(scope="session")
def sample_image_path() -> Path | None:
    """Path to a sample test image if available, otherwise None."""
    # Look for test images in common locations
    candidates = [
        Path(__file__).parent / "data" / "test.jpg",
        Path(__file__).parent / "data" / "test.raw",
        Path(__file__).parent.parent / "data" / "test.jpg",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


@pytest.fixture
def temp_dir(tmp_path: Path) -> Path:
    """Provide a temporary directory for test outputs."""
    return tmp_path
