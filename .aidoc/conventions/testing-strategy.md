---
domain: Conventions
status: Active
entry_points: []
dependencies:
  - .aidoc/architecture/system-overview.md
---

# Testing Strategy

Target uses pytest at three levels: unit tests per module, module-level isolation tests against a
shared fixture database, and end-to-end integration tests. All tests run via `pytest` (or `make test`).

## Related Docs

| Document | Relationship |
|----------|-------------|
| [System Overview](../architecture/system-overview.md) | Modules being tested |
| [Development Plan](../workflows/development-plan.md) | When each test suite is built |

## Why This Approach

Each module has different testing characteristics. Ingest needs idempotency checks; lex needs
BM25 determinism across edge cases; sem needs embedding consistency; correct needs graph
propagation; rank needs weight sensitivity. A shared fixture corpus with known-answer pairs
lets us measure retrieval quality, not just absence of errors.

## Unit Tests (Per Module)

- **target-ingest:** chunk extraction from markdown, email, plain text. Metadata tagging. Idempotent upserts.
- **target-lex:** tokenization, query parsing, BM25 ranking. Edge cases: CJK text, code blocks, empty queries, stop words. BM25 scores must be deterministic for a fixed corpus.
- **target-sem:** embedding storage and cosine similarity retrieval. Uses mock embeddings (deterministic hash → vector) to avoid model dependency.
- **target-correct:** correction graph construction. Chain propagation (A→B→C). Edge type handling.
- **target-rank:** weighted merge formula with controlled inputs. Weight sensitivity (zero out individual weights and verify behavior).
- **target-explain:** citation generation and reason code assignment from ranked results.

## Module-Level Isolation

Each module test suite creates its own SQLite database from the shared fixture corpus, runs
operations, and asserts results independently.

**Fixture corpus:** `tests/fixtures/` contains 20–30 curated markdown files with known
relationships, corrections, and varying trust levels.

**Known-answer pairs:** "For query X, the correct top-3 results are Y, Z, W." This enables
measuring retrieval quality rather than just testing for crashes.

**Embedding strategy:** mock embeddings (deterministic hash → vector) for unit tests; small local
model (all-MiniLM-L6-v2) for integration tests.

## Integration Tests

- **Pipeline test:** `ingest(fixtures) → query "topic" → assert top results match expectations`
- **Correction test:** ingest a document, then ingest a correction. Query must rank the correction higher and the original lower.
- **Regression harness:** save query→result snapshots. On code changes, re-run and diff. Flag ranking changes for review.

## CI

- GitHub Actions runs on every push and PR against `main`.
- Matrix: Python 3.10, 3.11, 3.12.
- Steps: lint (ruff) → test (pytest).
- Integration tests (with embedding model) will run on schedule or before releases once Phase 2 is implemented.

## Current State

Phase 1 delivered 36 tests across 4 modules: `test_db.py` (database layer), `test_ingest.py`
(chunking, metadata, upserts), `test_lex.py` (FTS5/BM25 search, ranking), `test_cli.py`
(CLI commands and output). Phase 2 added 38 tests across 4 new modules: `test_sem.py` (embedding
storage, cosine retrieval, mock embeddings), `test_rank.py` (weighted merge, weight sensitivity,
recency decay, determinism), `test_query_modes.py` (hybrid/lex/sem mode switching, fallback
behavior), `test_integration.py` (end-to-end index → embed → query pipeline). Total: 74 tests,
all passing on Python 3.10–3.12.
