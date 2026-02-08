# Sigil Tree - Project Status

Current state snapshot for session resumption. See [JOURNAL.md](JOURNAL.md) for build history, [BACKLOG.md](BACKLOG.md) for planned work.

## Current State (2026-02-07)

Phase 18 on `feature/detail-profile` branch. 226 tests pass. Server on port 8777.

### What just happened (this session)

1. **Unified walk+slider** — replaced two-step side+strength flow with signed bias model. Arrow keys accumulate directional bias on -1..+1 continuum. First press selects side at 0.50, subsequent presses nudge, crossing zero flips selection. Slider pole labels show actual contrast names aligned with visual layout (respects flip). `Choice.strength` field, `build_sigil()` slider logic.

2. **Removed profile page** — `/profile` page, its 3 routes, 3 handlers, toolbar button, PROFILE_HTML, and 4 tests all removed. Strength is now set inline during the walk via the unified bias slider. `update_sigil_strengths()` in arcade.py kept (still useful).

3. **Categories integration** — Fixed `handle_atlas_sigil_scores` to allow categories-only mode (no walk sigil needed). Added `has_categories` flag to API response. Atlas JS highlights categories toolbar button when filter active. Backend scoring pipeline was already complete — the only blocker was the 404 when no walk sigil existed. 2 new endpoint tests added.

4. **try/finally on sendChoice** — JS fetch in walk page now wrapped in try/finally so `choosing` flag always resets, preventing frozen UI on network errors.

### Current issue

The user reports categories filtering has "no effect" visually in the atlas. The backend IS returning differentiated scores (0.03-0.29 range with real gate values). The MCP Chrome extension lost its connection so visual verification is blocked. Possible causes:
- User may need to toggle sigil overlay on (concentric ellipses button in atlas toolbar)
- Or navigate from `/categories` save which redirects to `/atlas?sigil=1`
- Cache invalidation should work (version changes to "categories_only" for categories-only mode)

### What's live

- **Atlas viewer** — 5-level treemap of 874 images in 960 nodes
- **Calibration walk** (`/walk`) — Unified bias slider. Arrow keys: first press selects side at 50%, subsequent presses nudge bias. Crossing zero flips to other side. Pole labels show contrast names. Enter confirms, Space skips, Escape cancels.
- **Category filter** (`/categories`) — radar chart with 11 unipolar semantic categories. Now integrated: `final_score = walk_score * category_gate`. API returns 200 with categories-only (no walk needed).
- **Sigil overlay** — toggle in toolbar. Dimming + golden halo. Categories button highlighted when filter active.
- **Taste profile** — radar in atlas toolbar
- **Live at** https://sigilatlas.fly.dev/ (port 8777 locally)

### Scoring pipeline

```
walk sigil (bipolar contrasts) --> walk_score per node
category prefs (radar handles)  --> category_gate per node
final_score = walk_score * category_gate
```

Walk-only: gate = 1.0. Categories-only: walk_score = 0.5 * gate. Neither: 404.

### Key files

| File | Role |
|---|---|
| `sigiltree/viewer_server.py` | Server + all HTML/CSS/JS inline |
| `sigiltree/sigil_scoring.py` | `compute_sigil_scores()`, `compute_category_gate()` |
| `sigiltree/walk.py` | Walk session logic, `step_to_dict` now includes `flipped` flag |
| `sigiltree/arcade.py` | Sigil persistence, category prefs, `update_sigil_strengths()` |
| `sigiltree/atlas.py` | Atlas build: clustering, treemap, tiles |

### Test files

| File | Tests |
|---|---|
| `tests/test_categories.py` | 20 (gate computation, combined scoring, persistence, 2 new endpoint tests) |
| `tests/test_walk.py` | 43 (walk session, flip, slider strength — profile endpoint tests removed) |
| `tests/test_doors.py` | 30 (graph behavior, no dead ends) |
| `tests/test_sigil_scoring.py` | 11 (scoring algorithm) |
| `tests/test_arcade.py` | 30 (calibration arcade, sigil strength, slider strength in build_sigil) |
| `tests/test_atlas.py` | 38 (atlas build, treemap, determinism) |
| `tests/test_ride.py` | 28 (ride stats, engine, session) |
| `tests/test_contrasts.py` | 8 (mass scoring, exemplars) |
| `tests/test_embeddings.py` | 8 (embedding store) |
| `tests/test_indexer.py` | 11 (corpus ingestion) |
| **Total** | **226** |

### Commands

```bash
uv run sigiltree serve artifacts --port 8777   # local server
uv run pytest tests/ -x                         # run tests
fly deploy                                       # deploy to Fly.io
```

### Recent commits on feature/detail-profile

```
b308297 Unified walk+slider: signed bias replaces two-step side+strength flow
ef35ace Walk progress pie, fix taste sigil filter for bipolar sem_ contrasts
15e2fe1 Atlas taste profile: toggle radar showing calibrated visual preferences
```

### Pending changes (uncommitted)

- Categories integration: handler fix, has_categories flag, categories button highlight, 2 new tests
- Need visual verification that categories filtering shows in atlas
