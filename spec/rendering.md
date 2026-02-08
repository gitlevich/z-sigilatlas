# Rendering

Container: [INDEX](INDEX.md)

# Purpose

Define how user preferences (sigils and category weights) become visible on the atlas. Rendering is overlay-only: it modifies brightness and halo effects on atlas nodes without changing topology, tile content, or layout. The scoring pipeline combines walk scores and category gates into a per-node final score that drives visual salience.

# Boundary observables

**Scoring endpoint.** GET /api/atlas/sigil_scores?user_id=X&level=L returns per-node scores in [0, 1], a per-node breakdown of contributing contrasts, a sigil_version string for cache coordination, and a has_categories boolean.

**Combined formula.** final_score = walk_score × category_gate. Walk-only mode: gate = 1.0. Categories-only mode: walk_score = 0.5 × gate. Neither sigil nor categories: HTTP 404.

**Walk score.** Mean of per-contrast contributions. Each contribution is the quantile-normalized node mean for that contrast, optionally inverted by direction, scaled by strength. Only collapsed contrasts participate. Uncollapsed contrasts produce no effect.

**Category gate.** Weighted average of normalized coordinates across active categories. Category weights at or below the neutral threshold (0.5) are excluded — they do not participate in the average. Active weights are remapped from [0.5, 1.0] to [0, 1]. Normalization uses p10/p90 quantiles from the contrast library. No categories or all categories at/below neutral: gate = 1.0 (no filtering).

**Overlay behavior.** Toggling the sigil overlay causes immediate salience shifts: nodes aligned with preferences brighten (golden halo), others dim. Maximum dimming is 25% — spatial reorder is the primary signal. The atlas remains fully navigable with sigil active.

**Taste radar.** GET /api/atlas/taste_sigil?user_id=X returns only bipolar semantic contrasts (has "_vs_" or is perceptual). Excludes PCA and unipolar categories. Each entry has name, dir ∈ {left, right}, str ∈ [0, 1]. Radar center = 0 (no preference), radial distance = strength magnitude, direction shown by color only (blue = left, orange = right). Sorted_keys included for stable axis ordering.

**Cache control.** All scoring and sigil endpoints return Cache-Control: no-store to prevent stale browser cache responses.

# Invariants and non-goals

**Invariants.**
- Only collapsed contrasts affect overlays. Uncollapsed contrasts produce zero contribution to walk_score (verified by test_no_cross_axis_effect: nodes differing only on an uncollapsed axis get identical scores, difference < 0.001).
- Rendering is overlay-only (agents.md §2.3). Tile streaming and selection are purely geometric and sigil-independent.
- Sigil scoring does not mutate the input sigil dict (verified by test_invariant_4_3_no_sigil_mutation).
- All scores are in [0, 1] (verified by test_score_range).
- The world remains navigable with sigil active. No hard filtering unless explicitly requested.

**Non-goals.** This sigil does not define atlas topology or layout (see [Atlas](atlas.md)), calibration UI or sigil recording (see [Calibration](calibration.md)), or how contrasts and embeddings are produced (see [Pipeline](pipeline.md)).

# Canonical examples (golden fixtures)

Empty sigil neutral: a sigil with no collapsed entries → score = 0.5 for all nodes, empty breakdown.

Right-aligned single contrast: sigil with brightness=right, strength=1.0. Node with mean 0.925 → score > 0.85. Node with mean 0.075 → score < 0.15 (test_single_contrast_right_aligned).

Left-aligned inversion: same contrast with direction=left. High-mean node → score < 0.15, low-mean node → score > 0.85 (test_single_contrast_left_aligned).

No cross-axis contamination: brightness collapsed to right; saturation uncollapsed. Two nodes with identical brightness (0.5) but different saturation (0.1 vs 0.9). Score difference < 0.001 (test_no_cross_axis_effect).

Strength scaling: brightness=right at strength 1.0 on node with value 1.0 → score ≈ 1.0. Same at strength 0.5 → score ≈ 0.5 (test_strength_weighting).

Quantile normalization: p10=0.2, p90=0.8. Value 0.2 → score 0.0; value 0.8 → score 1.0; value 0.5 → score 0.5 (test_quantile_normalization).

Multiple contrasts: three contrasts all right at strength 1.0. Node values 0.8, 0.4, 0.6. Score = mean = 0.6 (test_multiple_contrasts_averaging).

Category gate dominance: portrait=1.0, landscape=0.15, architecture=0.15. Portrait node (0.9) → gate > 0.8. Non-portrait nodes (0.1) → gate < 0.2 (test_maxed_category_dominates_over_low_others).

Categories-only scoring: no walk sigil, portrait category active. High-portrait node gets higher score than low-portrait node (test_categories_only_no_walk).

Combined multiplicative: walk prefers brightness-right, category filters to portrait. Bright-portrait node gets highest score. Bright-non-portrait is gated down (score < 0.2). Dark-portrait gets medium-low score (test_combined_multiplicative).

Taste sigil filtering: sigil with entries for sharpness (bipolar), sem_natural_vs_manmade (bipolar), pca_clip_0 (emergent), brightness (bipolar), sem_portrait (unipolar). Endpoint returns only the 3 bipolar entries; PCA and unipolar are excluded.

# Contained sigils

[Scoring Pipeline](rendering/scoring-pipeline.md) — Walk score computation, category gate computation, quantile normalization, combination formula.

[Overlay](rendering/overlay.md) — Visual presentation: brighten/dim/halo, toggle, maximum dimming, debug readout.

[Taste Radar](rendering/taste-radar.md) — Radar visualization: axis layout, bipolar filtering, direction-by-color, live preview during calibration.

# Supersession notes

BUG-001 (fixed commit 24b0ab0): taste radar previously mapped left/right to 0.0–0.5/0.5–1.0 radial range. Now uses magnitude only; direction shown by color. BUG-002 (fixed commit 24b0ab0): added Cache-Control: no-store to prevent stale score responses. BUG-004 (fixed commit 24b0ab0): category gate changed from soft blend to sharp filter by excluding categories at/below neutral threshold and remapping active weights.
