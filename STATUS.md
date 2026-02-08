# Sigil Tree - Project Status

Current state snapshot for session resumption. See [JOURNAL.md](JOURNAL.md) for build history, [BACKLOG.md](BACKLOG.md) for planned work.

## Current State (2026-02-07)

Phase 20 on `master` branch. 244 tests pass. Server on port 8777.

### What just happened (this session)

4. **Calibration onboarding text** (backlog item 4) — Added intro overlay to `/walk` page:
   - Shows on first visit: explains what calibration does, how pairs represent visual contrasts, how to use slider
   - Controls hint: arrow keys, slider, Space to skip, Esc to exit
   - Dismisses on click or any keypress, then starts the walk
   - Skipped on return visits via sessionStorage (`sigilatlas_walk_intro_seen`)
   - Styled to match atlas help overlay pattern (dark overlay, centered card, `.intro-box`)

### Previous session

1. **Categories integration** — categories-only mode, cache invalidation fix, 3 endpoint tests.
2. **Sharper category gating** — cubed weights, reset button.
3. **Materialized emergent taste contrast** (backlog item 2) — first-class taste axis with per-image coordinates, z-summaries, exemplars, radar integration, `/api/atlas/taste_axis` endpoint, 16 tests.

### What's live

- **Atlas viewer** — 5-level treemap of 874 images in 960 nodes
- **Calibration walk** (`/walk`) — Unified bias slider with arrow keys, onboarding intro overlay on first visit
- **Category filter** (`/categories`) — radar chart with 11 categories, reset button, cubed weights for sharp gating
- **Sigil overlay** — toggle in toolbar. Dimming + golden halo. Categories button highlighted when filter active.
- **Taste profile** — radar in atlas toolbar, now includes "taste" axis
- **Taste axis** — materialized emergent contrast with per-image coordinates, z-summaries, exemplars
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
| `sigiltree/arcade.py` | Sigil persistence, category prefs, taste axis persistence |
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
(pending) Calibration onboarding: intro overlay on first walk visit
b308297 Unified walk+slider: signed bias replaces two-step side+strength flow
```
