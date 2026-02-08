# Overlay

Container: [Rendering](../rendering.md)

# Purpose

Define the visual presentation of sigil scores on the atlas. The overlay modifies node brightness and adds halos without changing topology, tile content, or layout. It is toggled on and off by a toolbar button.

# Boundary observables

**Toggle.** A toolbar button (fingerprint icon) toggles the sigil overlay on and off. Toggling causes immediate visual changes to node salience.

**Brightening and dimming.** Nodes with high scores brighten (golden halo). Nodes with low scores dim. Maximum dimming is 25% — spatial reorder (center-gravity layout bias) is the primary signal, not dimming.

**No content swapping.** The overlay changes brightness and adds halos. It never swaps tile images, rearranges nodes, or changes the treemap layout. Tile streaming and selection are purely geometric and sigil-independent.

**Debug readout.** Pressing D opens a debug overlay showing per-node scores and per-contrast breakdowns for the visible nodes.

**Categories button.** When a category filter is active, the categories toolbar button is highlighted.

**Auto-enable.** Redirecting to /atlas?sigil=1 (after completing a walk or saving categories) auto-enables the sigil overlay.

# Invariants and non-goals

**Invariants.**
- Overlay is purely visual — it never changes navigation paths, door structure, or atlas topology.
- The atlas remains fully navigable with overlay active.
- Maximum dimming is bounded (25%). Nodes are never hidden.
- Toggling off restores normal appearance.

**Non-goals.** This page does not define score computation (see [Scoring Pipeline](scoring-pipeline.md)) or the taste radar visualization (see [Taste Radar](taste-radar.md)).

# Canonical examples (golden fixtures)

Toggle on/off (from UI_TEST_PLAN.md §1.9): toggle sigil button → nodes recolor by score. Toggle off → nodes return to normal.

Debug overlay (from UI_TEST_PLAN.md §1.9): pressing D shows score details.

Walk→atlas integration (from UI_TEST_PLAN.md §9.1): complete walk → sigil saved → redirect to /atlas?sigil=1 → overlay auto-enabled, taste profile radar shows calibrated contrasts.

Categories→atlas integration (from UI_TEST_PLAN.md §9.2): save categories → redirect to /atlas?sigil=1 → categories button highlighted, sigil scores include category gate.

# Contained sigils

None. This is a leaf sigil.

# Supersession notes

Phase 8 introduced sigil rendering as "beauty gravity." Phase 12 added sigil-driven spatial reorder (center-gravity) and reduced dimming to 25% max (commit 6895e82). The spatial reorder is the primary signal; dimming is secondary.
