"""SQLite index builder for Darktable preset library."""

import sqlite3
from pathlib import Path

from .models import (
    Preset,
    PresetIndexEntry,
    clean_description,
    derive_category,
    derive_display_name,
)

SCHEMA_SQL = """
-- Main presets table
CREATE TABLE IF NOT EXISTS presets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    iop_list TEXT,
    plugin_count INTEGER NOT NULL DEFAULT 0,
    xml_hash TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    search_text TEXT NOT NULL DEFAULT '',
    file_path TEXT NOT NULL DEFAULT ''
);

-- Plugin references for each preset
CREATE TABLE IF NOT EXISTS preset_plugins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    preset_id INTEGER NOT NULL REFERENCES presets(id) ON DELETE CASCADE,
    operation TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0,
    multi_name TEXT,
    multi_priority INTEGER NOT NULL DEFAULT 0,
    num INTEGER NOT NULL DEFAULT 0,
    module INTEGER NOT NULL DEFAULT 0,
    op_params TEXT,
    blendop_params TEXT,
    blendop_version INTEGER NOT NULL DEFAULT 0,
    multi_name_hand_edited INTEGER NOT NULL DEFAULT 0
);

-- FTS5 virtual table for keyword search on display name, cleaned
-- description, and operations. Index the human-readable ``search_text``
-- rather than the raw i18n keys so the VLM/searcher can actually find
-- artistic presets ("sepia", "faded", "autumn colours") instead of only
-- matching camera baselines.
CREATE VIRTUAL TABLE IF NOT EXISTS presets_fts USING fts5(
    name,
    description,
    iops,
    tokenize='porter unicode61'
);

-- Trigger to keep FTS in sync with presets table
CREATE TRIGGER IF NOT EXISTS presets_fts_insert AFTER INSERT ON presets BEGIN
    INSERT INTO presets_fts(rowid, name, description, iops)
    VALUES (new.id, new.display_name, '', '');
END;

CREATE TRIGGER IF NOT EXISTS presets_fts_delete AFTER DELETE ON presets BEGIN
    DELETE FROM presets_fts WHERE rowid = old.id;
END;

CREATE TRIGGER IF NOT EXISTS presets_fts_update AFTER UPDATE ON presets BEGIN
    DELETE FROM presets_fts WHERE rowid = old.id;
    INSERT INTO presets_fts(rowid, name, description, iops)
    VALUES (new.id, new.display_name, '', '');
END;

-- Indexes for faster plugin lookups
CREATE INDEX IF NOT EXISTS idx_preset_plugins_preset_id ON preset_plugins(preset_id);
CREATE INDEX IF NOT EXISTS idx_preset_plugins_operation ON preset_plugins(operation);
"""


class PresetIndexer:
    """Builds and manages the SQLite preset index."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        """Get or create database connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._init_schema()
        return self._conn

    def _init_schema(self) -> None:
        """Initialize database schema."""
        conn = self.connect()
        conn.executescript(SCHEMA_SQL)
        self._migrate_schema(conn)
        conn.commit()

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        """Add columns added after the initial schema to legacy databases.

        ``ALTER TABLE ADD COLUMN`` is idempotent only if guarded by a
        pre-check on ``PRAGMA table_info``.  We add the v2 columns
        (``display_name``, ``category``, ``search_text``, ``file_path``)
        when they are missing from an already-existing presets table.
        """
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(presets)")}
        migrations = [
            ("display_name", "TEXT NOT NULL DEFAULT ''"),
            ("category", "TEXT NOT NULL DEFAULT ''"),
            ("search_text", "TEXT NOT NULL DEFAULT ''"),
            ("file_path", "TEXT NOT NULL DEFAULT ''"),
        ]
        for col, decl in migrations:
            if col not in existing:
                conn.execute(f"ALTER TABLE presets ADD COLUMN {col} {decl}")

    def close(self) -> None:
        """Close database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "PresetIndexer":
        return self

    def __exit__(
        self, exc_type: type | None, exc_val: BaseException | None, exc_tb: object | None
    ) -> None:
        self.close()

    def clear(self) -> None:
        """Clear all data from the index."""
        conn = self.connect()
        conn.execute("DELETE FROM preset_plugins")
        conn.execute("DELETE FROM presets")
        # Don't delete from presets_fts directly — triggers on 'presets' table handle FTS sync
        conn.commit()

    def index_presets(self, presets: list[Preset]) -> int:
        """
        Index a list of presets into the database.

        Args:
            presets: List of Preset objects to index.

        Returns:
            Number of presets indexed.
        """
        conn = self.connect()
        count = 0

        for preset in presets:
            display_name = derive_display_name(preset.name)
            category = derive_category(preset.name)
            cleaned_desc = clean_description(preset.description)
            enabled_ops = [p.operation for p in preset.plugins if p.enabled == 1]
            search_text = " ".join(
                part
                for part in [
                    display_name,
                    cleaned_desc,
                    " ".join(enabled_ops),
                ]
                if part
            )

            cursor = conn.execute(
                """
                INSERT INTO presets
                    (name, description, iop_list, plugin_count, xml_hash,
                     display_name, category, search_text, file_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    preset.name,
                    preset.description,
                    preset.iop_list,
                    preset.plugin_count,
                    preset.xml_hash,
                    display_name,
                    category,
                    search_text,
                    str(preset.file_path),
                ),
            )
            preset_id = cursor.lastrowid

            # Insert plugins
            for plugin in preset.plugins:
                conn.execute(
                    """
                    INSERT INTO preset_plugins
                    (preset_id, operation, enabled, multi_name, multi_priority, num, module,
                     op_params, blendop_params, blendop_version, multi_name_hand_edited)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        preset_id,
                        plugin.operation,
                        plugin.enabled,
                        plugin.multi_name,
                        plugin.multi_priority,
                        plugin.num,
                        plugin.module,
                        plugin.op_params,
                        plugin.blendop_params,
                        plugin.blendop_version,
                        plugin.multi_name_hand_edited,
                    ),
                )

            count += 1

        # Rebuild FTS table after all presets and plugins are inserted
        # (triggers fire before plugins are inserted, so iops would be NULL).
        # Index display_name as the FTS "name" column, the cleaned
        # description as "description", and enabled operations as "iops"
        # — this is what makes "sepia" / "faded" / "warm autumn colours"
        # searchable.
        conn.execute("DELETE FROM presets_fts")
        conn.execute("""
            INSERT INTO presets_fts (rowid, name, description, iops)
            SELECT p.id, p.display_name, '', ''
            FROM presets p
        """)

        conn.commit()
        return count

    def search_presets_fts(self, query: str, limit: int) -> list[PresetIndexEntry]:
        """
        Search presets using FTS5 full-text search.

        Args:
            query: FTS5 query string.
            limit: Maximum number of results.

        Returns:
            List of PresetIndexEntry objects.
        """
        conn = self.connect()
        cursor = conn.execute(
            """
            SELECT p.id, p.name, p.description, p.iop_list, p.plugin_count, p.xml_hash,
                   p.display_name, p.category, p.search_text, p.file_path,
                   bm25(presets_fts) as rank
            FROM presets_fts
            JOIN presets p ON presets_fts.rowid = p.id
            WHERE presets_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit),
        )

        results = []
        for row in cursor.fetchall():
            results.append(self._row_to_entry(row))
        return results

    def search_presets_fts_ranked(
        self, query: str, limit: int
    ) -> list[tuple[PresetIndexEntry, float]]:
        """
        Search presets using FTS5 and return entries with their BM25 ranks.

        BM25 in SQLite FTS5 is a distance-like value where lower = better match.
        This method returns both the entry and the raw rank so callers can convert
        it to a similarity score if needed.

        Args:
            query: FTS5 query string.
            limit: Maximum number of results.

        Returns:
            List of (PresetIndexEntry, rank) tuples, sorted from best to worst.
        """
        conn = self.connect()
        cursor = conn.execute(
            """
            SELECT p.id, p.name, p.description, p.iop_list, p.plugin_count, p.xml_hash,
                   p.display_name, p.category, p.search_text, p.file_path,
                   bm25(presets_fts) as rank
            FROM presets_fts
            JOIN presets p ON presets_fts.rowid = p.id
            WHERE presets_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit),
        )
        results: list[tuple[PresetIndexEntry, float]] = []
        for row in cursor.fetchall():
            entry = self._row_to_entry(row)
            results.append((entry, float(row["rank"])))
        return results

    def get_preset_by_id(self, preset_id: int) -> PresetIndexEntry | None:
        """Get a preset by its database ID."""
        conn = self.connect()
        cursor = conn.execute(
            """
            SELECT id, name, description, iop_list, plugin_count, xml_hash,
                   display_name, category, search_text, file_path
            FROM presets WHERE id = ?
            """,
            (preset_id,),
        )
        row = cursor.fetchone()
        if row:
            return self._row_to_entry(row)
        return None

    def get_full_preset_by_id(self, preset_id: int) -> Preset | None:
        """Get a fully-populated ``Preset`` (with plugins) by DB id.

        This re-reads plugins from ``preset_plugins`` and is what callers
        should use when they need the actual IOP blobs (e.g. the VLM
        orchestrator).  Differs from :meth:`get_preset_by_id` which only
        returns the lightweight index entry.
        """
        from .models import PluginRef
        from .parser import parse_preset

        conn = self.connect()
        entry = self.get_preset_by_id(preset_id)
        if entry is None:
            return None

        # If we have a file_path, the source-of-truth Preset is the file on
        # disk — re-parse it to recover the plugin op_params/blendops
        # (the preset_plugins table stores them too, but parsing keeps the
        # code path identical to the index builder).
        if entry.file_path:
            from pathlib import Path

            p = parse_preset(Path(entry.file_path))
            if p is not None:
                return p

        # Fallback: rebuild Preset from the preset_plugins table.
        cursor = conn.execute(
            """
            SELECT operation, enabled, multi_name, multi_priority, num, module,
                   op_params, blendop_params, blendop_version, multi_name_hand_edited
            FROM preset_plugins WHERE preset_id = ?
            """,
            (preset_id,),
        )
        plugins: list[PluginRef] = []
        for row in cursor.fetchall():
            plugins.append(
                PluginRef(
                    operation=row["operation"],
                    enabled=row["enabled"],
                    multi_name=row["multi_name"] or "",
                    multi_priority=row["multi_priority"],
                    num=row["num"],
                    module=row["module"],
                    op_params=row["op_params"] or "",
                    blendop_params=row["blendop_params"] or "",
                    blendop_version=row["blendop_version"],
                    multi_name_hand_edited=row["multi_name_hand_edited"],
                )
            )
        from .models import compute_xml_hash

        return Preset(
            name=entry.name,
            description=entry.description,
            iop_list=entry.iop_list,
            plugins=plugins,
            file_path=Path(entry.file_path) if entry.file_path else Path(""),
            xml_hash=entry.xml_hash or compute_xml_hash(""),
        )

    @staticmethod
    def _row_to_entry(row: dict) -> PresetIndexEntry:
        """Convert a sqlite3.Row to a PresetIndexEntry (handles legacy rows)."""
        return PresetIndexEntry(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            iop_list=row["iop_list"],
            plugin_count=row["plugin_count"],
            xml_hash=row["xml_hash"],
            display_name=row["display_name"] if "display_name" in row.keys() else "",
            category=row["category"] if "category" in row.keys() else "",
            search_text=row["search_text"] if "search_text" in row.keys() else "",
            file_path=row["file_path"] if "file_path" in row.keys() else "",
        )

    def get_preset_count(self) -> int:
        """Get total number of presets in the index."""
        conn = self.connect()
        cursor = conn.execute("SELECT COUNT(*) as count FROM presets")
        return int(cursor.fetchone()["count"])

    def get_preset_ids_in_insertion_order(self) -> list[int]:
        """
        Return preset IDs ordered by insertion order (AUTOINCREMENT).

        The semantic searcher uses this to map embedding array row indices
        (which mirror insertion order) to database IDs.
        """
        conn = self.connect()
        cursor = conn.execute("SELECT id FROM presets ORDER BY id ASC")
        return [row["id"] for row in cursor.fetchall()]

    def list_presets(self, category: str | None = None) -> list[PresetIndexEntry]:
        """List all presets, optionally filtered by category.

        Args:
            category: Optional category filter.

        Returns:
            List of PresetIndexEntry objects.
        """
        conn = self.connect()
        if category:
            cursor = conn.execute(
                """
                SELECT id, name, description, iop_list, plugin_count, xml_hash,
                       display_name, category, search_text, file_path
                FROM presets
                WHERE category = ?
                ORDER BY id ASC
                """,
                (category,),
            )
        else:
            cursor = conn.execute(
                """
                SELECT id, name, description, iop_list, plugin_count, xml_hash,
                       display_name, category, search_text, file_path
                FROM presets
                ORDER BY id ASC
                """
            )
        return [self._row_to_entry(row) for row in cursor.fetchall()]


def build_index(preset_dir: Path, db_path: Path, force: bool = False) -> int:
    """
    Convenience function to build the complete index from a preset directory.

    Args:
        preset_dir: Directory containing .dtstyle files.
        db_path: Output database path.
        force: If True, rebuild even if database exists.

    Returns:
        Number of presets indexed.
    """
    from .parser import parse_all_presets

    if db_path.exists() and not force:
        print(f"Database already exists at {db_path}. Use force=True to rebuild.")
        return 0

    presets = parse_all_presets(preset_dir)

    with PresetIndexer(db_path) as indexer:
        indexer.clear()
        count = indexer.index_presets(presets)

    return count
