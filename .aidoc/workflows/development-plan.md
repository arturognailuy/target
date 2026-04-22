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

## Phase 4: Explainability

- target-explain: citation and evidence generation
- CLI: `explain` command
- Integration tests with known-answer corpus

## Phase 5: Evaluation and Tuning

- Regression harness (snapshot-based)
- Weight tuning experiments
- Performance benchmarks

## Current Status

Phase 1 is in progress (PR #2). Includes project scaffold, target-ingest, target-lex, CLI, CI, and tests.
