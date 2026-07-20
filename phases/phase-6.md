# Phase 6: Composer & Orchestrator — style_composer, report, CLI, tests
**Type:** Backend/Logic

## Objective
Build the final composition pipeline: merge selected presets + scalar adjustments into a valid `.dtstyle`, generate markdown report, create the CLI entry point, and implement round-trip tests with real Darktable.

## Project Snapshot
> See `plan.md` → `## Project Snapshot`

## Required Context
- **Preset merging**: Multiple presets can be selected by VLM. Must merge their plugin lists respecting pipeline order (`iop_list` or default order from `src/common/iop_order.c`). Conflicts: same operation → keep highest priority or combine if different `multi_name`.
- **Scalar adjustments**: VLM proposes param tweaks for verified IOPs (filmicrgb, colorbalancergb, sigmoid, exposure, atrous). Apply on top of preset base using `iop_registry.pack_params()`.
- **Serializer**: Uses `codec.serializer.encode_plugin()` + `build_dtstyle_xml()` from Phase 3.
- **Report**: Markdown with style name, description, image analysis summary, preset(s) used, adjustments made, and rationale (from VLM `---REPORT---` section).
- **CLI**: Single entry point `dtstylekit generate <image> [--direction] [--model] [--output]`.
- **Round-trip test**: Generate `.dtstyle` → import via `darktable-cli` → verify no errors → export → compare blobs.

## Related Files (for context)
- `dtstylekit/codec/serializer.py`: `encode_plugin()`, `build_dtstyle_xml()` (Phase 3)
- `dtstylekit/codec/iop_registry.py`: `IOP_REGISTRY`, `pack_params()` (Phase 3)
- `dtstylekit/presets/search.py`: `PresetSearcher` (Phase 2)
- `dtstylekit/presets/parser.py`: Parse preset XML for merging (Phase 2)
- `dtstylekit/vlm/orchestrator.py`: `generate_style_spec()` (Phase 5)
- `dtstylekit/analyzer/pipeline.py`: `ImageAnalysis` (Phase 4)
- `../glm5Generated/format_analysis.md`: §2 (XML structure), §6 (iop_list), §10 (generate_dtstyle recipe)
- `../glm5Generated/darktable_source_map.md`: `src/common/iop_order.c` (pipeline order)
- `../src/common/styles.c:1269-1383`: Darktable's style writer for reference

## Inputs
- `StyleSpec` from VLM orchestrator (validated plugins with params, style_name, description)
- Selected preset objects (from search) to use as base
- Image analysis JSON (for report)

## Tasks
- [ ] Create `dtstylekit/composer/merger.py`: `merge_presets(presets: list[Preset], adjustments: dict[operation, dict]) -> list[PluginDict]`
  - Load plugins from each preset via parser
  - Combine into single plugin list, deduplicate by (operation, multi_name) — keep last
  - Apply scalar adjustments: for each operation in `adjustments`, find plugin and update params via `pack_params(merged_defaults + adjustments)`
  - Sort plugins by pipeline order (use `iop_list` from first preset or default order)
- [ ] Create `dtstylekit/composer/generator.py`: `generate_dtstyle(spec: StyleSpec, presets: list[Preset], analysis: ImageAnalysis, output_path: Path) -> Path`
  - Call merger → list of plugin dicts
  - Call `serializer.build_dtstyle_xml()` with spec name/description + merged plugins
  - Write `.dtstyle` file
- [ ] Create `dtstylekit/composer/report.py`: `generate_report(spec: StyleSpec, presets: list[Preset], analysis: ImageAnalysis, vlm_report: str, output_path: Path) -> Path`
  - Markdown sections: Style Overview, Image Analysis, Presets Used, Adjustments Applied, VLM Rationale, Import Instructions
  - Table of each plugin: operation, multi_name, key params changed, before/after values
- [ ] Create `dtstylekit/cli.py`: Main entry point with `typer`:
  - `generate` command: `dtstylekit generate <image> --direction "..." --model "gemma3:4b" --output ./styles/`
  - `preset index` subcommand (from Phase 2)
  - `vlm generate` subcommand (from Phase 5)
  - Config file support: `~/.config/dtstylekit/config.toml` (default model, output dir, Ollama host)
- [ ] Create `dtstylekit/composer/roundtrip.py`: `test_roundtrip(dtstyle_path: Path, darktable_cli: str = "darktable-cli") -> bool`
  - Run `darktable-cli --import-style <file>` — verify exit code 0
  - Optional: apply to test image, export, re-import, compare blobs
- [ ] Write integration tests:
  - End-to-end: test image → full pipeline → `.dtstyle` + report
  - Round-trip: generate → import in darktable → verify
  - CLI: `dtstylekit generate tests/fixtures/test.jpg --direction "warm portrait"`

## Expected Outputs
- `dtstylekit/composer/merger.py`: Preset merging + adjustment application
- `dtstylekit/composer/generator.py`: `.dtstyle` file generation
- `dtstylekit/composer/report.py`: Markdown report generator
- `dtstylekit/composer/roundtrip.py`: Round-trip test utility
- `dtstylekit/cli.py`: Typer CLI with `generate`, `preset`, `vlm` subcommands
- `dtstylekit/composer/__init__.py`: Exports
- `tests/test_composer.py`: Unit tests for merger, generator, report
- `tests/test_integration.py`: End-to-end + round-trip tests
- `tests/fixtures/`: Sample images for testing

## Dependencies
- Phase 2 (PresetSearcher, parser)
- Phase 3 (serializer, iop_registry)
- Phase 4 (ImageAnalysis)
- Phase 5 (StyleSpec, VLM orchestrator)

## Completion Criteria
- [ ] `dtstylekit generate tests/fixtures/test.jpg --direction "cinematic warm"` produces valid `.dtstyle` + `.md` report
- [ ] Generated `.dtstyle` imports in Darktable without errors (`darktable-cli --import-style`)
- [ ] Report includes: style name, image stats, presets used, param adjustments table, VLM rationale
- [ ] CLI has help text, config file support, subcommands work
- [ ] Round-trip test passes for at least 3 generated styles
- [ ] All tests pass: `pytest tests/test_composer.py tests/test_integration.py -v`