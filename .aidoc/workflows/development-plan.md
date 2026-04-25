---
domain: Workflows
status: Active
entry_points: []
dependencies:
  - .aidoc/architecture/system-overview.md
  - .aidoc/conventions/testing-strategy.md
---

# Development Plan

Target is built in six phases, each delivering a usable increment.

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

## Phase 5: End-to-End Tests

- Sci-fi themed fixture corpus (15–20 documents across 4 topic clusters)
- Full pipeline tests: ingest → query → assert in lex, sem, hybrid modes
- Correction regression tests (corrector always outranks corrected)
- Trust, recency, and explain output validation
- Edge cases: empty corpus, CJK content, re-index idempotency
- Known-answer pairs with must-outrank assertions

## Phase 6: Evaluation and Tuning

- Regression harness: snapshot-based golden-answer testing (`target eval snapshot/diff`)
- Quality metrics: precision@k, correction recall, noise rate (`target eval report`)
- Weight tuning: grid search over ranking formula weights (`target eval tune`)
- Performance benchmarks: query latency, index throughput, memory usage
- Design doc: `.aidoc/designs/evaluation-tuning.md`

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

Phase 4 (explainability) is **complete** (PR #6). Delivered: `target-explain` module (citation
generation, evidence pointers, dominant factor analysis, correction chain evidence, human-readable
formatting with verbose mode), CLI `target explain` command with `--json-output` and `--verbose`
flags, and 126 tests total (24 new in test_explain.py including integration tests with
known-answer corpus). All tests pass on Python 3.10–3.12.

Phase 5 (E2E tests) is **complete** (PR #7). Delivered: sci-fi fixture corpus
(`tests/fixtures/e2e/`, 17 documents + manifest), full pipeline E2E suite
(`tests/test_e2e.py`) covering topical retrieval, correction outrank assertions, trust/recency
weighting, explain output validation, edge cases (empty/single-doc/re-index/CJK), and semantic+
hybrid smoke coverage under `@pytest.mark.slow`.

Total test suite is now 140 passing tests. Phase 6 (evaluation and tuning) is next.
