# Scoring Pipeline

Container: [Rendering](../rendering.md)

# Purpose

Define the computation that converts a sigil and category weights into per-node scores. The pipeline takes three inputs — a sigil (or None), a contrast library with coordinates, and category weights (or None) — and produces a score in [0, 1] for each atlas node along with a per-contrast breakdown.

# Boundary observables

**Walk score computation.** For each collapsed contrast in the sigil: compute the node's mean coordinate across its images, normalize to [0, 1] using the contrast's p10 and p90 quantiles, optionally invert if direction is "left", and scale by strength. The walk score is the mean of these per-contrast contributions. If no contrasts are collapsed, walk score = 0.5 (neutral).

**Quantile normalization.** A raw coordinate value equal to p10 maps to 0.0. A value equal to p90 maps to 1.0. The midpoint of [p10, p90] maps to 0.5. Values outside [p10, p90] are clamped to [0, 1].

**Direction inversion.** Direction "right" uses the normalized value directly (high raw → high score). Direction "left" inverts: score = 1.0 - normalized (high raw → low score).

**Strength scaling.** Each contrast's contribution is multiplied by its strength. Strength 1.0 = full contribution. Strength 0.5 = half contribution. The final walk score is a weighted mean where weights are the strengths.

**Category gate computation.** See [Category Filter](../calibration/category-filter.md) for gate semantics. The gate is a value in [0, 1] per node.

**Combination.** final_score = walk_score × category_gate. Walk-only: gate = 1.0. Categories-only: walk_score = 0.5 × gate. Neither: HTTP 404 (no scores to compute).

**Breakdown.** Each node's result includes a breakdown array listing each collapsed contrast's name and its individual contribution. Uncollapsed contrasts do not appear in the breakdown.

**Missing images.** Nodes with image_ids not found in the coordinates are handled gracefully — only available images are used, no crash.

**Immutability.** The scoring function does not mutate its input sigil dict.

# Invariants and non-goals

**Invariants.**
- All scores in [0, 1].
- Only collapsed contrasts contribute to walk_score.
- Uncollapsed contrasts produce zero effect — nodes differing only on uncollapsed axes get identical scores.
- Empty sigil (no collapsed entries) → score = 0.5 for all nodes.
- Scoring does not mutate inputs.
- Missing image_ids are skipped, not errors.

**Non-goals.** This page does not define how the sigil is built (see [Calibration](../calibration.md)) or how scores are visualized (see [Overlay](overlay.md)).

# Canonical examples (golden fixtures)

Empty sigil: no entries → score = 0.5, empty breakdown (test_empty_sigil_neutral).

Right-aligned: brightness=right, strength=1.0. Images at 0.9/0.95 → score > 0.85. Images at 0.1/0.05 → score < 0.15 (test_single_contrast_right_aligned).

Left-aligned: brightness=left, strength=1.0. Same images. High-mean node → score < 0.15 (test_single_contrast_left_aligned).

No cross-axis: brightness collapsed, saturation uncollapsed. Nodes with same brightness (0.5) but different saturation → score difference < 0.001 (test_no_cross_axis_effect).

Uncollapsed absent from breakdown: brightness collapsed, saturation uncollapsed. Breakdown contains "brightness" but not "saturation" (test_uncollapsed_not_in_breakdown).

Strength scaling: node value 1.0, full strength → score ≈ 1.0. Half strength → score ≈ 0.5 (test_strength_weighting).

Quantile normalization: p10=0.2, p90=0.8. Values: 0.2→0.0, 0.8→1.0, 0.5→0.5 (test_quantile_normalization).

Mean of contributions: three contrasts, node values 0.8, 0.4, 0.6, all right at strength 1.0 → score = 0.6 (test_multiple_contrasts_averaging).

Missing images: node with ["a", "missing1", "missing2"], only "a"=0.8 in coordinates → score > 0.7, no crash (test_missing_image_ids_graceful).

Input immutability: deepcopy before and after scoring → sigil unchanged (test_invariant_4_3_no_sigil_mutation).

# Contained sigils

None. This is a leaf sigil.

# Supersession notes

The scoring formula has been stable since Phase 8. The category gate was added in Phase 13 as a multiplicative modifier. BUG-004 (commit 24b0ab0) sharpened the gate by excluding neutral categories and remapping weights.
