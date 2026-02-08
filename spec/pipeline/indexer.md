# Indexer

Container: [Pipeline](../pipeline.md)

# Purpose

Define corpus scanning, metadata cataloging, and thumbnail generation. The indexer is the first pipeline step: it takes a directory of images and produces a SQLite catalog plus thumbnails at four standard sizes.

# Boundary observables

**CLI.** `sigiltree index <corpus_path> <artifact_dir>` scans the corpus and writes artifacts.

**Catalog.** A SQLite database (catalog.db) with one row per image: image_id, path, filename, width, height, checksum, file_size, exif_time (where available).

**Thumbnails.** JPEG thumbnails generated at four fixed sizes: 64, 128, 256, 512 pixels on the long edge. Stored under artifact_dir/thumbnails/{size}/{image_id}.jpg.

**Idempotency.** Running index twice without changes performs no recomputation. Thumbnail file timestamps do not change on second run. Checksums are used to detect changes.

**Incremental updates.** Adding new images and re-running computes only the new entries and thumbnails. Deleting images and re-running updates only the deltas. No full reindex.

**Graceful handling.** Corrupt images are logged and skipped without crashing.

# Invariants and non-goals

**Invariants.**
- Every indexed image has a unique image_id derived from its filename.
- Every indexed image has a checksum for change detection.
- Every indexed image has thumbnails at all four sizes.
- No recomputation on unchanged images.

**Non-goals.** This page does not define embedding computation (see [Embeddings](embeddings.md)) or contrast discovery (see [Contrast Discovery](contrast-discovery.md)).

# Canonical examples (golden fixtures)

Checksum-based skip (from test_indexer.py): index a corpus, index again → no recomputation. Add new images → only new thumbnails generated.

Thumbnail generation: each image produces 4 JPEG files (64, 128, 256, 512).

# Contained sigils

None. This is a leaf sigil.

# Supersession notes

Agents.md §Phase 1 acceptance criteria: "Running index twice without changes performs no recomputation. Logs must show reuse; thumbnail file timestamps must not change on second run." This remains the authoritative specification.
