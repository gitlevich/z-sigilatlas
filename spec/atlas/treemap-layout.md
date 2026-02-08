# Treemap Layout

Container: [Atlas](../atlas.md)

# Purpose

Define the algorithm that converts neighborhoods into rectangular partitions of space. The layout is a squarified treemap fed by a stable 1D ordering derived from the fused neighbor graph's spectral structure (Fiedler vector). The result is a containment-preserving hierarchy where nearby rectangles tend to contain visually related images.

# Boundary observables

**Squarified treemap.** Given a list of values (node sizes) and a parent rectangle, produce a list of rectangles that:
- Have the same count as the input values.
- Tile the parent rectangle exactly (sum of areas = parent area within 1e-6).
- Have all widths > 0 and all heights > 0.
- Have bounded aspect ratios (max ratio < 15 in practice).

**Ordering.** The 1D ordering of neighborhoods is computed from the Fiedler vector (second-smallest eigenvector of the graph Laplacian) of the fused adjacency matrix. Two calls with the same input produce the same relative ordering (rank-equivalent). The Fiedler vector has no NaN or Inf values.

**Containment at every level.** At level L+1, each parent node's children are laid out by the same treemap algorithm into the parent's rectangle. Children's rectangles are geometrically contained within the parent's rectangle (within 1e-9 tolerance). Children's areas sum to the parent's area.

**Determinism.** With the same random seed and unchanged inputs, the layout is deterministic. Rebuilds produce identical rank orderings and rectangle IoU > 0.98.

# Invariants and non-goals

**Invariants.**
- Empty input returns empty output.
- Single value fills the entire frame.
- The treemap is purely geometric — it has no knowledge of sigils, preferences, or user state.
- Ordering is deterministic given identical adjacency matrices.

**Non-goals.** This page does not define how the adjacency matrix is constructed (fused graph construction belongs to [Pipeline](../pipeline.md)). It does not define navigation behavior (see [Navigation](navigation.md)).

# Canonical examples (golden fixtures)

Basic coverage: values [10, 8, 6, 4, 3, 2, 1] into (0, 0, 1, 1) → 7 rectangles, total area = 1.0 ±1e-6.

Single value: [5] into (0, 0, 2, 3) → [(0, 0, 2, 3)].

Empty: [] → [].

Custom parent rect: values [10, 5, 3] into (0.3, 0.2, 0.4, 0.5) → 3 rectangles, total area = 0.4 × 0.5 = 0.2, all contained within parent.

Ordering determinism: compute_ordering called twice on the same adjacency → rank arrays are identical (np.argsort equality).

No NaN: Fiedler vector on any valid adjacency matrix has all finite values.

# Contained sigils

None. This is a leaf sigil.

# Supersession notes

agents.md §2.2 described "ordered squarified treemap (or equivalent)" with ordering from "embedding-derived 2D projection (or neighbor graph traversal)." The implementation chose the Fiedler vector of the graph Laplacian as the 1D ordering — a spectral graph traversal. This is the authoritative method.
