# Target — Design Document

## 1. Problem

AI agents and knowledge systems need to retrieve the most relevant context from a growing corpus of documents. Simple keyword search misses semantic relationships; pure embedding search misses exact matches. Neither handles the case where a newer document *corrects* an older one.

Target solves this by combining multiple retrieval strategies with a correction-aware ranking layer, behind a minimal interface.

## 2. Interface

From the outside, Target exposes two operations:

```python
index(doc_key: str, doc_content: str, metadata: dict | None = None) -> None
query(text: str, top_n: int = 10) -> list[RankedResult]
```

Where:
- **`doc_key`** is a stable, unique identifier (e.g., `memory:2026-04-18`, `email:thread:dream-system`)
- **`doc_content`** is the raw text of the document
- **`metadata`** is optional hints (source type, date, trust level) — these can also be inferred from `doc_key` conventions

Everything else — chunking, embedding, FTS indexing, correction detection, ranking — is internal. The consumer never sees modules; just "give me relevant context for this query."

## 3. Architecture

Target is composed of six internal modules and a CLI wrapper:

```
                    ┌──────────────┐
                    │  target-cli  │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │ target-rank  │  ← weighted merge + final ranking
                    └──┬───┬───┬───┘
                       │   │   │
          ┌────────────┘   │   └────────────┐
          │                │                │
   ┌──────▼──────┐  ┌─────▼──────┐  ┌──────▼───────┐
   │ target-lex  │  │ target-sem │  │target-correct│
   │  (FTS5/BM25)│  │(sqlite-vec)│  │(correction   │
   │             │  │            │  │ graph)        │
   └──────┬──────┘  └─────┬──────┘  └──────┬───────┘
          │                │                │
          └────────────────┼────────────────┘
                           │
                    ┌──────▼───────┐
                    │target-ingest │  ← chunking, normalization
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │target-explain│  ← citation & evidence
                    └──────────────┘
```

### 3.1 Module Descriptions

#### target-ingest
Accepts `(doc_key, doc_content, metadata)` and produces normalized chunks suitable for indexing. Responsibilities:
- Split documents into chunks (respecting paragraph/section boundaries)
- Attach metadata (source type, date, trust level — inferred from doc_key if not provided)
- Upsert into storage (idempotent — re-ingesting the same doc_key replaces previous chunks)

#### target-lex (FTS5 / BM25)
Full-text search using SQLite FTS5 with BM25 scoring. Responsibilities:
- Maintain an FTS5 index over ingested chunks
- Accept a query string, return chunks ranked by BM25 score
- Handle tokenization, including CJK text and code blocks

#### target-sem (sqlite-vec)
Semantic similarity search using vector embeddings stored via `sqlite-vec`. Responsibilities:
- Generate embeddings for ingested chunks (using a configurable embedding model)
- Store embeddings in sqlite-vec
- Accept a query, embed it, return chunks ranked by cosine similarity

#### target-correct
Correction-aware scoring. When a newer document supersedes or contradicts an older one, this module adjusts rankings. Responsibilities:
- Maintain a correction graph (directed edges: "doc A corrects doc B")
- Detect corrections via metadata, doc_key conventions, or explicit API calls
- Provide a correction score modifier for ranked results (boost correctors, demote corrected)
- Propagate correction chains (A corrects B, B corrects C → A dominates C)

#### target-rank
The weighted merge layer. Combines scores from lex, sem, and correct into a final ranked list. Responsibilities:
- Accept scored results from each provider
- Apply configurable weights to each score component
- Produce a unified ranked result list with combined scores
- Support weight tuning (zero out individual weights to disable a provider)

#### target-explain
Citation and evidence generation. Given a ranked result, produce traceable evidence pointers. Responsibilities:
- For each result, identify which chunks contributed and why
- Assign reason codes (e.g., "lexical match", "semantic similarity", "correction of X")
- Generate human-readable citation strings

#### target-cli
Thin CLI wrapper (argparse or click). Responsibilities:
- `target index <file_or_dir>` — ingest documents
- `target query <text> [--top-n N]` — run a query and print ranked results
- `target explain <doc_key>` — show correction graph and indexing status
- Output in JSON (machine) or formatted text (human)

## 4. Technology Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Language | Python | Ecosystem fit (embedding models, sqlite-vec, numpy), existing scripts are Python |
| Database | SQLite | Single-file, zero-config, excellent for embedded use |
| FTS | FTS5 (built into SQLite) | Mature, fast, supports BM25 out of the box |
| Vector search | sqlite-vec | First-class Python bindings, same SQLite file |
| Embeddings | Configurable; default: all-MiniLM-L6-v2 via sentence-transformers | Small, fast, good quality for general text |
| Testing | pytest | Standard Python testing; fixtures for known-answer pairs |
| CLI | argparse or click | Thin wrapper, not the focus |

## 5. Testing Strategy

### 5.1 Unit Tests (per module)

Each module gets its own pytest test suite:

- **target-ingest:** chunk extraction from different source types (markdown, email, plain text). Assert correct metadata tagging. Test idempotent upserts.
- **target-lex:** tokenization, query parsing, BM25 ranking against known fixtures. Edge cases: CJK text, code blocks, empty queries, stop words.
- **target-sem:** embedding storage and cosine similarity retrieval. Use mock embeddings (deterministic hash → vector) for unit tests.
- **target-correct:** correction graph construction and chain propagation.
- **target-rank:** weighted merge formula with controlled inputs. Test weight sensitivity.
- **target-explain:** citation generation and reason code assignment.

### 5.2 Integration Tests

End-to-end: ingest fixtures → query → verify ranked results.

- **Pipeline test:** `ingest(fixtures) → query "topic" → assert top results match expectations`
- **Correction test:** ingest a file, then ingest a correction. Query should rank the correction higher.
- **Regression harness:** save query→result snapshots. On code changes, re-run and diff.

### 5.3 Test Infrastructure

- Fixture corpus: `tests/fixtures/` with 20–30 curated documents with known relationships, corrections, and varying trust levels.
- Known-answer pairs: "for query X, the correct top-3 results are Y, Z, W."
- Mock embeddings for unit tests; small local model (all-MiniLM-L6-v2) for integration tests.
- All tests runnable via `pytest` (or `make test`).
- CI runs unit + module tests on every push.
- Integration tests run on schedule or before releases.

## 6. Development Plan

### Phase 1: Foundation
- [ ] Project scaffold (package structure, pyproject.toml, CI)
- [ ] target-ingest: chunking and storage
- [ ] target-lex: FTS5 indexing and BM25 queries
- [ ] Unit tests for ingest + lex
- [ ] CLI: basic `index` and `query` commands

### Phase 2: Semantic Search
- [ ] target-sem: embedding generation and sqlite-vec storage
- [ ] target-rank: weighted merge of lex + sem scores
- [ ] Unit tests for sem + rank
- [ ] CLI: query returns hybrid-ranked results

### Phase 3: Corrections
- [ ] target-correct: correction graph and score modifiers
- [ ] Integration with target-rank
- [ ] Correction propagation tests

### Phase 4: Explainability
- [ ] target-explain: citation and evidence generation
- [ ] CLI: `explain` command
- [ ] Integration tests with known-answer corpus

### Phase 5: Evaluation & Tuning
- [ ] Regression harness (snapshot-based)
- [ ] Weight tuning experiments
- [ ] Performance benchmarks

## 7. Design Principles

1. **Minimal interface.** Consumers see only `index()` and `query()`. Internal complexity is hidden.
2. **General purpose.** Any `(key, text)` pair source can feed into Target. The first consumer is a memory/dream system, but it's not the only one.
3. **Correctness over speed.** Deterministic ranking for the same corpus and query. Reproducible results.
4. **No private information.** This is an open-source project. Design docs, tests, and code must not contain private data.
