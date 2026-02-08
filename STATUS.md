# Sigil Tree - Project Status

Current state snapshot for session resumption. See [JOURNAL.md](JOURNAL.md) for build history, [BACKLOG.md](BACKLOG.md) for planned work.

## Current State (2026-02-07)

Phase 19 on `feature/detail-profile` branch. 244 tests pass. Server on port 8777.

### What just happened (this session)

1. **Categories integration** — Fixed `handle_atlas_sigil_scores` to allow categories-only mode (no walk sigil needed). Added `has_categories` flag, categories button highlight. Cache invalidation fix: `sigil_version` now includes category timestamp so JS cache busts on changes. 3 endpoint tests added.

2. **Sharper category gating** — Cubed weights (`w^3`) so low-weight categories contribute almost nothing while high weights dominate. Fixes user report that dialing one category to 100% had diluted visual effect. Reset button added to `/categories` page.

3. **Materialized emergent taste contrast** (backlog item 2) — The calibration walk's dot product is now a first-class contrast:
   - New module `sigiltree/taste_axis.py` with `compute_taste_coordinates` (per-image projection) and `materialize_taste_axis` (I/O wrapper)
   - Per-image taste coordinate for all 874 images
   - Z-summaries computed for all 5 atlas levels
   - Exemplars (top/bottom/median 12 images)
   - Components list documenting which sigil entries contribute
   - Persisted to `artifacts/sigils/taste_axis_{user_id}.json`
   - Merged into ride stats response (radar shows "taste" axis on hover)
   - New endpoint `/api/atlas/taste_axis` returns exemplars/quantiles/components
   - 16 new tests in `tests/test_taste_axis.py`

### What's live

- **Atlas viewer** — 5-level treemap of 874 images in 960 nodes
- **Calibration walk** (`/walk`) — Unified bias slider with arrow keys
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

### Recent commits on feature/detail-profile

```
5cf57a3 Category gate: cube weights for sharper filtering, add reset button
ddd2b08 Categories integration: allow categories-only mode, fix cache invalidation
b308297 Unified walk+slider: signed bias replaces two-step side+strength flow
```
