"""Tests for silent calibration via flythrough and flow graph."""

import copy
import math
import time

import pytest

from sigiltree.flythrough import (
    MIN_VISITS,
    FlythroughSession,
    compute_flow_graph,
    flow_in_direction,
    flythrough_to_sigil,
    infer_preferences,
    _cosine_similarity,
    _z_profile,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_zsummaries(contrast_names, node_z_values):
    """Build zsummaries from {contrast: {node: z_mean}}.

    node_z_values: {contrast_name: {node_id: z_mean}}
    """
    result = {}
    for cname in contrast_names:
        vals = node_z_values.get(cname, {})
        result[cname] = {
            nid: {"z_mean": z, "z_std": 0.1, "n": 10}
            for nid, z in vals.items()
        }
    return result


def make_contrast_library(contrast_names, version="test_v1"):
    """Build a minimal contrast library."""
    import hashlib
    contrasts = []
    for name in contrast_names:
        cid = hashlib.md5(name.encode()).hexdigest()[:12]
        contrasts.append({
            "contrast_id": cid,
            "name": name,
            "source": "test",
            "description": f"test contrast {name}",
            "mass": 1.0,
            "stability": 1.0,
            "quantiles": {"p10": 0.1, "p50": 0.5, "p90": 0.9},
            "exemplars": {"low": [], "median": [], "high": []},
        })
    return {"version": version, "contrasts": contrasts}


# ---------------------------------------------------------------------------
# FlythroughSession tests
# ---------------------------------------------------------------------------

class TestFlythroughSession:

    def test_empty_session(self):
        s = FlythroughSession(user_id="test")
        assert len(s.visited) == 0
        assert len(s.distinct_nodes) == 0
        assert not s.is_ready

    def test_record_visit(self):
        s = FlythroughSession(user_id="test")
        s.record_visit("n_001", 0)
        assert len(s.visited) == 1
        assert s.visited[0]["node_id"] == "n_001"
        assert s.visited[0]["level"] == 0

    def test_deduplicate_consecutive(self):
        s = FlythroughSession(user_id="test")
        s.record_visit("n_001", 0)
        s.record_visit("n_001", 0)
        s.record_visit("n_001", 0)
        assert len(s.visited) == 1

    def test_non_consecutive_duplicates_kept(self):
        s = FlythroughSession(user_id="test")
        s.record_visit("n_001", 0)
        s.record_visit("n_002", 0)
        s.record_visit("n_001", 0)
        assert len(s.visited) == 3
        assert len(s.distinct_nodes) == 2

    def test_distinct_nodes(self):
        s = FlythroughSession(user_id="test")
        for i in range(7):
            s.record_visit(f"n_{i:03d}", 0)
        assert len(s.distinct_nodes) == 7

    def test_ready_after_min_visits(self):
        s = FlythroughSession(user_id="test")
        for i in range(MIN_VISITS - 1):
            s.record_visit(f"n_{i:03d}", 0)
        assert not s.is_ready
        s.record_visit(f"n_{MIN_VISITS:03d}", 0)
        assert s.is_ready


# ---------------------------------------------------------------------------
# infer_preferences tests
# ---------------------------------------------------------------------------

class TestInferPreferences:

    def test_all_high_z_nodes_right(self):
        """Visiting only high-z nodes -> direction='right'."""
        nodes = ["n_000", "n_001", "n_002", "n_003", "n_004",
                 "n_005", "n_006", "n_007", "n_008", "n_009"]
        # First 5 nodes have high z, last 5 have low z
        z_vals = {nid: 1.5 for nid in nodes[:5]}
        z_vals.update({nid: -1.5 for nid in nodes[5:]})

        zs = make_zsummaries(["brightness"], {"brightness": z_vals})
        lib = make_contrast_library(["brightness"])

        # Visit only high-z nodes
        visited = nodes[:5]
        entries = infer_preferences(visited, zs, nodes, lib)

        cid = lib["contrasts"][0]["contrast_id"]
        assert cid in entries
        assert entries[cid]["direction"] == "right"

    def test_all_low_z_nodes_left(self):
        """Visiting only low-z nodes -> direction='left'."""
        nodes = ["n_000", "n_001", "n_002", "n_003", "n_004",
                 "n_005", "n_006", "n_007", "n_008", "n_009"]
        z_vals = {nid: -1.5 for nid in nodes[:5]}
        z_vals.update({nid: 1.5 for nid in nodes[5:]})

        zs = make_zsummaries(["brightness"], {"brightness": z_vals})
        lib = make_contrast_library(["brightness"])

        visited = nodes[:5]
        entries = infer_preferences(visited, zs, nodes, lib)

        cid = lib["contrasts"][0]["contrast_id"]
        assert cid in entries
        assert entries[cid]["direction"] == "left"

    def test_scattered_visits_superposed(self):
        """Visits spread across spectrum -> no collapse."""
        nodes = [f"n_{i:03d}" for i in range(10)]
        z_vals = {nid: (i - 4.5) * 0.05 for i, nid in enumerate(nodes)}

        zs = make_zsummaries(["brightness"], {"brightness": z_vals})
        lib = make_contrast_library(["brightness"])

        # Visit all nodes -> mean z near zero -> below min_bias
        entries = infer_preferences(nodes, zs, nodes, lib)
        assert len(entries) == 0

    def test_empty_visits(self):
        """No visits -> no entries."""
        zs = make_zsummaries(["brightness"], {"brightness": {}})
        lib = make_contrast_library(["brightness"])
        entries = infer_preferences([], zs, [], lib)
        assert entries == {}

    def test_min_bias_threshold(self):
        """Bias just below threshold -> superposed."""
        nodes = [f"n_{i:03d}" for i in range(5)]
        # z_mean = 0.3 which is below default min_bias=0.4
        z_vals = {nid: 0.3 for nid in nodes}
        zs = make_zsummaries(["brightness"], {"brightness": z_vals})
        lib = make_contrast_library(["brightness"])

        entries = infer_preferences(nodes, zs, nodes, lib)
        assert len(entries) == 0

    def test_strength_proportional_to_bias(self):
        """Larger bias -> higher strength."""
        nodes = [f"n_{i:03d}" for i in range(5)]
        lib = make_contrast_library(["brightness"])

        # Moderate bias: z_mean = 0.6
        z_low = {nid: 0.6 for nid in nodes}
        zs_low = make_zsummaries(["brightness"], {"brightness": z_low})
        entries_low = infer_preferences(nodes, zs_low, nodes, lib)

        # Strong bias: z_mean = 1.8
        z_high = {nid: 1.8 for nid in nodes}
        zs_high = make_zsummaries(["brightness"], {"brightness": z_high})
        entries_high = infer_preferences(nodes, zs_high, nodes, lib)

        cid = lib["contrasts"][0]["contrast_id"]
        assert entries_low[cid]["strength"] < entries_high[cid]["strength"]

    def test_multiple_contrasts_independent(self):
        """Each contrast scored independently."""
        nodes = [f"n_{i:03d}" for i in range(5)]
        z_vals = {
            "brightness": {nid: 1.5 for nid in nodes},   # high -> right
            "temperature": {nid: -1.5 for nid in nodes},  # low -> left
            "sharpness": {nid: 0.1 for nid in nodes},     # near zero -> superposed
        }
        zs = make_zsummaries(["brightness", "temperature", "sharpness"], z_vals)
        lib = make_contrast_library(["brightness", "temperature", "sharpness"])

        entries = infer_preferences(nodes, zs, nodes, lib)

        cids = {c["name"]: c["contrast_id"] for c in lib["contrasts"]}
        assert entries[cids["brightness"]]["direction"] == "right"
        assert entries[cids["temperature"]]["direction"] == "left"
        assert cids["sharpness"] not in entries

    def test_no_mutation(self):
        """Inputs unchanged after call."""
        nodes = [f"n_{i:03d}" for i in range(5)]
        z_vals = {"brightness": {nid: 1.0 for nid in nodes}}
        zs = make_zsummaries(["brightness"], z_vals)
        lib = make_contrast_library(["brightness"])

        zs_copy = copy.deepcopy(zs)
        lib_copy = copy.deepcopy(lib)
        nodes_copy = list(nodes)

        infer_preferences(nodes, zs, nodes, lib)

        assert zs == zs_copy
        assert lib == lib_copy
        assert nodes == nodes_copy


# ---------------------------------------------------------------------------
# flythrough_to_sigil tests
# ---------------------------------------------------------------------------

class TestFlythroughToSigil:

    def test_produces_valid_sigil_structure(self):
        """Sigil has required fields."""
        s = FlythroughSession(user_id="test")
        for i in range(6):
            s.record_visit(f"n_{i:03d}", 0)

        nodes = [f"n_{i:03d}" for i in range(10)]
        z_vals = {"brightness": {nid: (1.5 if i < 5 else -1.5)
                                 for i, nid in enumerate(nodes)}}
        zs = {"0": make_zsummaries(["brightness"], z_vals)}
        lib = make_contrast_library(["brightness"])
        all_nodes = {"0": nodes}

        sigil = flythrough_to_sigil(s, zs, lib, all_nodes)

        assert "version" in sigil
        assert "contrast_library_version" in sigil
        assert "user_id" in sigil
        assert sigil["user_id"] == "test"
        assert "entries" in sigil
        assert "collapsed_count" in sigil
        assert "superposed_count" in sigil
        assert sigil["collapsed_count"] == len(sigil["entries"])

    def test_empty_visits_empty_sigil(self):
        """No visits -> no entries."""
        s = FlythroughSession(user_id="test")
        lib = make_contrast_library(["brightness"])
        sigil = flythrough_to_sigil(s, {}, lib, {})
        assert sigil["collapsed_count"] == 0
        assert len(sigil["entries"]) == 0

    def test_sigil_entry_structure(self):
        """Each entry has contrast_id, contrast_name, direction, strength,
        n_presentations, n_agreements."""
        s = FlythroughSession(user_id="test")
        for i in range(6):
            s.record_visit(f"n_{i:03d}", 0)

        nodes = [f"n_{i:03d}" for i in range(10)]
        z_vals = {"brightness": {nid: 1.5 for nid in nodes}}
        zs = {"0": make_zsummaries(["brightness"], z_vals)}
        lib = make_contrast_library(["brightness"])
        all_nodes = {"0": nodes}

        sigil = flythrough_to_sigil(s, zs, lib, all_nodes)

        for cid, entry in sigil["entries"].items():
            assert "contrast_id" in entry
            assert "contrast_name" in entry
            assert "direction" in entry
            assert entry["direction"] in ("left", "right")
            assert "strength" in entry
            assert 0.0 <= entry["strength"] <= 1.0
            assert "n_presentations" in entry
            assert "n_agreements" in entry


# ---------------------------------------------------------------------------
# Flow graph tests
# ---------------------------------------------------------------------------

class TestFlowGraph:

    def _make_nodes_and_zs(self, n=6):
        """Create nodes with distinct z-profiles for flow testing."""
        nodes = [f"n_{i:03d}" for i in range(n)]
        # Each node has a unique direction in 2D contrast space
        angles = [2 * math.pi * i / n for i in range(n)]
        z_vals = {
            "brightness": {nid: math.cos(a) for nid, a in zip(nodes, angles)},
            "temperature": {nid: math.sin(a) for nid, a in zip(nodes, angles)},
        }
        zs = make_zsummaries(["brightness", "temperature"], z_vals)
        return nodes, zs

    def test_all_nodes_have_neighbors(self):
        """No node is isolated."""
        nodes, zs = self._make_nodes_and_zs(6)
        flow = compute_flow_graph(nodes, zs)
        for nid in nodes:
            assert nid in flow
            assert len(flow[nid]) > 0

    def test_self_excluded(self):
        """Node never in its own flow list."""
        nodes, zs = self._make_nodes_and_zs(6)
        flow = compute_flow_graph(nodes, zs)
        for nid in nodes:
            assert nid not in flow[nid]

    def test_all_others_present(self):
        """Flow list contains all other nodes."""
        nodes, zs = self._make_nodes_and_zs(6)
        flow = compute_flow_graph(nodes, zs)
        for nid in nodes:
            assert len(flow[nid]) == len(nodes) - 1
            assert set(flow[nid]) == set(nodes) - {nid}

    def test_most_similar_first(self):
        """First flow-neighbor is the most similar in z-profile."""
        nodes = ["n_000", "n_001", "n_002"]
        # n_000 and n_001 are identical, n_002 is opposite
        z_vals = {
            "brightness": {"n_000": 1.0, "n_001": 1.0, "n_002": -1.0},
            "temperature": {"n_000": 0.5, "n_001": 0.5, "n_002": -0.5},
        }
        zs = make_zsummaries(["brightness", "temperature"], z_vals)
        flow = compute_flow_graph(nodes, zs)

        assert flow["n_000"][0] == "n_001"
        assert flow["n_001"][0] == "n_000"

    def test_single_node_empty_flow(self):
        """Single node has no flow neighbors."""
        nodes = ["n_000"]
        zs = make_zsummaries(["brightness"], {"brightness": {"n_000": 1.0}})
        flow = compute_flow_graph(nodes, zs)
        assert flow["n_000"] == []

    def test_flow_cross_branch(self):
        """Flow connects nodes regardless of tree parentage.
        (Flow graph only uses z-profiles, not tree structure.)"""
        # Simulate nodes from different parents but similar z-profiles
        nodes = ["parent_a_child_1", "parent_a_child_2", "parent_b_child_1"]
        z_vals = {
            "brightness": {
                "parent_a_child_1": 1.0,
                "parent_a_child_2": -1.0,
                "parent_b_child_1": 0.9,  # similar to parent_a_child_1
            },
        }
        zs = make_zsummaries(["brightness"], z_vals)
        flow = compute_flow_graph(nodes, zs)

        # parent_a_child_1's closest should be parent_b_child_1 (cross-branch)
        assert flow["parent_a_child_1"][0] == "parent_b_child_1"


class TestFlowInDirection:

    def _make_rects(self):
        """Three nodes in a horizontal line."""
        return {
            "n_left": (0.0, 0.0, 0.3, 0.5),
            "n_center": (0.35, 0.0, 0.3, 0.5),
            "n_right": (0.7, 0.0, 0.3, 0.5),
        }

    def _make_flow(self):
        """All nodes know about each other, sorted by similarity."""
        return {
            "n_left": ["n_center", "n_right"],
            "n_center": ["n_left", "n_right"],
            "n_right": ["n_center", "n_left"],
        }

    def test_right_picks_rightward(self):
        flow = self._make_flow()
        rects = self._make_rects()
        result = flow_in_direction("n_left", "right", flow, rects)
        assert result == "n_center"

    def test_left_picks_leftward(self):
        flow = self._make_flow()
        rects = self._make_rects()
        result = flow_in_direction("n_right", "left", flow, rects)
        assert result == "n_center"

    def test_wraps_when_no_direction(self):
        """When nothing is to the left of the leftmost, wraps to most similar."""
        flow = self._make_flow()
        rects = self._make_rects()
        # n_left has nothing further left, should wrap
        result = flow_in_direction("n_left", "left", flow, rects)
        assert result is not None  # should get something, not None

    def test_no_neighbors_returns_none(self):
        flow = {"n_000": []}
        rects = {"n_000": (0.0, 0.0, 0.5, 0.5)}
        result = flow_in_direction("n_000", "right", flow, rects)
        assert result is None

    def test_vertical_direction(self):
        """Up/down direction works."""
        rects = {
            "n_top": (0.0, 0.0, 0.5, 0.3),
            "n_bottom": (0.0, 0.5, 0.5, 0.3),
        }
        flow = {
            "n_top": ["n_bottom"],
            "n_bottom": ["n_top"],
        }
        assert flow_in_direction("n_top", "down", flow, rects) == "n_bottom"
        assert flow_in_direction("n_bottom", "up", flow, rects) == "n_top"


# ---------------------------------------------------------------------------
# Cosine similarity tests
# ---------------------------------------------------------------------------

class TestCosineSimilarity:

    def test_identical_vectors(self):
        assert abs(_cosine_similarity([1, 2, 3], [1, 2, 3]) - 1.0) < 1e-6

    def test_opposite_vectors(self):
        assert abs(_cosine_similarity([1, 0, 0], [-1, 0, 0]) - (-1.0)) < 1e-6

    def test_orthogonal_vectors(self):
        assert abs(_cosine_similarity([1, 0], [0, 1])) < 1e-6

    def test_zero_vector(self):
        assert _cosine_similarity([0, 0], [1, 1]) == 0.0
