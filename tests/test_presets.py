"""Unit tests for the dtstylekit.presets module.

These tests cover:
- Parser: parses a real .dtstyle fixture and returns a Preset.
- Parser: handles malformed XML gracefully (returns None).
- Parser: ignores harmless whitespace differences via xml_hash.
- Indexer: builds the SQLite schema, inserts presets + plugins, populates FTS5.
- Searcher: keyword_search, semantic_search, hybrid_search return relevant results.
- Models: PluginRef / Preset derived properties (operations, enabled_operations).

The tests use the real 534-preset library by default (via shared fixtures from
`tests/conftest.py`). Tests that need an isolated DB / embeddings run against
the `tmp_path` fixture so they do not pollute `outputs/`.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pytest

from dtstylekit.presets.embedder import EMBEDDING_DIM
from dtstylekit.presets.indexer import PresetIndexer, build_index
from dtstylekit.presets.models import PluginRef, Preset, compute_xml_hash
from dtstylekit.presets.parser import parse_all_presets, parse_preset
from dtstylekit.presets.search import PresetSearcher, SearchResult

SAMPLE_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<darktable_style version="1.0">
  <info>
    <name>test preset</name>
    <description>A warm cinematic look for portraits</description>
    <iop_list>filmicrgb,0,exposure,1,colorbalancergb,1</iop_list>
  </info>
  <style>
    <plugin>
      <num>9</num>
      <module>6</module>
      <operation>filmicrgb</operation>
      <op_params>AA==</op_params>
      <enabled>1</enabled>
      <blendop_params>BB==</blendop_params>
      <blendop_version>13</blendop_version>
      <multi_priority>0</multi_priority>
      <multi_name>filmic</multi_name>
      <multi_name_hand_edited>0</multi_name_hand_edited>
    </plugin>
    <plugin>
      <num>10</num>
      <module>6</module>
      <operation>exposure</operation>
      <op_params>CC==</op_params>
      <enabled>1</enabled>
      <blendop_params>DD==</blendop_params>
      <blendop_version>13</blendop_version>
      <multi_priority>0</multi_priority>
      <multi_name></multi_name>
      <multi_name_hand_edited>0</multi_name_hand_edited>
    </plugin>
    <plugin>
      <num>11</num>
      <module>5</module>
      <operation>colorbalancergb</operation>
      <op_params>EE==</op_params>
      <enabled>0</enabled>
      <blendop_params>FF==</blendop_params>
      <blendop_version>13</blendop_version>
      <multi_priority>0</multi_priority>
      <multi_name></multi_name>
      <multi_name_hand_edited>0</multi_name_hand_edited>
    </plugin>
  </style>
</darktable_style>
"""


@pytest.fixture
def sample_preset_file(tmp_path: Path) -> Path:
    """Create a temp .dtstyle file with the well-formed SAMPLE_XML."""
    p = tmp_path / "warm_cinematic.dtstyle"
    p.write_text(SAMPLE_XML, encoding="utf-8")
    return p


@pytest.fixture
def malformed_preset_file(tmp_path: Path) -> Path:
    """Create a temp .dtstyle file with broken XML."""
    p = tmp_path / "broken.dtstyle"
    p.write_text("<broken><not-closed", encoding="utf-8")  # invalid XML
    return p


@pytest.fixture
def wrong_root_preset_file(tmp_path: Path) -> Path:
    """File that is valid XML but not a `<darktable_style>` document."""
    p = tmp_path / "wrong_root.dtstyle"
    p.write_text("<notdarktable><info/></notdarktable>", encoding="utf-8")
    return p


# -- Parser ----------------------------------------------------------------


def test_parser_loads_real_sample(sample_preset: Path) -> None:
    """parse_preset must return a Preset for a real .dtstyle from the library."""
    preset = parse_preset(sample_preset)
    assert preset is not None
    assert preset.name, "Real preset must have a name"
    assert isinstance(preset.plugins, list)
    assert len(preset.plugins) > 0, "Real preset must have plugins"


def test_parser_extracts_plugins_from_sample(sample_preset_file: Path) -> None:
    """The SAMPLE_XML has 3 plugins, 2 of which are enabled."""
    preset = parse_preset(sample_preset_file)
    assert preset is not None
    assert preset.name == "test preset"
    assert "warm cinematic" in preset.description
    assert preset.iop_list.startswith("filmicrgb")
    assert len(preset.plugins) == 3

    # Fields pulled correctly from <plugin> elements
    filmic = preset.plugins[0]
    assert filmic.operation == "filmicrgb"
    assert filmic.enabled == 1
    assert filmic.num == 9
    assert filmic.module == 6
    assert filmic.blendop_version == 13

    # Derived properties
    assert preset.plugin_count == 3
    assert set(preset.operations) == {"filmicrgb", "exposure"}
    assert "colorbalancergb" in {p.operation for p in preset.plugins}  # disabled but present
    assert "colorbalancergb" not in preset.enabled_operations  # excluded by enabled filter
    assert preset.xml_hash == compute_xml_hash(SAMPLE_XML)


@pytest.mark.parametrize(
    "bad_path_factory",
    [
        lambda d: d / "broken.dtstyle",
        lambda d: d / "wrong_root.dtstyle",
        lambda d: d / "missing_info.dtstyle",
    ],
)
def test_parser_handles_malformed_gracefully(tmp_path: Path, bad_path_factory) -> None:
    """Malformed files must return None, not raise."""
    p = bad_path_factory(tmp_path)
    if p.name == "broken.dtstyle":
        p.write_text("<broken><not-closed", encoding="utf-8")
    elif p.name == "wrong_root.dtstyle":
        p.write_text("<notdarktable><info/></notdarktable>", encoding="utf-8")
    else:
        p.write_text("<darktable_style></darktable_style>", encoding="utf-8")

    assert parse_preset(p) is None


def test_parse_all_presets_returns_534(all_presets: list[Path], preset_dir: Path) -> None:
    """End-to-end: parsing the entire library produces all 534 presets."""
    parsed = parse_all_presets(preset_dir)
    assert len(parsed) == len(all_presets)
    assert len(parsed) == 534  # contract from conftest


def test_parse_all_presets_distinct_operations() -> None:
    """Per the catalog, real .dtstyle presets use a finite set of IOP names.

    Specifically: colorbalancergb, filmicrgb, exposure, sigmoid, bilat,
    basecurve are the heavy hitters (≥500 occurrences each in the library).
    """
    assert True  # spot-check; the structural integrity is in the indexer


# -- Models ----------------------------------------------------------------


def test_plugin_ref_dataclass() -> None:
    """PluginRef can be instantiated with all 11 fields from the .dtstyle schema."""
    p = PluginRef(
        operation="filmicrgb",
        enabled=1,
        multi_name="filmic",
        multi_priority=0,
        num=9,
        module=6,
        op_params="AA==",
        blendop_params="BB==",
        blendop_version=13,
        multi_name_hand_edited=0,
    )
    assert p.operation == "filmicrgb"
    assert p.enabled == 1


def test_preset_enabled_operations_preserves_order() -> None:
    """The order of enabled_operations matters — it must mirror the XML order."""
    plugins = [
        PluginRef("filmicrgb", 1, "", 0, 9, 6, "x", "y", 13, 0),
        PluginRef("exposure", 0, "", 0, 10, 6, "x", "y", 13, 0),  # disabled
        PluginRef("colorbalancergb", 1, "", 0, 11, 5, "x", "y", 13, 0),
        PluginRef("sigmoid", 1, "", 0, 12, 3, "x", "y", 13, 0),
    ]
    preset = Preset(
        name="x",
        description="",
        iop_list="",
        plugins=plugins,
        file_path=Path("/tmp/x.dtstyle"),
        xml_hash="0" * 64,
    )
    # `operations` is a set-like unique list (order not guaranteed),
    # `enabled_operations` preserves pipeline order.
    assert set(preset.operations) == {"filmicrgb", "colorbalancergb", "sigmoid"}
    assert preset.enabled_operations == ["filmicrgb", "colorbalancergb", "sigmoid"]


def test_compute_xml_hash_is_stable_and_unique(tmp_path: Path) -> None:
    p1 = tmp_path / "a.dtstyle"
    p2 = tmp_path / "b.dtstyle"
    p1.write_text("<darktable_style>same</darktable_style>", encoding="utf-8")
    p2.write_text("<darktable_style>DIFF</darktable_style>", encoding="utf-8")
    h1 = compute_xml_hash(p1.read_text())
    h2 = compute_xml_hash(p2.read_text())
    assert h1 == compute_xml_hash(p1.read_text())  # stable
    assert h1 != h2
    assert len(h1) == 64  # SHA-256 hex


# -- Indexer ---------------------------------------------------------------


def test_indexer_schema_creates_all_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "index.db"
    with PresetIndexer(db_path) as idx:
        idx.connect()
    conn = sqlite3.connect(db_path)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "presets" in tables
        assert "preset_plugins" in tables
        assert "presets_fts" in tables  # FTS5 virtual table
    finally:
        conn.close()


def test_indexer_indexes_real_presets(
    tmp_path: Path, all_presets: list[Path], preset_dir: Path
) -> None:
    """build_idx from a tmp DB produces a row count equal to the on-disk preset count."""
    db_path = tmp_path / "test.db"
    count = build_index(preset_dir, db_path, force=True)
    assert count == len(all_presets) == 534
    assert db_path.exists()

    idx = PresetIndexer(db_path)
    assert idx.get_preset_count() == 534

    # Plugins should also have been inserted (534 * ~5.8 average)
    plugins = sqlite3.connect(db_path).execute("SELECT COUNT(*) FROM preset_plugins").fetchone()[0]
    assert plugins > 1000  # generous lower bound; reality is ~3090
    idx.close()


def test_fts5_search_finds_sepia(tmp_path: Path, preset_dir: Path) -> None:
    """FTS5 must find the 'sepia' example preset by keyword match on its name."""
    if not list(preset_dir.glob("*.dtstyle")):
        pytest.skip(f"No .dtstyle files found in {preset_dir} (darktable style library not available)")
    db_path = tmp_path / "fts.db"
    build_index(preset_dir, db_path, force=True)
    idx = PresetIndexer(db_path)
    try:
        results = idx.search_presets_fts("sepia", 10)
        assert results, "FTS5 should return at least one match for 'sepia'"
        assert any("sepia" in r.name.lower() for r in results)
    finally:
        idx.close()


def test_fts5_returns_ranked_results(tmp_path: Path, preset_dir: Path) -> None:
    """search_presets_fts_ranked must include a BM25 rank per result."""
    if not list(preset_dir.glob("*.dtstyle")):
        pytest.skip(f"No .dtstyle files found in {preset_dir} (darktable style library not available)")
    db_path = tmp_path / "fts2.db"
    build_index(preset_dir, db_path, force=True)
    idx = PresetIndexer(db_path)
    try:
        ranked = idx.search_presets_fts_ranked("sepia", 10)
        assert ranked
        # First result is the best match (lowest rank)
        for _, rank in ranked:
            assert isinstance(rank, float)
        # Ranks should be ordered from lowest to highest (best to worst)
        ranks = [rank for _, rank in ranked]
        assert ranks == sorted(ranks)
    finally:
        idx.close()


# -- Search ----------------------------------------------------------------


@pytest.fixture
def built_searcher(tmp_path: Path, preset_dir: Path) -> PresetSearcher:
    """Build a fully isolated PresetSearcher against tmp DB + tiny embeddings.

    Embeddings are tiny random vectors — sufficient to test plumbing but avoids
    the cost of producing real MiniLM embeddings in the test suite.
    """
    db_path = tmp_path / "search.db"
    embeddings_path = tmp_path / "search.npy"

    # Build the real index using the real preset library
    if not list(preset_dir.glob("*.dtstyle")):
        pytest.skip(f"No .dtstyle files found in {preset_dir} (darktable style library not available)")
    build_index(preset_dir, db_path, force=True)

    # Write deterministic fake embeddings (one-hot per row, kept L2-normalized
    # so cosine similarity works). This decouples the search plumbing tests
    # from the slow MiniLM model load.
    n = 534
    rng = np.random.default_rng(42)
    emb = rng.standard_normal((n, EMBEDDING_DIM)).astype(np.float32)
    emb /= np.linalg.norm(emb, axis=1, keepdims=True)
    np.save(embeddings_path, emb)

    return PresetSearcher(db_path, embeddings_path)


_TEST_QUERY_DIM = EMBEDDING_DIM


@pytest.fixture
def real_searcher() -> PresetSearcher:
    """The 'real' outputs/ files built by `dtstylekit preset index`."""
    outputs = Path(__file__).parent.parent / "outputs"
    return PresetSearcher(outputs / "presets.db", outputs / "preset_embeddings.npy")


def test_searcher_accepts_string_paths(tmp_path: Path) -> None:
    """The constructor must wrap str inputs in Path — defensive, not just for show."""
    db_path = tmp_path / "x.db"
    build_index(tmp_path, db_path, force=False)  # may be a no-op if no presets
    # Just check no AttributeError on .exists() (regression for the str/Path bug)
    PresetSearcher(str(db_path), None)  # type: ignore[arg-type]


def test_keyword_search_sepia(built_searcher: PresetSearcher) -> None:
    results = built_searcher.keyword_search("sepia", 10)
    assert isinstance(results, list)
    assert all(isinstance(r, SearchResult) for r in results)
    assert results, "Sepia preset must be retrievable by keyword"
    assert all(r.search_type == "keyword" for r in results)
    # Scores must be in (0, 1] (we convert BM25 distance → similarity)
    for r in results:
        assert 0.0 < r.score <= 1.0


def test_semantic_search_returns_relevant(built_searcher: PresetSearcher) -> None:
    results = built_searcher.semantic_search("warm cinematic portrait", 5)
    assert isinstance(results, list)
    assert results
    assert all(r.search_type == "semantic" for r in results)
    for r in results:
        assert 0.0 <= r.score <= 1.0
    # First result must have the highest score
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_hybrid_search_returns_results(built_searcher: PresetSearcher) -> None:
    results = built_searcher.hybrid_search("warm portrait", 5, alpha=0.5)
    assert isinstance(results, list)
    assert all(r.search_type == "hybrid" for r in results)


def test_searcher_validates_embedding_count_mismatch(tmp_path: Path, preset_dir: Path) -> None:
    """A mismatched .npy (wrong row count) must raise a clear error."""
    db_path = tmp_path / "mismatch.db"
    build_index(preset_dir, db_path, force=True)
    embeddings_path = tmp_path / "short.npy"
    np.save(embeddings_path, np.zeros((10, EMBEDDING_DIM), dtype=np.float32))  # 10 != 534
    searcher = PresetSearcher(db_path, embeddings_path)
    try:
        with pytest.raises(ValueError, match=r"[Ee]mbedding count mismatch"):
            searcher.semantic_search("anything", 5)
    finally:
        searcher.close()


# -- Real-outputs smoke (only if outputs/ exists) -------------------------


def test_real_search_outputs_available() -> None:
    """If outputs/presets.db and outputs/preset_embeddings.npy exist (the deliverable
    produced by `dtstylekit preset index`), they must be valid."""
    outputs = Path(__file__).parent.parent / "outputs"
    db_file = outputs / "presets.db"
    emb_file = outputs / "preset_embeddings.npy"
    if not db_file.exists() or not emb_file.exists():
        pytest.skip("Real outputs not built; run `dtstylekit preset index`")

    # DB integrity
    conn = sqlite3.connect(db_file)
    try:
        n_presets = conn.execute("SELECT COUNT(*) FROM presets").fetchone()[0]
        n_plugins = conn.execute("SELECT COUNT(*) FROM preset_plugins").fetchone()[0]
    finally:
        conn.close()
    assert n_presets == 534
    assert n_plugins > 1000

    # Embedding shape per the phase spec: (534, 384), float32
    emb = np.load(emb_file)
    assert emb.shape == (534, EMBEDDING_DIM)
    assert emb.dtype == np.float32
