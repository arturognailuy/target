"""Database initialization and schema management."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_key TEXT NOT NULL UNIQUE,
    source_type TEXT,
    created_at TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    trust_level REAL NOT NULL DEFAULT 1.0,
    metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS record_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id INTEGER NOT NULL REFERENCES records(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    token_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE(record_id, chunk_index)
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
    chunk_text,
    content='record_chunks',
    content_rowid='id',
    tokenize='unicode61'
);

-- Triggers to keep FTS in sync with record_chunks
CREATE TRIGGER IF NOT EXISTS chunk_fts_insert AFTER INSERT ON record_chunks BEGIN
    INSERT INTO chunk_fts(rowid, chunk_text) VALUES (new.id, new.chunk_text);
END;

CREATE TRIGGER IF NOT EXISTS chunk_fts_delete AFTER DELETE ON record_chunks BEGIN
    INSERT INTO chunk_fts(chunk_fts, rowid, chunk_text) VALUES ('delete', old.id, old.chunk_text);
END;

CREATE TRIGGER IF NOT EXISTS chunk_fts_update AFTER UPDATE ON record_chunks BEGIN
    INSERT INTO chunk_fts(chunk_fts, rowid, chunk_text) VALUES ('delete', old.id, old.chunk_text);
    INSERT INTO chunk_fts(chunk_fts, rowid, chunk_text) VALUES (new.id, new.chunk_text);
END;

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);
"""


def open_db(path: str | Path) -> sqlite3.Connection:
    """Open or create a Target database with WAL mode and schema applied."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA_SQL)

    # Track schema version
    row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        conn.commit()

    return conn
