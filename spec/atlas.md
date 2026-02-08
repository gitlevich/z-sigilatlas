# Atlas

Container: [INDEX](INDEX.md)

# Purpose

Define the spatial organization of images and how users traverse it. The atlas is a multi-level squarified treemap where neighborhoods of visually similar images partition rectangular space exactly. Navigation enters and exits levels while preserving strict containment. The atlas topology is fixed — it never rearranges per user.

# Boundary observables

**Manifest.** The atlas exposes a manifest declaring max_level, root_bounds (x, y, w, h), and corpus_size. The root bounds define the coordinate frame for all rectangles at all levels.

**Level meta.** Each level 0..max_level contains a set of nodes. Each node has: node_id, rect (x, y, w, h), size (image count), image_ids, representatives, tile_path, child_ids (empty for leaves), parent_id (null for level 0), is_leaf.

**Rectangles tile exactly.** At level 0, node rectangles partition root_bounds with no gaps and no overlaps (total area equals root area within 1e-4). At level L>0, children of a parent partition the parent's rectangle exactly.

**Image partitioning.** At level 0, the union of all node image_ids equals the full corpus. For any parent node, the union of its children's image_ids equals the parent's image_ids. Every child's image_ids is a subset of its parent's.

**Determinism.** On unchanged inputs with the same random seed, rebuilds produce layouts where ≥95% of node rectangles have IoU ≥0.98 with the previous build.

**Doors.** Each non-root node has a back door to its parent. Leaf nodes expose member entries (individual images). Non-leaf nodes expose down (to children) or lateral (to neighbors) doors.

**Flow neighbors.** Each node at a level has a set of neighbor nodes. No node is its own neighbor. All neighbor node_ids exist in the same level.

**Labels.** Every node at every level has a non-empty string label.

**Navigation.** Entering a node at level L transitions to level L+1 showing that node's children inside its rectangle. Exiting returns to the parent level. Home returns to level 0. These transitions preserve containment: the camera anchors to the target region, and the child view renders inside the parent rectangle with no global permutation.

**Exit latency.** From any depth, one action (Escape or back) returns to the parent view within a hard bound (250ms warm, 1s cold). No additional confirmations are required.

# Invariants and non-goals

**Invariants.**
- Topology is sigil-independent (agents.md §2.1). User preferences never change atlas construction, layout, or tile content.
- Containment is strict: child rectangles are geometrically inside the parent rectangle at all levels (verified by test_invariant_4_1_children_inside_parent_rect).
- Atlas build does not create or modify sigil files (verified by test_invariant_4_3_no_sigil_on_atlas).
- No event horizons: from any depth, ≤1 action and ≤1 second returns to a wider view (agents.md §4.5).

**Non-goals.** This sigil does not define how preferences are measured (see [Calibration](calibration.md)), how scores are computed or displayed (see [Rendering](rendering.md)), or how embeddings are produced (see [Pipeline](pipeline.md)).

# Canonical examples (golden fixtures)

Treemap coverage (from test_atlas.py): values [10, 8, 6, 4, 3, 2, 1] laid into frame (0, 0, 1, 1) produce 7 rectangles whose total area is 1.0 within 1e-6. All rectangles have w>0 and h>0. Max aspect ratio < 15.

Single value fills frame: squarified_treemap([5], (0, 0, 2, 3)) → [(0, 0, 2, 3)].

Custom parent rect: treemap into (0.3, 0.2, 0.4, 0.5) produces rectangles that sum to parent area and are all geometrically contained within the parent.

End-to-end atlas build (50-image synthetic corpus): produces corpus_size=50, multiple neighborhoods, total rectangle area = 1.0 within 1e-4, all images accounted for, all tile files exist on disk.

Determinism rebuild: two builds with seed=42 on identical inputs produce node layouts with IoU > 0.98 for every cluster.

Recursive 2-level build (200 images): level 0 and level 1 exist, every level-1 node references a valid level-0 parent, parent child_ids match children in level 1.

Leaf criteria: leaf nodes have size < MIN_SPLIT_SIZE or are at max_level.

Image containment across levels: every child's image_ids is a strict subset of its parent's image_ids. Union of children equals parent.

# Contained sigils

[Treemap Layout](atlas/treemap-layout.md) — Squarified treemap algorithm, ordering from Fiedler vector, rectangle partitioning.

[Navigation](atlas/navigation.md) — Enter/exit transitions, camera anchoring, minimap, doors, flow graph.

# Supersession notes

The original spec (agents.md §5–§6) described continuous 2D driving with smooth camera. The implementation replaced continuous driving with click-to-enter navigation with discrete level transitions. The current behavior (click node → enter, Escape → exit, Home → root) is the authoritative spec. Continuous driving from agents.md §7 was never fully implemented; the dead code in ride_engine.py and ride_session.py is not part of the current system.
