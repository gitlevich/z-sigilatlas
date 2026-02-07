# Sigil Tree - Project Status

## Current Phase: Phase 13 — Categorical Calibration (COMPLETE, 2026-02-07)

### What just happened — Radar-based category filter

Branch `phase13-category-radar`. The 11 unipolar semantic categories (portrait, landscape, architecture,
etc.) that the binary walk excludes now have a radar chart UI for direct preference setting.

**Scoring model:** Categories act as a multiplicative gate on sigil scores.
`final_score = walk_score * category_gate`. Walk says "how good is this node for your taste."
Categories say "is this the kind of thing you want to see at all." All handles at center (0) =
everything dimmed. Pull handles outward = those categories brighten proportionally.

**New files:**
- `tests/test_categories.py` — 18 tests (gate computation, combined scoring, persistence)

**Modified files:**
- `sigiltree/arcade.py` — Added `save_category_prefs()` + `load_category_prefs()` for separate persistence
- `sigiltree/sigil_scoring.py` — Added `compute_category_gate()`, modified `compute_sigil_scores()` with optional `category_weights` param
- `sigiltree/viewer_server.py` — 3 new routes (`/categories`, `/api/categories/data`, `/api/categories/save`), 3 new handlers, `CATEGORIES_HTML` radar chart page, toolbar radar button, help entry, modified `handle_atlas_sigil_scores` to load category prefs

**UI:** Canvas-based radar chart with 11 axes, draggable handles, green polygon fill, percentage labels,
exemplar thumbnails on hover. Save redirects to `/atlas?sigil=1`. Pre-fills from saved weights.

**Persistence:** `artifacts/sigils/categories_{user_id}.json` — separate from walk sigil.

All 199 tests pass (181 existing + 18 new).

### Previous — Phase 12: Sigil reorder implementation

Branch `phase12-sigil-reorder`. All changes in `sigiltree/viewer_server.py` (client-side JS only).

When sigil is toggled ON, the treemap physically rearranges: high-scoring nodes (aligned with taste)
gravitate to center and grow larger; low-scoring nodes shrink and push to edges. Toggle OFF restores
the original layout exactly.

**New functions:** `saveOriginalLayout()`, `restoreOriginalLayout()`, `layoutWithSigil()`, `applySigilLayout()`
**Weight formula:** `weight = baseSize * (0.5 + score)` where score is rank-stretched [0,1]. 3:1 ratio best-to-worst.
**Modified:** `fetchSigilScores()`, `toggleSigil()`, `enterNode()`, `exitToParent()`, `popToLevel()`, `goHome()`

All 181 tests pass. No Python changes.

### Previous — Dead flythrough code removal

Removed ~880 lines of dead flythrough code across 4 files:
- `sigiltree/flythrough.py` — stripped to flow-graph functions only (`compute_flow_graph`, `flow_in_direction`, helpers). Removed: `FlythroughSession`, `infer_preferences`, `flythrough_to_sigil`, `_empty_sigil`, `MIN_VISITS`.
- `sigiltree/viewer_server.py` — removed: flythrough handler, route, app state, CSS, HTML elements, JS globals, 7 JS functions (toggleFlythrough through showFlythroughToast), drawing highlight, debug overlay references, `recordFlythroughVisit()` call in enterNode.
- `tests/test_flythrough.py` — deleted entirely (454 lines, 39 tests).
- `tests/test_ride.py` — removed 2 flythrough endpoint tests.
- All 181 tests pass. Committed `847bcf6`, pushed, deployed.

### Previous — Calibration Walk + UI polish (2026-02-07)

Walk UI:
- Exit button (top-left) + Escape key to return to atlas
- Obvious controls: arrow key hints, `[Space]` on skip button, hover highlights whole column
- Flash animation on mosaic columns confirms choice (250ms blue/orange)

Atlas UI:
- Toolbar: Back, Home, Calibrate (⚖), Sigil (SVG fingerprint), Help (?)
- Buttons 44px, icons 20px
- Help overlay: Esc-dismissable, kept in sync with toolbar changes
- goHome() is instant (pop all to root)
- Server port: always 8777 locally

### Previous — Calibration Walk implementation

**Goal**: Resurrect the calibration mechanism as a clean, focused experience. Two image mosaics side by side (extreme low vs extreme high exemplars of a contrast). User picks left, right, or skip. No contrast names shown. Only bipolar contrasts, with PCA as conditional extension. ~17-26 steps, under 2 minutes.

**New file: `sigiltree/walk.py`**:
- `classify_contrast(name)` — classifies as 'bipolar', 'unipolar', or 'pca' by naming convention
- `filter_walk_contrasts(library)` — filters to 17 bipolars + 9 PCA, excludes 11 unipolar categories
- `WalkStep` dataclass — `left_ids`, `right_ids`, `flipped` flag (randomized left/right assignment)
- `WalkSession` — manages walk flow: bipolar phase -> repeats -> conditional PCA
- Reuses `arcade.py`'s `Choice`, `build_sigil()`, `save_sigil()` — no modifications to arcade.py
- Left/right randomization prevents positional bias: 50% chance each step swaps low/high sides
- PCA early termination: if >= 8 bipolars collapsed, skip PCA entirely

**Modified: `sigiltree/viewer_server.py`**:
- New route: `GET /walk` serves `WALK_HTML` (full-screen calibration page)
- New endpoints: `POST /api/walk/start`, `POST /api/walk/choose`
- `WALK_HTML`: dark full-screen page, two 3x2 image grids side by side, skip button, progress dots
- Keyboard: ArrowLeft/A, ArrowRight/D, Space/ArrowUp for skip
- On completion: "Preferences recorded" overlay -> redirect to `/atlas?sigil=1`
- Atlas toolbar: new "Calibrate" button between Explore and Sigil
- Atlas init: auto-activates sigil overlay when `?sigil=1` param present

**New tests: `tests/test_walk.py`** — 27 tests:
- TestContrastClassification (5): perceptual/color/semantic-bipolar/unipolar/pca
- TestFilterWalkContrasts (4): excludes unipolars, sorted by mass, correct counts
- TestWalkSession (5): bipolars-only schedule, no contrast name exposed, exemplar count, progress
- TestWalkSkip (2): all skips -> 0 collapsed, maps to center internally
- TestWalkConsistency (2): consistent choices -> full strength
- TestPCAEarlyTermination (3): many collapsed -> skip PCA, few -> extend, PCA after bipolars
- TestWalkRepeats (2): different exemplars, fraction bounded
- TestLeftRightFlip (2): flipped direction de-flipped correctly
- TestWalkCompletion (2): returns sigil, reports complete

**Test results**: 215/215 pass (188 existing + 27 new)

**Browser verification**:
- `/walk` renders two mosaics with 6 images each, obvious visual contrast
- Click advances to next step, progress dots update
- Skip button works
- No contrast names visible anywhere
- Atlas toolbar shows 6 buttons: Back, Home, Explore, Calibrate, Sigil, Help
- Calibrate button navigates to `/walk`

**Files changed**:
- `sigiltree/walk.py` — NEW: walk session logic
- `sigiltree/viewer_server.py` — walk routes, handlers, WALK_HTML, toolbar button, sigil auto-activate
- `tests/test_walk.py` — NEW: 27 tests

### Previous session (2026-02-06) — Unlimited depth + hierarchy-first viewer

**Problem**: n_014 (112 images, largest L0 neighborhood) appeared as a wall of undifferentiated images despite having 10 well-defined sub-clusters. Two root causes:

1. **`max_levels=4` cap**: Atlas artificially stopped at 4 levels. With 874 images, the tree needed 5 levels to reach natural leaf termination.
2. **View flattened members**: When entering any node, the viewer showed ALL individual member images mixed with child doors. The clustering hierarchy was invisible.

**Fix 1 — atlas.py: unlimited depth**:
- `build_atlas_recursive()` default changed from `max_levels=4` to `max_levels=None` (unlimited).
- Loop changed from `for lvl in range(1, max_levels)` to `while True` with `break` when cap reached or no splittable nodes remain.
- Natural stopping: `MIN_SPLIT_SIZE=4` + Louvain failure drive termination.
- CLI `--levels` default changed to `None` (unlimited). Passing `--levels N` still caps depth.
- Tests still pass — they pass explicit `max_levels` values.

**Fix 2 — viewer_server.py: show children, not members, for non-leaf nodes**:
- `enterNode()` now checks `hasDown` (whether node has child doors).
- If `hasDown`: show sub-neighborhoods as primary content (children ARE the view).
- If no children + has members: show individual member images (leaf behavior).
- Members only appear at leaf nodes where there's nothing deeper to show.

**Rebuild results**:
- Atlas: 5 levels (was 4), 960 nodes (was 865), stopped naturally at level 4 (all 94 L4 nodes are leaves).
- Ride stats rebuilt for 5 levels.
- All 188 tests pass.

**Files changed**:
- `sigiltree/atlas.py` — `build_atlas_recursive()` signature + loop
- `sigiltree/cli.py` — `--levels` default + dispatch logic
- `sigiltree/viewer_server.py` — `enterNode()` content tile selection (JS)

### Previous: Treemap layout restored at every level
- **Root cause**: `layoutAsGrid()` (commit a836289) replaced treemap rects with a uniform justified-row grid, destroying the spatial organization by similarity.
- **Fix**: Ported squarified treemap algorithm (Bruls-Huizing-van Wijk 2000) from `atlas.py` to client-side JS. New `squarifiedTreemap()`, `_squarify()`, `_worstRatio()` + `layoutAsTreemap()` wrapper.
- **Root init**: Uses `meta.nodes` directly (they carry pre-computed treemap rects from atlas build).
- **enterNode()**: All sublevel views (down + back + lateral doors, members, self-tiles) now use `layoutAsTreemap()` with `size` as weight. Area proportional to image count, spatial adjacency from Fiedler/similarity ordering.
- **Cover-fit rendering**: Montage mosaics use `Math.max` scale (fills cell, center-crops excess — invisible on mosaic grids). Individual photos (`door_type === 'member'`) use `Math.min` scale (contain-fit, no cropping).
- **Simplified door indicators**: Colored borders removed. Small white arrow icons only: up (back), down (enter deeper), right (lateral peer). Uniform visual treatment — all sigils look the same, just their montage + tiny arrow.
- All 184 tests pass. No Python changes, no atlas rebuild needed.
- `layoutAsGrid()` kept as dead code.

### Previous: Zero-waste montage tiles (kept)
- `render_neighborhood_tile()` uses `_partition_into_rows(n)` — zero wasted cells for any N.
- All tiles 1024x1024 square. Cover-fit handles cell aspect mismatch at draw time.
- Tile cache TILE_CACHE_MAX = 50, LRU eviction.

### Previous: Individual image "room" view (DELETED)
- `layoutImageRoom()` was deleted — it wasted 12% of screen on a door column.
- Replaced by unified grid: main image is a weighted tile in `layoutAsGrid`.

### Key files
- `sigiltree/viewer_server.py` — ALL code (server + HTML/CSS/JS inline)
- `sigiltree/flythrough.py` — flow graph only: `compute_flow_graph`, `flow_in_direction` (pure Python, no I/O)
- `sigiltree/walk.py` — calibration walk session logic (pure Python)
- `tests/test_doors.py` — 30 graph behavior tests
- `tests/test_walk.py` — 27 walk tests
- Server startup: `uv run sigiltree serve artifacts --port 8777`
- Deploy: `fly deploy` from project root

### Architecture
- aiohttp server, single file, all JS/CSS inline in raw Python string
- Atlas: L0 (21) → L1 (123) → L2 (275) → L3 (447) → L4 (94 leaves). 874 images, 960 nodes.
- Every node is a sigil with doors (back/down/lateral). No dead ends.
- Doors endpoint: `GET /api/atlas/node/{id}/doors?level=N&from_node=X&from_level=Y`
- Tile images: montage composites at higher levels, single images at leaf level
- Camera locked to viewport, no pan/zoom/scroll, click-only navigation
- Floating toolbar: Back, Home, Calibrate, Sigil, Help
- Justified row layout: `layoutAsGrid()` respects each tile's aspect ratio
- Contain-fit rendering: `Math.min` scale, full image, no cropping

### Backlog
1. **Materialize the emergent taste contrast** — the calibration walk discovers coefficients of a personal good-bad axis in contrast space. Currently computed transiently as a dot product during scoring. Make it a first-class contrast: own z-summary per node, own exemplars (top-N / bottom-N images), own name. The individual contrasts are scaffolding; the emergent one is the signal. This is dimensionality reduction from N contrasts to one personally meaningful axis.
2. **Live sigil during calibration** — show taste sigil updating in real-time during walk (experimental featurette)
3. **README / landing page** — explain the "neighborhood is a sigil" vision
4. **Evolve the spec** — refine the specification to match what has been built. The spec should evolve as the product does, becoming a sigil of this application: a sigil that, when worn by an LLM, will get it to design an app to this spec within the resolution of the spec. Our secondary deliverable is the evolved spec: the sigil of sigilatlas.

## Phase 11: The Sigil Graph — No Leaves, No Dead Ends (COMPLETE)

### Conceptual shift
- "The node IS a sigil" — self-similar structure at every level
- Every node shows **doors**: back (where you came from), down (children), lateral (flow-neighbors)
- No leaf nodes exist in the UX — the filmstrip/member panel is gone
- No keyboard navigation — everything is click-based ("joystick metaphor")
- Floating toolbar replaces keyboard shortcuts: Back, Home, Explore, Sigil, Help
- Home button replays path in reverse with animation

### Files modified
- `sigiltree/viewer_server.py` — new `/api/atlas/node/{id}/doors` endpoint, rewrote `enterNode()` to use doors API, removed member panel, keyboard handlers, flow d-pad, added toolbar + touch support

### What was removed
- `showMembers()` / `closeMembers()` / `showingMembers` / `currentMemberNode`
- `#neighborhood-panel` HTML/CSS (filmstrip)
- All keyboard navigation (WASD, arrows, ESC, R, G, H, Enter/Space)
- `keysDown`, `DRIVE_KEYS`, `updateKeyboardDriving()`
- `flowToNeighbor()` (replaced by click-to-enter lateral door tiles)
- `#help-badge` (help moved to toolbar)

### What was added
- `GET /api/atlas/node/{node_id}/doors?level=N&from_node=X` — returns back + down + lateral doors
- `enterNode()` now fetches doors and displays them as a grid of clickable tiles
- `layoutAsGrid(doors)` — arranges doors in a square grid filling [0,1]x[0,1]
- Door type visual indicators: back door (return arrow + dim border), lateral door (blue border)
- `#toolbar` — 5 floating buttons: Back, Home, Explore, Sigil, Help
- `goHome()` — animated reverse path back to root (pop one level every 300ms)
- `toggleSigil()` — toolbar button for sigil overlay
- Touch handlers (tap-to-enter) for mobile
- Updated help overlay with click/toolbar descriptions

### Camera lock (latest)
- Camera is locked to fill 100% of the viewport for every frame
- Zero padding: `fitToRect(0, 0, 1, 1, cw, ch, 0)`
- Disabled: mouse drag panning, wheel scroll/zoom, touch panning
- Removed: `camVel`, `CAM_LERP`, `PAN_FRICTION`, `ZOOM_FRICTION`, `ZOOM_SENSITIVITY`, `CAM_POS_THRESHOLD`, `CAM_ZOOM_THRESHOLD`, `dragging`, `dragStart`, `camStart`, `lastMousePos`
- `setCameraTarget()` now snaps immediately (delegates to `setCameraImmediate()`)
- `updateCamera()` is a no-op (cam = camTarget, always)
- `isMoving()` always returns false (no animation loop)
- `resize()` refits camera on window resize
- All navigation functions (`enterNode`, `exitToParent`, `popToLevel`, `goHome`) use `fitOverview()` to snap camera

### Tests
- 152/152 pass (no Python logic tests broken; JS-only changes in viewer)

### Browser verification results
- Atlas loads at L0 with all neighborhoods visible, filling viewport
- Click any tile -> enters sigil, shows doors (down + lateral) as grid tiles, fills viewport
- At former leaf nodes: lateral doors appear, click to continue navigating (no dead end)
- Back button pops one level (verified)
- Home button animates back to root from any depth (verified)
- Breadcrumb shows navigation path and is clickable
- Radar chart shows on hover at all levels
- Minimap functional
- No JS errors in console
- Toolbar buttons all visible and functional (Back, Home, Explore, Sigil, Help)
- Door type indicators visible: blue border on lateral doors, return arrow on back door
- Camera locked: wheel event has no effect (verified via JS test)
- No drag panning, no zoom, no scroll — only click-to-enter
- 152/152 tests pass

### Post-Phase 11 fixes

#### Graph behavior tests (test_doors.py) — 30 tests
- Built comprehensive 4-level atlas fixture (L0: 4, L1: 8, L2: 16, L3: 32 leaves, 128 images)
- TestNoDeadEnds (5), TestBackDoor (5), TestDownDoors (3), TestLateralDoors (4)
- TestGraphNavigability (4), TestDoorStructure (4), TestFlowGraphProperties (5)
- All 184 tests pass (154 existing + 30 new)

#### Browser performance fix: LRU tile eviction
- Root cause: tile cache never evicted, 1024px tiles decode to ~2.7MB RGBA each
- After 53 tiles: 138MB decoded memory, causing browser GC jank
- Fix: `TILE_CACHE_MAX = 30`, `evictTiles()` evicts oldest half of non-visible tiles
- Result: memory stabilizes at ~54MB (22 tiles) after 7+ door navigations
- enterNode timing: consistent 53ms per click

#### Door type visual indicators — redesigned
- **Back door**: warm gradient band at top + upward arrow icon (previously broken Unicode escape)
- **Down door**: green gradient band at bottom + downward arrow icon (previously no indicator)
- **Lateral door**: blue accent bar on left edge (previously thin blue border, hard to see)

#### Click delay fix: missing scheduleFrame
- Root cause: `setCameraImmediate()` set camera without scheduling a redraw
- `enterNode()` -> `fitOverview()` -> `setCameraImmediate()` — no `scheduleFrame()` call
- Canvas only redrawed when mousemove triggered `scheduleFrame()`
- User symptom: "click waits, but click-and-move loads right away"
- Fix: added `scheduleFrame()` at end of `setCameraImmediate()`

#### Image presentation: justified row layout with aspect-ratio-aware cells
- Principle: NO CROPPING. This app is about images — show them in their natural proportions.
- Server-side: `_enrich_tile_dimensions()` reads tile image headers at cache time, adds `tile_w`/`tile_h` to each node.
- Client-side: `layoutAsGrid()` replaced with justified row algorithm:
  - Each tile's aspect ratio (tile_w/tile_h) determines its cell width relative to row height.
  - Rows fill the full viewport width. Items per row chosen to balance row heights.
  - World coordinates are [0, 0, viewAspect, totalHeight]; `fitOverview()` computes bounds from actual nodes.
- Rendering: contain-fit (`Math.min` scale) — full image, centered, dark background only if tiny mismatch.
- Result: Wide images are wide, tall images are tall, montages fill their natural shape. Zero cropping.

#### Deployments
- First deploy to Fly.io: https://sigilatlas.fly.dev/ (Phase 11 + performance fixes + door indicators + click fix)
- Second deploy: grid layout fix (viewport-filling tiles, contain-fit)
- Third deploy: viewport-proportional grid + contain-fit rendering
- Fourth deploy: justified row layout with aspect-ratio-aware cells, zero cropping
- Fifth deploy: individual image "room" view (image fills screen + door strip on left)

### Deferred
- Update README / landing page

## Phase 1: Corpus ingestion and artifacts (ACCEPTED)

### Files
- `sigiltree/db.py` - SQLite catalog
- `sigiltree/indexer.py` - corpus scanner, checksums, thumbnails
- `sigiltree/cli.py` - CLI (`index`, `embed`, `nn`, `serve`)
- `sigiltree/viewer_server.py` - aiohttp server (grid viewer + NN explorer)
- `tests/test_indexer.py` - 11 tests

### Artifacts
- `artifacts/catalog.db` - 906 images
- `artifacts/thumbnails/{64,128,256,512}/`

## Phase 2: Embedding families (ACCEPTED)

### Files created/modified
- `sigiltree/embeddings.py` - EmbeddingStore (mmap numpy), ClipEmbedder, DinoEmbedder, TextureEmbedder, nearest_neighbors()
- `sigiltree/cli.py` - added `embed` and `nn` commands
- `sigiltree/viewer_server.py` - added /nn page, /api/nn, /api/random_id endpoints
- `tests/test_embeddings.py` - 8 tests (store CRUD, incremental, mmap, texture shape/discrimination)

### Artifacts
- `artifacts/embeddings/clip/` - 906 x 512 vectors (CLIP ViT-B-32)
- `artifacts/embeddings/dino/` - 906 x 384 vectors (DINOv2 ViT-S/14)
- `artifacts/embeddings/texture/` - 906 x 97 vectors (multiscale Laplacian+FFT)

### Verification results
- All 906 images embedded in all 3 families (0 errors)
- First run: CLIP 24.5s, DINO 24.7s, texture 38.0s (on MPS)
- Second run: 0 computed, all up to date (incremental confirmed)
- NN query latency: 0.2-0.5ms for k=20 (well under 250ms bound)
- Qualitative spot checks (3 random images x 3 families):
  - CLIP: semantic neighbors share content (overhead views, lit buildings, windows)
  - DINO: structural neighbors share composition (grids, diagonals, spatial layout)
  - Texture: texture neighbors share grain/scale/color profile
- 19/19 tests pass (11 indexer + 8 embedding)

## Phase 3: Contrast discovery and selection (ACCEPTED)

### Files created/modified
- `sigiltree/contrasts.py` - contrast discovery (perceptual, semantic, emergent PCA), mass/stability selection, exemplars
- `sigiltree/cli.py` - added `contrasts` command
- `sigiltree/viewer_server.py` - added /contrasts page, /api/contrasts endpoint
- `tests/test_contrasts.py` - 8 tests (mass scoring, exemplar structure/overlap, perceptual metrics)

### Artifacts
- `artifacts/contrasts/contrast_library.json` - version v1_00ed2561, 36 contrasts
- `artifacts/contrasts/coordinates.json` - per-image scalar coordinates for all 36 contrasts

### Contrast library summary
- 43 candidates evaluated: 10 perceptual + 18 semantic + 15 emergent (PCA top-5 x 3 families)
- Semantic sources: 11 unipolar categories (multi-term averaged centroids) + 7 bipolar contrasts
- 7 PCA dropped for stability < 0.9 (clip_2, clip_3, dino_3, dino_4, texture_2-4)
- 36 selected: within 20-60 target range
- All kept contrasts have stability >= 0.9 (perceptual/semantic = 1.0, PCA >= 0.948)
- Top 10 by mass: sharpness, red_dominance, pca_dino_0, blue_dominance, pca_clip_0, pca_dino_1, pca_clip_1, pca_dino_2, green_dominance, brightness

### Verification results
- All 10 top contrasts visually verified: LOW vs HIGH exemplar mosaics obviously distinct
- 27/27 tests pass (11 indexer + 8 embedding + 8 contrast)
- Incremental rebuild: re-running contrasts on unchanged embeddings reproduces same library
- Invariant probe: no sigil file created during browsing (vacuously true)

## Phase 4: Calibration arcade (ACCEPTED)

### Files created/modified
- `sigiltree/arcade.py` - ArcadeSession, DoorTriplet, Choice, Sigil, repeat scheduling, sigil construction
- `sigiltree/viewer_server.py` - added /calibrate page, /api/arcade/* endpoints, /api/sigil
- `tests/test_arcade.py` - 16 tests (session, center/left/right, cooling, repeats, budget, gap, persistence)

### Artifacts
- `artifacts/sigils/sigil_<user>.json` - per-user sigils tied to contrast_library_version

### Design
- 36 contrasts presented in mass-descending order
- Repeat budget: 20% of total, min gap 5, max 2 per contrast
- Repeats biased toward turned (left/right) and high-mass contrasts; centered at most once
- Inconsistent repeats: equal disagreement drops, majority wins with decayed strength
- Center records nothing; only left/right produce sigil entries

### Bugfix: exemplar selection
- User spotted sem_portrait HIGH showing no actual portraits, sem_street similarly wrong
- Root cause: `_compute_exemplars` randomly sampled from top/bottom 20% band, which for low-mass semantic contrasts was essentially noise
- Fix: changed to pick the actual most extreme n_exemplars by score rank (sorted argsort)
- After fix: sem_portrait HIGH shows genuine portrait faces, all contrasts verified

### Enhancement: multi-term CLIP semantic scoring
- Replaced single pos/neg prompt pairs with multi-term averaged centroids from user taxonomy
- Unipolar categories: portrait (7 terms), street (17 terms), architecture (7 terms), etc.
- Bipolar contrasts: bw_vs_color, interior_vs_exterior, people_vs_empty, abstract_vs_representational, closeup_vs_wide, natural_vs_manmade, simple_vs_complex
- Score ranges dramatically wider: portrait [0.08, 0.29], street [0.05, 0.33]
- Visual verification: sem_portrait HIGH = actual faces, sem_street HIGH = crosswalks/pedestrians, sem_bw_vs_color LOW = B&W photos / HIGH = saturated color

### Verification results
- 43/43 tests pass (11 indexer + 8 embedding + 8 contrast + 16 arcade)
- Automated full pass: 45 choices, 0.0s (well under 3 min)
- Budget: 45 <= 80 prompts
- Sparse sigil: 24 collapsed < 45 total choices
- Center-only contrasts: 0 collapsed (confirmed)
- Invariant §4.3: no sigil for browse-only user (404)
- Invariant §4.4: all-center session produces 0 collapsed entries
- UI live at http://127.0.0.1:8777/calibrate with keyboard controls
- All semantic contrasts visually verified as obviously distinct

## Phase 5: Atlas level 0 (ACCEPTED)

### Files created/modified
- `sigiltree/atlas.py` - fused neighbor graph, Louvain clustering, Fiedler ordering, squarified treemap, tile rendering, determinism verification
- `sigiltree/cli.py` - added `atlas` command with `--levels` and `--seed`
- `sigiltree/viewer_server.py` - added /atlas page, /api/atlas/meta, /api/atlas/neighborhood/{id}, /atlas_tiles/ endpoints, canvas-based pan/zoom viewer
- `tests/test_atlas.py` - 22 tests (treemap, fused graph, clustering, ordering, representatives, end-to-end, determinism, invariants)

### Algorithm
- Fused neighbor graph: per-family k=20 kNN (cosine), keep edges with >= 2/3 family votes
- Clustering: Louvain community detection (networkx), resolution binary-searched to target 20-40 neighborhoods
- Ordering: Fiedler vector (second eigenvector of graph Laplacian via scipy.sparse.linalg.eigsh)
- Layout: squarified treemap (Bruls-Huizing-van Wijk 2000), neighborhoods ordered by mean Fiedler value
- Tiles: 64px thumbnail collages rendered per neighborhood, sorted by Fiedler value for consistency

### Artifacts
- `artifacts/atlas/level0/meta.json` - build atlas_v1_cfa061e0, 22 neighborhoods
- `artifacts/atlas/level0/tiles/` - 22 neighborhood tile JPEGs

### Atlas summary
- 906 images in 22 neighborhoods (range: 5-69 images per neighborhood)
- Build time: 1.0s
- 14,015 fused edges (>= 2 family votes)
- Louvain resolution: 2.575
- Rectangles tile the frame exactly (total area = 1.0)
- No new dependencies required (uses numpy, scipy, scikit-learn, networkx, Pillow)

### Verification results
- 65/65 tests pass (11 indexer + 8 embedding + 8 contrast + 16 arcade + 22 atlas)
- Determinism: IoU = 1.0 for all 22 rects, Kendall tau = 1.0
- Rebuild produces identical meta.json
- Neighborhoods visually coherent:
  - n_017: portraits/people/animals (55 images)
  - n_021: Bali landscapes/rice terraces (23 images)
  - Top rows: cityscapes, skylines, night city scenes
  - Bottom: nature, green fields, botanical subjects
- Viewer: canvas-based pan/zoom with mouse drag and scroll wheel
- Click enters neighborhood (camera anchors, member grid appears)
- ESC returns to overview (instant)
- Invariant §4.1: click anchors camera to neighborhood rect (verified)
- Invariant §4.2: ESC returns to overview (trivially instant, single frame)
- Invariant §4.3: atlas build and navigation do not touch sigil (test passes)
- Invariant §4.4: still passing (arcade tests unchanged)
- Invariant §4.5: ESC from any depth returns to full atlas view (1 action)
- UI live at http://127.0.0.1:8777/atlas

## Phase 6: Multiscale atlas pyramid (ACCEPTED)

### Files created/modified
- `sigiltree/atlas.py` - extended AtlasNode (level, parent_id, child_ids, is_leaf), build_sublevel_graph, compute_target_range, build_atlas_recursive, _build_level_nodes, _save_level_meta, load_atlas_manifest, get_children, _cover_crop, _best_thumb_dir, render_neighborhood_tile rewrite
- `sigiltree/cli.py` - dispatch to build_atlas_recursive when --levels > 1
- `sigiltree/viewer_server.py` - added /api/atlas/manifest, /api/atlas/level/{L}/meta, /api/atlas/node/{id}/children endpoints; updated tile handler for multi-level paths; rewrote ATLAS_VIEWER_HTML with level stack, minimap, debug overlay
- `tests/test_atlas.py` - 16 new tests (38 total atlas tests, 81 total)

### Algorithm
- Recursive level-by-level build: each non-leaf node at level L is split into children at level L+1
- Sublevel graph: rebuild local fused kNN (k=min(10,n-1)) within image subset; fully connected for n < 6
- Cluster target: max(2, sqrt(n)), capped at 12
- Louvain fallback: if 1 cluster -> split by Fiedler median
- Children rects in parent coordinate space: squarified_treemap(sizes, rect=parent.rect)
- Leaf criteria: size < MIN_SPLIT_SIZE (4) or at max level
- Exit is stack pop (no network request): guarantees §4.2 at any depth

### Tile rendering improvements
- Replaced fixed-thumb-size grid with adaptive grid computed from image count
- Added `_cover_crop()`: scale-to-cover + center-crop eliminates distortion
- Added `_best_thumb_dir()`: always uses highest-resolution thumbnails (512px)
- Bumped tile_long from 512 to 1024 for crisp display at all zoom levels
- Cell aspect ratio constrained to max 2:1 (no skinny unrecognizable strips)
- No image repetition: each image placed exactly once, waste cells left as background
- Last column/row absorbs integer-division remainder pixels (no edge gaps)

### Artifacts
- `artifacts/atlas/manifest.json` - build atlas_v2_8bce78f3, 4 levels
- `artifacts/atlas/level0/` - 22 nodes, 22 tiles
- `artifacts/atlas/level1/` - 130 nodes (24 leaves), 130 tiles
- `artifacts/atlas/level2/` - 276 nodes (151 leaves), 276 tiles
- `artifacts/atlas/level3/` - 485 nodes (460 leaves), 485 tiles
- Total: 913 nodes across 4 levels

### Atlas pyramid summary
- 906 images, 913 total nodes, 4 levels
- Build time: ~14s (seed=42, 1024px tiles)
- Level 0: 22 coarse neighborhoods (0 leaves)
- Level 1: 130 nodes (24 leaves)
- Level 2: 276 nodes (151 leaves)
- Level 3: 485 nodes (460 leaves)
- No new dependencies

### Viewer features
- Level stack navigation: click non-leaf -> enterNode (fetch children, zoom to parent rect)
- Click leaf -> show member images panel
- ESC -> exitToParent (stack pop, instant, no network request)
- Home/H -> pop all to root
- D key -> debug overlay (level, node_id, parent_id, camera, stack depth)
- Minimap: 120x120 canvas showing level-0 overview with viewport and active parent rect
- Breadcrumb: clickable path from root to current level
- Trackpad: two-finger scroll = pan, pinch = zoom

### Verification results
- 81/81 tests pass (11 indexer + 8 embedding + 8 contrast + 16 arcade + 38 atlas)
- 16 new atlas tests: sublevel graph, target range, custom rect treemap, 2-level build, 4-level build, child rects partition parent, children partition parent images, child images subset of parent, all images at every level, leaf node criteria, recursive determinism, children inside parent rect, no sigil on recursive build, manifest synthesis, get_children
- Level 0 determinism: IoU = 1.0, Kendall tau = 1.0
- All 4 level directories + tiles verified present
- API endpoints tested: /api/atlas/manifest, /api/atlas/level/1/meta, /api/atlas/node/n_000/children
- Invariant §4.1: enter anchors camera to parent rect (verified)
- Invariant §4.2: exit is stack pop, instant at any depth (verified)
- Invariant §4.3: no sigil created during build or navigation (test passes)
- Invariant §4.5: ESC returns up one level, Home returns to root
- UI live at http://127.0.0.1:8777/atlas

## Phase 7: Driving (continuous navigation) (ACCEPTED)

### Files modified
- `sigiltree/viewer_server.py` - rewrote ATLAS_VIEWER_HTML JavaScript: replaced event-driven draw() with requestAnimationFrame loop, added camera interpolation, WASD/Arrow driving, velocity-based wheel zoom, animated transitions, tile prefetching, minimap click, Enter/Space node entry, enhanced debug overlay

### Architecture changes (JS only, no Python changes)
- **Animation loop**: `scheduleFrame()` / `tick()` with self-terminating rAF; only runs while moving
- **Camera model**: dual state `cam` (current) + `camTarget` (desired) with exponential lerp (CAM_LERP=0.15)
- **Velocity system**: `camVel` {x, y, z} with per-axis friction; wheel and pan accumulate impulses
- **Keyboard driving**: `keysDown` Set tracks held keys; WASD/Arrows pan, Q/E zoom continuously
- **Animated transitions**: enterNode/exitToParent use `setCameraTarget()` for smooth zoom
- **Direct manipulation**: mouse drag bypasses lerp, sets cam+camTarget directly for zero-latency feel
- **Tile prefetching**: every 10 frames, scan 1.5x viewport bounds, ensureTile for uncached nodes
- **Minimap click**: click handler maps minimap coords to world position, sets camTarget
- **Hovered node tracking**: mousemove updates `hoveredNode` for Enter/Space keyboard entry

### Key bindings (changed)
- W/Up, S/Down, A/Left, D/Right: continuous pan
- Q/E: continuous zoom in/out
- Escape: exit to parent (animated)
- Home/H: pop to root (animated)
- Enter/Space: enter hovered node
- Backtick/F3: toggle debug overlay (moved from D)
- D key: now drives right (was debug toggle)

### Constants
- CAM_LERP = 0.15, DRIVE_SPEED = 8, ZOOM_KEY_FACTOR = 1.02
- ZOOM_SENSITIVITY = 0.003, ZOOM_FRICTION = 0.85, PAN_FRICTION = 0.88
- PREFETCH_MARGIN = 1.5, PREFETCH_INTERVAL = 10 frames

### Debug overlay enhancements
- FPS counter
- Camera target readout
- Velocity readout (x, y, z)
- Active keys display
- Hovered node info

### Deferred
- Guidance overlays (spec marks as optional): deferred
- Tile cache eviction: 913 tiles manageable, deferred to Phase 10

### Verification results
- 81/81 tests pass (no Python changes, all existing tests unaffected)
- Invariant §4.1: enterNode animates to parent rect (camera anchors via setCameraTarget)
- Invariant §4.2: exitToParent is stack pop + animated restore (no network request, instant)
- Invariant §4.3: no sigil created during driving or navigation (test passes)
- Invariant §4.5: ESC always available, exits within 1 action
- UI live at http://127.0.0.1:8777/atlas
- Manual verification passed: atlas loads, enter/exit animated, WASD drives, debug overlay shows FPS/velocity/keys, ESC returns to root

## Phase 8: Sigil rendering - "beauty gravity" (ACCEPTED)

### Files created/modified
- `sigiltree/sigil_scoring.py` - **NEW**: pure score computation, `compute_sigil_scores(sigil, library, coordinates, nodes)` returns per-node score + breakdown
- `sigiltree/viewer_server.py` - added `/api/atlas/sigil_scores` endpoint, ATLAS_VIEWER_HTML: sigil state, G toggle, fetch/cache, dim+halo overlay, debug "why" readout, minimap tinting
- `tests/test_sigil_scoring.py` - **NEW**: 11 unit tests

### Algorithm
- Per collapsed entry in sigil: look up coordinates by contrast_name, quantiles by contrast_id
- `node_mean = mean(coordinates[contrast_name][iid] for iid in node.image_ids)` (missing IDs skipped)
- `normalized = clamp((node_mean - p10) / (p90 - p10), 0, 1)`
- Direction alignment: "right" -> `aligned = normalized`; "left" -> `aligned = 1 - normalized`
- `contribution = aligned * strength`
- `score = mean(contributions)` across all collapsed entries; empty sigil -> 0.5

### Rendering (overlay-only, per spec section 2.3)
- Dim: `rgba(0,0,0, (1-score)*0.55)` overlay after tile, before border
- Halo: amber `strokeRect` for score > 0.7, alpha proportional to `(score - 0.7) / 0.3`
- Minimap: warm/cool tint per node when sigil active
- Debug "why" readout: hover any node with backtick+G to see per-contrast breakdown (mean, normalized, direction, contribution)

### Key bindings
- G: toggle sigil overlay on/off
- SIGIL badge appears in header bar when active (amber, styled)

### Endpoint
- `GET /api/atlas/sigil_scores?user_id=default&level=0`
- Returns `{user_id, sigil_version, collapsed_contrasts, scores: {node_id: {score, breakdown}}}`
- 404 when no sigil file exists for user

### Tests (11 new, 92 total)
1. test_empty_sigil_neutral - no entries -> all scores = 0.5
2. test_single_contrast_right_aligned - high-mean node ~1.0, low-mean ~0.0
3. test_single_contrast_left_aligned - direction inversion
4. test_no_cross_axis_effect - uncollapsed axis doesn't affect score
5. test_uncollapsed_not_in_breakdown - absent from breakdown list
6. test_strength_weighting - strength=0.5 halves contribution
7. test_quantile_normalization - p10->0, p90->1, midpoint->0.5
8. test_missing_image_ids_graceful - skips unknown IDs
9. test_score_range - all scores in [0,1]
10. test_multiple_contrasts_averaging - mean of contributions
11. test_invariant_4_3_no_sigil_mutation - input sigil unchanged

### Verification results
- 92/92 tests pass (11 indexer + 8 embedding + 8 contrast + 16 arcade + 38 atlas + 11 sigil scoring)
- G toggle ON: SIGIL badge, dim overlay, amber halos visible immediately
- G toggle OFF: overlay removed, normal appearance restored
- Sublevel navigation: scores fetched per level, overlay applied at level 1+
- Debug "why" readout: 10 collapsed contrasts with per-contrast score, mean, normalized, contribution
- ESC returns to parent with sigil active (instant, no interference)
- FPS 57 with sigil overlay (no frame drops)
- Invariant 4.1: enter still anchors to rect (sigil overlay doesn't interfere)
- Invariant 4.2: ESC instant from any depth with sigil active
- Invariant 4.3: sigil file MD5 unchanged after browsing (6803425b0275465d24e4b238b3c318f3)
- Invariant 4.5: ESC always available, no added friction
- UI live at http://127.0.0.1:8777/atlas

## Phase 9: Contrast rides with drift policy (SUPERSEDED by Phase 10)

### Files created/modified
- `sigiltree/ride_stats.py` - **NEW**: precompute per-node z-summaries + inter-contrast Pearson correlations
- `sigiltree/ride_engine.py` - **NEW**: ride planning with drift policy cascade (single/condition/compound/reject)
- `sigiltree/ride_session.py` - **NEW**: ride state tracking, band construction, sigil merging
- `sigiltree/cli.py` - added `ride-stats` subcommand
- `sigiltree/viewer_server.py` - 5 new endpoints + full ride UI in ATLAS_VIEWER_HTML
- `tests/test_ride.py` - **NEW**: 28 tests (5 stats + 7 engine + 9 session + 2 merge + 1 lock_set + 2 drift + 2 integration)

### Algorithm: Drift Policy Cascade
- **Single**: all locked contrast drifts < tolerance (2.0 z-score) -> ride proceeds normally
- **Condition**: restrict path to nodes where drifting contrast z_mean is within median +/- band_width/2; must retain >= min_path_length nodes
- **Compound**: promote to two-axis ride (show user both contrasts); only if exactly 1 drifter
- **Reject**: cannot isolate contrast; honest explanation shown to user

### Tolerance tuning
- Original tolerance=0.5: with 10 collapsed contrasts, ALL 36 contrasts rejected (inter-contrast correlations cause universal drift)
- Tested values: 0.5 (0 rideable), 1.0 (4), 1.5 (17), 2.0 (27), 2.5 (36)
- Selected tolerance=2.0: 27 rideable (10 single + 10 condition + 7 compound), 9 rejected — good balance of availability vs. honesty

### Precomputation: `ride-stats` CLI
- Computes per-node z_mean/z_std for all 36 contrasts across all 4 atlas levels
- Computes 36x36 Pearson correlation matrix across all contrasts
- 36 contrasts x 913 nodes = ~33K z-computations, under 1 second
- Artifacts: `atlas/node_zsummaries.json`, `atlas/contrast_correlations.json`

### Ride Engine: `ride_engine.py`
- `RidePlan` dataclass: ride_contrast, resolution, path (sorted node_ids), locked, drift_estimates, condition_info, compound_info, reject_reason
- `plan_ride()`: sort nodes by z_mean, compute drift per locked contrast, apply cascade
- `derive_lock_set()`: all collapsed contrasts in sigil except ride contrast
- `compute_ride_drift_at_position()`: runtime drift monitoring at any path position

### Ride Session: `ride_session.py`
- `RideSession` class: manages path traversal, records choices (approach/retreat/silence)
- `build_band()`: approach->right, retreat->left, silence->ignored; majority wins, strength = n_agreements/n_directional
- `merge_band_into_sigil()`: combines ride band into existing sigil, handles same/opposing directions, returns new dict (no mutation)

### API Endpoints (5 new routes)
- `POST /api/ride/plan` - plan ride from user sigil + contrast selection
- `POST /api/ride/step` - current node, drift readings, progress
- `POST /api/ride/choose` - record direction, advance; on completion merges band into sigil
- `GET /api/ride/summary` - session state + band outcome
- `GET /api/ride/stats` - debug: zsummaries + correlations

### Ride UI (ATLAS_VIEWER_HTML)
- **R key**: opens contrast picker overlay listing all 36 contrasts, collapsed ones highlighted amber
- **Resolution consent**: single (proceed), compound (show both axes?), condition (restricted N nodes), reject (honest explanation)
- **Ride controls** (override drive keys during ride): Right=more like this, Left=less like this, Space=skip, ESC=abort
- **Camera animation**: setCameraTarget to current ride node per step; snap-reset on completion/abort
- **Drift monitor**: top-right panel with per-locked-contrast drift bars (green/yellow/red)
- **Progress bar**: bottom bar with spatial layout: `Left = less like this | [pole_low] ━━━ [pole_high] | N/total | Right = more like this | Space=skip ESC=abort`
- **Completion overlay**: band direction + strength, agreement counts, sigil update status
- **RIDE badge**: amber header badge during active ride
- **Sigil overlay suppression**: sigil dimming/halos automatically hidden during ride to avoid visual conflict; resumes on ride end

### Semantic pole labels (`ridePoleLabels()`)
- Bipolar `sem_X_vs_Y` -> LOW=X, HIGH=Y (e.g., "bw" / "color")
- Unipolar `sem_X` -> "less X" / "more X" (e.g., "less street" / "more street")
- Perceptual -> "less name" / "more name" (e.g., "less brightness" / "more brightness")
- PCA -> "LOW" / "HIGH" (no semantic meaning available)
- Applied in consent screens, progress bar, and completion overlay

### Camera snap fix
- After ride completion or abort, camera must return to atlas overview
- Original approach (setCameraTarget with lerp) failed: animation from deep zoom to overview takes too many frames
- Fix: snap both `cam` and `camTarget` directly to overview coordinates (no animation)
- viewStack also reset to root level

### Node labels (atlas neighborhoods)
- `/api/atlas/node_labels?level=N` endpoint computes descriptive labels from z-summaries
- For each node: finds semantic/perceptual contrast with most extreme z_mean
- Priority: semantic (0) > perceptual (1) > PCA (2, skipped)
- Bipolar `sem_X_vs_Y`: high z -> Y, low z -> X; Unipolar `sem_X`: high z -> X, low z skipped
- Labels rendered as bold white text + dark shadow on each node in atlas view
- Fetched on init (level 0) and on enterNode (new level)

### Key bindings during ride
- Right arrow: "more like this" (record approach + advance)
- Left arrow: "less like this" (record retreat + advance)
- Space: skip (record + advance, no collapse)
- ESC: abort ride, return to atlas
- D/A keys still functional as hidden shortcuts but not shown in UI

### Tests (28 new, 120 total)
- TestRideStats (5): zsummary known values, single image node, correlation symmetric, diagonal one, known data
- TestRideEngine (7): single no drift, high drift triggers policy, path monotone, condition restricts, reject when all fail, empty lock set, no mutation
- TestRideSession (9): fresh at zero, step advances, approach/right, retreat/left, silence no collapse, consistent approaches, mixed decay, all silence none, completes after full path
- TestMergeBand (2): merge new contrast, merge same direction combines
- TestDeriveLockSet (1): excludes ride contrast
- TestDriftAtPosition (2): drift at start zero, drift increases along path
- TestIntegration (2): ride_plan_endpoint, full_ride_flow

### Verification results
- 120/120 tests pass (11 indexer + 8 embedding + 8 contrast + 16 arcade + 38 atlas + 11 sigil scoring + 28 ride)
- ride-stats CLI: artifacts created (36 contrasts, 4 levels, under 1s)
- R key opens picker with all 36 contrasts, collapsed ones highlighted
- Temperature ride: single resolution, 22 nodes, pole labels "less temperature"/"more temperature"
- Camera snaps back to overview on ESC abort and on ride completion (no black screen)
- Sigil overlay (G key) suppressed during ride; resumes after abort/completion
- Drift monitor shows all locked contrasts at 0.00 at start, updates per step
- ESC dismisses all dialogs correctly
- Invariant 4.1: enter still anchors to rect
- Invariant 4.2: ESC instant from any depth
- Invariant 4.3: navigation without ride choices doesn't modify sigil
- Invariant 4.5: ESC always available during ride
- UI live at http://127.0.0.1:8888/atlas

## Phase 10: Silent Calibration + Flowing Navigation (COMPLETE)

### Conceptual shift
- "A neighborhood IS a sigil" — its z-profile across all contrasts defines its character; images conform to it
- Navigation IS calibration: you explore; the system silently records where you go; preferences emerge from visited z-profiles
- No contrast names shown, no explicit left/right choices, no picker, no consent screens
- The tree is invisible: at leaf level, arrow keys flow to adjacent neighborhoods in sigil-space
- The space is contained and loops — you never hit a wall

### Files created
- `sigiltree/flythrough.py` — **NEW**: silent calibration engine + flow graph
- `tests/test_flythrough.py` — **NEW**: 32 tests

### Files modified
- `sigiltree/viewer_server.py` — removed all ride UI, added flythrough + flow navigation

### `sigiltree/flythrough.py`
- `FlythroughSession`: tracks visited nodes, deduplicates consecutive visits, `is_ready` when >= 5 distinct nodes
- `infer_preferences()`: for each contrast, computes `mean(z_mean[n] for n in visited)`; if `|bias| > 0.4` -> collapse with direction + clamped strength
- `flythrough_to_sigil()`: packages inferred preferences into sigil dict compatible with `save_sigil()`
- `compute_flow_graph()`: pairwise cosine similarity of z-profiles across all leaf nodes; returns `{node_id: [neighbors sorted by similarity]}`
- `flow_in_direction()`: picks nearest flow-neighbor in spatial direction (right/left/up/down), wraps around if none found in that direction
- `_z_profile()`, `_cosine_similarity()`: helper functions

### viewer_server.py changes

**Removed** (entire ride UI):
- All ride state variables (rideActive, ridePlan, rideSession, etc.)
- All ride functions (toggleRidePicker, loadContrastList, startRidePlan, confirmRide, beginRide, navigateToRideNode, fetchRideDrift, updateDriftMonitor, updateRideProgress, rideChoose, endRide, abortRide, dismissRideCompletion, updateRideIndicator, ridePoleLabels)
- 4 ride endpoints (plan, step, choose, summary) — kept ride/stats
- All ride CSS (picker, consent, drift monitor, progress bar, completion overlay)
- All ride HTML (picker, consent, drift monitor, progress bar, completion divs)
- Ride keyboard intercepts

**Added** (flythrough + flow):
- JS state: `flythroughActive`, `flythroughVisits`, `MIN_FLYTHROUGH_VISITS`, `flowNeighborsCache`, `currentMemberNode`
- Functions: `toggleFlythrough()`, `startFlythrough()`, `finishFlythrough()`, `cancelFlythrough()`, `recordFlythroughVisit()`, `updateFlythroughIndicator()`, `showFlythroughToast()`, `fetchFlowNeighbors()`, `flowToNeighbor()`
- `enterNode()` hook: records flythrough visit when active
- `showMembers()` / `closeMembers()`: tracks `currentMemberNode` for flow navigation
- R key: toggles flythrough (start/finish exploration)
- Arrow keys at leaf: flow to nearest neighbor in that direction (no dead ends)
- ESC during flythrough: cancel, clear visits
- `#flythroughIndicator`: header counter "Exploring (N)"
- `#flythrough-toast`: brief completion message
- 2 endpoints replacing 4 ride endpoints:
  - `POST /api/flythrough/record` — builds session, infers preferences, saves sigil
  - `GET /api/flow_neighbors` — computes flow graph, returns top-10 neighbors with rects
- Debug overlay: flythrough visit count + active status
- Help overlay: updated text ("Start / finish exploration" instead of "Start a contrast ride")

### Tests (32 new flythrough + 2 updated integration = 152 total)
- TestFlythroughSession (6): empty, record, dedup consecutive, distinct nodes, ready threshold
- TestInferPreferences (8): high-z right, low-z left, scattered superposed, empty, min_bias, strength proportional, multi-contrast independent, no mutation
- TestFlythroughToSigil (3): valid structure, empty visits, entry structure
- TestFlowGraph (6): all have neighbors, self excluded, all others present, most similar first, single node, cross-branch
- TestFlowInDirection (5): right picks nearest rightward, left picks nearest leftward, wraps, no neighbors, vertical
- TestCosineSimilarity (4): identical, opposite, orthogonal, zero vector
- TestIntegration (2 updated): flythrough_record_endpoint, flythrough_full_flow

### Files kept unchanged
- `sigiltree/ride_stats.py` — z-summaries power both old rides and new flythrough
- `sigiltree/ride_engine.py` — unused but harmless
- `sigiltree/ride_session.py` — unused but harmless

### Verification results
- 152/152 tests pass (11 indexer + 8 embedding + 8 contrast + 16 arcade + 38 atlas + 11 sigil scoring + 28 ride stats/engine/session + 32 flythrough)
- No ride UI visible anywhere (no picker, no consent, no drift monitor, no progress bar)
- R starts exploration, counter ticks up as you navigate
- R again after 5+ distinct nodes -> sigil saved -> "N preferences recorded. Press G to see."
- Arrow keys at leaf level flow to adjacent neighborhoods (cosine similarity of z-profiles)
- Flow crosses parent boundaries transparently
- Navigation loops — no dead ends
- ESC still works at every depth
- WASD driving still works at non-leaf levels
- G overlay reflects flythrough-inferred preferences
- Invariant 4.1: enter anchors camera to rect (verified)
- Invariant 4.2: ESC instant from any depth (verified)
- Invariant 4.3: navigation without finishing flythrough doesn't modify sigil (verified)
- Invariant 4.5: ESC always available, no added friction (verified)

### Deferred
- Update README and create landing page to explain "neighborhood is a sigil" vision

## Phase 11: The Sigil Graph — No Leaves, No Dead Ends (COMPLETE)

### Conceptual shift
- Every node is a sigil with doors. No dead ends. Self-similar at every level.
- Doors: back (where you came from), down (children), lateral (flow-neighbors)
- No keyboard navigation. Click-only. Camera locked to 100% viewport.
- Floating toolbar: Back, Home, Calibrate, Sigil, Help

### Files modified
- `sigiltree/viewer_server.py` — doors endpoint, camera lock, cover-crop tile drawing, server-side caching, cache preheating

### Performance fixes
- Server-side caching: `_cached_meta()`, `_cached_stats()`, `_cached_flow()` avoid recomputation
- Cache preheating: `_preheat_caches()` runs at startup, loads all levels
- Cover-crop drawing: 9-argument `ctx.drawImage` eliminates image distortion
- Camera lock: zero-padding `fitToRect`, no lerp, no velocity, no animation
- Flow graph: O(N^2) per level but cached — computed once at startup
- L3 verified: 25 nodes, 33 contrasts, flow graph in 1.5ms, 9 doors returned in 50ms

### Performance tests
- `TestDoorsPerformance` in `tests/test_ride.py`
- `test_doors_response_time_all_levels`: all levels respond < 200ms
- `test_doors_cached_is_fast`: warm cache < 200ms

### Verified
- L3 doors endpoint returns 9 doors (1 back + 8 lateral) in 50ms on production
- No dead ends at any level — lateral doors always present
- Camera locked: no zoom, pan, or scroll
- Cover-crop: no image distortion
- 154/154 tests pass
- Deployed to https://sigilatlas.fly.dev/

### Note on cold start
- Fly.io scales to zero when idle. First request after cold start takes ~8s (container boot + Python startup + cache preheat). Subsequent requests are fast (<50ms).

### Graph behavior tests: `tests/test_doors.py` (30 tests)
- TestNoDeadEnds (5): root has doors, mid-level has doors, leaf has lateral doors, exhaustive every-node check, back door always provides way out
- TestBackDoor (5): present when from_node specified, absent without from_node, cross-level, same-level lateral, not duplicated in lateral
- TestDownDoors (3): match children, at next level, leaf has none
- TestLateralDoors (4): same level, max 8, from flow graph, exclude self
- TestGraphNavigability (4): can always go back, lateral forms cycle, all L3 reachable, down-then-back identity
- TestDoorStructure (4): required fields, all types present, no duplicates, nonexistent node safe
- TestFlowGraphProperties (5): complete graph, symmetric reachability, stable ordering, empty zsummaries, single contrast
- All 184 tests pass (154 existing + 30 new)

### Treemap layout restoration + aspect-ratio tiles + full-size image view (2026-02-06)

**Treemap restored at every level**:
- Commit `a836289` replaced treemap rects with `layoutAsGrid()`, destroying spatial organization.
- Fix: ported squarified treemap (Bruls-Huizing-van Wijk 2000) to client-side JS.
- Root init uses `meta.nodes` directly (pre-computed treemap rects from atlas build).
- `enterNode()` uses `layoutAsTreemap()` for all sublevel views (down + back + lateral + members).
- `layoutAsGrid()` kept as dead code.

**Aspect-ratio-matched tiles** (atlas.py):
- Montage tiles now rendered at the treemap cell's aspect ratio, not square.
- `TILE_LONG = 1024`, tile_w and tile_h computed from `cell_aspect = rw / rh`.
- Contain-fit on these tiles fills the cell with zero black bars and zero distortion.
- Both `build_atlas()` (level 0) and `_build_level_nodes()` (recursive) updated.
- Atlas rebuilt: 254 nodes, 4 levels, 3.7s.

**Contain-fit for ALL tiles**:
- `Math.min` scale for both member photos and montage tiles.
- No cropping, no stretching, no distortion. Exhibition-quality image presentation.

**Simplified door indicators**:
- Colored borders removed. Small white arrow icons only: up (back), down (deeper), right (lateral).
- Uniform visual treatment — all sigils look the same, just their montage + tiny arrow.

**Full-size individual image view**:
- Clicking a member image pushes a "showcase" frame onto the viewStack.
- Full-resolution original served via `GET /api/image/{image_id}/full` (new endpoint).
- Showcase tile gets size=8 (89% of space), back door gets size=1 (11%).
- Treemap layout places the full image left, back door right.
- `door_type: 'showcase'` — clicking it does nothing; clicking the back door exits.
- Contain-fit rendering (no distortion, no cropping).

**Files modified**:
- `sigiltree/viewer_server.py` — JS treemap functions, `layoutAsTreemap()`, `enterNode()` member handling, `handle_image_full()` endpoint, showcase rendering
- `sigiltree/atlas.py` — tile dimensions based on treemap cell aspect ratio

All 184 tests pass.

### Leaf node member images fix (2026-02-06)
- **Problem**: Clicking a multi-image leaf node (e.g., L1_0029 with 3 images) showed only lateral flow-neighbors. The node's own images — visible in its montage cover tile — vanished on entry. User reported: "the pink image looks like a cluster that i enter, yet i can't see any of the images on the 'cover' inside."
- **Root cause**: `enterNode()` only had a `size === 1` branch for showing self-tiles. Multi-image leaves (size > 1) fell through to the else branch showing only doors. Additionally, `fromLevel` in the client was computed from `curFrame.level` (the frame's display level) instead of `parentNode.level` (the actual node level), causing back doors to fail cross-level lookup.
- **Fix (viewer_server.py)**:
  - Server: `handle_atlas_node_doors` now returns `members` list for leaf nodes with size > 1, each with `image_id`, `thumb_url`, `door_type: "member"`
  - Client: `enterNode()` detects members and creates member tiles (non-clickable, loaded via `/thumbs/512/`) + layout weight so they dominate the first row
  - Client: `tileCacheKey()` function handles both `node_id` and `image_id` cache keys
  - Client: `tilePath()` supports `thumb_url` for member tiles
  - Client: Fixed `fromLevel` to use `parentNode.level` for correct cross-level back door lookup
  - Member tiles have `door_type: 'member'` — clicking them does nothing (like 'self' tiles)
- **Result**: Entering L1_0029 now shows its 3 member images (yellow blocks, orange blur, pink wall) as large tiles in the top row, back door with amber border, and 8 lateral doors below. Cover images match inner view.
- All 184 tests pass.

### Self-dominant layout + cover-fit montages + self-tile clickable (2026-02-06)

**Self-dominant layout** — hierarchy clarity:
- Current sigil (self tile or member images) takes ~75% of screen area.
- `selfWeight = max(totalDoorWeight * 3, 10)` — doors are peripheral exits.
- For leaf nodes with members: each member gets `floor(selfWeight / members.length)` weight.
- For non-leaf: a single self tile gets `selfWeight`, doors get their natural size.
- Treemap layout distributes space proportionally — big self, small exits around edges.

**Cover-fit for montage tiles** — zero black space:
- Non-member, non-showcase tiles use `Math.max` scale + center-crop (cover-fit).
- Montage grids of many small thumbnails tolerate slight cropping — imperceptible.
- Individual photos (member/showcase) still use contain-fit (`Math.min` scale) — no cropping.
- Result: no black bars anywhere on montage tiles.

**Self tile clickable** — sigils are composites, not atoms:
- Removed `'self'` from `enterNode()` early return guard.
- Only `'showcase'` is non-clickable (individual full-size image).
- Clicking the self tile enters it — shows its children/members with the self-dominant layout at the next level.
- A montage tile is a sigil (composite of images), not a single image — it should always be enterable.

**Files modified**: `sigiltree/viewer_server.py` (JS only)
All 184 tests pass.

### Back door at every level + visible arrow badges (2026-02-06)

**Back door missing at first level**:
- When entering a node from root, `from_node` was empty, so the server returned no back door.
- Fix: client creates a synthetic back door (`node_id: '__back_to_parent__'`) when the server doesn't return one and `viewStack.length > 0`.
- Clicking any back door now calls `exitToParent()` directly (new early return at top of `enterNode()`), instead of trying to fetch doors for the back node.

**Visible arrow badges**:
- Replaced tiny 12-18px text arrows with pill-shaped badges (dark rounded-rect background + white arrow).
- Badge size: `max(16, min(28, min(iw, ih) * 0.18))` — scales with tile size.
- Back: up-arrow badge in top-left. Down: down-arrow badge in bottom-right. Lateral: right-arrow badge in top-right.
- Dark background (`rgba(0,0,0,0.55)`) makes arrows readable on any image.

**Files modified**: `sigiltree/viewer_server.py` (JS only)
All 184 tests pass (A).

### Non-overlapping back door layout (2026-02-06)

**Problem**: Back door thumbnail was superimposed on top of content (showcase image or member grid), hiding part of the image.

**Fix**: Back door gets its own dedicated left strip instead of overlapping content:
- `backStrip = 0.08` (8% width) — back door occupies `[0, 0, 0.08, 0.08]` (square in top-left)
- Content (treemap of members/doors or showcase image) laid out in remaining space `[0.08, 0, 0.92, 1]`
- `layoutAsTreemap()` now accepts optional `bounds` parameter for non-default bounding rect
- Showcase view: image fills `[0.08, 0, 0.92, 1]`, back door in its own `[0, 0, 0.08, 0.08]`
- Member grid: treemap runs in `[0.08, 0, 0.92, 1]`, back door pinned at `[0, 0, 0.08, 0.08]`
- When no back door exists (e.g., entering from root), content fills full `[0, 0, 1, 1]`

**Files modified**: `sigiltree/viewer_server.py` (JS only)
All 184 tests pass.

### Root as proper sigil + snapshot back doors (2026-02-06)

**Root modeled as real AtlasNode**:
- `__root__` stored in `artifacts/atlas/root/meta.json` with `level: -1`, `parent_id: null`, `child_ids: [L0 node ids]`.
- `_save_root_node()` helper creates root node during `build_atlas()` and `build_atlas_recursive()`.
- `load_root_meta()` loads root meta. Server `_cached_meta()` handles key `"root"`.
- Removed synthetic root construction in `handle_atlas_node_doors()`.

**Tile cache removed**:
- Removed `TILE_CACHE_MAX = 50`, `evictTiles()`, LRU tracking, `lastUsed` timestamps.
- `tileCache` is now a plain map — browser manages memory.
- `ensureTile()` simplified: just creates Images, no eviction.

**Snapshot-based back doors**:
- Back door now shows a screenshot of the previous view (what the room looked like), not the sigil's montage tile.
- `captureSnapshot()` captures `canvas.toDataURL('image/jpeg', 0.7)` before each transition.
- Snapshot Image stored on the back door tile as `_snapshotImg` with unique `_snapshotKey`.
- `tileCacheKey()` checks for `_snapshotKey` first; `ensureTile()` registers pre-built snapshot Images.
- Works at all levels: Root->n_000 shows root overview snapshot, n_000->n_006 shows n_000 room snapshot.

**Files modified**:
- `sigiltree/atlas.py` — `_save_root_node()`, `load_root_meta()`, updated `build_atlas()` and `build_atlas_recursive()`
- `sigiltree/viewer_server.py` — tile cache removal, `captureSnapshot()`, snapshot back doors in `enterNode()`
- `tests/test_doors.py` — fixture generates proper root `meta.json`, 31 tests (1 new root back door test)

All 185 tests pass.

### Compact member layout: aspect-aware treemap + cover-fit (2026-02-06)

**Problem**: Member images wasted ~28% of space as black bars. All declared 512x512 but actual aspect ratios range 0.59-4.7.

**Server: thumbnail dimensions with members**:
- `handle_atlas_node_doors()` batch-queries `images` table for `width, height`.
- Computes thumbnail dimensions (long side=512, preserve ratio).
- Each member now includes `thumb_w` and `thumb_h`.

**Client: aspect-ratio treemap weights**:
- Member `size` = `perMember * (thumb_w / thumb_h)` instead of equal weight.
- Wider images get wider cells, tall images get taller cells.

**Client: cover-fit for members**:
- Members switched from contain-fit to cover-fit (`Math.max` scale + center-crop).
- Showcase (full-size view) stays contain-fit.
- Zero black bars in member grid. Minor center-cropping (~17% on 3:2 images).

**Files modified**:
- `sigiltree/viewer_server.py` — server: member dimension enrichment; client JS: aspect weights + cover-fit
- `tests/test_doors.py` — 3 new tests (TestMemberDimensions)

All 188 tests pass.

### Unlimited atlas depth + hierarchy-first viewer (2026-02-06)

Commit `3706a86`. See "Session Recovery Context" section above for full details.

### Zoned layout: children center, laterals on edges (2026-02-06)

**Problem**: Down doors (children) and lateral doors (flow neighbors) looked identical — same size, interleaved in treemap.

**Fix — zoned layout for non-leaf nodes**:
- When `hasDown`: split doors into `downDoors` (center, large) and `lateralDoors` (thin strips on left/right edges).
- Down doors fill remaining center area after back strip + lateral strips.
- Laterals split into left/right halves, each getting 6% width strips.
- Back door unchanged: 8% left strip. Leaf nodes unchanged.
- Lateral arrow changed from right-arrow at top-right to bidirectional at bottom-center.

Deployed as commit `bb1deee`.

### Leaf images: contain-fit + single-image member threshold (2026-02-06)

**Problem 1**: Member images at leaf nodes used cover-fit (cropping).
**Fix**: Changed `Math.max` to `Math.min` with dark background fill.

**Problem 2**: Single-image leaf nodes via lateral navigation still cropped.
**Root cause**: Server threshold `size > 1` excluded single-image nodes from returning members.
**Fix**: Changed to `size >= 1`.

Deployed as commit `f18a146`.

### Current atlas stats
- 5 levels (0-4), 960 nodes, 874 images
- Level 4: 94 leaf nodes, all naturally terminated
- Live at https://sigilatlas.fly.dev/
