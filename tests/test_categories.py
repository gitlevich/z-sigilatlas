"""Tests for categorical calibration: radar-based category filter."""

import json
import pytest
from pathlib import Path

from sigiltree.arcade import save_category_prefs, load_category_prefs
from sigiltree.sigil_scoring import compute_category_gate, compute_sigil_scores


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

def _make_contrast_library(category_names=None):
    """Create a minimal contrast library with unipolar categories."""
    if category_names is None:
        category_names = ["sem_portrait", "sem_landscape", "sem_architecture"]
    contrasts = []
    for i, name in enumerate(category_names):
        contrasts.append({
            "contrast_id": f"cat_{i:03d}",
            "name": name,
            "source": "semantic",
            "mass": 1.0,
            "stability": 1.0,
            "quantiles": {
                "p10": 0.1,
                "p25": 0.25,
                "p50": 0.5,
                "p75": 0.75,
                "p90": 0.9,
            },
            "exemplars": {
                "low": [f"{name}_low_{j}" for j in range(6)],
                "median": [f"{name}_med_{j}" for j in range(6)],
                "high": [f"{name}_high_{j}" for j in range(6)],
            },
        })
    return {
        "version": "v1_test_categories",
        "count": len(contrasts),
        "contrasts": contrasts,
    }


def _make_coordinates(library, node_profiles):
    """Create coordinates dict from per-node profiles.

    Args:
        library: contrast library dict
        node_profiles: {node_id: {contrast_name: mean_value}}

    Returns:
        {contrast_name: {image_id: float}}
    """
    coords = {}
    for c in library["contrasts"]:
        name = c["name"]
        image_scores = {}
        for node_id, profiles in node_profiles.items():
            val = profiles.get(name, 0.5)
            # Assign same value to all images in this node
            for img_id in _node_image_ids(node_id):
                image_scores[img_id] = val
        coords[name] = image_scores
    return coords


def _node_image_ids(node_id, count=4):
    """Generate image IDs for a node."""
    return [f"{node_id}_img_{j}" for j in range(count)]


def _make_nodes(node_ids, images_per_node=4):
    """Create atlas node dicts."""
    return [
        {"node_id": nid, "image_ids": _node_image_ids(nid, images_per_node)}
        for nid in node_ids
    ]


def _make_sigil_with_entries(entries):
    """Create a minimal sigil dict with given entries."""
    return {
        "version": "sigil_v1_test",
        "contrast_library_version": "v1_test",
        "user_id": "default",
        "created_at": 0.0,
        "entries": entries,
        "total_choices": len(entries),
        "collapsed_count": len(entries),
        "superposed_count": 0,
    }


# ---------------------------------------------------------------------------
# TestComputeCategoryGate
# ---------------------------------------------------------------------------

class TestComputeCategoryGate:
    def test_no_weights_returns_all_ones(self):
        lib = _make_contrast_library()
        nodes = _make_nodes(["n1", "n2"])
        coords = _make_coordinates(lib, {"n1": {}, "n2": {}})

        gates = compute_category_gate({}, lib, coords, nodes)
        assert gates["n1"] == 1.0
        assert gates["n2"] == 1.0

    def test_none_weights_returns_all_ones(self):
        lib = _make_contrast_library()
        nodes = _make_nodes(["n1"])
        coords = _make_coordinates(lib, {"n1": {}})

        gates = compute_category_gate(None, lib, coords, nodes)
        assert gates["n1"] == 1.0

    def test_all_zero_weights_returns_all_zeros(self):
        """All handles at center = everything dimmed."""
        lib = _make_contrast_library()
        nodes = _make_nodes(["n1", "n2"])
        coords = _make_coordinates(lib, {"n1": {}, "n2": {}})

        gates = compute_category_gate({"cat_000": 0.0, "cat_001": 0.0}, lib, coords, nodes)
        assert gates["n1"] == 0.0
        assert gates["n2"] == 0.0

    def test_single_category_high_node_gets_high_gate(self):
        """Node with high portrait score gets high gate when portrait is active."""
        lib = _make_contrast_library(["sem_portrait"])
        nodes = _make_nodes(["portrait_node", "other_node"])
        coords = _make_coordinates(lib, {
            "portrait_node": {"sem_portrait": 0.85},  # high portrait score
            "other_node": {"sem_portrait": 0.15},      # low portrait score
        })

        gates = compute_category_gate({"cat_000": 1.0}, lib, coords, nodes)
        assert gates["portrait_node"] > gates["other_node"]
        # 0.85 normalized: (0.85 - 0.1) / (0.9 - 0.1) = 0.9375
        assert gates["portrait_node"] > 0.9

    def test_single_category_low_node_gets_low_gate(self):
        lib = _make_contrast_library(["sem_portrait"])
        nodes = _make_nodes(["low_node"])
        coords = _make_coordinates(lib, {
            "low_node": {"sem_portrait": 0.12},
        })

        gates = compute_category_gate({"cat_000": 1.0}, lib, coords, nodes)
        # (0.12 - 0.1) / (0.9 - 0.1) = 0.025
        assert gates["low_node"] < 0.1

    def test_multiple_categories_weighted_average(self):
        """Two categories: gate = weighted average of both."""
        lib = _make_contrast_library(["sem_portrait", "sem_landscape"])
        nodes = _make_nodes(["n1"])
        # Node is high portrait (0.9), low landscape (0.1)
        coords = _make_coordinates(lib, {
            "n1": {"sem_portrait": 0.9, "sem_landscape": 0.1},
        })

        # Portrait at 1.0, landscape at 1.0 — equal weight
        gates = compute_category_gate(
            {"cat_000": 1.0, "cat_001": 1.0}, lib, coords, nodes
        )
        # portrait_norm = (0.9-0.1)/0.8 = 1.0, landscape_norm = (0.1-0.1)/0.8 = 0.0
        # gate = (1.0*1.0 + 1.0*0.0) / (1.0+1.0) = 0.5
        assert 0.45 <= gates["n1"] <= 0.55

    def test_weight_affects_contribution(self):
        """Higher weight on a category gives it more influence."""
        lib = _make_contrast_library(["sem_portrait", "sem_landscape"])
        nodes = _make_nodes(["n1"])
        coords = _make_coordinates(lib, {
            "n1": {"sem_portrait": 0.9, "sem_landscape": 0.1},
        })

        # Portrait at 1.0, landscape at 0.1 (nearly zero)
        gates = compute_category_gate(
            {"cat_000": 1.0, "cat_001": 0.1}, lib, coords, nodes
        )
        # Portrait dominates, gate should be close to 1.0
        assert gates["n1"] > 0.8

    def test_zero_weight_excluded(self):
        """Category at weight 0 doesn't contribute to gate."""
        lib = _make_contrast_library(["sem_portrait", "sem_landscape"])
        nodes = _make_nodes(["n1"])
        coords = _make_coordinates(lib, {
            "n1": {"sem_portrait": 0.9, "sem_landscape": 0.1},
        })

        # Portrait at 1.0, landscape at 0 (excluded)
        gates_with = compute_category_gate(
            {"cat_000": 1.0, "cat_001": 0.0}, lib, coords, nodes
        )
        gates_without = compute_category_gate(
            {"cat_000": 1.0}, lib, coords, nodes
        )
        assert abs(gates_with["n1"] - gates_without["n1"]) < 0.01

    def test_gate_range_zero_to_one(self):
        """All gate values should be in [0, 1]."""
        lib = _make_contrast_library(["sem_portrait", "sem_landscape", "sem_architecture"])
        nodes = _make_nodes(["n1", "n2", "n3"])
        coords = _make_coordinates(lib, {
            "n1": {"sem_portrait": 0.0, "sem_landscape": 0.0, "sem_architecture": 0.0},
            "n2": {"sem_portrait": 0.5, "sem_landscape": 0.5, "sem_architecture": 0.5},
            "n3": {"sem_portrait": 1.0, "sem_landscape": 1.0, "sem_architecture": 1.0},
        })

        gates = compute_category_gate(
            {"cat_000": 0.5, "cat_001": 0.8, "cat_002": 0.3},
            lib, coords, nodes,
        )
        for nid, gate in gates.items():
            assert 0.0 <= gate <= 1.0, f"Gate for {nid} = {gate}, out of range"


# ---------------------------------------------------------------------------
# TestCombinedScoring
# ---------------------------------------------------------------------------

class TestCombinedScoring:
    def test_walk_only_no_categories(self):
        """Walk scores unchanged when no category prefs."""
        lib = _make_contrast_library(["sem_portrait"])
        # Add a bipolar contrast for the sigil
        lib["contrasts"].append({
            "contrast_id": "bp_000",
            "name": "brightness",
            "source": "perceptual",
            "mass": 5.0,
            "stability": 1.0,
            "quantiles": {"p10": 0.1, "p25": 0.25, "p50": 0.5, "p75": 0.75, "p90": 0.9},
            "exemplars": {"low": [], "median": [], "high": []},
        })
        nodes = _make_nodes(["n1", "n2"])
        coords = _make_coordinates(lib, {
            "n1": {"brightness": 0.8, "sem_portrait": 0.5},
            "n2": {"brightness": 0.2, "sem_portrait": 0.5},
        })
        # Add brightness coords for our images
        for nid in ["n1", "n2"]:
            for img_id in _node_image_ids(nid):
                coords["brightness"][img_id] = 0.8 if nid == "n1" else 0.2

        sigil = _make_sigil_with_entries({
            "bp_000": {
                "contrast_id": "bp_000",
                "contrast_name": "brightness",
                "direction": "right",
                "strength": 1.0,
                "n_presentations": 1,
                "n_agreements": 1,
            }
        })

        scores_no_cat = compute_sigil_scores(sigil, lib, coords, nodes)
        scores_with_none = compute_sigil_scores(sigil, lib, coords, nodes, category_weights=None)

        assert scores_no_cat["n1"]["score"] == scores_with_none["n1"]["score"]
        assert scores_no_cat["n2"]["score"] == scores_with_none["n2"]["score"]

    def test_categories_only_no_walk(self):
        """No walk sigil, categories only: base 0.5 * gate."""
        lib = _make_contrast_library(["sem_portrait"])
        nodes = _make_nodes(["high_p", "low_p"])
        coords = _make_coordinates(lib, {
            "high_p": {"sem_portrait": 0.9},
            "low_p": {"sem_portrait": 0.1},
        })

        scores = compute_sigil_scores(
            None, lib, coords, nodes,
            category_weights={"cat_000": 1.0},
        )
        # base = 0.5, gate for high_p >> gate for low_p
        assert scores["high_p"]["score"] > scores["low_p"]["score"]
        # high_p gate ~= 1.0, so score ~= 0.5
        assert scores["high_p"]["score"] > 0.4

    def test_combined_multiplicative(self):
        """Walk score * category gate."""
        lib = _make_contrast_library(["sem_portrait"])
        lib["contrasts"].append({
            "contrast_id": "bp_000",
            "name": "brightness",
            "source": "perceptual",
            "mass": 5.0,
            "stability": 1.0,
            "quantiles": {"p10": 0.1, "p25": 0.25, "p50": 0.5, "p75": 0.75, "p90": 0.9},
            "exemplars": {"low": [], "median": [], "high": []},
        })
        nodes = _make_nodes(["bright_portrait", "bright_other", "dark_portrait"])
        profiles = {
            "bright_portrait": {"brightness": 0.9, "sem_portrait": 0.9},
            "bright_other": {"brightness": 0.9, "sem_portrait": 0.1},
            "dark_portrait": {"brightness": 0.1, "sem_portrait": 0.9},
        }
        coords = _make_coordinates(lib, profiles)
        for nid, prof in profiles.items():
            for img_id in _node_image_ids(nid):
                coords["brightness"][img_id] = prof["brightness"]

        sigil = _make_sigil_with_entries({
            "bp_000": {
                "contrast_id": "bp_000",
                "contrast_name": "brightness",
                "direction": "right",
                "strength": 1.0,
                "n_presentations": 1,
                "n_agreements": 1,
            }
        })

        scores = compute_sigil_scores(
            sigil, lib, coords, nodes,
            category_weights={"cat_000": 1.0},  # portrait filter
        )

        # bright_portrait: high walk * high gate = highest
        # bright_other: high walk * low gate = low
        # dark_portrait: low walk * high gate = medium-low
        assert scores["bright_portrait"]["score"] > scores["dark_portrait"]["score"]
        assert scores["bright_portrait"]["score"] > scores["bright_other"]["score"]
        # bright_other should be gated down despite high walk score
        assert scores["bright_other"]["score"] < 0.2

    def test_gate_included_in_result(self):
        """When category weights provided, gate value is in result."""
        lib = _make_contrast_library(["sem_portrait"])
        nodes = _make_nodes(["n1"])
        coords = _make_coordinates(lib, {"n1": {"sem_portrait": 0.5}})

        scores = compute_sigil_scores(
            None, lib, coords, nodes,
            category_weights={"cat_000": 1.0},
        )
        assert "gate" in scores["n1"]


# ---------------------------------------------------------------------------
# TestCategoryPrefsPersistence
# ---------------------------------------------------------------------------

class TestCategoryPrefsPersistence:
    def test_save_load_roundtrip(self, tmp_path):
        prefs = {
            "user_id": "test_user",
            "version": "v1",
            "created_at": 123.0,
            "weights": {"cat_000": 0.8, "cat_001": 0.3, "cat_002": 0.0},
        }
        save_category_prefs(prefs, tmp_path)
        loaded = load_category_prefs(tmp_path, "test_user")
        assert loaded is not None
        assert loaded["weights"] == prefs["weights"]
        assert loaded["user_id"] == "test_user"

    def test_load_nonexistent_returns_none(self, tmp_path):
        result = load_category_prefs(tmp_path, "nonexistent")
        assert result is None

    def test_save_creates_sigils_dir(self, tmp_path):
        prefs = {"user_id": "default", "weights": {"cat_000": 0.5}}
        path = save_category_prefs(prefs, tmp_path)
        assert path.exists()
        assert path.parent.name == "sigils"

    def test_default_user_id(self, tmp_path):
        prefs = {"user_id": "default", "weights": {"cat_000": 0.5}}
        save_category_prefs(prefs, tmp_path)
        loaded = load_category_prefs(tmp_path)
        assert loaded is not None
        assert loaded["weights"]["cat_000"] == 0.5

    def test_overwrite_existing(self, tmp_path):
        prefs1 = {"user_id": "default", "weights": {"cat_000": 0.5}}
        save_category_prefs(prefs1, tmp_path)

        prefs2 = {"user_id": "default", "weights": {"cat_000": 0.9, "cat_001": 0.3}}
        save_category_prefs(prefs2, tmp_path)

        loaded = load_category_prefs(tmp_path)
        assert loaded["weights"]["cat_000"] == 0.9
        assert loaded["weights"]["cat_001"] == 0.3
