"""Composer module: merge presets, generate .dtstyle, generate reports."""

from .explanation import generate_explanation
from .generator import generate_dtstyle
from .merger import ComposerPlugin, merge_presets
from .report import generate_report
from .roundtrip import find_darktable_cli, test_roundtrip

__all__ = [
    "ComposerPlugin",
    "merge_presets",
    "generate_dtstyle",
    "generate_report",
    "generate_explanation",
    "test_roundtrip",
    "find_darktable_cli",
]
