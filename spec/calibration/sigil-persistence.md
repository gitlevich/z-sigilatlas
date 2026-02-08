# Sigil Persistence

Container: [Calibration](../calibration.md)

# Purpose

Define how sigils, category preferences, walk progress, and taste axis data are stored, loaded, versioned, and reset. All preference data lives in the sigils/ subdirectory of the artifact directory as JSON files keyed by user_id.

# Boundary observables

**Sigil storage.** Sigils are saved as sigil_{user_id}.json. Each contains: entries (dict of collapsed contrasts), collapsed_count, total_choices, contrast_library_version, user_id, created_at timestamp.

**Category preference storage.** Category weights are saved as categories_{user_id}.json. Each contains: user_id, weights (dict of contrast_id → float), version, created_at timestamp.

**Walk progress storage.** In-progress walk state is saved as walk_progress_{user_id}.json after every interaction. Contains: library_version, choices (serialized list of direction, strength, contrast_id per choice), step_index. Deleted on walk completion or reset.

**Taste axis storage.** The materialized emergent taste axis is stored alongside other artifacts. Per-image coordinates, z-summaries, exemplars, and quantiles are persisted.

**Version binding.** Walk progress is bound to a library version string. If the library changes between sessions, saved progress is rejected (restore returns false) and the walk starts fresh.

**Reset semantics.** Reset (POST /api/walk/reset) deletes the sigil file, the categories file, and the walk progress file for that user_id. After reset, sigil overlay returns 404 and does not alter layout.

**Persistence across restarts.** All files persist on disk. Restarting the server and re-requesting the same user_id returns the same data.

**Session isolation.** User A's sigil, categories, and walk progress are stored in separate files from User B's. No cross-contamination.

# Invariants and non-goals

**Invariants.**
- Saving creates the sigils/ directory if it does not exist.
- Loading a nonexistent user returns None (not an error).
- Overwriting replaces the previous file entirely.
- Walk progress version mismatch returns false without error.
- Reset is total: removes all preference files for the user.

**Non-goals.** This page does not define the walk flow (see [Taste Walk](taste-walk.md)), the category filter UI (see [Category Filter](category-filter.md)), or multi-user session management. The JS client currently hardcodes user_id="default" everywhere.

# Canonical examples (golden fixtures)

Save/load roundtrip: save {weights: {cat_000: 0.8, cat_001: 0.3}} → load → same weights (test_save_load_roundtrip).

Load nonexistent: load_category_prefs(tmp_path, "nonexistent") → None (test_load_nonexistent_returns_none).

Save creates directory: saving to a fresh tmp_path creates sigils/ subdirectory (test_save_creates_sigils_dir).

Overwrite: save weights {cat_000: 0.5}, then save {cat_000: 0.9, cat_001: 0.3} → load returns second version (test_overwrite_existing).

Walk progress save/restore: save 2 choices with strengths 0.6 and 0.8, restore into new session → current_index = 2, same strengths (test_save_and_restore_choices).

Version mismatch rejects: save with version "v1", create session with version "different_version", restore → returns false, current_index = 0 (test_restore_with_version_mismatch_returns_false).

Delete walk progress: save progress, call delete_walk_progress → file no longer exists (test_delete_walk_progress).

Cross-restart persistence (from UI_TEST_PLAN.md §9.3): complete walk as user A, restart server, API returns same sigil entries.

# Contained sigils

None. This is a leaf sigil.

# Supersession notes

Walk progress persistence was added in Phase 20. Before this, walk state was lost on page reload. BACKLOG.md item 8 notes that JS hardcodes user_id="default" — multi-user support is not yet implemented on the client side, though the server API supports arbitrary user_ids.
