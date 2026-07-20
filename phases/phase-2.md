# Phase 2: Preset Library — Parse, Index, Embed
**Type:** Backend/Logic

## Objective
Parse all 534 `.dtstyle` files, extract metadata (name, description, IOPs used, blendop info), build a SQLite index with full-text search, and generate semantic embeddings for aesthetic search.

## Project Snapshot
> See `plan.md` → `## Project Snapshot`

## Required Context
- 534 `.dtstyle` files accessible via symlink at `dtstylekit/data/presets/`
- XML structure per `format_analysis.md` §2: `<info><name>`, `<description>`, `<iop_list>`, `<style><plugin>` with `<operation>`, `<enabled>`, `<multi_name>`
- Each preset contains 1-N plugins (IOPs); we need the list of operations and their enabled/multi_name
- Goal: Enable queries like "warm cinematic portrait", "high contrast B&W", "film emulation"
- Embeddings: Use `sentence-transformers/all-MiniLM-L6-v2` (384-dim, fast, good for short text)
- Search: Combine FTS5 (exact/keyword) + vector similarity (semantic)

## Related Files (for context)
- `dtstylekit/data/presets/`: 534 `.dtstyle` files (created in Phase 1)
- `../glm5Generated/format_analysis.md`: XML structure, `<info>`, `<style>`, `<plugin>` fields
- `../glm5Generated/iop_modules_catalog.md`: IOP names and categories for tagging
- `../glm5Generated/darktable_source_map.md`: `src/common/styles.c` parser reference
- `../src/common/styles.c:1619-1680`: Darktable's SAX parser for reference

## Inputs
- `dtstylekit/data/presets/*.dtstyle` (534 files from Phase 1 symlink)

## Tasks
- [ ] Create `dtstylekit/presets/parser.py`: Parse `.dtstyle` XML → `Preset` dataclass (name, description, iop_list, plugins: list of `PluginRef` with operation, enabled, multi_name, multi_priority)
- [ ] Create `dtstylekit/presets/models.py`: Dataclasses `Preset`, `PluginRef`, `PresetIndexEntry`
- [ ] Create `dtstylekit/presets/indexer.py`: Build SQLite database (`presets.db`) with tables:
  - `presets(id, name, description, iop_list, plugin_count, xml_hash)`
  - `preset_plugins(preset_id, operation, enabled, multi_name, multi_priority)`
  - FTS5 virtual table `presets_fts(name, description, iops)` for keyword search
- [ ] Create `dtstylekit/presets/embedder.py`: Generate embeddings for each preset using combined text: `name + " " + description + " " + " ".join(operations)`. Store in `preset_embeddings(preset_id, embedding BLOB)` or separate `.npy` file
- [ ] Create `dtstylekit/presets/search.py`: `PresetSearcher` class with methods:
  - `keyword_search(query: str, limit: int) -> list[Preset]`
  - `semantic_search(query: str, limit: int) -> list[Preset]`
  - `hybrid_search(query: str, limit: int, alpha: float=0.5) -> list[Preset]`
- [ ] Create `dtstylekit/presets/cli.py`: Subcommand `dtstylekit preset index` to build/rebuild index
- [ ] Write tests: parse sample presets, verify plugin extraction, test search queries

## Expected Outputs
- `dtstylekit/presets/models.py`: `Preset`, `PluginRef`, `PresetIndexEntry` dataclasses
- `dtstylekit/presets/parser.py`: XML parser with error handling for malformed files
- `dtstylekit/presets/indexer.py`: SQLite index builder (creates `outputs/presets.db`)
- `dtstylekit/presets/embedder.py`: Embedding generator (saves `outputs/preset_embeddings.npy`)
- `dtstylekit/presets/search.py`: `PresetSearcher` with keyword/semantic/hybrid search
- `dtstylekit/presets/cli.py`: `index` subcommand
- `outputs/presets.db`: SQLite database with 534 presets indexed
- `outputs/preset_embeddings.npy`: (534, 384) float32 array
- `tests/test_presets.py`: Unit tests for parser, indexer, searcher

## Dependencies
- Phase 1 (symlink to presets, package structure)

## Completion Criteria
- [ ] `dtstylekit preset index` completes in <30s, creates `outputs/presets.db` with 534 rows
- [ ] `PresetSearcher.hybrid_search("warm portrait", 5)` returns relevant presets (e.g., containing colorbalancergb, filmicrgb, warm tones)
- [ ] `PresetSearcher.keyword_search("sepia", 10)` finds presets with "sepia" in name/description
- [ ] All 534 presets parsed without errors (malformed XML handled gracefully)
- [ ] Embeddings shape `(534, 384)`, dtype `float32`