# Category Filter

Container: [Calibration](../calibration.md)

# Purpose

Define the radar-based category weighting interface. Users drag handles on a radar chart to express interest in unipolar semantic categories (portrait, landscape, architecture, etc.). The resulting weights produce a multiplicative gate on sigil scores — boosting neighborhoods that match active categories and dimming those that do not.

# Boundary observables

**Data endpoint.** GET /api/categories/data?user_id=X returns categories (array of unipolar sem_ contrasts only — no bipolar _vs_, no pca_) and existing_weights (null or dict of previously saved weights). Each category has contrast_id, name, and exemplar_ids.

**Save endpoint.** POST /api/categories/save with {user_id, weights: {contrast_id: float}} persists the weights. Re-fetching data returns them in existing_weights. Overwrites any previous weights for that user.

**Neutral threshold.** The radar center represents "excluded" (weight = 0.5). Categories at or below 0.5 are excluded from the gate computation entirely. Active categories have weights in (0.5, 1.0], remapped to effective strength [0, 1]. Display shows effective filter strength: 0% at threshold, 100% at maximum.

**Gate computation.** For each atlas node, the gate is a weighted average of quantile-normalized coordinates across only the active (above-threshold) categories. If no categories are active, gate = 1.0 (no filtering). Gate values are in [0, 1].

**Sharp filtering.** When one category is at maximum and others are at or near neutral, the gate strongly separates matching from non-matching nodes. This is not a soft blend — categories excluded at neutral do not dilute the signal.

**Radar interaction.** Each category has a draggable handle on its radar axis. Drag outward increases weight. Active handles (above threshold) shown in green. A filled polygon tracks handle positions. Reset or double-click returns a handle to neutral (0.5). Save button triggers redirect to atlas with sigil overlay enabled.

**Exemplar preview.** Hovering a category shows its high-end exemplar images.

**Default state.** When no saved preferences exist, all handles initialize at neutral (0.5), rendering a full polygon at the midline rather than an empty graph.

# Invariants and non-goals

**Invariants.**
- Only unipolar semantic categories appear (no bipolar, no PCA).
- No weights or all weights at/below neutral = gate 1.0 (no filtering).
- Categories at weight 0 or at the neutral threshold are excluded entirely from the weighted average.
- Gate values are in [0, 1] for all nodes.
- The category filter is multiplicative on walk_score, not additive.

**Non-goals.** This page does not define the taste walk (see [Taste Walk](taste-walk.md)), how categories are discovered in the contrast library (see [Contrast Discovery](../pipeline/contrast-discovery.md)), or the visual overlay rendering (see [Rendering](../rendering.md)).

# Canonical examples (golden fixtures)

No weights = no filtering: compute_category_gate({}, ...) → all gates = 1.0 (test_no_weights_returns_all_ones).

All zero weights = no filtering: weights {cat_000: 0.0, cat_001: 0.0} → gates = 1.0 (test_all_zero_weights_returns_no_filtering).

Single active category: portrait at 1.0. Node with portrait score 0.85 → gate > 0.9. Node with portrait score 0.12 → gate < 0.1 (test_single_category_high_node_gets_high_gate, test_single_category_low_node_gets_low_gate).

Two categories weighted average: portrait at 1.0, landscape at 1.0. Node with portrait=0.9, landscape=0.1 → gate ≈ 0.5 (test_multiple_categories_weighted_average).

Zero-weight excluded: portrait at 1.0, landscape at 0.0. Result identical to portrait-only (test_zero_weight_excluded).

Sharp dominance: portrait=1.0, landscape=0.15, architecture=0.15. Portrait node → gate > 0.8. Non-portrait nodes → gate < 0.2 (test_maxed_category_dominates_over_low_others).

Gate range: all gate values in [0, 1] across diverse inputs (test_gate_range_zero_to_one).

Default state: no prefs file → radar renders all handles at neutral, not empty (BUG-003 fix).

# Contained sigils

None. This is a leaf sigil.

# Supersession notes

The category filter was added in Phase 13. BUG-004 (fixed commit 24b0ab0) changed the gate from a soft blend to a sharp filter: categories at or below neutral (0.5) are now excluded entirely, and active weights are remapped from [0.5, 1.0] to [0, 1]. BUG-003 (fixed commit 24b0ab0) added neutral default initialization when no prefs exist.
