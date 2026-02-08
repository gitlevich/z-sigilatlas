# Sigil Tree - Backlog

Prioritized work items.

0. **Bug fixes** — BUG-002: sigil overlay serves stale category scores (add Cache-Control headers). BUG-003: category radar empty when no prefs exist (default to neutral handles). BUG-004: category filter is a soft blend, not a hard filter (portrait=max + others=zero should show ONLY portraits).

1. ~~**Calibration walk polish**~~ DONE (Phase 17) — (a) replaced live radar with progress pie chart (donut ring, one slice per contrast, amber=right, blue=left, gray=skipped), (b) display contrast name label during walk, (c) taste profile toggle on atlas.

2. **Materialize the emergent taste contrast** — the calibration walk discovers coefficients of a personal good-bad axis in contrast space. Currently computed transiently as a dot product during scoring. Make it a first-class contrast: own z-summary per node, own exemplars (top-N / bottom-N images), own name. The individual contrasts are scaffolding; the emergent one is the signal. This is dimensionality reduction from N contrasts to one personally meaningful axis.

3. **README / landing page** — explain the "neighborhood is a sigil" vision

4. **Calibration onboarding text** — add a paragraph in the calibration view explaining what it does and how to use it.

5. **Rename walk to calibration** — rename the concept from "walk" to "calibration" throughout; remap `/walk` path to `/calibration`.

6. **Make category selection visible in atlas** — category radar preferences should visibly affect the atlas display. Currently unclear whether they are reflected.

7. **Evolve the spec** — refine the specification to match what has been built. The spec should evolve as the product does, becoming a sigil of this application: a sigil that, when worn by an LLM, will get it to design an app to this spec within the resolution of the spec. Our secondary deliverable is the evolved spec: the sigil of sigilatlas.

8. **Multi-user support / test user** — JS currently hardcodes `user_id='default'` everywhere. Add a mechanism (URL param, cookie, or session) to switch user_id so that dev/test usage doesn't overwrite real user preferences. Server APIs already accept `user_id` parameter; only the JS client needs updating.

9. **Persist UI state across reloads** — Button/toggle states (sigil overlay active, taste radar visible, current navigation depth, etc.) are lost on page reload. Use `sessionStorage` or `localStorage` to remember UI state per page so reloads restore the same view. Applies to all screens: atlas (sigil active, taste radar toggle, navigation path), walk (help panel state), categories (unsaved edits warning).

10. **Minimap click = go up one level** — The small tile in the bottom-right corner of the atlas currently navigates home (root). Should instead go up one level (same as Esc / back button), which is the intuitive expectation when clicking a minimap overview.

11. **Calibration: Space/Enter advances to next contrast** — On the calibration page, pressing Space or Enter should submit the current slider value for the current contrast and advance to the next one. Currently only arrow keys + explicit navigation work.

### Epic: Settings UI

12. **Semantic contrast management** — UI to set the order in which contrasts are shown during calibration and to include/exclude/add/delete semantic contrasts. Currently calibration starts with low-relevance contrasts (sharpness, tint, temperature); user should control ordering and which contrasts participate.

13. **Category management (CRUD)** — UI to create, read, update, and delete semantic categories. Currently categories are derived from the contrast library with no user control over which categories exist or how they're defined.
