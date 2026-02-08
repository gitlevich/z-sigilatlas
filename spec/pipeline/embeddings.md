# Embeddings

Container: [Pipeline](../pipeline.md)

# Purpose

Define the computation and storage of embedding families. Three complementary families capture different aspects of visual similarity: semantic (CLIP), structural (DINOv2), and textural (wavelet/multiscale descriptor). Embeddings are stored in a memory-mappable format keyed by (image_id, family_id).

# Boundary observables

**CLI.** `sigiltree embed <artifact_dir>` computes all families incrementally.

**Three families.**
- Semantic (CLIP, 512D): captures what things mean — a bridge, a face, a forest.
- Structural (DINO, 384D): captures how things are composed — symmetry, depth, negative space.
- Textural (97D): captures what surfaces feel like — grain, sharpness, color temperature.

**Storage.** Embeddings are stored as memory-mappable numpy arrays per family, allowing querying without loading everything into memory.

**Nearest-neighbor queries.** Given a family, an image_id, and k, return k nearest neighbors sorted by similarity descending. Query image not in its own neighbor list. Similarity values in [0, 1]. Latency: under 250ms for k=20 after warm cache.

**Incrementality.** Re-running embed after adding new images computes only the new embeddings. Existing embeddings are not recomputed.

**All images covered.** All indexed images have embeddings for each family.

# Invariants and non-goals

**Invariants.**
- Every indexed image has an embedding vector in every family.
- Embedding vectors are L2-normalized.
- The store supports incremental adds without rewriting existing data.
- NN queries are deterministic for the same inputs.

**Non-goals.** This page does not define how embeddings are fused into a neighbor graph (see [Atlas](../atlas.md)) or how contrasts are discovered from them (see [Contrast Discovery](contrast-discovery.md)).

# Canonical examples (golden fixtures)

Store roundtrip (from test_embeddings.py): save embeddings for a set of image_ids, reload, retrieve vectors. Incremental add extends the store.

NN endpoint (from UI_TEST_PLAN.md §7.2): GET /api/nn?family=clip&image_id=X&k=20 → neighbors sorted by similarity descending, query image absent from results, similarities in [0, 1], works for all three families.

Family-specific behavior (from agents.md §Phase 2): semantic neighbors share content, structural neighbors share composition/shape, texture neighbors share grain/scale.

# Contained sigils

None. This is a leaf sigil.

# Supersession notes

Agents.md §Phase 2 specified "semantic (CLIP-like), structural (DINO-like), texture/scale (wavelet or multiscale descriptor)." The implementation uses CLIP (512D), DINOv2 (384D), and a custom texture descriptor (97D). These are the authoritative families.
