# Contrast Discovery

Container: [Pipeline](../pipeline.md)

# Purpose

Define how contrasts are discovered from the corpus, how they are validated for mass and stability, and how the contrast library is structured. The output is a versioned contrast library with per-image scalar coordinates, quantiles, and exemplar sets.

# Boundary observables

**CLI.** `sigiltree contrasts <artifact_dir>` builds the contrast library.

**Contrast sources.** Three sources:
- Perceptual: temperature, tint, tonality, saturation, contrast, texture scale, sharpness, color dominance. These are bipolar.
- Semantic: unipolar categories from a curated prompt list (portrait, landscape, street, architecture, nature, abstract, night, interior, etc.) and bipolar semantic pairs (bw_vs_color, natural_vs_manmade, interior_vs_exterior, etc.).
- Emergent: PCA/ICA directions from embedding families. Bounded count.

**Library structure.** A versioned JSON file (contrast_library.json) containing: version string, count, and an array of contrasts. Each contrast has: contrast_id, name, source, mass, stability, quantiles (p10, p25, p50, p75, p90), and exemplars (low, median, high — arrays of image_ids).

**Mass.** Score distribution spans a meaningful range. Quantiles are well-separated. Mass is a positive float.

**Stability.** Direction/measure stable under subsampling. Correlation of per-image scores between full corpus and 50% subsample exceeds 0.9 for all kept contrasts.

**Library size.** Bounded at 20–60 contrasts for v1.

**Per-image coordinates.** A JSON file (coordinates.json) mapping contrast_name → {image_id → float} for every kept contrast and every image.

**Exemplars.** For the top contrasts by mass, low-vs-high exemplar mosaics are obviously distinct at a glance. Each quantile band has enough exemplar images for two presentations (to support repeat logic in the walk).

**Contrast API.** GET /api/contrasts returns the full library with name, source, mass, stability, exemplars for each contrast.

# Invariants and non-goals

**Invariants.**
- All kept contrasts pass the stability check (subsample correlation > 0.9).
- Library size is bounded (20–60 for v1).
- Every contrast has non-empty exemplar sets for low, median, and high bands.
- Per-image coordinates cover all indexed images.
- Rebuilding contrasts with unchanged embeddings is incremental.

**Non-goals.** This page does not define how contrasts are presented in calibration (see [Taste Walk](../calibration/taste-walk.md), [Category Filter](../calibration/category-filter.md)) or how coordinates are used in scoring (see [Scoring Pipeline](../rendering/scoring-pipeline.md)).

# Canonical examples (golden fixtures)

Mass scoring (from test_contrasts.py): each contrast has a positive mass and stability value. Exemplar structure has low, median, high arrays.

Contrast classification rule (from test_walk.py): perceptual names and color_dominance names → bipolar. sem_ with "_vs_" → bipolar. sem_ without "_vs_" → unipolar. pca_ → emergent.

Library endpoint (from UI_TEST_PLAN.md §8.1): GET /api/contrasts → each contrast has name, source, mass, stability, exemplars with low/median/high arrays.

# Contained sigils

None. This is a leaf sigil.

# Supersession notes

Agents.md §Phase 3 described selection rules including "perceptual (temperature, tint, tonality/high-key vs low-key, saturation, global contrast, texture scale, sharpness/blur, motion where detectable)" and "semantic unipolar categories from a curated prompt list (start small: portrait, landscape, street, architecture, nature, abstract, night, interior)." The implementation follows this list with additions (color dominance channels, bipolar semantic pairs). The materialized taste axis (added Phase 13, BACKLOG item 2) is a separate emergent contrast computed from the user's sigil, not a corpus-level contrast.
