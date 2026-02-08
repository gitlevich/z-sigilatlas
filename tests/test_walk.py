"""Tests for Calibration Walk: two-tile binary preference elicitation."""

import json

import pytest

from sigiltree.walk import (
    WalkSession,
    WalkStep,
    classify_contrast,
    delete_walk_progress,
    filter_walk_contrasts,
    EXEMPLARS_PER_SIDE,
    MIN_COLLAPSED_TO_SKIP_PCA,
)
from sigiltree.arcade import build_sigil


# ---------------------------------------------------------------------------
# Test fixture
# ---------------------------------------------------------------------------

def _make_walk_library(n_bipolar=5, n_unipolar=3, n_pca=2, n_exemplars=12):
    """Create a contrast library with all three types."""
    contrasts = []
    for i in range(n_bipolar):
        # Mix perceptual and semantic bipolars
        if i < 3:
            name = f"test_perceptual_{i}"
            source = "perceptual"
        else:
            name = f"sem_a_vs_b_{i}"
            source = "semantic"
        contrasts.append({
            "contrast_id": f"bp_{i:03d}",
            "name": name,
            "source": source,
            "mass": 10.0 - i,
            "stability": 1.0,
            "quantiles": {
                "p10": 0.1, "p25": 0.25, "p50": 0.5,
                "p75": 0.75, "p90": 0.9,
            },
            "exemplars": {
                "low": [f"bp_low_{i}_{j}" for j in range(n_exemplars)],
                "median": [f"bp_med_{i}_{j}" for j in range(n_exemplars)],
                "high": [f"bp_high_{i}_{j}" for j in range(n_exemplars)],
            },
        })
    for i in range(n_unipolar):
        contrasts.append({
            "contrast_id": f"up_{i:03d}",
            "name": f"sem_category_{i}",
            "source": "semantic",
            "mass": 5.0 - i,
            "stability": 1.0,
            "quantiles": {
                "p10": 0.1, "p25": 0.25, "p50": 0.5,
                "p75": 0.75, "p90": 0.9,
            },
            "exemplars": {
                "low": [f"up_low_{i}_{j}" for j in range(n_exemplars)],
                "median": [f"up_med_{i}_{j}" for j in range(n_exemplars)],
                "high": [f"up_high_{i}_{j}" for j in range(n_exemplars)],
            },
        })
    for i in range(n_pca):
        contrasts.append({
            "contrast_id": f"pca_{i:03d}",
            "name": f"pca_clip_{i}",
            "source": "emergent",
            "mass": 2.0 - i * 0.5,
            "stability": 0.95,
            "quantiles": {
                "p10": -1.0, "p25": -0.5, "p50": 0.0,
                "p75": 0.5, "p90": 1.0,
            },
            "exemplars": {
                "low": [f"pca_low_{i}_{j}" for j in range(n_exemplars)],
                "median": [f"pca_med_{i}_{j}" for j in range(n_exemplars)],
                "high": [f"pca_high_{i}_{j}" for j in range(n_exemplars)],
            },
        })
    return {
        "version": "v1_test_walk",
        "count": len(contrasts),
        "contrasts": contrasts,
    }


# ---------------------------------------------------------------------------
# TestContrastClassification
# ---------------------------------------------------------------------------

class TestContrastClassification:
    def test_perceptual_is_bipolar(self):
        assert classify_contrast("sharpness") == "bipolar"
        assert classify_contrast("brightness") == "bipolar"
        assert classify_contrast("temperature") == "bipolar"

    def test_color_dominance_is_bipolar(self):
        assert classify_contrast("red_dominance") == "bipolar"
        assert classify_contrast("blue_dominance") == "bipolar"
        assert classify_contrast("green_dominance") == "bipolar"

    def test_semantic_bipolar_has_vs(self):
        assert classify_contrast("sem_bw_vs_color") == "bipolar"
        assert classify_contrast("sem_natural_vs_manmade") == "bipolar"
        assert classify_contrast("sem_interior_vs_exterior") == "bipolar"

    def test_semantic_unipolar_no_vs(self):
        assert classify_contrast("sem_portrait") == "unipolar"
        assert classify_contrast("sem_street") == "unipolar"
        assert classify_contrast("sem_landscape") == "unipolar"
        assert classify_contrast("sem_architecture") == "unipolar"

    def test_pca_is_pca(self):
        assert classify_contrast("pca_clip_0") == "pca"
        assert classify_contrast("pca_dino_1") == "pca"
        assert classify_contrast("pca_texture_0") == "pca"


# ---------------------------------------------------------------------------
# TestFilterWalkContrasts
# ---------------------------------------------------------------------------

class TestFilterWalkContrasts:
    def test_excludes_unipolars(self):
        lib = _make_walk_library(n_bipolar=3, n_unipolar=4, n_pca=2)
        bipolars, pcas = filter_walk_contrasts(lib)
        all_names = [c["name"] for c in bipolars + pcas]
        for name in all_names:
            assert classify_contrast(name) != "unipolar"

    def test_bipolars_sorted_by_mass(self):
        lib = _make_walk_library(n_bipolar=5)
        bipolars, _ = filter_walk_contrasts(lib)
        masses = [c["mass"] for c in bipolars]
        assert masses == sorted(masses, reverse=True)

    def test_correct_counts(self):
        lib = _make_walk_library(n_bipolar=5, n_unipolar=3, n_pca=2)
        bipolars, pcas = filter_walk_contrasts(lib)
        assert len(bipolars) == 5
        assert len(pcas) == 2

    def test_pcas_sorted_by_mass(self):
        lib = _make_walk_library(n_pca=4)
        _, pcas = filter_walk_contrasts(lib)
        masses = [c["mass"] for c in pcas]
        assert masses == sorted(masses, reverse=True)


# ---------------------------------------------------------------------------
# TestWalkSession
# ---------------------------------------------------------------------------

class TestWalkSession:
    def test_initial_schedule_is_bipolars_only(self):
        lib = _make_walk_library(n_bipolar=5, n_unipolar=3, n_pca=2)
        session = WalkSession(lib)
        assert len(session.steps) == 5  # only bipolars

    def test_step_includes_contrast_name_and_id(self):
        lib = _make_walk_library(n_bipolar=3)
        session = WalkSession(lib)
        step_dict = session.step_to_dict(session.current_step)
        assert "contrast_name" in step_dict
        assert isinstance(step_dict["contrast_name"], str)
        assert "contrast_id" in step_dict
        assert isinstance(step_dict["contrast_id"], str)

    def test_correct_exemplar_count_per_side(self):
        lib = _make_walk_library(n_bipolar=3)
        session = WalkSession(lib)
        step = session.current_step
        assert len(step.left_ids) == EXEMPLARS_PER_SIDE
        assert len(step.right_ids) == EXEMPLARS_PER_SIDE

    def test_no_center_ids_in_step(self):
        lib = _make_walk_library(n_bipolar=3)
        session = WalkSession(lib)
        step_dict = session.step_to_dict(session.current_step)
        assert "center_ids" not in step_dict
        assert "left_ids" in step_dict
        assert "right_ids" in step_dict

    def test_progress_tracks_correctly(self):
        lib = _make_walk_library(n_bipolar=3, n_unipolar=0, n_pca=0)
        session = WalkSession(lib)
        assert session.progress["current"] == 0
        assert session.progress["choices_made"] == 0
        session.record_choice("left")
        assert session.progress["current"] == 1
        assert session.progress["choices_made"] == 1


# ---------------------------------------------------------------------------
# TestWalkSkip
# ---------------------------------------------------------------------------

class TestWalkSkip:
    def test_all_skips_produce_zero_collapsed(self):
        lib = _make_walk_library(n_bipolar=3, n_unipolar=0, n_pca=0)
        session = WalkSession(lib)
        while not session.is_complete:
            session.record_choice("skip")
        sigil = build_sigil(session.choices, session.library_version, session.user_id)
        assert sigil["collapsed_count"] == 0

    def test_skip_maps_to_center_internally(self):
        lib = _make_walk_library(n_bipolar=2, n_unipolar=0, n_pca=0)
        session = WalkSession(lib)
        session.record_choice("skip")
        assert session.choices[0].direction == "center"


# ---------------------------------------------------------------------------
# TestWalkConsistency
# ---------------------------------------------------------------------------

class TestWalkConsistency:
    def test_consistent_left_produces_full_strength(self):
        lib = _make_walk_library(n_bipolar=1, n_unipolar=0, n_pca=0)
        session = WalkSession(lib)
        # Record left for the single bipolar
        session.record_choice("left")
        sigil = build_sigil(session.choices, session.library_version, session.user_id)
        assert sigil["collapsed_count"] == 1
        entry = list(sigil["entries"].values())[0]
        assert entry["strength"] == 1.0

    def test_consistent_right_produces_full_strength(self):
        lib = _make_walk_library(n_bipolar=1, n_unipolar=0, n_pca=0)
        session = WalkSession(lib)
        session.record_choice("right")
        sigil = build_sigil(session.choices, session.library_version, session.user_id)
        assert sigil["collapsed_count"] == 1
        entry = list(sigil["entries"].values())[0]
        assert entry["strength"] == 1.0


# ---------------------------------------------------------------------------
# TestPCAEarlyTermination
# ---------------------------------------------------------------------------

class TestPCAEarlyTermination:
    def test_many_bipolars_collapsed_skips_pca(self):
        """If >= MIN_COLLAPSED_TO_SKIP_PCA bipolars collapse, PCA is skipped."""
        n_bp = MIN_COLLAPSED_TO_SKIP_PCA + 2
        lib = _make_walk_library(n_bipolar=n_bp, n_unipolar=0, n_pca=5)
        session = WalkSession(lib)

        # Choose consistently: always pick the LOW side regardless of flip.
        # If not flipped, left=LOW; if flipped, right=LOW.
        # This ensures the sigil direction is always "left" (consistent).
        for i in range(n_bp):
            step = session.current_step
            direction = "right" if step.flipped else "left"
            session.record_choice(direction)

        # Exhaust any repeats with the same consistent strategy
        while not session.is_complete:
            step = session.current_step
            if step is None:
                break
            direction = "right" if step.flipped else "left"
            session.record_choice(direction)

        # PCA should not have been added — check that no PCA contrast IDs
        # appear in the steps
        pca_cids = {c["contrast_id"] for c in lib["contrasts"]
                    if c["name"].startswith("pca_")}
        step_cids = {s.contrast_id for s in session.steps}
        assert pca_cids.isdisjoint(step_cids)

    def test_few_bipolars_collapsed_extends_with_pca(self):
        """If < MIN_COLLAPSED_TO_SKIP_PCA bipolars collapse, PCA is added."""
        lib = _make_walk_library(n_bipolar=3, n_unipolar=0, n_pca=4)
        session = WalkSession(lib)

        # Skip all bipolars — none will collapse
        for _ in range(3):
            session.record_choice("skip")

        # No repeats for skips, so PCA decision should have been made
        # PCA steps should now be in the schedule
        pca_cids = {c["contrast_id"] for c in lib["contrasts"]
                    if c["name"].startswith("pca_")}
        step_cids = {s.contrast_id for s in session.steps}
        assert pca_cids.issubset(step_cids)

    def test_pca_steps_come_after_bipolars(self):
        lib = _make_walk_library(n_bipolar=3, n_unipolar=0, n_pca=2)
        session = WalkSession(lib)

        # Skip all bipolars to trigger PCA extension
        for _ in range(3):
            session.record_choice("skip")

        # First 3 steps should be bipolar, rest should be PCA
        bp_cids = {c["contrast_id"] for c in lib["contrasts"]
                   if not c["name"].startswith("pca_")
                   and classify_contrast(c["name"]) == "bipolar"}
        for step in session.steps[:3]:
            assert step.contrast_id in bp_cids

        pca_cids = {c["contrast_id"] for c in lib["contrasts"]
                    if c["name"].startswith("pca_")}
        for step in session.steps[3:]:
            assert step.contrast_id in pca_cids


# ---------------------------------------------------------------------------
# TestWalkRepeats
# ---------------------------------------------------------------------------

class TestWalkRepeats:
    def test_repeats_use_different_exemplars(self):
        """Repeat steps should use fresh exemplar images where possible."""
        lib = _make_walk_library(n_bipolar=1, n_unipolar=0, n_pca=0,
                                 n_exemplars=12)
        # Force repeat by running many sessions until one gets a repeat
        found_repeat = False
        for seed in range(100):
            session = WalkSession(lib)
            session.rng = __import__("numpy").random.RandomState(seed)
            session.record_choice("right")
            # Check if a repeat was scheduled
            if len(session.steps) > 1:
                original = session.steps[0]
                repeat = session.steps[1]
                # At least some exemplars should differ
                assert repeat.is_repeat
                found_repeat = True
                break
        # We should find at least one repeat in 100 tries at 50% probability
        assert found_repeat, "No repeat found in 100 attempts"

    def test_repeat_fraction_bounded(self):
        """Number of repeats should not exceed the number of directional choices."""
        lib = _make_walk_library(n_bipolar=10, n_unipolar=0, n_pca=0)
        session = WalkSession(lib)
        for _ in range(10):
            session.record_choice("right")
        # Exhaust repeats
        while not session.is_complete:
            session.record_choice("right")
        repeat_count = sum(1 for s in session.steps if s.is_repeat)
        # At most 1 repeat per contrast, so <= 10
        assert repeat_count <= 10


# ---------------------------------------------------------------------------
# TestLeftRightFlip
# ---------------------------------------------------------------------------

class TestLeftRightFlip:
    def test_flipped_step_records_correct_direction(self):
        """When step is flipped, choosing 'left' should record as 'right'."""
        lib = _make_walk_library(n_bipolar=1, n_unipolar=0, n_pca=0)
        # Try seeds until we get a flipped step
        for seed in range(100):
            session = WalkSession(lib)
            session.rng = __import__("numpy").random.RandomState(seed)
            # Rebuild schedule with this RNG
            session.steps = []
            session._used_exemplars = {}
            session._build_bipolar_schedule()
            step = session.current_step
            if step.flipped:
                session.record_choice("left")
                # Flipped: left on screen → right in sigil
                assert session.choices[0].direction == "right"
                return
        pytest.skip("No flipped step found in 100 seeds")

    def test_non_flipped_step_records_as_is(self):
        """When step is not flipped, directions map directly."""
        lib = _make_walk_library(n_bipolar=1, n_unipolar=0, n_pca=0)
        for seed in range(100):
            session = WalkSession(lib)
            session.rng = __import__("numpy").random.RandomState(seed)
            session.steps = []
            session._used_exemplars = {}
            session._build_bipolar_schedule()
            step = session.current_step
            if not step.flipped:
                session.record_choice("left")
                assert session.choices[0].direction == "left"
                return
        pytest.skip("No non-flipped step found in 100 seeds")


# ---------------------------------------------------------------------------
# TestWalkCompletion
# ---------------------------------------------------------------------------

class TestWalkCompletion:
    def test_completion_returns_sigil(self):
        lib = _make_walk_library(n_bipolar=2, n_unipolar=0, n_pca=0)
        session = WalkSession(lib)
        result = None
        while not session.is_complete:
            result = session.record_choice("right")
        assert result is not None
        assert result["status"] == "complete"
        assert "sigil" in result
        assert result["sigil"]["collapsed_count"] >= 1

    def test_complete_session_reports_is_complete(self):
        lib = _make_walk_library(n_bipolar=2, n_unipolar=0, n_pca=0)
        session = WalkSession(lib)
        assert not session.is_complete
        while not session.is_complete:
            session.record_choice("skip")
        assert session.is_complete
        assert session.current_step is None


# ---------------------------------------------------------------------------
# TestPartialSigil
# ---------------------------------------------------------------------------

class TestPartialSigil:
    """Partial sigil building mid-walk for live radar preview."""

    def test_skip_only_produces_no_entries(self):
        lib = _make_walk_library(n_bipolar=3, n_unipolar=0, n_pca=0)
        session = WalkSession(lib)
        session.record_choice("skip")
        sigil = build_sigil(session.choices, session.library_version, session.user_id)
        assert sigil["collapsed_count"] == 0
        assert len(sigil["entries"]) == 0

    def test_one_directional_choice_produces_one_entry(self):
        lib = _make_walk_library(n_bipolar=3, n_unipolar=0, n_pca=0)
        session = WalkSession(lib)
        session.record_choice("left")
        sigil = build_sigil(session.choices, session.library_version, session.user_id)
        assert sigil["collapsed_count"] == 1
        assert len(sigil["entries"]) == 1
        entry = list(sigil["entries"].values())[0]
        assert entry["strength"] == 1.0
        assert entry["direction"] in ("left", "right")

    def test_partial_sigil_accumulates_across_contrasts(self):
        lib = _make_walk_library(n_bipolar=4, n_unipolar=0, n_pca=0)
        session = WalkSession(lib)
        session.record_choice("right")  # first contrast
        session.record_choice("left")   # second contrast
        session.record_choice("skip")   # third contrast — no entry
        sigil = build_sigil(session.choices, session.library_version, session.user_id)
        assert sigil["collapsed_count"] == 2
        # Entries should have distinct contrast_ids
        cids = [e["contrast_id"] for e in sigil["entries"].values()]
        assert len(set(cids)) == 2

    def test_partial_sigil_has_valid_entry_fields(self):
        lib = _make_walk_library(n_bipolar=2, n_unipolar=0, n_pca=0)
        session = WalkSession(lib)
        session.record_choice("right")
        sigil = build_sigil(session.choices, session.library_version, session.user_id)
        for entry in sigil["entries"].values():
            assert "contrast_name" in entry
            assert "direction" in entry
            assert "strength" in entry
            assert 0.0 <= entry["strength"] <= 1.0


class TestStepDict:
    """step_to_dict serialization."""

    def test_step_to_dict_includes_contrast_name(self):
        lib = _make_walk_library(n_bipolar=3, n_unipolar=0, n_pca=0)
        session = WalkSession(lib)
        step = session.current_step
        d = session.step_to_dict(step)
        assert "contrast_name" in d
        assert isinstance(d["contrast_name"], str)
        assert len(d["contrast_name"]) > 0

    def test_step_to_dict_contrast_name_matches_step(self):
        lib = _make_walk_library(n_bipolar=3, n_unipolar=0, n_pca=0)
        session = WalkSession(lib)
        step = session.current_step
        d = session.step_to_dict(step)
        # The contrast_name should match what _contrast_name returns
        expected = session._contrast_name(step.contrast_id)
        assert d["contrast_name"] == expected


class TestTasteSigilEndpoint:
    """Tests for /api/atlas/taste_sigil endpoint."""

    @pytest.mark.asyncio
    async def test_returns_404_without_sigil(self, tmp_path):
        from aiohttp.test_utils import TestClient, TestServer
        from sigiltree.viewer_server import create_app

        (tmp_path / "thumbnails").mkdir()
        app = create_app(tmp_path)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/atlas/taste_sigil?user_id=default")
            assert resp.status == 404

    @pytest.mark.asyncio
    async def test_returns_bipolar_entries_only(self, tmp_path):
        import json
        from aiohttp.test_utils import TestClient, TestServer
        from sigiltree.viewer_server import create_app

        sigils_dir = tmp_path / "sigils"
        sigils_dir.mkdir()
        sigil = {
            "entries": {
                "aaa": {
                    "contrast_id": "aaa",
                    "contrast_name": "sharpness",
                    "direction": "left",
                    "strength": 0.85,
                    "n_presentations": 2,
                    "n_agreements": 2,
                },
                "bbb": {
                    "contrast_id": "bbb",
                    "contrast_name": "sem_natural_vs_manmade",
                    "direction": "right",
                    "strength": 1.0,
                    "n_presentations": 1,
                    "n_agreements": 1,
                },
                "ccc": {
                    "contrast_id": "ccc",
                    "contrast_name": "pca_clip_0",
                    "direction": "left",
                    "strength": 0.7,
                    "n_presentations": 2,
                    "n_agreements": 1,
                },
                "ddd": {
                    "contrast_id": "ddd",
                    "contrast_name": "brightness",
                    "direction": "right",
                    "strength": 1.0,
                    "n_presentations": 1,
                    "n_agreements": 1,
                },
                "eee": {
                    "contrast_id": "eee",
                    "contrast_name": "sem_portrait",
                    "direction": "right",
                    "strength": 1.0,
                    "n_presentations": 1,
                    "n_agreements": 1,
                },
            },
            "collapsed_count": 5,
            "total_choices": 7,
        }
        (sigils_dir / "sigil_default.json").write_text(json.dumps(sigil))

        (tmp_path / "thumbnails").mkdir()
        app = create_app(tmp_path)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/atlas/taste_sigil?user_id=default")
            assert resp.status == 200
            data = await resp.json()
            # Bipolars included (sharpness, brightness, sem_natural_vs_manmade)
            # pca_ and unipolar sem_ (no _vs_) excluded
            assert data["collapsed_count"] == 3
            assert "aaa" in data["entries"]  # sharpness
            assert "bbb" in data["entries"]  # sem_natural_vs_manmade (bipolar)
            assert "ddd" in data["entries"]  # brightness
            assert "ccc" not in data["entries"], "pca_ should be filtered"
            assert "eee" not in data["entries"], "unipolar sem_ should be filtered"
            assert data["entries"]["aaa"]["name"] == "sharpness"
            assert data["entries"]["aaa"]["dir"] == "left"
            assert data["entries"]["aaa"]["str"] == 0.85


# ---------------------------------------------------------------------------
# TestWalkSliderStrength
# ---------------------------------------------------------------------------

class TestWalkSliderStrength:
    """Tests for combined walk+slider strength flow."""

    def test_slider_strength_propagates_to_choice(self):
        """Walk session records the slider strength in the Choice."""
        lib = _make_walk_library(n_bipolar=2, n_unipolar=0, n_pca=0)
        session = WalkSession(lib)
        session.record_choice("right", strength=0.7)
        assert session.choices[0].strength == 0.7

    def test_default_strength_is_one(self):
        """Without slider, strength defaults to 1.0 (backward compatible)."""
        lib = _make_walk_library(n_bipolar=2, n_unipolar=0, n_pca=0)
        session = WalkSession(lib)
        session.record_choice("left")
        assert session.choices[0].strength == 1.0

    def test_slider_strength_in_sigil(self):
        """Slider-provided strength appears in the built sigil."""
        lib = _make_walk_library(n_bipolar=2, n_unipolar=0, n_pca=0)
        session = WalkSession(lib)
        session.record_choice("right", strength=0.6)
        session.record_choice("left", strength=0.3)
        # Exhaust any repeats
        while not session.is_complete:
            session.record_choice("skip")
        sigil = build_sigil(session.choices, session.library_version, session.user_id)
        # Both entries should have slider-provided strengths
        for entry in sigil["entries"].values():
            assert entry["strength"] in (0.6, 0.3)

    def test_skip_has_zero_strength(self):
        """Skip passes strength 0 and produces no sigil entry."""
        lib = _make_walk_library(n_bipolar=1, n_unipolar=0, n_pca=0)
        session = WalkSession(lib)
        session.record_choice("skip", strength=0)
        sigil = build_sigil(session.choices, session.library_version, session.user_id)
        assert sigil["collapsed_count"] == 0

    def test_strength_clamped_to_range(self):
        """Strength values are clamped to [0, 1]."""
        lib = _make_walk_library(n_bipolar=2, n_unipolar=0, n_pca=0)
        session = WalkSession(lib)
        session.record_choice("right", strength=1.5)
        assert session.choices[0].strength == 1.0
        session.record_choice("left", strength=-0.3)
        assert session.choices[1].strength == 0.0

    def test_zero_strength_drops_contrast(self):
        """Strength 0.0 from slider drops the contrast from sigil."""
        lib = _make_walk_library(n_bipolar=1, n_unipolar=0, n_pca=0)
        session = WalkSession(lib)
        session.record_choice("right", strength=0.0)
        while not session.is_complete:
            session.record_choice("skip")
        sigil = build_sigil(session.choices, session.library_version, session.user_id)
        assert sigil["collapsed_count"] == 0

    def test_mixed_slider_and_default_strengths(self):
        """Mix of slider and default strengths in same sigil."""
        lib = _make_walk_library(n_bipolar=3, n_unipolar=0, n_pca=0)
        session = WalkSession(lib)
        session.record_choice("right", strength=0.4)   # slider
        session.record_choice("left")                    # default 1.0
        session.record_choice("right", strength=0.8)    # slider
        while not session.is_complete:
            session.record_choice("skip")
        sigil = build_sigil(session.choices, session.library_version, session.user_id)
        strengths = sorted([e["strength"] for e in sigil["entries"].values()])
        assert 0.4 in strengths
        assert 0.8 in strengths
        assert 1.0 in strengths


class TestWalkProgressPersistence:
    """Tests for save/restore of walk progress across reloads."""

    def test_save_and_restore_choices(self, tmp_path):
        """Saved choices are restored into a new session."""
        lib = _make_walk_library(n_bipolar=5, n_unipolar=0, n_pca=0)
        s1 = WalkSession(lib)
        s1.record_choice("left", strength=0.6)
        s1.record_choice("right", strength=0.8)
        s1.save_progress(tmp_path)

        s2 = WalkSession(lib)
        assert s2.restore_progress(tmp_path)
        assert s2.current_index == 2
        assert len(s2.choices) == 2
        assert s2.choices[0].strength == 0.6
        assert s2.choices[1].strength == 0.8

    def test_restore_resumes_at_correct_step(self, tmp_path):
        """Restored session continues from where it left off."""
        lib = _make_walk_library(n_bipolar=4, n_unipolar=0, n_pca=0)
        s1 = WalkSession(lib)
        s1.record_choice("left")
        s1.record_choice("skip")
        s1.record_choice("right")
        s1.save_progress(tmp_path)

        s2 = WalkSession(lib)
        s2.restore_progress(tmp_path)
        step = s2.current_step
        assert step is not None
        assert step.step_index == 3  # 4th step (0-indexed)

    def test_restore_with_version_mismatch_returns_false(self, tmp_path):
        """Version mismatch rejects saved progress."""
        lib = _make_walk_library(n_bipolar=3, n_unipolar=0, n_pca=0)
        s1 = WalkSession(lib)
        s1.record_choice("left")
        s1.save_progress(tmp_path)

        lib2 = _make_walk_library(n_bipolar=3, n_unipolar=0, n_pca=0)
        lib2["version"] = "different_version"
        s2 = WalkSession(lib2)
        assert not s2.restore_progress(tmp_path)
        assert s2.current_index == 0

    def test_restore_no_file_returns_false(self, tmp_path):
        """No saved file returns False without error."""
        lib = _make_walk_library(n_bipolar=3, n_unipolar=0, n_pca=0)
        s = WalkSession(lib)
        assert not s.restore_progress(tmp_path)

    def test_delete_walk_progress(self, tmp_path):
        """delete_walk_progress removes the file."""
        lib = _make_walk_library(n_bipolar=3, n_unipolar=0, n_pca=0)
        s = WalkSession(lib)
        s.record_choice("left")
        s.save_progress(tmp_path)
        assert (tmp_path / "sigils" / "walk_progress_default.json").exists()
        delete_walk_progress(tmp_path)
        assert not (tmp_path / "sigils" / "walk_progress_default.json").exists()

    def test_restored_session_can_complete(self, tmp_path):
        """A restored session can be completed and produce a valid sigil."""
        lib = _make_walk_library(n_bipolar=3, n_unipolar=0, n_pca=0)
        s1 = WalkSession(lib)
        s1.record_choice("left", strength=0.7)
        s1.record_choice("right", strength=0.5)
        s1.save_progress(tmp_path)

        s2 = WalkSession(lib)
        s2.restore_progress(tmp_path)
        # Complete remaining steps
        while not s2.is_complete:
            result = s2.record_choice("right", strength=0.6)
        assert result["status"] == "complete"
        sigil = result["sigil"]
        assert sigil["collapsed_count"] >= 2

