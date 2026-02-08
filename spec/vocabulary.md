# Vocabulary

Container: [INDEX](INDEX.md)

# Purpose

Define the foundational concepts that every other sigil page in this vault depends on. These terms have precise meanings within Sigil Atlas. Their definitions are drawn from the Attention Language reference stored in-repo and from the implementation spec (agents.md §1).

# Boundary observables

These definitions are stable external commitments. Any behavior in the system that contradicts them is a defect.

**Frame.** Everything the user observes at a given moment: color, composition, texture, associations, affect. A frame is a viewport state, not a stored object.

**Contrast.** A span between opposites along which images differ. Contrasts are bipolar (light–dark, warm–cool, natural–manmade), unipolar (portrait, landscape, architecture — presence vs. absence), or emergent (PCA/ICA directions discovered in embedding space). A contrast has mass (how much of the corpus it spans) and stability (whether the direction holds under subsampling).

**Sigil.** A sparse vector of explicitly collapsed contrasts: the axes where the user has declared a direction and a strength. Records what the user chose, not what the user viewed. Uncollapsed contrasts are absent from the sigil — not zero, but unmeasured.

**Collapse.** The irreversible (within a session) transformation of superposition into a definite choice on one contrast axis. Choosing left or right on a contrast collapses it into the sigil with a direction and strength. Choosing skip/center preserves superposition.

**Superposition.** The state of an unmeasured contrast. Distinct from indifference (a measured zero). The system must never treat superposition as neutral weight, and must never infer a preference the user has not declared.

**Drift.** What happens when contrasts are entangled in a corpus. Riding one axis may inadvertently sweep another. The drift policy requires the system to detect and resolve drift transparently — by conditioning, compounding with consent, or rejecting the ride — never by silently conflating axes.

**Neighborhood.** A cluster of visually similar images produced by community detection on the fused neighbor graph. Neighborhoods nest recursively into a multi-level hierarchy.

**Atlas.** The squarified treemap of all neighborhoods. Layout is deterministic and topology-invariant: it never rearranges based on user preferences. Navigation is always reversible.

# Invariants and non-goals

**Invariants.** Every term above has a single meaning throughout the system. Collapse is irreversible within a session (re-riding updates, not undoes). Superposition is never treated as zero. Sigil records only explicit choices.

**Non-goals.** This page does not define how contrasts are discovered, how the atlas is laid out, or how sigils are rendered. Those are deferred to contained sigils.

# Canonical examples (golden fixtures)

Contrast classification (from test_walk.py):
- "sharpness", "brightness", "temperature", "red_dominance" → bipolar
- "sem_bw_vs_color", "sem_natural_vs_manmade" → bipolar (semantic, contains "_vs_")
- "sem_portrait", "sem_street", "sem_landscape" → unipolar (semantic, no "_vs_")
- "pca_clip_0", "pca_dino_1" → emergent PCA

Sigil entry structure (from test_walk.py fixture):
- Each entry: contrast_id, contrast_name, direction ∈ {left, right}, strength ∈ [0, 1], n_presentations, n_agreements.
- A sigil with collapsed_count = 0 has an empty entries dict and records no preferences.

# Contained sigils

None. This is a leaf page — a vocabulary anchor for the rest of the vault.

# Supersession notes

Vocabulary is drawn from docs/attention-language.md (committed) and agents.md §1. If these sources conflict, attention-language.md wins for terminology; agents.md §1 wins for behavioral semantics.
