# UI Test Plan

Executable test plan covering all UI surfaces. Each section maps to a page/component. Tests are grouped by: API contract (testable via aiohttp test client), rendering logic (testable via extracted Python helpers), and visual verification (manual or browser automation).

## 1. Atlas Page (`/atlas`)

### 1.1 API: Manifest
- GET `/api/atlas/manifest` returns `{max_level, root_bounds, versions}`
- `max_level` >= 0, `root_bounds` has `x, y, w, h`

### 1.2 API: Level Meta
- GET `/api/atlas/meta?level=0` returns nodes array
- Each node has `node_id, rect, size, image_ids, representatives, tile_path`
- `rect` has `x, y, w, h`, all non-negative, w and h > 0
- Node rects at level 0 tile the root_bounds (no gaps, no overlaps beyond rounding)
- Levels 0 through max_level all return valid meta

### 1.3 API: Node Children
- GET `/api/atlas/node/{node_id}/children?level=0` returns children
- Children node_ids exist in level+1 meta
- Leaf nodes return `is_leaf: true` with no children

### 1.4 API: Neighborhood
- GET `/api/atlas/neighborhood/{node_id}?level=0` returns members
- `members` array is non-empty for leaf nodes
- Each member has valid `image_id` and `thumb_url`

### 1.5 API: Node Labels
- GET `/api/atlas/node_labels?level=0` returns `{labels: {nid: string}}`
- Labels exist for all nodes at that level
- Labels are non-empty strings

### 1.6 API: Flow Neighbors
- GET `/api/atlas/flow_neighbors?node_id=X&level=0` returns neighbors
- No node is its own neighbor
- Neighbor node_ids exist in the same level meta

### 1.7 API: Doors
- GET `/api/atlas/node/{node_id}/doors?level=0` returns doors array
- Every non-root node has a `back` door pointing to parent
- Root-level nodes have `back` door pointing to root
- Leaf nodes have `member` entries
- Non-leaf nodes have `down` or `lateral` doors

### 1.8 Visual: Navigation Stack
- Click node at L0 → view transitions to L1 children
- Press Esc → returns to previous level
- Home button → returns to L0
- Breadcrumb shows correct current level

### 1.9 Visual: Sigil Overlay
- Toggle sigil button → nodes recolor by score
- Toggle off → nodes return to normal
- Scores visible in debug overlay (`D` key)

### 1.10 Visual: Minimap
- Minimap shows L0 layout at all zoom levels
- Click minimap → viewport jumps to clicked region

## 2. Walk Page (`/walk`)

### 2.1 API: Start
- POST `/api/walk/start` with `{user_id: "test"}` returns `{status: "continue", step, progress, contrasts}`
- `step` has `left_ids, right_ids, contrast_name, flipped, step_index`
- `contrasts` array contains all bipolar contrast names (no unipolar, no pca initially)
- `left_ids` and `right_ids` each have EXEMPLARS_PER_SIDE (6) entries
- `progress.total` >= number of bipolar contrasts

### 2.2 API: Choose — Direction
- POST `/api/walk/choose` with `{direction: "left", strength: 0.7}` returns next step
- Choosing "right" also works
- Choosing "skip" records no preference (center)
- `partial_sigil` included in response when collapsed_count > 0

### 2.3 API: Choose — Flip Correctness
- Start walk, get a flipped step (`step.flipped === true`)
- Choose "left" → server records as "right" (de-flipped)
- Verify via partial_sigil: entry direction matches the de-flipped direction

### 2.4 API: Choose — Slider Strength
- Choose with `strength: 0.3` → sigil entry `strength` reflects slider value
- Choose with `strength: 0.0` → contrast dropped from sigil (near-zero)
- Choose with `strength: 1.0` → full strength (default binary behavior)

### 2.5 API: Completion
- Complete all steps → response has `{status: "complete", sigil}`
- Sigil has `entries, collapsed_count, total_choices`
- Sigil saved to disk at `artifacts/sigils/sigil_{user_id}.json`

### 2.6 API: Partial Sigil for Live Radar
- After each choice, `partial_sigil.entries` includes all collapsed contrasts so far
- Entry format: `{contrast_name, direction, strength, n_presentations, n_agreements}`

### 2.7 Visual: Mosaics
- Left and right columns each show 6 images in a grid
- Images correspond to `left_ids` and `right_ids` from the step
- Flipped steps show high exemplars on left, low on right

### 2.8 Visual: Strength Slider
- Clicking a side reveals the slider zone
- Slider range is -100 to +100 visually, mapped to bias
- Pole labels show contrast names matching the visual layout
- Crossing zero flips the selected side

### 2.9 Visual: Progress Dots
- Total dots = total steps
- Current dot highlighted
- Completed dots show green

### 2.10 Visual: Live Radar
- After first directional choice, radar appears with one axis
- Subsequent choices add axes
- Skipped contrasts shown differently (dimmed or absent)
- Entry color: blue for left, orange for right

## 3. Arcade Page (`/calibrate`)

### 3.1 API: Start
- POST `/api/arcade/start` with `{user_id: "test"}` returns prompt
- Prompt has `contrast_id, contrast_name, doors` (3 doors: left, center, right)
- Each door has `image_ids` (9 exemplars from low/median/high quantiles)

### 3.2 API: Choose
- POST `/api/arcade/choose` with `{user_id: "test", direction: "left"}` returns next prompt
- Direction "center" records a skip
- After all prompts → `{status: "complete", sigil}`

### 3.3 API: Summary
- GET `/api/arcade/summary?user_id=test` returns complete session history
- Includes all choices, sigil entries, progress

### 3.4 Visual: Three-Door Layout
- Three image grids displayed side-by-side
- Left door = low-end exemplars, center = median, right = high-end
- Arrow key selection highlights the chosen door

## 4. Categories Page (`/categories`)

### 4.1 API: Data
- GET `/api/categories/data?user_id=test` returns `{categories, existing_weights}`
- `categories` array has unipolar sem_ contrasts only (no _vs_, no pca_)
- Each category has `contrast_id, name, exemplar_ids`
- `existing_weights` is null or dict of previously saved weights

### 4.2 API: Save
- POST `/api/categories/save` with `{user_id: "test", weights: {cid: 0.8}}` returns ok
- Saved weights persist: re-fetching data returns them in `existing_weights`
- Zero-weight categories treated as inactive

### 4.3 API: Save → Score Integration
- After saving categories, GET `/api/atlas/sigil_scores` includes category gate
- `has_categories: true` in response
- Scores differ from walk-only scores (multiplicative gate applied)

### 4.4 Visual: Radar Handles
- Each category has a draggable handle on its axis
- Drag outward → weight increases (0 to 1)
- Active handles (weight > 0) shown in green
- Filled polygon tracks handle positions

### 4.5 Visual: Exemplar Preview
- Hovering a category shows its exemplar images below the radar
- Exemplar images match the contrast's high-end exemplars

### 4.6 Visual: Save/Reset
- Save button → done overlay → redirect to atlas
- Reset button → all handles return to center

## 5. Taste Sigil Radar (Atlas Toolbar)

### 5.1 API: Taste Sigil
- GET `/api/atlas/taste_sigil?user_id=default` returns entries
- Only bipolar sem_ contrasts (has `_vs_`, excludes `pca_`)
- Each entry: `{name, dir, str}` where dir ∈ {left, right}, str ∈ [0, 1]
- `collapsed_count` matches number of entries

### 5.2 Rendering: Bipolar Mapping (BUG-001)
- Entries with `dir: "left"` and `dir: "right"` should produce radar values centered at 0
- Radar center = no preference (str=0), outer edge = strong preference (str=1)
- Direction shown by color only (blue=left, orange=right), NOT by radial position
- Currently broken: left entries collapse toward center, right expand outward

### 5.3 Visual: Toggle
- Taste button in toolbar toggles panel visibility
- Panel shows contrast names, colored dots, and strength polygon
- Count text: "N calibrated tastes"

## 6. Sigil Scoring Pipeline

### 6.1 API: Scores — Walk Only
- With walk sigil, no categories → scores use walk_score only, gate = 1.0
- GET `/api/atlas/sigil_scores?user_id=X&level=0` returns per-node scores
- Scores range [0, 1], breakdown shows per-contrast components

### 6.2 API: Scores — Categories Only
- With categories, no walk sigil → `walk_score = 0.5 * gate`
- Response has `has_categories: true`
- Not a 404 (this was a fixed bug)

### 6.3 API: Scores — Combined
- Walk sigil + categories → `final = walk_score * category_gate`
- Nodes matching active categories get higher scores

### 6.4 API: Scores — Neither
- No sigil, no categories → 404

## 7. NN Explorer (`/nn`)

### 7.1 API: Random
- GET `/api/random_id` returns `{image_id, filename}`
- image_id is a valid corpus entry

### 7.2 API: Nearest Neighbors
- GET `/api/nn?family=clip&image_id=X&k=20` returns neighbors array
- Neighbors sorted by similarity descending
- Query image not in its own neighbor list
- Similarity values in [0, 1]
- Works for all three families: clip, dino, texture

### 7.3 Visual: Family Grids
- Three horizontal scrollable grids
- Each shows k=20 neighbors with similarity scores
- Clicking a neighbor → becomes new query

## 8. Contrast Library (`/contrasts`)

### 8.1 API: Contrasts
- GET `/api/contrasts` returns full library
- Each contrast has `name, source, mass, stability, exemplars`
- `exemplars` has `low, median, high` arrays
- Mass and stability are positive floats

### 8.2 Visual: Cards
- Each contrast shown as a card with name, source tag, mass, stability
- Three rows of exemplar thumbnails (low / median / high)

## 9. Cross-Page Integration

### 9.1 Walk → Atlas
- Complete walk → sigil saved → redirect to `/atlas?sigil=1`
- Atlas auto-enables sigil overlay on `?sigil=1`
- Taste profile radar shows calibrated contrasts

### 9.2 Categories → Atlas
- Save categories → redirect to `/atlas?sigil=1`
- Categories button highlighted in toolbar
- Sigil scores include category gate

### 9.3 Sigil Persistence
- Complete walk as user A → save sigil
- Restart server → sigil loads from disk
- API returns same sigil entries

### 9.4 Session Isolation
- Start walk as user A, start walk as user B
- Choices don't cross-contaminate
- Each user's sigil is independent

## 10. Error Handling

### 10.1 Invalid Endpoints
- GET `/api/nonexistent` → 404
- Malformed JSON in POST body → 400

### 10.2 Missing Sigil
- GET `/api/atlas/taste_sigil?user_id=nonexistent` → 404
- GET `/api/atlas/sigil_scores` with no sigil and no categories → 404

### 10.3 Walk Before Start
- POST `/api/walk/choose` without starting → error response

### 10.4 Double Start
- POST `/api/walk/start` twice → resets session (no crash)

## Execution Notes

API tests (sections 1.1–1.7, 2.1–2.6, 3.1–3.3, 4.1–4.3, 5.1, 6.1–6.4, 7.1–7.2, 8.1, 9.1–9.4, 10.1–10.4) can be automated with aiohttp test client in pytest. Visual tests (sections marked "Visual") require browser automation (MCP Chrome tools or manual verification). BUG-001 (section 5.2) has a dedicated test to be written.
