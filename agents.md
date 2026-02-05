# IMPLEMENTATION SPEC (SIGIL) — Multiscale Atlas Viewer + Calibration Arcade

## Audience: coding agent implementing an end-to-end runnable local-first app

§0 Scope

Build a local-first application that ingests an image corpus, computes multiple embedding families, discovers contrasts that actually exist in the corpus, constructs a multiscale self-similar atlas ("sigil tree") rendered as a rectangular mosaic, and provides two core experiences: (1) continuous driving/zooming through the atlas, and (2) a calibration arcade that collapses user preference only when the user explicitly turns left/right on obvious contrast doors; straight/center preserves superposition.

§1 Global invariants (must hold in every phase)

§1.1 Continuity. Enter/zoom expands the region the user is aiming at. Exiting restores the parent view without global re-layout jumps.

§1.2 Reserve attention. From any depth, the user can return to a wider atlas view in one action, within a hard time bound. The system must not create "event horizon" stickiness.

§1.3 No passive profiling. Never infer preference from dwell time, hovering, or viewport exposure. Only explicit actions may update preference state.

§1.4 Superposition is not zero. "Center/straight" means "do not record a preference." It is not a neutral weight.

§2 Architecture commitments (apply immediately, shape all downstream work)

§2.1 Atlas topology is sigil-independent. The atlas is built from the corpus only and versioned by build id. User sigils never change atlas construction or layout. Sigils only affect rendering overlays and optional guidance, never the underlying tile content.

§2.2 Containment + visual coherence. Use a containment-preserving layout family for every level: ordered treemap rectangles that partition parent rectangles exactly. Achieve "embedding-like" coherence by computing a stable ordering from an embedding-derived 2D projection (or neighbor graph traversal) and feeding that 1D order into an ordered squarified treemap (or equivalent). Containment comes from treemap; coherence comes from ordering.

§2.3 Sigil-aware rendering must be overlay-only. Tile streaming and tile selection are purely geometric and sigil-independent. Sigil effects are per-node overlays derived from node summary statistics (brighten/dim/halo/edge emphasis/attractor arrows). This keeps 60fps feasible and prevents hidden content swapping.

§2.4 Session persistence. Persist navigation state as (atlas_build_id, node path from root, camera pose, cursor pose, current mode, active sigil id). On reopen: if build id matches, restore exactly; if not, rebase to nearest surviving ancestor by overlap and drop to closest valid level.

§3 Data artifacts (versioned, incremental)

Artifacts live in an artifact directory. Everything is incremental and resumable.

Required artifacts: metadata DB; thumbnails at multiple sizes; embedding shards per family; contrast library (versioned); per-image contrast coordinates; atlas pyramid (levels, nodes, rectangles, neighbor edges, representative tiles); user sigils; session state.

§4 Cross-cutting invariant test suite

This suite runs after every phase. Each phase declares which probes are applicable and which are not yet testable. A probe that is applicable must pass. A probe that is not yet testable (because the relevant subsystem does not exist) is marked N/A for that phase but becomes applicable as soon as the subsystem ships and remains applicable in all subsequent phases. Later phases may not weaken invariant compliance; regressions are blocking defects.

§4.1 Continuity probe. Choose a node rectangle R at level L, enter it, and verify that (a) the camera target stays anchored to R within tolerance and (b) the child view renders inside R with no global permutation.

§4.2 Reserve attention probe. From maximum available depth, perform one exit action and verify the parent view returns within a hard bound (250 ms warm, 1 s cold) and without additional confirmations.

§4.3 No passive profiling probe. Replay a navigation trace with only camera motion and no explicit turn events; verify the sigil file does not change. If no sigil file exists yet, verify that no sigil file is created (vacuously true).

§4.4 Center-means-no-write probe. In calibration, run a sequence of center choices; verify the sigil records nothing for those contrasts. Not applicable until calibration UI exists.

§4.5 Event horizon gate (global). From any depth, in ≤ 1 second and ≤ 1 action, the user can return to a wider atlas view that restores broad superposition.

PHASE 1 — Corpus ingestion and thumbnails

Goal: index images and create durable, incremental artifacts.

Deliverables: CLI command `index <corpus_path> <artifact_dir>` that catalogs images into a SQLite metadata DB (image_id, path, dimensions, EXIF time where available, checksum) and generates thumbnails at multiple fixed sizes (64, 128, 256, 512) persisted to artifact_dir. A minimal grid viewer that renders thumbnails from the DB.

Accepted when:

- Running index twice without changes performs no recomputation. Logs must show reuse; thumbnail file timestamps must not change on second run.
- Adding 100 new images and deleting 100 updates only those deltas. No full reindex.
- The viewer can scroll a 10k-thumbnail grid without multi-second stalls.
- Opening any 20 randomly sampled thumbnails confirms correct match to source files.
- Invariant probes: §4.3 applicable (vacuously true: verify no sigil file is created during index or grid browsing). §4.1 N/A (no atlas levels). §4.2 N/A (no atlas levels). §4.4 N/A (no calibration). §4.5 N/A (no atlas levels).

PHASE 2 — Embedding families

Goal: compute at least three complementary embedding families, persisted and queryable.

Required families: semantic (CLIP-like), structural (DINO-like), texture/scale (wavelet or multiscale descriptor).

Deliverables: CLI command `embed <artifact_dir>` computing all families incrementally. Memory-mappable embedding store keyed by (image_id, family_id). Per-family nearest-neighbor query tool: `nn --family <id> --image <image_id> --k 20`.

Accepted when:

- All indexed images have embeddings for each family.
- Embeddings are stored in a format that can be queried without loading everything into memory.
- NN queries return within bounded latency on a medium corpus (under 250 ms for k=20 after warm cache).
- Qualitative spot checks on 10 random images confirm family-specific neighbor behavior: semantic neighbors share content, structural neighbors share composition/shape, texture neighbors share grain/scale.
- Re-running embed after adding new images computes only the new embeddings.
- Invariant probes: §4.3 applicable (vacuously true). §4.1 N/A. §4.2 N/A. §4.4 N/A. §4.5 N/A.

PHASE 3 — Contrast discovery and selection (mass + stability)

Goal: discover contrasts that exist with mass and stability in this corpus and select a compact library.

Sources of contrasts: perceptual (temperature, tint, tonality/high-key vs low-key, saturation, global contrast, texture scale, sharpness/blur, motion where detectable); semantic unipolar categories from a curated prompt list (start small: portrait, landscape, street, architecture, nature, abstract, night, interior); optional emergent directions from embedding families (PCA/ICA, bounded count).

Selection rules: Mass — score distribution spans meaningful range (quantiles well-separated). Stability — direction/measure stable under subsampling; correlation of per-image scores between full corpus and 50% subsample must exceed 0.9 for kept contrasts.

Deliverables: CLI command `contrasts build <artifact_dir>`. Versioned `contrast_library.json` describing each contrast and its metadata. Per-image scalar coordinates for each kept contrast. Per-contrast quantiles and exemplar sets for low/median/high bands.

Accepted when:

- Library size is bounded (target 20–60 for v1).
- For the top 10 contrasts by mass, low vs high exemplar mosaics are obviously distinct at a glance.
- Stability check passes for all kept contrasts (subsample correlation > 0.9).
- Rebuilding contrasts with unchanged embeddings is incremental.
- Invariant probes: §4.3 applicable (vacuously true). §4.1 N/A. §4.2 N/A. §4.4 N/A. §4.5 N/A.

PHASE 4 — Calibration Arcade (three-door collapse)

Goal: quickly collapse only the contrasts the user is sensitive to, via easy, obvious door choices.

Interaction: each prompt is a DoorTriplet(contrast_id, left, center, right). Left/right are extreme quantile exemplar mosaics; center is median band mosaic. Controls: LEFT chooses left, RIGHT chooses right, FORWARD chooses center. Center explicitly records nothing. Each choice advances immediately.

Interaction budget: a v1 arcade session is ≤ 80 prompts total including repeats. Target completion time under 3 minutes.

Reliability and repeat schedule: repeats are interleaved during the arcade flow. Constraints on repeats:

- Repeats must not exceed 20% of total prompts in a session.
- Minimum gap between a contrast's first presentation and its repeat is 5 other prompts.
- Maximum repeats per contrast is 2.
- Repeat probability is biased toward contrasts the user turned on (left/right) and toward high-mass contrasts; contrasts the user centered are repeated at most once.
- Repeats use different exemplar images drawn from the same quantile slices.
- Inconsistent repeats (direction disagreement across presentations) decay or drop that contrast from the sigil.

Sigil recording: left/right records preference sign and strength. Center records nothing. Dwell time is never used.

Deliverables: calibration UI; persisted `sigil_<user>.json` tied to (contrast_library_version, atlas_build_id); replay/summary view of collapsed contrasts after calibration.

Accepted when:

- A full pass (≤ 80 prompts including repeats) completes in under 3 minutes and produces a sparse sigil (only a minority of contrasts collapsed).
- Center choices produce no writes to the sigil.
- Repeated contrasts for obvious axes show ≥ 80% direction agreement.
- Inconsistent axes are automatically cooled (not recorded or decayed).
- Invariant probes: §4.3 applicable (verify browsing calibration mosaics without choosing does not write to sigil). §4.4 now applicable (center choices produce no sigil writes). §4.1 N/A. §4.2 N/A. §4.5 N/A.

PHASE 5 — Atlas Level 0 (whole-corpus mosaic)

Goal: render the entire corpus as one rectangular mosaic of neighborhoods, containment-ready.

Construction: build a fused neighbor graph across embedding families. Cluster into coarse neighborhoods with meaningful mass. Compute a 2D projection for ordering (e.g., UMAP of fused embeddings), then derive a stable 1D order (space-filling curve index or graph traversal). Lay out neighborhoods using ordered squarified treemap into stable rectangles that partition the full atlas frame exactly.

Rendering: each neighborhood rectangle shows a mosaic proxy (micro-thumbnails or representative collage) that reads as texture/pattern at the overview scale.

Determinism tolerance: on unchanged inputs, rebuilds must produce layouts where ≥ 95% of node rectangles have IoU ≥ 0.98 with the previous build, and the 1D ordering has Kendall tau ≥ 0.99 with the previous ordering. If the layout algorithm involves stochastic steps (e.g., UMAP), pin random seeds per build and store them in the atlas metadata. Violations of these thresholds are defects.

Deliverables: CLI command `atlas build --levels 1 <artifact_dir>`. Atlas level 0 artifacts (nodes, rectangles, neighbor edges, representative tiles). Viewer with pan/cursor and node preview on click.

Accepted when:

- The entire corpus is visible in one rectangular frame as a patterned mosaic.
- Clicking neighborhoods yields coherent internal samples (a human can say "yes, these belong together" for most).
- Determinism tolerance holds across rebuilds on unchanged inputs.
- Panning is interactive with progressive tile loading.
- Invariant probes: §4.1 applicable (entering a neighborhood must anchor camera to it). §4.2 applicable (exit from level 0 is trivially instant). §4.3 applicable. §4.4 applicable. §4.5 applicable.

PHASE 6 — Multiscale Atlas Pyramid (sigil tree)

Goal: build multiple levels where each node contains a child atlas that partitions the node's rectangle exactly.

Construction: for each node at level L, compute residual structure within its images and split into child neighborhoods. Derive ordering for children from local embedding structure. Lay out children via ordered treemap that partitions the parent rectangle exactly. Store neighbor edges per level.

Viewer: enter expands the node's rectangle and reveals child atlas inside it. Exit returns to parent instantly. Maintain a persistent mini-map or peripheral overview indicating parent context.

Deliverables: `atlas build --levels N <artifact_dir>` for N ≥ 4. Viewer with enter/exit transitions. Debug overlay showing level, node id, parent id, child count, and child rectangle partition boundaries.

Accepted when:

- Enter/exit transitions exhibit strict containment: entering expands the aimed region and reveals children inside the same rectangle; exiting returns to parent without re-layout jumps.
- Exit latency does not degrade with depth: exiting remains instant (within reserve attention bound) from any level.
- Debug overlay makes containment violations and stale parent references immediately obvious.
- All invariant probes applicable and pass.

PHASE 7 — Driving (continuous navigation) + optional guidance

Goal: implement the "just drive" experience with smooth continuous controls.

Controls: continuous 2D steering in atlas plane; continuous forward/back for zoom velocity; enter/exit also available as discrete actions. Smooth camera motion at display refresh rate while streaming tiles.

Guidance (optional): overlay-level suggestion only (brightening, arrows, gentle camera nudges). May use only explicit actions (turns, enter/exit, arcade choices) as input. Must be bounded in strength. Must decay without continued explicit reinforcement. Must never prevent exit or increase exit friction.

Deliverables: smooth camera and tile streaming targeting 60fps during motion. Optional attractor overlays. "Fight the guide" must remain easy.

Accepted when:

- Driving feels continuous with no stepping or jumping.
- Frame pacing is close to display refresh during motion on a medium corpus.
- If guidance is implemented, it is provably driven only by explicit actions and decays without reinforcement.
- "Fight the guide" test passes: user can always steer away and exit without additional friction.
- Reserve attention probe remains green under active guidance.
- All invariant probes applicable and pass.

PHASE 8 — Sigil rendering ("beauty gravity")

Goal: apply the calibrated sigil to bias visual salience without changing topology or swapping content.

Rules: only collapsed contrasts in the sigil affect overlays. Uncollapsed contrasts remain superposed and must not bias anything. Bias is visual and navigational suggestion, not forced filtering. The world remains fully navigable with sigil active.

Implementation: compute per-node compatibility with the sigil using node summary statistics for collapsed contrasts only. Apply as brighten/dim/halo overlays. Optionally suggest direction via attractor arrows. Never hard-filter unless the user explicitly requests it.

Deliverables: sigil toggle on/off; per-node overlay shading; per-node "why" debug readout showing contributions from collapsed contrasts only.

Accepted when:

- Toggling sigil causes immediate, intuitive salience shifts aligned with the user's arcade turns.
- A sigil with only one collapsed contrast produces changes aligned to that contrast and does not systematically shift unrelated axes.
- Uncollapsed contrasts produce no effect on overlays.
- The world remains navigable with sigil on.
- All invariant probes applicable and pass.

PHASE 9 — Contrast rides (continuous morph) with drift policy

Goal: provide continuous calibration rides as an alternative to door triplets, with honest handling of correlated contrasts.

Ride definition: pick contrast c. Sweep a target parameter t from low → high quantiles of c. Traverse atlas nodes to approximate monotone change in c.

Drift computation (must be cheap at runtime): during atlas build, precompute per-node z-score summaries (mean, stddev) for each kept contrast and store them in the atlas artifacts. During a ride, measure drift as the difference in node-level z-means for locked contrasts along the ride path. This avoids per-image scans at ride time.

Drift policy (must be implemented, not advisory). Each ride declares a lock-set L (contrasts to hold stable) and a drift tolerance per locked contrast. Before the ride begins, the system computes expected drift from the corpus correlation structure using the precomputed node summaries. Resolution paths when drift exceeds tolerance:

- Compound: promote the ride to explicitly show both c and the drifting contrast. The user sees and consents to a two-axis ride.
- Condition: restrict the ride to a subregion of the atlas where the correlation is weaker (e.g., hold brightness to a narrow band). The restriction is shown to the user.
- Reject: declare c non-calibratable as a single-axis ride in this corpus and keep c superposed. The user is told why.
The system must never silently present a multi-axis ride as single-axis.

Deliverables: ride UI; drift monitor overlay showing real-time drift in locked contrasts; band recording with identical semantics to arcade (only explicit approach/retreat collapses; silence keeps superposed).

Accepted when:

- Rides feel perceptually single-axis in typical cases.
- Drift is measured in real time using precomputed node z-summaries; the sum of absolute z-score changes across locked contrasts stays within the declared tolerance most of the time.
- When drift is structurally unavoidable, the system applies one of the three resolution paths (compound/condition/reject) and does not silently proceed.
- Repeated rides for the same contrast produce stable bands when collapsible (same band within tolerance across runs).
- If stable bands cannot be produced, the contrast remains uncollapsed.
- All invariant probes applicable and pass.

PHASE 10 — Robustness, performance, packaging

Goal: make the system usable at realistic corpus scale with clean operational behavior.

Requirements: incremental rebuilds for all pipeline steps (index, embed, contrasts, atlas). Artifact versioning: rebuilds produce new versions without destroying previous ones unless explicitly pruned. Streaming tiles with no blocking on the main UI thread. Graceful handling of corrupt images, missing files, partial embeddings (log, skip, offer repair path). Session restore as specified in §2.4. Clear README with commands for each phase and verification procedures.

Accepted when:

- A medium corpus (target 50k+ images) remains interactive for browsing, driving, and calibration.
- Rebuilds preserve prior artifact versions unless explicitly pruned.
- Adding images and rebuilding is incremental (no "start over" events).
- Session restore returns to prior navigation state or cleanly rebases across builds.
- Failures (missing files, corrupt images, partial embeddings) are handled without crashing, with clear logs and repair/rebuild paths.
- All invariant probes applicable and pass on cold and warm starts.

Operational stop rule

A phase is done only when its acceptance criteria and all applicable invariant probes pass. Later phases may not weaken invariants; regressions are blocking defects. If any phase fails its verification, fix it before implementing later phases.
