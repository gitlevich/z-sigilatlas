# Sigil Atlas — Specification Vault

# Purpose and scope

This vault is the Markov blanket of Sigil Atlas: the smallest set of boundary observables, invariants, and canonical examples such that any coding agent, conditioned on these pages alone, can regenerate the application without behavioral drift.

Sigil Atlas organizes a collection of photographs into a zoomable map based on visual similarity. Three embedding families (semantic, structural, textural) are fused into a neighbor graph, clustered into neighborhoods, and laid out as a multi-level squarified treemap. Two calibration interfaces let users declare preferences through explicit binary choices and category handles. Preferences accumulate into a sigil — a sparse vector of collapsed contrasts — projected onto the atlas as brightness overlays. The atlas topology never changes; only the light does.

The vocabulary and conceptual framework come from Attention Language (see [vocabulary](vocabulary.md)).

# How to use this vault

Each page is one abstraction level. Pages define what a subsystem constrains (boundary observables, invariants) and what it defers to children. No page mixes levels.

To regenerate the full system: start at this index, follow the top-level sigil links, and recurse into contained sigils as needed. Every claim is grounded in repository evidence. Uncertain claims are marked as open questions in [OPEN-QUESTIONS](OPEN-QUESTIONS.md).

To update the spec: make a delta in the appropriate sigil page, add a [CHANGELOG](CHANGELOG.md) entry that supersedes the previous text. Code changes are downstream projections of spec changes. Latest wins.

# Top-level sigils

The root decomposes into five top-level sigils. Together they are sufficient and complete.

[Vocabulary](vocabulary.md) — Foundational concepts: frame, contrast, sigil, collapse, superposition, drift. Every other page depends on these definitions.

[Atlas](atlas.md) — The map: treemap hierarchy, navigation, containment, determinism. Constrains how images are spatially organized and traversed.

[Calibration](calibration.md) — Preference elicitation: taste walk, category filter, arcade. Constrains how user preference is measured and recorded.

[Rendering](rendering.md) — Projection of preferences onto the atlas: scoring pipeline, overlays, taste radar. Constrains how sigils become visible.

[Pipeline](pipeline.md) — Corpus processing: indexing, embedding, contrast discovery. Constrains how raw images become the artifacts that Atlas, Calibration, and Rendering consume.
