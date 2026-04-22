"""target-cli: command-line interface for Target search system."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from target_search.db import open_db
from target_search.ingest import index
from target_search.lex import search_lex

DEFAULT_DB = "target.db"


@click.group()
@click.option("--db", default=DEFAULT_DB, envvar="TARGET_DB", help="Database file path.")
@click.pass_context
def main(ctx: click.Context, db: str) -> None:
    """Target — general-purpose document search and ranking."""
    ctx.ensure_object(dict)
    ctx.obj["db_path"] = db


@main.command("index")
@click.argument("doc_key")
@click.argument("file", type=click.Path(exists=True))
@click.option("--source-type", default=None, help="Override source type.")
@click.option("--trust-level", type=float, default=None, help="Override trust level (0.0-1.0).")
@click.option("--max-chunk-tokens", type=int, default=256, help="Max tokens per chunk.")
@click.pass_context
def index_cmd(
    ctx: click.Context,
    doc_key: str,
    file: str,
    source_type: str | None,
    trust_level: float | None,
    max_chunk_tokens: int,
) -> None:
    """Index a document from a file."""
    conn = open_db(ctx.obj["db_path"])
    content = Path(file).read_text(encoding="utf-8")

    metadata = {}
    if source_type:
        metadata["source_type"] = source_type
    if trust_level is not None:
        metadata["trust_level"] = trust_level

    result = index(conn, doc_key, content, metadata or None, max_chunk_tokens=max_chunk_tokens)
    conn.close()

    action = "replaced" if result.replaced else "indexed"
    click.echo(f"{action} {result.doc_key}: {result.chunks} chunks (record_id={result.record_id})")


@main.command("index-stdin")
@click.argument("doc_key")
@click.option("--source-type", default=None)
@click.option("--trust-level", type=float, default=None)
@click.option("--max-chunk-tokens", type=int, default=256)
@click.pass_context
def index_stdin_cmd(
    ctx: click.Context,
    doc_key: str,
    source_type: str | None,
    trust_level: float | None,
    max_chunk_tokens: int,
) -> None:
    """Index a document from stdin."""
    conn = open_db(ctx.obj["db_path"])
    content = sys.stdin.read()

    metadata = {}
    if source_type:
        metadata["source_type"] = source_type
    if trust_level is not None:
        metadata["trust_level"] = trust_level

    result = index(conn, doc_key, content, metadata or None, max_chunk_tokens=max_chunk_tokens)
    conn.close()

    action = "replaced" if result.replaced else "indexed"
    click.echo(f"{action} {result.doc_key}: {result.chunks} chunks (record_id={result.record_id})")


@main.command("query")
@click.argument("text")
@click.option("--top-n", type=int, default=10, help="Number of results.")
@click.option("--json-output", "json_out", is_flag=True, help="Output as JSON.")
@click.pass_context
def query_cmd(
    ctx: click.Context,
    text: str,
    top_n: int,
    json_out: bool,
) -> None:
    """Query indexed documents (BM25 lexical search)."""
    conn = open_db(ctx.obj["db_path"])
    results = search_lex(conn, text, top_n)
    conn.close()

    if json_out:
        output = [
            {
                "chunk_id": r.chunk_id,
                "doc_key": r.doc_key,
                "chunk_index": r.chunk_index,
                "bm25_score": r.bm25_score,
                "source_type": r.source_type,
                "trust_level": r.trust_level,
                "text": r.chunk_text,
            }
            for r in results
        ]
        click.echo(json.dumps(output, indent=2))
    else:
        if not results:
            click.echo("No results found.")
            return
        for i, r in enumerate(results, 1):
            click.echo(f"\n--- Result {i} (score: {r.bm25_score:.4f}) ---")
            click.echo(f"Key: {r.doc_key} | Chunk: {r.chunk_index}")
            click.echo(r.chunk_text[:200] + ("..." if len(r.chunk_text) > 200 else ""))


@main.command("stats")
@click.pass_context
def stats_cmd(ctx: click.Context) -> None:
    """Show database statistics."""
    conn = open_db(ctx.obj["db_path"])
    records = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    chunks = conn.execute("SELECT COUNT(*) FROM record_chunks").fetchone()[0]
    conn.close()
    click.echo(f"Records: {records}, Chunks: {chunks}")


if __name__ == "__main__":
    main()
