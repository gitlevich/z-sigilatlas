# Open Questions

# Conflicts

**Continuous driving vs. click navigation.** agents.md §7 specifies continuous 2D driving with smooth camera at 60fps and optional attractor overlays. The implementation uses discrete click-to-enter navigation with level transitions. ride_engine.py and ride_session.py contain ~15K LOC of dead code for continuous rides and drift policy. The code contradicts the spec. Resolution: the click-to-enter model is the authoritative behavior. The spec pages in this vault reflect the implementation, not agents.md §7. Whether continuous driving should ever be built is a product decision, not a spec conflict.

**Arcade vs. walk.** agents.md §4 specifies a three-door DoorTriplet arcade with center/median mosaics and ≤80 prompt budget. The implementation has both an arcade (arcade.py, /calibrate route) and a binary taste walk (/walk route). The walk is the primary calibration path; the arcade exists but is secondary. The prompt budget constraint (≤80, <3 minutes) from agents.md §4 applies to the arcade specifically. The walk has no explicit budget — it presents all bipolar contrasts plus optional PCA. It is unclear whether the arcade's budget constraint should apply to the walk as well.

**Minimap behavior.** BACKLOG.md item 10 states minimap click should "go up one level." The implementation navigates to root (home). Which behavior is authoritative is unresolved. The spec vault documents current behavior (home) and notes the backlog intent.

# Blocking questions

**Multi-user isolation on the client.** The server API supports arbitrary user_id parameters. The JS client hardcodes user_id="default" everywhere (BACKLOG.md item 8). This means all users of a shared deployment share one sigil. The spec vault assumes single-user behavior is current; multi-user is a future concern. If multi-user is needed, the client must be updated before the spec can define session isolation guarantees.

**Category neutral threshold value.** BUG-004 fix introduced a 0.5 threshold for category exclusion: categories at or below 0.5 are excluded from the gate. However, BUG-003 fix initializes all categories to 0.5 (neutral) when no prefs exist. This means the default state is "all categories excluded" (gate = 1.0, no filtering), which is correct. But the choice of 0.5 as the threshold is not justified by any explicit design document — it is an implementation decision. Whether this threshold should be configurable or whether a different value would be more appropriate is unexamined.

**Taste axis as a first-class contrast.** The materialized taste axis (Phase 13, BACKLOG item 2) projects the user's sigil into a single emergent "good–bad" axis. It has per-image coordinates, z-summaries, exemplars, and a radar position (pinned to north). However, it is not part of the contrast library — it is computed from the sigil, not from the corpus. Its status relative to the contrast library (is it a contrast? a derived quantity? a separate artifact type?) is not formally defined. The spec vault treats it as a rendering artifact (it appears in the taste radar) but does not attempt to classify it within the contrast taxonomy.

**Contrast ride drift policy.** agents.md §9 specifies a detailed drift policy with three resolution paths (compound, condition, reject) and declares it "must be implemented, not advisory." The implementation has ride_stats.py (z-summaries, correlations) but ride_engine.py and ride_session.py are marked as unused/dead code. The drift policy was never fully integrated into the serving path. Whether drift detection and resolution should be restored or formally dropped is unresolved.

**Dead code disposition.** ride_engine.py (~8.2K), ride_session.py (~6.5K), and parts of flythrough.py (~4.4K) are dead code. test_ride.py has 28 tests for this dead code. The spec vault does not cover dead code — it documents only observable behavior. Whether to remove this code or revive it is a product decision.

**Session persistence across builds.** agents.md §2.4 specifies that if the atlas build_id changes, the system should "rebase to nearest surviving ancestor by overlap and drop to closest valid level." The implementation persists walk progress with a library version check (version mismatch rejects saved progress) but there is no evidence of atlas build_id rebasing for navigation state. Whether this rebasing was implemented or dropped is unclear from the test suite.
