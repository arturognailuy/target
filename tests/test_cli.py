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
