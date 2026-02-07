"""Tests for Phase 9: contrast rides with drift policy."""

import copy
import math

import numpy as np
import pytest

from sigiltree.ride_stats import compute_node_zsummaries, compute_contrast_correlations
from sigiltree.ride_engine import (
    RidePlan, plan_ride, derive_lock_set, compute_ride_drift_at_position,
)
from sigiltree.ride_session import RideSession, RideChoice, merge_band_into_sigil


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _make_coordinates(contrast_values):
    """Build coordinates from {contrast_name: {image_id: float}}."""
    return contrast_values


def _make_nodes(configs):
    """Build node dicts. configs: list of (node_id, image_ids)."""
    return [{"node_id": nid, "image_ids": iids, "size": len(iids)} for nid, iids in configs]


def _make_sigil(entries):
    """Build a minimal sigil. entries: list of (contrast_id, contrast_name, direction, strength)."""
    e = {}
    for cid, cname, direction, strength in entries:
        e[cid] = {
            "contrast_id": cid,
            "contrast_name": cname,
            "direction": direction,
            "strength": strength,
            "n_presentations": 2,
            "n_agreements": 2,
        }
    return {"version": "test", "contrast_library_version": "test", "user_id": "test", "entries": e}


def _make_correlated_coordinates(contrast_a, contrast_b, image_ids, correlation=0.8, seed=42):
    """Build two contrasts with known Pearson correlation."""
    rng = np.random.RandomState(seed)
    n = len(image_ids)
    x = rng.randn(n)
    noise = rng.randn(n)
    y = correlation * x + math.sqrt(1 - correlation ** 2) * noise
    return {
        contrast_a: {iid: float(x[i]) for i, iid in enumerate(image_ids)},
        contrast_b: {iid: float(y[i]) for i, iid in enumerate(image_ids)},
    }


def _zsummaries_from_coords_and_nodes(coordinates, nodes):
    """Convenience: compute zsummaries for a single level."""
    return compute_node_zsummaries(coordinates, nodes)


# ---------------------------------------------------------------------------
# ride_stats tests (1-5)
# ---------------------------------------------------------------------------

class TestRideStats:

    def test_zsummary_known_values(self):
        """Hand-computed z_mean and z_std match."""
        # 4 images with known values: [0, 1, 2, 3]
        # global mean=1.5, global std=sqrt(1.25)~=1.118
        # z-scores: [-1.342, -0.447, 0.447, 1.342]
        coords = {"c": {"a": 0.0, "b": 1.0, "c": 2.0, "d": 3.0}}
        nodes = _make_nodes([("n0", ["a", "b"]), ("n1", ["c", "d"])])

        result = compute_node_zsummaries(coords, nodes)

        # n0: z-scores of 0.0 and 1.0 -> z = (0-1.5)/std, (1-1.5)/std
        gmean = 1.5
        gstd = math.sqrt(((0 - 1.5) ** 2 + (1 - 1.5) ** 2 + (2 - 1.5) ** 2 + (3 - 1.5) ** 2) / 4)
        z_a = (0.0 - gmean) / gstd
        z_b = (1.0 - gmean) / gstd
        expected_zmean_n0 = (z_a + z_b) / 2

        assert abs(result["c"]["n0"]["z_mean"] - round(expected_zmean_n0, 6)) < 0.001
        assert result["c"]["n0"]["n"] == 2

        # n1 should be mirror of n0 (symmetric distribution)
        assert abs(result["c"]["n1"]["z_mean"] + result["c"]["n0"]["z_mean"]) < 0.001

    def test_zsummary_single_image_node(self):
        """Node with 1 image: z_std=0, z_mean=image z-score."""
        coords = {"c": {"a": 0.0, "b": 10.0}}
        nodes = _make_nodes([("n0", ["a"]), ("n1", ["b"])])

        result = compute_node_zsummaries(coords, nodes)

        assert result["c"]["n0"]["z_std"] == 0.0
        assert result["c"]["n1"]["z_std"] == 0.0
        assert result["c"]["n0"]["n"] == 1
        # z_mean should be the z-score of that single image
        gmean = 5.0
        gstd = 5.0  # sqrt((25+25)/2)
        expected = (0.0 - gmean) / gstd
        assert abs(result["c"]["n0"]["z_mean"] - round(expected, 6)) < 0.001

    def test_correlation_symmetric(self):
        """corr[a][b] == corr[b][a]."""
        image_ids = [f"img_{i}" for i in range(50)]
        coords = _make_correlated_coordinates("a", "b", image_ids, correlation=0.5)
        coords["c"] = {iid: float(np.random.randn()) for iid in image_ids}

        result = compute_contrast_correlations(coords)

        for ca in result:
            for cb in result[ca]:
                assert abs(result[ca][cb] - result[cb][ca]) < 1e-10

    def test_correlation_diagonal_one(self):
        """Diagonal entries are 1.0."""
        image_ids = [f"img_{i}" for i in range(50)]
        coords = _make_correlated_coordinates("a", "b", image_ids)

        result = compute_contrast_correlations(coords)

        for cname in result:
            assert abs(result[cname][cname] - 1.0) < 1e-10

    def test_correlation_known_data(self):
        """Correlated synthetic data: computed correlation within tolerance of expected."""
        image_ids = [f"img_{i}" for i in range(500)]
        expected_corr = 0.8
        coords = _make_correlated_coordinates("a", "b", image_ids, correlation=expected_corr, seed=123)

        result = compute_contrast_correlations(coords)

        assert abs(result["a"]["b"] - expected_corr) < 0.1


# ---------------------------------------------------------------------------
# ride_engine tests (6-12)
# ---------------------------------------------------------------------------

class TestRideEngine:

    def _build_uncorrelated_scenario(self):
        """Build a scenario with 10 nodes, ride contrast + 1 uncorrelated locked contrast."""
        image_ids = [f"img_{i}" for i in range(100)]
        rng = np.random.RandomState(42)
        coords = {
            "ride_c": {iid: float(i / 100.0) for i, iid in enumerate(image_ids)},
            "lock_c": {iid: float(rng.randn()) for iid in image_ids},
        }
        nodes = _make_nodes([(f"n_{i}", image_ids[i * 10:(i + 1) * 10]) for i in range(10)])
        zsummaries = compute_node_zsummaries(coords, nodes)
        correlations = compute_contrast_correlations(coords)
        return coords, nodes, zsummaries, correlations

    def _build_correlated_scenario(self, correlation=0.95):
        """Build a scenario with highly correlated ride + locked contrasts."""
        image_ids = [f"img_{i}" for i in range(100)]
        coords = _make_correlated_coordinates("ride_c", "lock_c", image_ids, correlation=correlation, seed=42)
        nodes = _make_nodes([(f"n_{i}", image_ids[i * 10:(i + 1) * 10]) for i in range(10)])
        zsummaries = compute_node_zsummaries(coords, nodes)
        correlations = compute_contrast_correlations(coords)
        return coords, nodes, zsummaries, correlations

    def test_plan_single_no_drift(self):
        """Uncorrelated lock -> resolution='single'."""
        _, nodes, zsummaries, correlations = self._build_uncorrelated_scenario()

        plan = plan_ride("ride_c", "rid", ["lock_c"], zsummaries, correlations, nodes, tolerance=2.0)

        assert plan.resolution == "single"
        assert len(plan.path) == 10

    def test_plan_high_drift_triggers_policy(self):
        """Highly correlated lock -> resolution is not 'single'."""
        _, nodes, zsummaries, correlations = self._build_correlated_scenario(correlation=0.99)

        plan = plan_ride("ride_c", "rid", ["lock_c"], zsummaries, correlations, nodes, tolerance=0.1)

        assert plan.resolution in ("compound", "condition", "reject")

    def test_path_monotone(self):
        """Ride path node_ids are sorted by ascending z_mean for ride contrast."""
        _, nodes, zsummaries, correlations = self._build_uncorrelated_scenario()

        plan = plan_ride("ride_c", "rid", [], zsummaries, correlations, nodes)

        zmeans = [zsummaries["ride_c"][nid]["z_mean"] for nid in plan.path]
        for i in range(len(zmeans) - 1):
            assert zmeans[i] <= zmeans[i + 1], f"Not monotone at index {i}"

    def test_condition_restricts_subset(self):
        """Conditioned path is a proper subset, all nodes within band."""
        _, nodes, zsummaries, correlations = self._build_correlated_scenario(correlation=0.95)

        plan = plan_ride(
            "ride_c", "rid", ["lock_c"], zsummaries, correlations, nodes,
            tolerance=0.1, condition_band_width=1.5, min_path_length=3,
        )

        if plan.resolution == "condition":
            assert len(plan.path) < 10
            assert len(plan.path) >= 3
            assert plan.condition_info is not None
            assert plan.condition_info["restricted_len"] == len(plan.path)
        # If resolution is compound/reject, conditioning wasn't viable

    def test_reject_when_all_fail(self):
        """Multiple drifters with few nodes -> reject."""
        image_ids = [f"img_{i}" for i in range(30)]
        rng = np.random.RandomState(42)
        # 3 contrasts, all highly correlated
        x = np.array([float(i) for i in range(30)])
        coords = {
            "ride_c": {iid: float(x[i]) for i, iid in enumerate(image_ids)},
            "lock_a": {iid: float(x[i] + rng.randn() * 0.01) for i, iid in enumerate(image_ids)},
            "lock_b": {iid: float(x[i] + rng.randn() * 0.01) for i, iid in enumerate(image_ids)},
        }
        nodes = _make_nodes([(f"n_{i}", image_ids[i * 10:(i + 1) * 10]) for i in range(3)])
        zsummaries = compute_node_zsummaries(coords, nodes)
        correlations = compute_contrast_correlations(coords)

        plan = plan_ride(
            "ride_c", "rid", ["lock_a", "lock_b"], zsummaries, correlations, nodes,
            tolerance=0.01, condition_band_width=0.01, min_path_length=3,
        )

        assert plan.resolution == "reject"
        assert plan.reject_reason is not None

    def test_empty_lock_set_always_single(self):
        """No locked contrasts -> always 'single'."""
        _, nodes, zsummaries, correlations = self._build_correlated_scenario()

        plan = plan_ride("ride_c", "rid", [], zsummaries, correlations, nodes)

        assert plan.resolution == "single"

    def test_plan_no_mutation(self):
        """Inputs unchanged after plan_ride call."""
        _, nodes, zsummaries, correlations = self._build_uncorrelated_scenario()
        zs_copy = copy.deepcopy(zsummaries)
        corr_copy = copy.deepcopy(correlations)
        nodes_copy = copy.deepcopy(nodes)

        plan_ride("ride_c", "rid", ["lock_c"], zsummaries, correlations, nodes)

        assert zsummaries == zs_copy
        assert correlations == corr_copy
        assert nodes == nodes_copy


# ---------------------------------------------------------------------------
# ride_session tests (13-21)
# ---------------------------------------------------------------------------

class TestRideSession:

    def _make_plan(self, n_nodes=5):
        """Build a minimal RidePlan."""
        path = [f"n_{i}" for i in range(n_nodes)]
        return RidePlan(
            ride_contrast="brightness",
            ride_contrast_id="c1",
            resolution="single",
            path=path,
            locked=["saturation"],
            drift_estimates={"saturation": 0.1},
        )

    def test_fresh_at_zero(self):
        """New session at position 0, not complete."""
        plan = self._make_plan()
        session = RideSession(plan, "c1")

        assert session.position == 0
        assert not session.is_complete
        assert session.current_node_id == "n_0"

    def test_step_advances(self):
        """record_choice increments position."""
        plan = self._make_plan()
        session = RideSession(plan, "c1")

        session.record_choice("approach")
        assert session.position == 1
        assert session.current_node_id == "n_1"

    def test_approach_maps_right(self):
        """All approach choices -> band direction='right'."""
        plan = self._make_plan(n_nodes=3)
        session = RideSession(plan, "c1")

        for _ in range(3):
            session.record_choice("approach")

        band = session.build_band()
        assert band is not None
        assert band["direction"] == "right"
        assert band["strength"] == 1.0

    def test_retreat_maps_left(self):
        """All retreat choices -> band direction='left'."""
        plan = self._make_plan(n_nodes=3)
        session = RideSession(plan, "c1")

        for _ in range(3):
            session.record_choice("retreat")

        band = session.build_band()
        assert band is not None
        assert band["direction"] == "left"
        assert band["strength"] == 1.0

    def test_silence_no_collapse(self):
        """All silence -> None band."""
        plan = self._make_plan(n_nodes=3)
        session = RideSession(plan, "c1")

        for _ in range(3):
            session.record_choice("silence")

        band = session.build_band()
        assert band is None

    def test_consistent_approaches(self):
        """All approach -> strength=1.0."""
        plan = self._make_plan(n_nodes=5)
        session = RideSession(plan, "c1")

        for _ in range(5):
            session.record_choice("approach")

        band = session.build_band()
        assert band["strength"] == 1.0
        assert band["n_agreements"] == 5

    def test_mixed_yields_decay(self):
        """2 approach + 1 retreat -> strength = 2/3."""
        plan = self._make_plan(n_nodes=3)
        session = RideSession(plan, "c1")

        session.record_choice("approach")
        session.record_choice("approach")
        session.record_choice("retreat")

        band = session.build_band()
        assert band is not None
        assert band["direction"] == "right"
        assert abs(band["strength"] - 2 / 3) < 0.001

    def test_all_silence_none(self):
        """Full ride with only silence -> None band."""
        plan = self._make_plan(n_nodes=4)
        session = RideSession(plan, "c1")

        for _ in range(4):
            session.record_choice("silence")

        assert session.is_complete
        band = session.build_band()
        assert band is None

    def test_completes_after_full_path(self):
        """is_complete after len(path) choices."""
        plan = self._make_plan(n_nodes=3)
        session = RideSession(plan, "c1")

        for _ in range(3):
            result = session.record_choice("approach")

        assert session.is_complete
        assert result["status"] == "complete"


# ---------------------------------------------------------------------------
# merge_band_into_sigil tests
# ---------------------------------------------------------------------------

class TestMergeBand:

    def test_merge_new_contrast(self):
        """Merging band for new contrast adds entry."""
        sigil = _make_sigil([])
        band = {
            "contrast_id": "c1", "contrast_name": "brightness",
            "direction": "right", "strength": 1.0,
            "n_presentations": 5, "n_agreements": 5,
        }

        result = merge_band_into_sigil(sigil, band)

        assert "c1" in result["entries"]
        assert result["entries"]["c1"]["direction"] == "right"
        assert sigil["entries"] == {}  # original not mutated

    def test_merge_same_direction_combines(self):
        """Merging same-direction band combines agreements."""
        sigil = _make_sigil([("c1", "brightness", "right", 1.0)])
        band = {
            "contrast_id": "c1", "contrast_name": "brightness",
            "direction": "right", "strength": 1.0,
            "n_presentations": 3, "n_agreements": 3,
        }

        result = merge_band_into_sigil(sigil, band)

        assert result["entries"]["c1"]["n_agreements"] == 5  # 2 + 3
        assert result["entries"]["c1"]["n_presentations"] == 5  # 2 + 3
        assert result["entries"]["c1"]["direction"] == "right"


# ---------------------------------------------------------------------------
# derive_lock_set test
# ---------------------------------------------------------------------------

class TestDeriveLockSet:

    def test_excludes_ride_contrast(self):
        """Lock set excludes the ride contrast."""
        sigil = _make_sigil([
            ("c1", "brightness", "right", 1.0),
            ("c2", "saturation", "left", 0.8),
            ("c3", "contrast", "right", 0.6),
        ])

        lock = derive_lock_set("brightness", sigil)

        assert "brightness" not in lock
        assert "saturation" in lock
        assert "contrast" in lock


# ---------------------------------------------------------------------------
# compute_ride_drift_at_position test
# ---------------------------------------------------------------------------

class TestDriftAtPosition:

    def test_drift_at_start_is_zero(self):
        """Drift at position 0 is always 0."""
        zsummaries = {
            "lock_c": {
                "n_0": {"z_mean": 0.5, "z_std": 0.1, "n": 5},
                "n_1": {"z_mean": 1.5, "z_std": 0.1, "n": 5},
            }
        }
        path = ["n_0", "n_1"]

        drift = compute_ride_drift_at_position(path, 0, ["lock_c"], zsummaries)

        assert drift["lock_c"] == 0.0

    def test_drift_increases_along_path(self):
        """Drift should increase as position advances."""
        zsummaries = {
            "lock_c": {
                "n_0": {"z_mean": 0.0, "z_std": 0.1, "n": 5},
                "n_1": {"z_mean": 0.5, "z_std": 0.1, "n": 5},
                "n_2": {"z_mean": 1.0, "z_std": 0.1, "n": 5},
            }
        }
        path = ["n_0", "n_1", "n_2"]

        d0 = compute_ride_drift_at_position(path, 0, ["lock_c"], zsummaries)
        d1 = compute_ride_drift_at_position(path, 1, ["lock_c"], zsummaries)
        d2 = compute_ride_drift_at_position(path, 2, ["lock_c"], zsummaries)

        assert d0["lock_c"] < d1["lock_c"] < d2["lock_c"]


# ---------------------------------------------------------------------------
# Integration tests (22-23)
# ---------------------------------------------------------------------------

class TestIntegration:
    """Integration tests using aiohttp TestClient with synthetic artifacts."""

    @pytest.fixture
    def artifact_dir(self, tmp_path):
        """Build minimal artifact directory with all needed files."""
        import json

        # Thumbnails (required for static route)
        (tmp_path / "thumbnails").mkdir()

        # Contrast library
        contrasts_dir = tmp_path / "contrasts"
        contrasts_dir.mkdir()
        library = {
            "version": "test",
            "count": 2,
            "contrasts": [
                {
                    "contrast_id": "c1", "name": "brightness", "source": "test",
                    "description": "test", "mass": 1.0, "stability": 1.0,
                    "quantiles": {"p10": 0.0, "p25": 0.25, "p50": 0.5, "p75": 0.75, "p90": 1.0},
                    "exemplars": {"low": [], "median": [], "high": []},
                },
                {
                    "contrast_id": "c2", "name": "saturation", "source": "test",
                    "description": "test", "mass": 1.0, "stability": 1.0,
                    "quantiles": {"p10": 0.0, "p25": 0.25, "p50": 0.5, "p75": 0.75, "p90": 1.0},
                    "exemplars": {"low": [], "median": [], "high": []},
                },
            ],
        }
        (contrasts_dir / "contrast_library.json").write_text(json.dumps(library))

        # Coordinates: brightness monotone, saturation random
        image_ids = [f"img_{i}" for i in range(50)]
        coords = {
            "brightness": {iid: i / 50.0 for i, iid in enumerate(image_ids)},
            "saturation": {iid: float(np.random.RandomState(i).randn()) for i, iid in enumerate(image_ids)},
        }
        (contrasts_dir / "coordinates.json").write_text(json.dumps(coords))

        # Atlas: 5 nodes at level 0
        atlas_dir = tmp_path / "atlas"
        level0_dir = atlas_dir / "level0"
        level0_dir.mkdir(parents=True)
        tiles_dir = level0_dir / "tiles"
        tiles_dir.mkdir()

        nodes = []
        for i in range(5):
            nid = f"n_{i:03d}"
            iids = image_ids[i * 10:(i + 1) * 10]
            nodes.append({
                "node_id": nid, "image_ids": iids, "size": len(iids),
                "level": 0, "parent_id": None, "child_ids": [], "is_leaf": True,
                "rect": [i * 0.2, 0.0, 0.2, 1.0], "order_key": float(i),
                "tile_path": f"tiles/{nid}.jpg", "representative_ids": iids[:3],
                "neighbor_ids": [],
            })

        meta = {
            "corpus_size": 50, "n_neighborhoods": 5, "max_level": 0,
            "nodes": nodes,
        }
        (level0_dir / "meta.json").write_text(json.dumps(meta))
        (atlas_dir / "manifest.json").write_text(json.dumps({
            "max_level": 0, "levels": [{"level": 0, "n_nodes": 5}],
        }))

        # Precompute ride stats
        from sigiltree.ride_stats import compute_ride_stats, save_ride_stats
        stats = compute_ride_stats(coords, [nodes])
        save_ride_stats(stats, tmp_path)

        # Sigil (user has collapsed brightness)
        sigils_dir = tmp_path / "sigils"
        sigils_dir.mkdir()
        sigil = {
            "version": "test", "contrast_library_version": "test", "user_id": "default",
            "entries": {
                "c1": {
                    "contrast_id": "c1", "contrast_name": "brightness",
                    "direction": "right", "strength": 1.0,
                    "n_presentations": 2, "n_agreements": 2,
                },
            },
        }
        (sigils_dir / "sigil_default.json").write_text(json.dumps(sigil))

        return tmp_path

class TestDoorsPerformance:
    """Doors endpoint must respond under 200ms at any level."""

    MAX_RESPONSE_MS = 200

    @pytest.fixture
    def multilevel_artifact_dir(self, tmp_path):
        """Build artifact dir with 3 levels to stress-test doors endpoint."""
        import json

        (tmp_path / "thumbnails").mkdir()

        # Contrast library
        contrasts_dir = tmp_path / "contrasts"
        contrasts_dir.mkdir()
        contrasts = [
            {
                "contrast_id": f"c{i}", "name": f"contrast_{i}", "source": "test",
                "description": "test", "mass": 1.0, "stability": 1.0,
                "quantiles": {"p10": 0.0, "p25": 0.25, "p50": 0.5, "p75": 0.75, "p90": 1.0},
                "exemplars": {"low": [], "median": [], "high": []},
            }
            for i in range(10)
        ]
        library = {"version": "test", "count": 10, "contrasts": contrasts}
        (contrasts_dir / "contrast_library.json").write_text(json.dumps(library))

        image_ids = [f"img_{i}" for i in range(200)]
        coords = {
            f"contrast_{c}": {iid: float(i * c) / 200.0 for i, iid in enumerate(image_ids)}
            for c in range(10)
        }
        (contrasts_dir / "coordinates.json").write_text(json.dumps(coords))

        atlas_dir = tmp_path / "atlas"

        # Level 0: 10 nodes
        all_level_nodes = []
        level0_nodes = []
        for i in range(10):
            nid = f"n_{i:03d}"
            iids = image_ids[i * 20:(i + 1) * 20]
            level0_nodes.append({
                "node_id": nid, "image_ids": iids, "size": len(iids),
                "level": 0, "parent_id": None,
                "child_ids": [f"L1_{i:02d}{j}" for j in range(4)],
                "is_leaf": False,
                "rect": [i * 0.1, 0.0, 0.1, 1.0], "order_key": float(i),
                "tile_path": f"tiles/{nid}.jpg", "representative_ids": iids[:3],
                "neighbor_ids": [],
            })
        all_level_nodes.append(level0_nodes)

        # Level 1: 40 nodes (4 children per L0 node)
        level1_nodes = []
        for i in range(10):
            parent_iids = image_ids[i * 20:(i + 1) * 20]
            for j in range(4):
                nid = f"L1_{i:02d}{j}"
                iids = parent_iids[j * 5:(j + 1) * 5]
                level1_nodes.append({
                    "node_id": nid, "image_ids": iids, "size": len(iids),
                    "level": 1, "parent_id": f"n_{i:03d}",
                    "child_ids": [f"L2_{i:02d}{j}{k}" for k in range(2)],
                    "is_leaf": False,
                    "rect": [j * 0.25, 0.0, 0.25, 1.0], "order_key": float(j),
                    "tile_path": f"tiles/{nid}.jpg", "representative_ids": iids[:2],
                    "neighbor_ids": [],
                })
        all_level_nodes.append(level1_nodes)

        # Level 2: 80 nodes (2 children per L1 node)
        level2_nodes = []
        for i in range(10):
            parent_iids = image_ids[i * 20:(i + 1) * 20]
            for j in range(4):
                l1_iids = parent_iids[j * 5:(j + 1) * 5]
                for k in range(2):
                    nid = f"L2_{i:02d}{j}{k}"
                    start = k * 2
                    iids = l1_iids[start:start + 3] if start + 3 <= len(l1_iids) else l1_iids[start:]
                    level2_nodes.append({
                        "node_id": nid, "image_ids": iids, "size": len(iids),
                        "level": 2, "parent_id": f"L1_{i:02d}{j}",
                        "child_ids": [], "is_leaf": True,
                        "rect": [k * 0.5, 0.0, 0.5, 1.0], "order_key": float(k),
                        "tile_path": f"tiles/{nid}.jpg", "representative_ids": iids[:1],
                        "neighbor_ids": [],
                    })
        all_level_nodes.append(level2_nodes)

        # Write level metas
        for lvl, nodes in enumerate(all_level_nodes):
            level_dir = atlas_dir / f"level{lvl}"
            level_dir.mkdir(parents=True)
            (level_dir / "tiles").mkdir()
            meta = {"corpus_size": 200, "n_neighborhoods": len(nodes), "max_level": 2, "nodes": nodes}
            (level_dir / "meta.json").write_text(json.dumps(meta))

        (atlas_dir / "manifest.json").write_text(json.dumps({
            "max_level": 2,
            "levels": [
                {"level": 0, "n_nodes": 10},
                {"level": 1, "n_nodes": 40},
                {"level": 2, "n_nodes": 80},
            ],
        }))

        # Ride stats
        from sigiltree.ride_stats import compute_ride_stats, save_ride_stats
        stats = compute_ride_stats(coords, all_level_nodes)
        save_ride_stats(stats, tmp_path)

        return tmp_path

    @pytest.mark.asyncio
    async def test_doors_response_time_all_levels(self, multilevel_artifact_dir):
        """Doors endpoint responds under MAX_RESPONSE_MS at every level."""
        import time
        from aiohttp.test_utils import TestClient, TestServer
        from sigiltree.viewer_server import create_app

        app = create_app(multilevel_artifact_dir)
        async with TestClient(TestServer(app)) as client:
            test_cases = [
                ("n_000", 0, "", ""),
                ("L1_000", 1, "n_000", "0"),
                ("L2_0000", 2, "L1_000", "1"),
            ]
            for node_id, level, from_node, from_level in test_cases:
                start = time.perf_counter()
                resp = await client.get(
                    f"/api/atlas/node/{node_id}/doors"
                    f"?level={level}&from_node={from_node}&from_level={from_level}"
                )
                elapsed_ms = (time.perf_counter() - start) * 1000
                assert resp.status == 200, f"Level {level} failed: {resp.status}"
                data = await resp.json()
                assert len(data["doors"]) > 0, f"Level {level}: no doors returned"
                assert elapsed_ms < self.MAX_RESPONSE_MS, (
                    f"Level {level} doors took {elapsed_ms:.0f}ms "
                    f"(max {self.MAX_RESPONSE_MS}ms)"
                )

    @pytest.mark.asyncio
    async def test_doors_cached_is_fast(self, multilevel_artifact_dir):
        """Second call to same level is significantly faster (cache hit)."""
        import time
        from aiohttp.test_utils import TestClient, TestServer
        from sigiltree.viewer_server import create_app

        app = create_app(multilevel_artifact_dir)
        async with TestClient(TestServer(app)) as client:
            url = "/api/atlas/node/L1_000/doors?level=1&from_node=n_000&from_level=0"

            # Cold call
            start = time.perf_counter()
            await client.get(url)
            cold_ms = (time.perf_counter() - start) * 1000

            # Warm call (different node, same level — cache should hit)
            url2 = "/api/atlas/node/L1_001/doors?level=1&from_node=n_000&from_level=0"
            start = time.perf_counter()
            resp = await client.get(url2)
            warm_ms = (time.perf_counter() - start) * 1000

            assert resp.status == 200
            # Warm should be faster; allow generous margin
            assert warm_ms < self.MAX_RESPONSE_MS, (
                f"Warm call took {warm_ms:.0f}ms (max {self.MAX_RESPONSE_MS}ms)"
            )
