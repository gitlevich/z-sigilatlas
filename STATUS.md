# Sigil Tree - Project Status

## Current Phase: 6 (ACCEPTED)

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

## Phase 6: Multiscale atlas pyramid (PENDING ACCEPTANCE)

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
