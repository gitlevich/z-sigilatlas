# Bug Tracker

## BUG-001: Taste radar renders bipolar contrasts as unipolar (0 to 1)

**Status:** FIXED
**Reported:** 2026-02-07
**Component:** Atlas taste profile radar (`viewer_server.py`, `tasteRadarVal` function)

**Description:**
The taste profile radar chart in the atlas toolbar renders all contrast entries as if their values range from 0 to 1, when contrasts are bipolar and range from -1 to +1. The chart should show values distributed around its center (0 = no preference), with magnitude extending outward regardless of direction, and direction indicated by color (blue=left, orange=right).

**Expected behavior:**
Center of radar = 0 (neutral). Radial distance = strength of preference (magnitude). A user with 3 left preferences and 2 right preferences should see 5 dots extending outward from center, with blue/orange coloring distinguishing direction.

**Actual behavior:**
The `tasteRadarVal` function maps `right` entries to 0.5–1.0 (outward from midring) and `left` entries to 0.0–0.5 (inward toward chart center). This makes left preferences look like "no preference" since the chart center represents -1, not 0. The dashed midring represents 0 but looks like a minimum bound rather than a neutral center.

**Root cause:**
`tasteRadarVal` in `viewer_server.py` line ~4413:
```javascript
function tasteRadarVal(entry) {
  if (entry.dir === 'right') return 0.5 + entry.str * 0.5;
  return 0.5 - entry.str * 0.5;
}
```
Maps signed [-1,+1] to [0,1] radial range. Left preferences collapse toward chart center, visually indistinguishable from "uncalibrated."

**Fix:**
Change `tasteRadarVal` to return `entry.str` directly (magnitude only). Direction is already encoded in dot color (orange/blue) and label suffix (+/-). Adjust or remove the 0.5 dashed guide ring since center now represents 0.

**Verification:**
Sigil with mixed left/right entries should produce a radar where all dots extend outward from center proportional to preference strength, regardless of direction.

---

## BUG-002: Sigil overlay serves stale category scores after save

**Status:** FIXED
**Reported:** 2026-02-08
**Component:** Atlas sigil overlay (`viewer_server.py`, `handle_atlas_sigil_scores`, JS `fetchSigilScores`)

**Description:**
After saving category filter preferences (e.g. portraits strongest, everything else low) and returning to the atlas, clicking the fingerprint button shows a layout that does not reflect the new category weights.

**Repro:**
1. Go to `/categories`, set portraits strongest, save
2. Navigate to `/atlas`
3. Click fingerprint (sigil overlay) button
4. Layout does not reflect portrait-heavy category weighting

**Root cause:**
The `/api/atlas/sigil_scores` endpoint returns no `Cache-Control` headers. The browser may serve a cached HTTP response with old category weights. The JS `fetch()` call at line ~3159 uses default cache mode (no cache-buster). The `sigil_version` string includes `cat_{created_at}` timestamp so the JS-level cache key would invalidate correctly IF the server response actually arrives — but the browser HTTP cache may intercept it first.

**Reproduction attempt (2026-02-08):**
Could not reproduce on localhost. Saved portrait=100%, atlas reflected it. Changed to portrait=13%, atlas reflected the change. Version string updated correctly (`cat_1770571117` → `cat_1770571193`). Browser did not serve stale HTTP response. May require fly.dev / production conditions, or a specific browser cache state.

**Fix:**
Add `Cache-Control: no-store` headers to the `/api/atlas/sigil_scores` response. Alternatively, append a timestamp query param to the fetch URL as a cache-buster. Defensive fix even if not consistently reproducible.

---

## BUG-003: Category radar shows empty graph when no preferences exist

**Status:** FIXED
**Reported:** 2026-02-08
**Component:** Categories page (`viewer_server.py`, `/categories` HTML/JS)

**Description:**
Before calibration or after reset, the category filter page shows an empty radar graph instead of a radar with all handles at neutral (default) positions.

**Expected behavior:**
Radar chart shows all category handles at their default neutral position (e.g. midpoint), visually indicating "no preference set yet" but still rendering the full radar shape.

**Actual behavior:**
Radar graph is empty — no polygon, no handles. User sees only the grid/axes with nothing on them.

**Root cause:**
When no `categories_default.json` file exists, the JS fetches category prefs and gets a 404 or empty response. The radar drawing code doesn't fall back to default neutral values for all categories — it simply draws nothing.

**Fix:**
When no saved preferences exist, initialize all category weights to their neutral default (1.0 or equivalent) so the radar renders a full polygon at the midline. The user can then drag handles to express preferences.

---

## BUG-004: Category filter is a soft blend, not a hard filter

**Status:** FIXED
**Reported:** 2026-02-08
**Component:** `sigil_scoring.py`, `compute_category_gate()`

**Description:**
When portrait is at 100% and everything else near zero, non-portrait neighborhoods still show golden halos. The category system should act as a filter: portrait=max + others=zero means ONLY portrait tiles are highlighted.

**Root cause:**
`compute_category_gate()` computes a weighted average of normalized coordinates across ALL active categories (line 97-99). Even with cubed weights, low-weight categories (0.2^3 = 0.008) are nonzero and 10 of them collectively dilute the portrait signal. The gate becomes a soft blend, not a binary filter.

Additionally, the `normalized` value at line 93 maps node means to [0,1] using p10/p90 quantile range. A node with moderate portrait content gets normalized ~0.5, not ~0. The gate for that node ends up around 0.5, which is then multiplied with walk_score, yielding a middling final_score that still shows a partial halo.

**Expected behavior:**
Portrait=100%, others=0% should produce: portrait-heavy nodes get bright halos, non-portrait nodes are fully dimmed. The filter should be sharp — it's called "filter" not "blend."

**Fix options:**
1. Zero-gate nodes below a threshold (e.g. gate < 0.1 → gate = 0)
2. Raise gate to a higher power (gate^3 or gate^5) for sharper cutoff
3. Treat categories with weight near zero as excluded entirely (don't include in weighted average), so only high-weight categories count
4. Change semantics: weight=0 means "exclude this category" (gate contribution = 0 for matching images), weight=1 means "include" (gate contribution = 1)
