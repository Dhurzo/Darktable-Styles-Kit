# Phase 5: VLM Integration — Prompt, Query, Parse
**Type:** Backend/Logic

## Objective
Build the VLM prompt system: construct prompts with image analysis + preset search results, call Ollama with a VLM model, parse the JSON response, and validate against the IOP registry.

## Project Snapshot
> See `plan.md` → `## Project Snapshot`

## Required Context
- VLM runs via Ollama (local): models `llava:7b`, `gemma3:4b`, `llama3.2-vision:11b`
- Ollama Python client: `ollama.chat(model, messages, options)` with `messages=[{"role": "user", "content": prompt, "images": [base64_image]}]`
- Prompt structure per `architecture_proposal.md` §2.2 and `ai_integration_notes.md` §2-4:
  - System: Role + output format spec (JSON + ---REPORT---)
  - IOP schema: Compact table of available IOPs with key params/ranges (from `iop_registry.py`)
  - Image analysis: Compact JSON from `ImageAnalysis.to_prompt_dict()`
  - Preset candidates: Top-K from `PresetSearcher.hybrid_search()` with name, description, key IOPs
  - User direction: Style direction string (e.g., "cinematic warm portrait", "film emulation Portra 400")
- Output format: JSON block with `style_name`, `style_description`, `plugins[]` (operation, enabled, multi_name, params), optional `iop_list`, then `---REPORT---` markdown section
- Temperature: 0.3-0.5 for consistency (per `ai_integration_notes.md` §6)
- Validation: Parse JSON, verify all operations exist in `IOP_REGISTRY`, clamp params to ranges, merge defaults

## Related Files (for context)
- `../glm5Generated/ai_integration_notes.md`: §2 (prompt design), §3 (templates), §4 (schema), §5 (post-processing), §6 (temperature), §7 (few-shot), §8 (error handling)
- `../glm5Generated/architecture_proposal.md`: §2.2 (style_prompter), §4 (data flow)
- `../glm5Generated/iop_modules_catalog.md`: IOP list for schema inclusion
- `dtstylekit/codec/iop_registry.py`: `IOP_REGISTRY` for validation (Phase 3)
- `dtstylekit/presets/search.py`: `PresetSearcher.hybrid_search()` (Phase 2)
- `dtstylekit/analyzer/pipeline.py`: `analyze_image()` (Phase 4)

## Inputs
- Image path (for VLM vision + analysis)
- Style direction string (user input or "auto")
- Ollama model name (configurable, default `gemma3:4b`)

## Tasks
- [ ] Create `dtstylekit/vlm/models.py`: `VLMRequest`, `VLMResponse`, `StyleSpec` (parsed JSON), `ReportSection` dataclasses
- [ ] Create `dtstylekit/vlm/prompt_builder.py`: `build_prompt(analysis: ImageAnalysis, presets: list[Preset], direction: str, iop_schema: str) -> list[dict]` — returns Ollama messages format
- [ ] Create `dtstylekit/vlm/schema_renderer.py`: `render_iop_schema(registry: IOPRegistry, max_iops: int = 12) -> str` — compact markdown table for prompt
- [ ] Create `dtstylekit/vlm/client.py`: `VLMClient` class with `generate(messages, model, temperature, options) -> str` — wraps Ollama client with retries/timeout
- [ ] Create `dtstylekit/vlm/parser.py`: `parse_response(text: str) -> tuple[StyleSpec, str]` — extracts JSON + report (per `ai_integration_notes.md` §5.1)
- [ ] Create `dtstylekit/vlm/validator.py`: `validate_style(spec: StyleSpec, registry: IOPRegistry) -> tuple[StyleSpec, list[str]]` — clamps params, merges defaults, returns validated spec + warnings
- [ ] Create `dtstylekit/vlm/orchestrator.py`: `generate_style_spec(image_path, direction, model, searcher, analyzer, registry) -> tuple[StyleSpec, str]` — end-to-end: analyze → search → prompt → VLM → parse → validate
- [ ] Create `dtstylekit/vlm/cli.py`: Subcommand `dtstylekit vlm generate <image> --direction "..." --model "..."`
- [ ] Write tests: mock Ollama response, test parser/validator with various inputs

## Expected Outputs
- `dtstylekit/vlm/models.py`: Request/response dataclasses
- `dtstylekit/vlm/prompt_builder.py`: Prompt construction with all sections
- `dtstylekit/vlm/schema_renderer.py`: IOP schema rendering for prompt
- `dtstylekit/vlm/client.py`: Ollama wrapper with error handling
- `dtstylekit/vlm/parser.py`: JSON + report extraction
- `dtstylekit/vlm/validator.py`: Validation + default merging + clamping
- `dtstylekit/vlm/orchestrator.py`: End-to-end VLM style generation
- `dtstylekit/vlm/cli.py`: `vlm generate` subcommand
- `tests/test_vlm.py`: Unit tests with mocked Ollama

## Dependencies
- Phase 2 (PresetSearcher)
- Phase 3 (IOP (IOPRegistry, validation)
- Phase 4 (ImageAnalysis)

## Completion Criteria
- [ ] `build_prompt()` produces messages with all sections, total <6000 tokens (leaves room for output)
- [ ] `parse_response()` extracts JSON and report from VLM output (handles ```json``` fences and raw JSON)
- [ ] `validate_style()` clamps out-of-range params, merges defaults, rejects unknown IOPs
- [ ] `orchestrator.generate_style_spec()` returns validated `StyleSpec` + report for test image
- [ ] Works with at least one Ollama VLM model (`gemma3:4b` or `llava:7b`)
- [ ] All tests pass: `pytest tests/test_vlm.py -v`