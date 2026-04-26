---
domain: Designs
status: Active
entry_points: []
dependencies:
  - .aidoc/architecture/system-overview.md
  - .aidoc/conventions/e2e-testing.md
  - .aidoc/conventions/testing-strategy.md
---

# Evaluation and Tuning

A regression harness, quality metrics, weight tuning, and performance benchmarks
to answer: "Does the system return the right results in the right order, and how do we improve it?"

## Related Docs

| Document | Relationship |
|----------|-------------|
| [System Overview](../architecture/system-overview.md) | Modules being evaluated |
| [E2E Testing](../conventions/e2e-testing.md) | Fixture corpus reused as eval foundation |
| [Testing Strategy](../conventions/testing-strategy.md) | Where eval fits in the test hierarchy |
| [Interface Contract](interface-contract.md) | Query modes and ranking formula under tuning |

## Why

The retrieval pipeline is built and tested. But passing tests only proves the system
doesn't crash — it doesn't prove it returns *good* results. Evaluation closes this gap by
measuring ranking quality with concrete metrics, detecting regressions when code or weights
change, and systematically finding better weight configurations.

## Three Components

### 1. Regression Harness (Snapshot-Based)

A "golden answer" system for ranking quality. The workflow:

1. Define an eval query set (20–30 queries with known relevant documents and expected rankings).
2. `target eval snapshot` — run all eval queries and save ranked results as JSON snapshots.
3. After code or weight changes, `target eval diff` — compare current results against snapshots.
4. Review diffs: accept improvements (update snapshot) or fix regressions.

Snapshots live in the repo (`tests/eval/`) for git-tracked quality history. This is the ranking
equivalent of snapshot testing — instead of "did it crash?", it asks "did answers get worse?"

### 2. Quality Metrics

Three metrics measure retrieval quality:

- **Precision@k**: Of the top-k results for a query, how many are actually relevant? Measures
  whether the system surfaces the right documents. Computed per query, averaged across the eval set.
- **Correction recall**: When a correction relationship exists, does the corrector consistently
  rank above the corrected document? Measures whether correction edges actually work. Binary
  pass/fail per correction pair.
- **Noise rate**: How often do irrelevant results appear in the top-k? The complement of
  precision — measures how much junk leaks through.

`target eval report` computes and displays all three metrics for the current state.

### 3. Weight Tuning

The ranking formula `score = w_s·S + w_l·L + w_r·R + w_c·C + w_t·T` has five tunable weights.
Current values are hand-picked defaults (0.35, 0.25, 0.15, 0.10, 0.15).

Tuning approach:
1. Use the eval query set with known-good answers as the objective function.
2. Run a grid search over weight combinations (5 variables, discrete steps).
3. Score each combination by precision@k and correction recall.
4. Select the combination that maximizes the combined metric.
5. Save winning weights as the new defaults with justification.

This is parameter sweep, not machine learning — we have 5 knobs and a small eval set.
Like tuning an equalizer: try combinations, measure, pick the best.

### 4. Performance Benchmarks

Establish baselines to detect future performance regressions:

- **Query latency**: time from query input to ranked results (lex, sem, hybrid modes).
- **Index throughput**: documents per second during ingestion.
- **Memory usage**: peak memory during embedding generation.

Benchmarks run separately from the test suite (they're slow and environment-dependent).
Results are saved as reference baselines, not hard pass/fail thresholds.

## CLI Commands

- `target eval snapshot` — run eval queries, save results as golden snapshots
- `target eval diff` — compare current results against saved snapshots
- `target eval report` — compute and display quality metrics
- `target eval tune` — run weight grid search and report optimal weights

## Eval Query Set

Built on the existing sci-fi E2E fixture corpus. Each eval query specifies:
- Query text
- Relevant doc_keys (the "right answers")
- Must-outrank pairs (ordering constraints)
- Expected top-k (optional strict ordering)

The eval set extends E2E fixtures with explicit relevance judgments — the same documents,
but with richer annotations about what counts as a correct result and why.

## Implementation Plan

**Single PR delivering:**
- `target eval` CLI subcommands (snapshot, diff, report, tune)
- Eval query set with relevance judgments (extending E2E fixtures)
- Metrics computation (precision@k, correction recall, noise rate)
- Weight grid search with best-weights selection
- Performance benchmark scripts (latency, throughput, memory)
- Documentation updates
