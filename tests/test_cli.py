"""Tests for CLI commands."""

from click.testing import CliRunner

from target_search.cli import main


class TestCLI:
    def test_stats_empty(self, tmp_path):
        runner = CliRunner()
        db = str(tmp_path / "test.db")
        result = runner.invoke(main, ["--db", db, "stats"])
        assert result.exit_code == 0
        assert "Records: 0" in result.output

    def test_index_and_query(self, tmp_path):
        runner = CliRunner()
        db = str(tmp_path / "test.db")
        doc_file = tmp_path / "doc.txt"
        doc_file.write_text("Python is great for data science and machine learning.")

        # Index
        result = runner.invoke(main, ["--db", db, "index", "test:python", str(doc_file)])
        assert result.exit_code == 0
        assert "indexed" in result.output

        # Query
        result = runner.invoke(main, ["--db", db, "query", "data science"])
        assert result.exit_code == 0
        assert "test:python" in result.output

    def test_index_stdin(self, tmp_path):
        runner = CliRunner()
        db = str(tmp_path / "test.db")
        result = runner.invoke(
            main, ["--db", db, "index-stdin", "test:stdin"],
            input="Hello from stdin content.",
        )
        assert result.exit_code == 0
        assert "indexed" in result.output

    def test_query_json(self, tmp_path):
        runner = CliRunner()
        db = str(tmp_path / "test.db")
        doc_file = tmp_path / "doc.txt"
        doc_file.write_text("Rust is a systems programming language.")

        runner.invoke(main, ["--db", db, "index", "test:rust", str(doc_file)])
        result = runner.invoke(main, ["--db", db, "query", "programming", "--json-output"])
        assert result.exit_code == 0
        assert '"doc_key"' in result.output

    def test_query_no_results(self, tmp_path):
        runner = CliRunner()
        db = str(tmp_path / "test.db")
        result = runner.invoke(main, ["--db", db, "query", "nonexistent"])
        assert result.exit_code == 0
        assert "No results" in result.output

    def test_lex_mode_correction_ranking(self, tmp_path):
        """Corrector doc should rank above corrected doc even in lex-only mode."""
        runner = CliRunner()
        db = str(tmp_path / "test.db")
        v1 = tmp_path / "v1.txt"
        v1.write_text("We lost the game.")
        v2 = tmp_path / "v2.txt"
        v2.write_text("No. Actually, we won the game.")

        runner.invoke(main, ["--db", db, "index", "doc:v1", str(v1)])
        runner.invoke(main, ["--db", db, "index", "doc:v2", str(v2)])
        runner.invoke(main, ["--db", db, "correct", "doc:v2", "doc:v1", "--reason", "Updated"])

        result = runner.invoke(main, ["--db", db, "query", "game", "--json-output"])
        assert result.exit_code == 0
        import json
        data = json.loads(result.output)
        assert len(data) == 2
        # Corrector (doc:v2) should rank first
        assert data[0]["doc_key"] == "doc:v2"
        assert data[1]["doc_key"] == "doc:v1"
        # Both should have correction features
        assert data[0]["features"]["C"] > 0
        assert data[1]["features"]["C"] < 0
