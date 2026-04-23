---
domain: Workflows
status: Active
entry_points: []
dependencies:
  - .aidoc/architecture/system-overview.md
  - .aidoc/conventions/testing-strategy.md
---

# Development Plan

Target is built in five phases, each delivering a usable increment. Estimated timeline:
weeks 1–2 for a working retriever, week 3 for correction logic, week 4+ for evaluation and tuning.

## Related Docs

| Document | Relationship |
|----------|-------------|
| [System Overview](../architecture/system-overview.md) | Modules built in each phase |
| [Testing Strategy](../conventions/testing-strategy.md) | Test suites built alongside each phase |

## Phase 1: Foundation

- Project scaffold: package structure, pyproject.toml, CI
- target-ingest: chunking and storage
- target-lex: FTS5 indexing and BM25 queries
- Unit tests for ingest + lex
- CLI: basic `index` and `query` commands

## Phase 2: Semantic Search

- target-sem: embedding generation and sqlite-vec storage
- target-rank: weighted merge of lex + sem scores
- Unit tests for sem + rank
- CLI: query returns hybrid-ranked results

## Phase 3: Corrections

- target-correct: correction graph and score modifiers
- Integration with target-rank
- Correction propagation tests
- CLI: `target correct`, `target uncorrect`, `target corrections`, `--audit` flag

## Phase 4: Explainability

- target-explain: citation and evidence generation
- CLI: `explain` command
- Integration tests with known-answer corpus

## Phase 5: Evaluation and Tuning

- Regression harness (snapshot-based)
- Weight tuning experiments
- Performance benchmarks

## Current Status

Phase 1 is **complete** (PR #2, merged 2026-04-22). Delivered: project scaffold (`pyproject.toml`,
package structure, GitHub Actions CI for Python 3.10/3.11/3.12), `target-ingest` (paragraph-aware
chunking, metadata inference, idempotent upserts), `target-lex` (FTS5/BM25 search), CLI (`target
index`, `target index-stdin`, `target query`, `target stats`), and 36 tests across 4 test modules.

Phase 2 is **complete** (PR #4). Delivered: `target-sem` (all-MiniLM-L6-v2 embeddings via
sentence-transformers, sqlite-vec cosine search, incremental embedding), `target-rank` (weighted
merge with recency decay, trust scoring, correction stub), CLI updates (`target query --mode
hybrid|lex|sem`, `target embed`, `target index --embed`, `--json-output` with feature breakdown
and reason codes), graceful fallback to lex-only when semantic extras or embeddings are absent,
and 74 tests total (38 new). All tests pass on Python 3.10–3.12.

Phase 3 is **complete** (PR #5). Delivered: `target-correct` (directed correction graph with
cycle detection, self-correction prevention, transitive propagation, confidence-weighted scoring),
integration with `target-rank` (correction scores as ranking feature, C normalized from [-1,1]
to [0,1]), CLI commands (`target correct`, `target uncorrect`, `target corrections [--doc-key]`,
`target query --audit`), schema migration (v1→v2 with correction_edges table), doc audit, and
102 tests total (28 new). All tests pass on Python 3.10–3.12.

Phase 4 (explainability) is next.
