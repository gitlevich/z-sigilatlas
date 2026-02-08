# Pipeline

Container: [INDEX](INDEX.md)

# Purpose

Define how raw images become the artifacts that Atlas, Calibration, and Rendering consume. The pipeline is a sequence of offline CLI commands that produce versioned, incremental artifacts: a metadata catalog, thumbnails, embeddings across three families, a contrast library with per-image coordinates, and precomputed statistics. All artifacts are local files. No cloud dependencies. No telemetry.

# Boundary observables

**CLI commands.** The pipeline exposes these commands, each operating on an artifact directory:
- `index <corpus_path> <artifact_dir>` — catalog images, generate thumbnails
- `embed <artifact_dir>` — compute embedding families
- `contrasts <artifact_dir>` — discover and select contrasts
- `atlas <artifact_dir> --levels N --seed S` — build multi-level treemap
- `ride-stats <artifact_dir>` — precompute z-summaries and correlations
- `serve <artifact_dir> --port P` — start the web server

**Incrementality.** Every step is incremental. Running index twice without changes performs no recomputation. Adding images and re-running updates only the deltas. Re-running embed after adding new images computes only new embeddings. Rebuilding contrasts with unchanged embeddings is incremental.

**Artifact directory structure.** All artifacts live under a single directory. Required artifacts: SQLite metadata database (catalog.db), thumbnails at sizes 64/128/256/512, embedding shards per family (memory-mappable), contrast library (versioned JSON), per-image contrast coordinates (JSON), atlas pyramid (levels, nodes, rectangles, tiles), user sigils, session state.

**Serving dependencies.** The serve command requires only pillow, aiohttp, numpy. Embedding computation requires PyTorch and transformers. These are separate dependency tiers.

# Invariants and non-goals

**Invariants.**
- Artifacts are versioned and incremental. No "start over" events for normal operations.
- Corrupt images, missing files, and partial embeddings are handled without crashing.
- All pipeline steps can be run independently after their prerequisites exist.

**Non-goals.** This sigil does not define atlas topology or navigation (see [Atlas](atlas.md)), calibration mechanics (see [Calibration](calibration.md)), or rendering (see [Rendering](rendering.md)). It defines only the offline artifact production that those systems consume.

# Canonical examples (golden fixtures)

Index idempotency (from agents.md §Phase 1 acceptance): running index twice without changes performs no recomputation. Thumbnail file timestamps do not change on second run.

Embedding coverage (from agents.md §Phase 2 acceptance): all indexed images have embeddings for each family. NN queries return within 250ms for k=20 after warm cache.

Contrast library bounds (from agents.md §Phase 3 acceptance): library size is 20–60 contrasts. Stability check passes for all kept contrasts (subsample correlation > 0.9). Top 10 contrasts by mass have obviously distinct low-vs-high exemplar mosaics.

Embedding store roundtrip (from test_embeddings.py): save embeddings for a set of image_ids, reload via memory-map, retrieve vectors for specific IDs. Incremental adds extend the store without rewriting existing data.

Indexer checksums (from test_indexer.py): each image gets a checksum; re-indexing unchanged images skips recomputation.

# Contained sigils

[Indexer](pipeline/indexer.md) — Corpus scanning, metadata catalog, thumbnail generation.

[Embeddings](pipeline/embeddings.md) — CLIP, DINOv2, and texture embedding families; memory-mappable store.

[Contrast Discovery](pipeline/contrast-discovery.md) — Mass scoring, stability checking, exemplar selection, coordinate computation.

# Supersession notes

The original spec (agents.md §3) listed required artifact types generically. The implementation materialized specific formats: SQLite for catalog, numpy memory-mapped arrays for embeddings, JSON for contrast library and coordinates, JPEG for tiles and thumbnails. These concrete formats are the current authority.
