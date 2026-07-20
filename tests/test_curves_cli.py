"""Tests for the curves CLI subcommand."""

from __future__ import annotations

from io import StringIO
from unittest.mock import patch

import pytest

from dtstylekit.curves.cli import (
    cmd_curves_list,
    cmd_curves_info,
)


def _make_namespace(**kwargs):
    import argparse
    return argparse.Namespace(**kwargs)


class TestCurvesList:
    def test_list_default(self, capsys) -> None:
        args = _make_namespace(category=None, quiet=False)
        rc = cmd_curves_list(args)
        assert rc == 0
        captured = capsys.readouterr().out
        assert "Curve templates (19 total" in captured
        for tmpl in ["s_strong", "lift_medium", "bleach_bypass", "shadow_cool"]:
            assert tmpl in captured

    def test_list_quiet(self, capsys) -> None:
        args = _make_namespace(category=None, quiet=True)
        rc = cmd_curves_list(args)
        assert rc == 0
        out = capsys.readouterr().out
        # Quiet mode: just names, one per line
        assert "s_strong" in out
        assert "bleach_bypass" in out
        # Should NOT contain category headers
        assert "───" not in out

    def test_list_filter_category(self, capsys) -> None:
        args = _make_namespace(category="vintage", quiet=False)
        rc = cmd_curves_list(args)
        assert rc == 0
        out = capsys.readouterr().out
        # Only vintage items
        assert "lift_medium" in out
        assert "inverted_s_strong" in out
        assert "inverted_s_soft" in out
        # Contrast-only items NOT in output (use word-boundary check
        # to avoid "s_strong" matching "inverted_s_strong")
        # We check that no line starts with whitespace + "s_strong" + " "
        # (which is the format used by the list renderer)
        lines_with_s_strong_alone = [
            line for line in out.split("\n")
            if "s_strong" in line and "inverted_s_strong" not in line
        ]
        assert not lines_with_s_strong_alone, (
            f"Found unexpected s_strong lines: {lines_with_s_strong_alone}"
        )
        # Bleach-bypass must NOT be there either
        assert "bleach_bypass" not in out

    def test_list_quiet_filter_category(self, capsys) -> None:
        args = _make_namespace(category="filmic", quiet=True)
        rc = cmd_curves_list(args)
        assert rc == 0
        out_lines = capsys.readouterr().out.strip().split("\n")
        assert set(out_lines) == {"highlights_soft", "bleach_bypass", "matte_film"}

    def test_list_unknown_category(self, capsys) -> None:
        # Category not registered -> empty result, exit 1, helpful message
        args = _make_namespace(category="doesntexist", quiet=False)
        rc = cmd_curves_list(args)
        assert rc == 1
        err = capsys.readouterr().err
        assert "No templates found" in err


class TestCurvesInfo:
    def test_info_known_template(self, capsys) -> None:
        args = _make_namespace(name="s_strong")
        rc = cmd_curves_info(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Template: s_strong" in out
        assert "Title:" in out
        assert "Category:" in out
        assert "Nodes per channel:" in out

    def test_info_unknown_template(self, capsys) -> None:
        args = _make_namespace(name="nonexistent_template")
        rc = cmd_curves_info(args)
        assert rc == 1
        err = capsys.readouterr().err
        assert "Unknown curve template" in err

    def test_info_includes_example_json(self, capsys) -> None:
        args = _make_namespace(name="bleach_bypass")
        rc = cmd_curves_info(args)
        out = capsys.readouterr().out
        assert '"operation": "tonecurve"' in out
        assert '"curve_preset": "bleach_bypass"' in out


class TestCliIntegration:
    """Quick end-to-end check: run main() with 'curves list'."""

    def test_cli_runs_curves_list(self) -> None:
        from dtstylekit.cli import main
        rc = main(["curves", "list", "--quiet"])
        assert rc == 0

    def test_cli_runs_curves_info(self) -> None:
        from dtstylekit.cli import main
        rc = main(["curves", "info", "s_strong"])
        assert rc == 0

    def test_cli_curves_info_unknown_returns_nonzero(self) -> None:
        from dtstylekit.cli import main
        rc = main(["curves", "info", "nothing"])
        assert rc != 0
