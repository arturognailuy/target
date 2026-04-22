---
domain: Designs
status: Draft
entry_points: []
dependencies:
  - .aidoc/architecture/system-overview.md
---

# Performance Improvement Plan

Model loading dominates CLI latency for semantic queries. This document outlines options to
reduce cold-start time and improve the interactive experience.

## Related Docs

| Document | Relationship |
|----------|-------------|
| [System Overview](../architecture/system-overview.md) | Module where model loading occurs (target-sem) |
| [Interface Contract](interface-contract.md) | Query modes that avoid model loading (--mode lex) |

## Problem

Each `target query` invocation (in hybrid or sem mode) loads the embedding model from disk into
memory. For all-MiniLM-L6-v2 via sentence-transformers, this takes ~2–4 seconds on typical
hardware. The model is cached on disk (in `~/.cache/huggingface/`), so there is no network
download after first use — the delay is purely from loading weights into memory.

Lexical-only queries (`--mode lex`) avoid this entirely and return results instantly.

## Options

### Option 1: ONNX Runtime (recommended first step)

Replace the PyTorch sentence-transformers backend with ONNX Runtime for inference. Benefits:
- **Faster loading:** ONNX models load significantly faster than PyTorch checkpoints (often 2–5x).
- **Smaller footprint:** no PyTorch dependency needed for inference (reduces install size).
- **Same model quality:** ONNX export of all-MiniLM-L6-v2 produces identical embeddings.
- **Easy migration:** sentence-transformers supports ONNX export; alternatively, use
  `optimum` or export manually.

Implementation path:
1. Export all-MiniLM-L6-v2 to ONNX format.
2. Add `onnxruntime` as an optional dependency (`pip install target-search[semantic-onnx]`).
3. Update `target-sem` to detect and prefer the ONNX backend when available.
4. Keep the sentence-transformers backend as a fallback.

### Option 2: Model Preloading / Daemon Mode

Keep the model loaded in a long-running process that serves embedding requests.
- **Eliminates cold start entirely** for repeated queries.
- **Higher complexity:** requires a background process, IPC, and lifecycle management.
- **Best for:** batch workflows or interactive sessions with many queries.

Not recommended as a first step due to added complexity. Consider if ONNX improvements are
insufficient.

### Option 3: Lazy Model Loading with Caching Hints

Use OS-level page cache hints (e.g., `mmap` with `MAP_POPULATE`) to keep model weights warm
in the filesystem cache between CLI invocations. Effectiveness depends on available RAM and
system memory pressure. Low effort but unreliable.

### Option 4: Smaller / Distilled Models

Switch to a smaller embedding model for faster loading at the cost of some retrieval quality.
Candidates: all-MiniLM-L4-v2, gte-small, e5-small-v2. Useful as a "fast mode" option alongside
the default model.

## Recommendation

Start with **Option 1 (ONNX Runtime)** as a future improvement. It provides the best
effort-to-impact ratio without architectural changes. Options 2 and 4 can be evaluated later
if needed.

For immediate use, **`--mode lex`** avoids model loading entirely and is the right default for
quick keyword queries.
