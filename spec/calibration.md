# Calibration

Container: [INDEX](INDEX.md)

# Purpose

Define how user preference is measured and recorded. Calibration produces a sigil — a sparse vector of collapsed contrasts — from explicit user actions only. Three interfaces exist: taste walk (primary), category filter (secondary), and arcade (legacy). The system records preference only from deliberate choices; it never infers from viewing behavior.

# Boundary observables

**No passive profiling.** Browsing, hovering, dwell time, and viewport exposure never update preference state. Only explicit left/right/skip choices in the walk, handle drags in the category radar, or door selections in the arcade produce sigil writes. This is verified by invariant probe §4.3: replaying a navigation trace with no explicit turn events must not change the sigil file.

**Superposition preserved.** Skip/center choices record nothing. The sigil has no entry for skipped contrasts. collapsed_count reflects only contrasts where the user chose a direction with nonzero strength. This is verified by invariant probe §4.4.

**Sigil structure.** A sigil is a JSON object with: entries (dict keyed by contrast_id, each with contrast_name, direction, strength, n_presentations, n_agreements), collapsed_count, total_choices. Persisted to disk as sigil_{user_id}.json in the sigils/ subdirectory.

**Session isolation.** Each user_id has an independent sigil. Choices made by one user do not affect another user's sigil.

**Library version binding.** A sigil is bound to a contrast_library_version. Walk progress saved with one library version is rejected when loaded against a different version.

# Invariants and non-goals

**Invariants.**
- Only explicit actions produce sigil writes.
- Skip/center is not a neutral preference; it is the absence of measurement.
- Strength is clamped to [0, 1]. Zero strength drops the contrast from the sigil.
- Direction is always {left, right} in the sigil; "skip" is converted to "center" internally and produces no entry.
- Sigils persist across server restarts.

**Non-goals.** This sigil does not define how the atlas is built (see [Atlas](atlas.md)), how scores are computed from sigils (see [Rendering](rendering.md)), or how contrasts are discovered (see [Pipeline](pipeline.md)).

# Canonical examples (golden fixtures)

All skips produce empty sigil: 3-contrast walk where every choice is "skip" → collapsed_count = 0, entries = {} (test_all_skips_produce_zero_collapsed).

Single directional choice: choosing "left" on one contrast → collapsed_count = 1, entry has strength = 1.0, direction ∈ {left, right} (test_one_directional_choice_produces_one_entry).

Partial sigil accumulates: right, left, skip on three contrasts → collapsed_count = 2 with distinct contrast_ids (test_partial_sigil_accumulates_across_contrasts).

Walk completion: completing all steps → response with status = "complete" and a sigil with collapsed_count ≥ 1 (test_completion_returns_sigil).

Flipped step correction: when a step is flipped, choosing "left" on screen records as "right" in the sigil (test_flipped_step_records_correct_direction).

No sigil returns 404: GET /api/atlas/taste_sigil for a nonexistent user → 404. No sigil and no categories → GET /api/atlas/sigil_scores → 404.

# Contained sigils

[Taste Walk](calibration/taste-walk.md) — Binary preference elicitation along bipolar contrast axes with slider strength.

[Category Filter](calibration/category-filter.md) — Radar-based unipolar category weighting with multiplicative gate.

[Sigil Persistence](calibration/sigil-persistence.md) — Storage format, version binding, walk progress, reset semantics.

# Supersession notes

The original spec (agents.md §4) described a "Calibration Arcade" with three-door DoorTriplet prompts and a repeat schedule with ≤80 prompt budget. The implementation evolved into two distinct interfaces: a taste walk (binary left/right with slider strength) and a category filter (radar handles). The arcade remains in code but is secondary. The walk is the primary calibration path. The category filter was added in Phase 13 and refined through Phases 17–20.

Phase 17 replaced the live radar with a progress pie chart during the walk. Phase 20 replaced the pie chart with an amber polygon radar showing current calibration state with live preview.
