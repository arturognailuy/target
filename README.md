# Target

A general-purpose document search and ranking system. Given a collection of documents identified by stable keys, Target indexes them using both full-text search (BM25) and semantic embeddings, then returns ranked results for natural-language queries with explainable citations.

## Features

- **Hybrid retrieval:** combines BM25 (lexical) and vector similarity (semantic) for high-quality results
- **Correction awareness:** when a newer document supersedes an older one, rankings reflect the correction
- **Explainable results:** every ranked result includes traceable evidence pointers
- **Simple interface:** the only concepts a consumer needs are *doc key* and *doc content*
- **General purpose:** any system that produces `(key, text)` pairs can use Target

## Quick Start

```bash
pip install -e ".[dev]"

# Index a document
target index "doc:readme" README.md

# Query
target query "search ranking"

# Run tests
pytest -v
```

## Status

Phase 1: Foundation (ingest + lexical search + CLI). See [.aidoc/INDEX.md](.aidoc/INDEX.md) for full documentation.

## License

MIT
