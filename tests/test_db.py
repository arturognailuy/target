"""Tests for database initialization."""

from target_search.db import SCHEMA_VERSION, open_db


class TestOpenDb:
    def test_creates_db(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = open_db(db_path)
        assert db_path.exists()
        conn.close()

    def test_creates_tables(self, tmp_path):
        conn = open_db(tmp_path / "test.db")
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = [t["name"] for t in tables]
        assert "records" in table_names
        assert "record_chunks" in table_names
        assert "schema_version" in table_names
        conn.close()

    def test_wal_mode(self, tmp_path):
        conn = open_db(tmp_path / "test.db")
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"
        conn.close()

    def test_schema_version(self, tmp_path):
        conn = open_db(tmp_path / "test.db")
        version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
        assert version == SCHEMA_VERSION
        conn.close()

    def test_idempotent_open(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn1 = open_db(db_path)
        conn1.close()
        conn2 = open_db(db_path)
        version = conn2.execute("SELECT version FROM schema_version").fetchone()[0]
        assert version == SCHEMA_VERSION
        conn2.close()

    def test_nested_path(self, tmp_path):
        db_path = tmp_path / "a" / "b" / "c" / "test.db"
        conn = open_db(db_path)
        assert db_path.exists()
        conn.close()
