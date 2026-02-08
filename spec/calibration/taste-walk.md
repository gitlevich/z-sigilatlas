# Taste Walk

Container: [Calibration](../calibration.md)

# Purpose

Define the binary preference elicitation interface. The taste walk presents pairs of image mosaics — one from each extreme of a bipolar contrast axis — and records the user's explicit choice of direction and strength. Skipping records nothing. The walk processes bipolar contrasts first (sorted by mass), then optionally extends with emergent PCA contrasts if few bipolars were collapsed.

# Boundary observables

**Start.** POST /api/walk/start with {user_id} returns status "continue", a step, progress, and a contrasts array. The contrasts array contains all bipolar contrast names (no unipolar, no PCA initially). Steps have left_ids, right_ids (each with 6 exemplar image IDs), contrast_name, contrast_id, flipped flag, and step_index.

**Choose.** POST /api/walk/choose with {direction, strength} returns the next step or completion. Direction is "left", "right", or "skip". Strength is a float in [0, 1] (default 1.0). Values outside [0, 1] are clamped.

**Flip correction.** Steps are randomly flipped (low exemplars shown on left sometimes, high on right, and vice versa). When a step is flipped, the user's visual "left" choice maps to "right" in the sigil, and vice versa. The server de-flips before recording.

**Strength semantics.** Strength 1.0 = full preference (default binary behavior). Strength 0.0 = drop the contrast from the sigil (equivalent to skip for scoring). Intermediate values scale the contrast's contribution proportionally.

**PCA extension.** If fewer than MIN_COLLAPSED_TO_SKIP_PCA bipolar contrasts are collapsed when bipolars are exhausted, PCA contrasts are appended to the schedule. If enough bipolars collapse, PCA is skipped entirely. PCA steps always come after all bipolar steps.

**Repeats.** Directional choices may trigger repeat presentations of the same contrast with different exemplar images. Repeat fraction is bounded. Repeats use the is_repeat flag. Inconsistent repeats (direction disagreement) decay or drop the contrast.

**Completion.** When all steps are exhausted, the response has status "complete" with a full sigil containing entries, collapsed_count, and total_choices. The sigil is saved to disk.

**Partial sigil.** After each directional choice, a partial_sigil is available with all collapsed contrasts so far, enabling live radar preview during the walk.

**Progress persistence.** Walk choices are saved to walk_progress_{user_id}.json after every interaction. On page reload, the session restores from saved progress if the library version matches. Progress is deleted on completion or reset.

# Invariants and non-goals

**Invariants.**
- Initial schedule contains only bipolar contrasts, sorted by mass descending.
- Each step has exactly EXEMPLARS_PER_SIDE (6) images per side.
- No center_ids in steps (walk is binary, not three-door).
- Skip maps to "center" internally and produces no sigil entry.
- Flipped steps de-flip direction before recording.
- Strength is clamped to [0, 1].
- Completed session has is_complete = true and current_step = None.

**Non-goals.** This page does not define the category filter (see [Category Filter](category-filter.md)), the arcade (legacy), or how scores are computed from sigils (see [Rendering](../rendering.md)).

# Canonical examples (golden fixtures)

Initial schedule is bipolars only: library with 5 bipolar, 3 unipolar, 2 PCA → session has 5 steps (test_initial_schedule_is_bipolars_only).

Bipolars sorted by mass: step order follows descending mass (test_bipolars_sorted_by_mass).

Skip produces no entry: skip on every step → collapsed_count = 0 (test_all_skips_produce_zero_collapsed).

Skip maps to center: recording "skip" → choice.direction = "center" (test_skip_maps_to_center_internally).

Consistent left = full strength: one bipolar, choose left → collapsed_count = 1, strength = 1.0 (test_consistent_left_produces_full_strength).

Slider strength propagation: record_choice("right", strength=0.7) → choice.strength = 0.7 (test_slider_strength_propagates_to_choice).

Default strength is 1.0: record_choice("left") without strength → choice.strength = 1.0 (test_default_strength_is_one).

Zero strength drops contrast: record_choice("right", strength=0.0) → collapsed_count = 0 (test_zero_strength_drops_contrast).

Strength clamped: strength=1.5 → clamped to 1.0; strength=-0.3 → clamped to 0.0 (test_strength_clamped_to_range).

PCA skipped when enough collapse: ≥ MIN_COLLAPSED_TO_SKIP_PCA bipolars collapse → no PCA steps in schedule (test_many_bipolars_collapsed_skips_pca).

PCA added when few collapse: all bipolars skipped → PCA steps appended (test_few_bipolars_collapsed_extends_with_pca).

Progress persistence: save 2 choices, restore into new session → current_index = 2, same strengths. Version mismatch → restore returns false. No file → restore returns false. Restored session can be completed to produce valid sigil (TestWalkProgressPersistence suite).

# Contained sigils

None. This is a leaf sigil.

# Supersession notes

The original spec (agents.md §4) described a three-door arcade with DoorTriplet prompts including center/median mosaics. The implementation replaced this with a two-tile binary walk (no center mosaic). The walk UI evolved through several phases: Phase 4 introduced it, Phase 10 added signed bias slider, Phase 14 added live radar, Phase 17 replaced radar with pie chart, Phase 20 replaced pie with amber polygon radar with live preview and progress persistence.
