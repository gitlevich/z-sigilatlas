# Taste Radar

Container: [Rendering](../rendering.md)

# Purpose

Define the radar chart that visualizes the user's calibrated taste profile on the atlas and during calibration. The radar shows collapsed bipolar contrasts as axes radiating from a center, with direction encoded by color and magnitude by radial distance.

# Boundary observables

**Taste sigil endpoint.** GET /api/atlas/taste_sigil?user_id=X returns only bipolar semantic contrasts. Filtering rules: include perceptual bipolars (sharpness, brightness, etc.) and semantic bipolars (contain "_vs_"). Exclude PCA (name starts with "pca_") and unipolar semantic categories (sem_ without "_vs_"). Each entry has: name, dir ∈ {left, right}, str ∈ [0, 1]. Response includes collapsed_count and sorted_keys for stable axis ordering.

**Radar geometry.** Center = 0 (no preference). Outer edge = maximum strength. Radial distance is proportional to preference magnitude. Direction is shown by dot color only: blue for left, orange for right. Un-voted/skipped axes appear at the midline (50% radius). The taste_axis is always pinned to the north position (index 0). Remaining axes are sorted for smooth polygon shape.

**Atlas toolbar.** The taste radar is visible by default in the atlas toolbar (tasteRadarVisible = true). The toolbar button starts with the active class. The button is always visible (no hidden-until-data logic).

**Unified radar.** One radar, two overlaid polygons on the atlas: amber (taste profile, always visible when toggled) and blue (node hover profile). Same axes, same coordinate space. Taste dots are orange/blue by direction; un-voted axes are gray at midline.

**Live preview during calibration.** On the /walk page, the radar shows the current calibration state. As the slider moves, the radar updates in real time (currentContrastId set in showStep). New choices merge into existing radar entries rather than replacing the entire state. Prior calibration state (loaded from taste sigil on page open) survives as new choices arrive.

**Dynamic axes.** The radar axes are built dynamically from the taste sigil response, not from a hardcoded list. Shows all calibrated contrasts, sorted by strength descending, with taste_axis pinned to north.

# Invariants and non-goals

**Invariants.**
- Only bipolar contrasts appear in the radar. PCA and unipolar categories are filtered out.
- Direction is encoded by color, not radial position.
- Center represents absence of preference, not negative preference.
- taste_axis is always at north (position 0).
- The radar does not affect scoring or atlas layout — it is purely informational.

**Non-goals.** This page does not define score computation (see [Scoring Pipeline](scoring-pipeline.md)) or the overlay brightness effects (see [Overlay](overlay.md)).

# Canonical examples (golden fixtures)

Bipolar-only filtering (from test_walk.py TestTasteSigilEndpoint): sigil with entries for sharpness (bipolar), sem_natural_vs_manmade (bipolar), pca_clip_0 (PCA), brightness (bipolar), sem_portrait (unipolar). Endpoint returns 3 entries (sharpness, sem_natural_vs_manmade, brightness). PCA and unipolar excluded.

Entry format: each entry has name="sharpness", dir="left", str=0.85.

No sigil returns 404: GET /api/atlas/taste_sigil for nonexistent user → 404.

# Contained sigils

None. This is a leaf sigil.

# Supersession notes

BUG-001 (fixed commit 24b0ab0): the tasteRadarVal function previously mapped left preferences to 0.0–0.5 (toward center) and right to 0.5–1.0 (toward edge), making left preferences visually invisible. Fixed to use magnitude only; direction shown by color.

Phase 17 introduced the walk progress pie chart. Phase 20 replaced it with the amber polygon radar with live preview. Phase 20 also removed the hardcoded RADAR_AXES list (11 items) in favor of dynamic axes from the API response, and pinned taste_axis to north.
