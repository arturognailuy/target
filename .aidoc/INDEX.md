---
domain: Conventions
status: Active
entry_points: []
dependencies: []
---

# Target — Documentation Index

Target is a general-purpose document search and ranking system that combines BM25 lexical search
with semantic vector similarity, plus correction-aware ranking and explainable results, behind a minimal `index()`/`query()` interface.

## Document Inventory

| Document | Domain | Status | Summary |
|----------|--------|--------|---------|
| [System Overview](architecture/system-overview.md) | Architecture | Active | Six-module pipeline, data flow, technology stack |
| [Interface Contract](designs/interface-contract.md) | Designs | Active | Public API surface, query modes, design principles, invariants |
| [Correction Graph](designs/correction-graph.md) | Designs | Active | Graph model, scoring formula, cycle detection, edge cases |
| [Performance Plan](designs/performance-plan.md) | Designs | Draft | Model loading optimization options (ONNX, daemon, smaller models) |
| [Evaluation and Tuning](designs/evaluation-tuning.md) | Designs | Active | Regression harness, quality metrics, weight tuning, baseline results |
| [Testing Strategy](conventions/testing-strategy.md) | Conventions | Active | Unit, integration, and evaluation testing approach |
| [E2E Testing](conventions/e2e-testing.md) | Conventions | Active | End-to-end testing strategy: fixture corpus, pipeline regression, correction validation |
| [Development Plan](workflows/development-plan.md) | Workflows | Active | Six-phase build plan with deliverables |
| [Setup Guide](workflows/setup-guide.md) | Workflows | Active | Environment setup, running tests, quick start |

## Reading Chains

**New contributor:** Interface Contract → System Overview → Testing Strategy → Development Plan

**Architecture deep-dive:** System Overview → Interface Contract → Correction Graph → Evaluation and Tuning

**Starting development:** Setup Guide → Development Plan → Testing Strategy → E2E Test Plan → System Overview
