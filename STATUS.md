# Sigil Tree - Project Status

Current state snapshot for session resumption. See [JOURNAL.md](JOURNAL.md) for build history, [BACKLOG.md](BACKLOG.md) for planned work.

## Current State (2026-02-08)

Phase 20 on `master` branch. 244 tests pass. Server on port 8777.

### What just happened (this session)

8. **Taste radar on by default** — `tasteRadarVisible = true`, toolbar button starts with `active` class. Button always visible (removed hidden-until-data logic).

9. **Taste axis pinned to north** — In unified radar, taste_axis is always at position 0 (north/top), remaining axes sorted for smooth polygon.

10. **Reset clears everything** — `delete_sigil()` now also removes `categories_{user_id}.json`. After reset, sigil overlay returns 404 and doesn't alter layout.

### Previous session

4. **Calibration onboarding** (backlog item 4) — Inline help panel on `/walk` with `?` toggle button. Shows on first visit.

5. **Taste profile radar fix** — Labels now show winning pole names ("bright", "abstract", "wide") instead of contrast names with +/- suffixes. Added `_POLE_OVERRIDES` dict and `_pole_labels()` helper.

6. **Unified radar** — Merged separate taste profile panel into the main atlas hover radar. One radar, two overlaid polygons: amber (taste, always visible when toggled) + blue (node, on hover). Same axes, same coordinate space, sorted for smooth shape. Taste dots orange/blue by direction, un-voted axes gray at midline.

7. **Calibration reset button** — "reset" button top-right on `/walk` page. Calls `POST /api/walk/reset` to delete sigil + taste axis, then reloads. `delete_sigil()` added to `arcade.py`.

### Older session

1. **Categories integration** — categories-only mode, cache invalidation fix, 3 endpoint tests.
2. **Sharper category gating** — cubed weights, reset button.
3. **Materialized emergent taste contrast** (backlog item 2) — first-class taste axis with per-image coordinates, z-summaries, exemplars, radar integration, `/api/atlas/taste_axis` endpoint, 16 tests.

### What's live

- **Atlas viewer** — 5-level treemap of 874 images in 960 nodes
- **Calibration walk** (`/walk`) — Unified bias slider with arrow keys, onboarding help panel with `?` toggle, reset button
- **Category filter** (`/categories`) — radar chart with 11 categories, reset button, cubed weights for sharp gating
- **Sigil overlay** — toggle in toolbar. Dimming + golden halo. Categories button highlighted when filter active.
- **Taste profile** — unified radar in atlas, on by default, taste_axis at north
- **Taste axis** — materialized emergent contrast with per-image coordinates, z-summaries, exemplars, green/red dot
- **Live at** https://sigilatlas.fly.dev/ (port 8777 locally)

### Scoring pipeline

```
walk sigil (bipolar contrasts) --> walk_score per node
category prefs (radar handles)  --> category_gate per node (weights cubed)
final_score = walk_score * category_gate
taste_axis = per-image projection of sigil onto contrast space
```

Walk-only: gate = 1.0. Categories-only: walk_score = 0.5 * gate. Neither: 404.

### Key files

| File | Role |
|---|---|
| `sigiltree/viewer_server.py` | Server + all HTML/CSS/JS inline |
| `sigiltree/sigil_scoring.py` | `compute_sigil_scores()`, `compute_category_gate()` |
| `sigiltree/taste_axis.py` | `compute_taste_coordinates()`, `materialize_taste_axis()` |
| `sigiltree/walk.py` | Walk session logic |
| `sigiltree/arcade.py` | Sigil persistence, category prefs, taste axis persistence, `delete_sigil()` |
| `sigiltree/atlas.py` | Atlas build: clustering, treemap, tiles |

### Test files

| File | Tests |
|---|---|
| `tests/test_categories.py` | 22 (gate computation, cubed weights, combined scoring, persistence, 3 endpoint tests) |
| `tests/test_taste_axis.py` | 16 (taste coordinates, exemplars, quantiles, materialization, z-summaries) |
| `tests/test_walk.py` | 43 (walk session, flip, slider strength) |
| `tests/test_doors.py` | 30 (graph behavior, no dead ends) |
| `tests/test_sigil_scoring.py` | 11 (scoring algorithm) |
| `tests/test_arcade.py` | 30 (calibration arcade, sigil strength) |
| `tests/test_atlas.py` | 38 (atlas build, treemap, determinism) |
| `tests/test_ride.py` | 28 (ride stats, engine, session) |
| `tests/test_contrasts.py` | 8 (mass scoring, exemplars) |
| `tests/test_embeddings.py` | 8 (embedding store) |
| `tests/test_indexer.py` | 11 (corpus ingestion) |
| **Total** | **244** |

### Commands

```bash
uv run sigiltree serve artifacts --port 8777   # local server
uv run pytest tests/ -x                         # run tests
fly deploy                                       # deploy to Fly.io
```

### Recent commits on master

```
(pending) Radar UX: taste on by default, taste_axis north, full reset, button sync
918938e Calibration walk: inline help panel with toggle button
b308297 Unified walk+slider: signed bias replaces two-step side+strength flow
```
