# Navigation

Container: [Atlas](../atlas.md)

# Purpose

Define how users move through the atlas hierarchy: entering neighborhoods, exiting to parents, panning, zooming, and using the minimap. Navigation preserves containment at every transition and guarantees escape from any depth in one action.

# Boundary observables

**Enter.** Clicking a node at level L transitions the view to level L+1, showing that node's children inside its rectangle. The camera anchors to the target region. The child view renders inside the parent rectangle with no global permutation.

**Exit.** Pressing Escape or the back button returns to the previous level. The parent view is restored without re-layout jumps.

**Home.** The home button returns directly to level 0 from any depth.

**Minimap.** A small overview tile in the bottom-right corner shows the level-0 layout at all zoom levels. Currently, clicking the minimap navigates to root (home).

**Doors API.** GET /api/atlas/node/{node_id}/doors?level=L returns a doors array. Every non-root node has a "back" door pointing to its parent. Root-level nodes have a "back" door pointing to root. Leaf nodes have "member" entries (individual images). Non-leaf nodes have "down" or "lateral" doors.

**Flow neighbors API.** GET /api/atlas/flow_neighbors?node_id=X&level=L returns neighbor nodes at the same level. No node is its own neighbor. All returned node_ids exist in the same level's meta.

**Pan and zoom.** WASD keys or drag for panning. Scroll wheel for zoom. Pan is interactive with progressive tile loading.

**Breadcrumb.** Shows the current navigation level.

# Invariants and non-goals

**Invariants.**
- Reserve attention: from any depth, one action returns to a wider view within 1 second and without additional confirmations (agents.md §4.2, §4.5).
- Continuity: enter expands the aimed region; exit restores the parent with no global permutation (agents.md §4.1).
- Navigation never creates "event horizon" stickiness.
- Navigation is sigil-independent — the same navigation paths exist regardless of user preferences.

**Non-goals.** This page does not define the treemap layout algorithm (see [Treemap Layout](treemap-layout.md)) or how visual overlays change during navigation (see [Rendering](../rendering.md)).

# Canonical examples (golden fixtures)

Door structure (from test_doors.py): a 4-level atlas fixture (L0:4, L1:8, L2:16, L3:32 nodes). Every non-root node has a back door. Leaf nodes have member entries with valid image_ids. Non-leaf nodes have down doors to children. No dead ends exist — every node has at least one navigable door.

Flow neighbors (from UI_TEST_PLAN.md §1.6): GET /api/atlas/flow_neighbors returns neighbors where no node is its own neighbor and all neighbor IDs exist at the same level.

Navigation stack (from UI_TEST_PLAN.md §1.8): click node at L0 → view shows L1 children. Press Esc → returns to L0. Home button → returns to L0 regardless of depth.

# Contained sigils

None. This is a leaf sigil.

# Supersession notes

agents.md §7 described continuous 2D driving with smooth camera motion at 60fps. The implementation uses discrete click-to-enter navigation with level transitions instead. Continuous driving was not built. The current click/enter/exit model is authoritative.

BACKLOG.md item 10 notes that minimap click currently goes home; the intended behavior is "go up one level." This is a known deviation; current behavior (home) is what the system does.
