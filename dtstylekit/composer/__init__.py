"""Composer module: merge presets, generate .dtstyle, generate reports."""

from .merger import ComposerPlugin, merge_presets
from .generator import generate_dtstyle
from .report import generate_report
from .roundtrip import test_roundtrip, find_darktable_cli

__all__ = [
    "ComposerPlugin",
    "merge_presets",
    "generate_dtstyle",
    "generate_report",
    "test_roundtrip",
    "find_darktable_cli",
]
