# Sigil Tree - Project Status

Current state snapshot for session resumption. See [JOURNAL.md](JOURNAL.md) for build history, [BACKLOG.md](BACKLOG.md) for planned work.

## Current State (2026-02-07)

Phase 18 in progress on `feature/detail-profile` branch. 228 tests pass.

### What's live

- **Atlas viewer** — 5-level treemap of 874 images in 960 nodes. Click to enter, back door to exit. No dead ends.
- **Calibration walk** (`/walk`) — Combined walk+slider UI. 17 bipolar contrasts shown as image pairs. Click left/right to select a side, then a slider (0-1) appears below to set preference strength. Enter to confirm, Space to skip. Produces sigil with per-contrast strengths in ~2 minutes. Progress pie shows all contrasts as a donut ring; slices fill amber (right) or blue (left) as you choose, gray for skipped. Current contrast name displayed at top.
- **Detail profile** (`/profile`) — Standalone slider page for post-walk fine-tuning. Sliders for each collapsed contrast. Adjust strength from 0 to 1 for each dimension. Exemplar thumbnails at each end. Saves profiled strengths back to sigil.
- **Category filter** (`/categories`) — radar chart with 11 unipolar semantic categories. Multiplicative gate on sigil scores: `final_score = walk_score * category_gate`.
- **Sigil overlay** — toggle in toolbar. High-scoring nodes brighten + golden halo. Sigil reorder: best nodes gravitate to center and grow.
- **Taste profile** — radar button in atlas toolbar (visible only after calibration). Shows spider chart of calibrated contrast preferences with direction-colored spokes.
- **Live at** https://sigilatlas.fly.dev/ (port 8777 locally)

### Combined calibration pipeline

```
1. Walk+Slider (combined UI)  → direction + strength per contrast
   - Click left/right to select side
   - Slider [0, 1] sets strength (default 0.5)
   - Skip = no entry (strength 0)
   - Strength stored directly in Choice → build_sigil uses it
2. Detail profile (/profile)  → optional post-walk fine-tuning
3. Taste projection           → weighted combination → emergent axis (future)
```

### Scoring pipeline

```
walk sigil (bipolar contrasts) --> walk_score per node
category prefs (radar handles)  --> category_gate per node
final_score = walk_score * category_gate
```

Walk-only: gate = 1.0. Categories-only: walk_score = 0.5. Neither: score = 0.5.

### Key files

| File | Role |
|---|---|
| `sigiltree/viewer_server.py` | Server + all HTML/CSS/JS inline |
| `sigiltree/sigil_scoring.py` | `compute_sigil_scores()`, `compute_category_gate()` |
| `sigiltree/walk.py` | Walk session logic (pure Python) |
| `sigiltree/arcade.py` | Sigil persistence, category prefs persistence, `update_sigil_strengths()` |
| `sigiltree/flythrough.py` | Flow graph: `compute_flow_graph`, `flow_in_direction` |
| `sigiltree/atlas.py` | Atlas build: clustering, treemap, tiles |
| `sigiltree/contrasts.py` | Contrast discovery, semantic scoring |
| `sigiltree/ride_stats.py` | Z-summaries, correlation matrix |

### Test files

| File | Tests |
|---|---|
| `tests/test_categories.py` | 18 (gate computation, combined scoring, persistence) |
| `tests/test_walk.py` | 47 (walk session, flip, PCA termination, partial sigil, step dict, taste sigil endpoint, profile endpoints, slider strength) |
| `tests/test_doors.py` | 30 (graph behavior, no dead ends) |
| `tests/test_sigil_scoring.py` | 11 (scoring algorithm) |
| `tests/test_arcade.py` | 26 (calibration arcade, sigil strength profiling, slider strength in build_sigil) |
| `tests/test_atlas.py` | 38 (atlas build, treemap, determinism) |
| `tests/test_ride.py` | 28 (ride stats, engine, session) |
| `tests/test_contrasts.py` | 8 (mass scoring, exemplars) |
| `tests/test_embeddings.py` | 8 (embedding store) |
| `tests/test_indexer.py` | 11 (corpus ingestion) |
| **Total** | **228** |

### Commands

```bash
uv run sigiltree serve artifacts --port 8777   # local server
uv run pytest tests/ -x                         # run tests
fly deploy                                       # deploy to Fly.io
```

### Atlas structure

- L0 (21 nodes) -> L1 (123) -> L2 (275) -> L3 (447) -> L4 (94 leaves)
- 874 images, 960 nodes, 5 levels
- Every node has doors: back + down + lateral (flow neighbors)
- Camera locked to viewport, click-only navigation
- Toolbar: Back, Home, Walk, Categories, Sigil, Profile, Taste Profile, Help

### Phase workflow

Each implementation phase follows this sequence:

1. Branch, implement, test
2. Merge to master, push, deploy
3. Verify in browser
4. Update STATUS.md
5. **Housekeeping** — update README if user-facing changes, check `.gitignore` for new artifact patterns, remove stale files, run test count

### Artifacts

```
artifacts/
  catalog.db                          # 906 images
  thumbnails/{64,128,256,512}/        # multi-resolution thumbs
  embeddings/{clip,dino,texture}/     # 3 embedding families
  contrasts/
    contrast_library.json             # 36 contrasts (v1_00ed2561)
    coordinates.json                  # per-image scalar coordinates
  atlas/
    manifest.json                     # 5-level atlas
    root/meta.json                    # root node (level -1)
    level{0-4}/meta.json + tiles/     # per-level nodes and montage tiles
    node_zsummaries.json              # per-node z-scores for all contrasts
    contrast_correlations.json        # 36x36 Pearson matrix
  sigils/
    sigil_{user_id}.json              # walk-derived taste sigil (profiled strengths after /profile)
    categories_{user_id}.json         # radar-based category preferences
```
