"""CLI parser contract tests.

Guards the ``generate``/``analyze`` alias against flag drift: the alias
previously had its own parser without ``--refine-raw``/``--temperature``,
so ``dtstylekit analyze`` crashed with ``AttributeError`` before reaching
the VLM.
"""

from __future__ import annotations

import argparse

import pytest

import dtstylekit.cli as cli


def test_generate_and_analyze_share_flags() -> None:
    parser = cli.build_parser()
    generate = vars(parser.parse_args(["generate", "photo.jpg"]))
    analyze = vars(parser.parse_args(["analyze", "photo.jpg"]))

    assert set(generate) == set(analyze)
    assert analyze["command"] == "analyze"
    assert analyze["refine_raw"] is None
    assert analyze["refine_iterations"] == 0
    assert analyze["temperature"] is None


def test_apply_command_parses_style_and_images() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["apply", "style.dtstyle", "image.jpg"])
    assert args.command == "apply"
    assert args.style == "style.dtstyle"
    assert args.images == ["image.jpg"]
    assert args.output == "outputs"


def test_apply_command_dispatches_to_cmd_apply(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_cmd_apply(args: argparse.Namespace) -> int:
        seen.append(args.command)
        return 0

    monkeypatch.setattr(cli, "cmd_apply", fake_cmd_apply)

    assert cli.main(["apply", "style.dtstyle", "image.jpg"]) == 0
    assert seen == ["apply"]


def test_preset_subcommand_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("dtstylekit.presets.cli.main_preset", lambda _args: 7)
    assert cli.main(["preset", "index"]) == 7


def test_vlm_generate_subcommand_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("dtstylekit.vlm.cli.cmd_vlm_generate", lambda _args: 8)
    assert cli.main(["vlm", "generate", "image.jpg"]) == 8


def test_curves_subcommand_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("dtstylekit.curves.cli.cmd_curves", lambda _args: 9)
    assert cli.main(["curves", "list"]) == 9


@pytest.mark.parametrize("command", ["generate", "analyze"])
def test_command_dispatches_to_cmd_generate(command: str, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_cmd_generate(args: argparse.Namespace) -> int:
        seen.append(args.command)
        return 0

    monkeypatch.setattr(cli, "cmd_generate", fake_cmd_generate)

    assert cli.main([command, "photo.jpg"]) == 0
    assert seen == [command]
