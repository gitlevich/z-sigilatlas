"""Tests for Phase 8: sigil rendering score computation."""

import copy
import json
from pathlib import Path

import pytest

from sigiltree.sigil_scoring import compute_sigil_scores


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_sigil(entries):
    """Build a minimal sigil dict.

    entries: list of (contrast_id, contrast_name, direction, strength)
    """
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
    return {
        "version": "sigil_v1_test",
        "contrast_library_version": "v1_test",
        "user_id": "test",
        "entries": e,
    }


def _make_library(contrasts):
    """Build a minimal contrast library.

    contrasts: list of (contrast_id, name, p10, p90)
    """
    items = []
    for cid, name, p10, p90 in contrasts:
        items.append({
            "contrast_id": cid,
            "name": name,
            "source": "test",
            "description": f"test {name}",
            "mass": 1.0,
            "stability": 1.0,
            "quantiles": {"p10": p10, "p25": 0.0, "p50": 0.0, "p75": 0.0, "p90": p90},
            "exemplars": {"low": [], "median": [], "high": []},
        })
    return {"version": "v1_test", "count": len(items), "contrasts": items}


def _make_nodes(configs):
    """Build node dicts.

    configs: list of (node_id, image_ids)
    """
    return [{"node_id": nid, "image_ids": iids, "size": len(iids)} for nid, iids in configs]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_empty_sigil_neutral():
    """Empty sigil (no collapsed entries) produces score=0.5 for all nodes."""
    sigil = _make_sigil([])
    library = _make_library([])
    coords = {}
    nodes = _make_nodes([("n_0", ["a", "b"]), ("n_1", ["c"])])

    result = compute_sigil_scores(sigil, library, coords, nodes)

    assert result["n_0"]["score"] == 0.5
    assert result["n_1"]["score"] == 0.5
    assert result["n_0"]["breakdown"] == []
    assert result["n_1"]["breakdown"] == []


def test_single_contrast_right_aligned():
    """Direction='right': node with high mean scores near 1.0, low mean near 0.0."""
    sigil = _make_sigil([("c1", "brightness", "right", 1.0)])
    library = _make_library([("c1", "brightness", 0.0, 1.0)])
    coords = {
        "brightness": {"a": 0.9, "b": 0.95, "c": 0.1, "d": 0.05},
    }
    nodes = _make_nodes([
        ("high_node", ["a", "b"]),
        ("low_node", ["c", "d"]),
    ])

    result = compute_sigil_scores(sigil, library, coords, nodes)

    assert result["high_node"]["score"] > 0.85
    assert result["low_node"]["score"] < 0.15


def test_single_contrast_left_aligned():
    """Direction='left': node with high mean gets LOW score (inverted)."""
    sigil = _make_sigil([("c1", "brightness", "left", 1.0)])
    library = _make_library([("c1", "brightness", 0.0, 1.0)])
    coords = {
        "brightness": {"a": 0.9, "b": 0.95, "c": 0.1, "d": 0.05},
    }
    nodes = _make_nodes([
        ("high_node", ["a", "b"]),
        ("low_node", ["c", "d"]),
    ])

    result = compute_sigil_scores(sigil, library, coords, nodes)

    # Inverted: high-mean node gets low score
    assert result["high_node"]["score"] < 0.15
    assert result["low_node"]["score"] > 0.85


def test_no_cross_axis_effect():
    """Single collapsed contrast: nodes differing only on uncollapsed axis get same score."""
    sigil = _make_sigil([("c1", "brightness", "right", 1.0)])
    library = _make_library([
        ("c1", "brightness", 0.0, 1.0),
        ("c2", "saturation", 0.0, 1.0),  # uncollapsed
    ])
    coords = {
        "brightness": {"a": 0.5, "b": 0.5, "c": 0.5, "d": 0.5},
        "saturation": {"a": 0.1, "b": 0.1, "c": 0.9, "d": 0.9},
    }
    nodes = _make_nodes([
        ("low_sat", ["a", "b"]),
        ("high_sat", ["c", "d"]),
    ])

    result = compute_sigil_scores(sigil, library, coords, nodes)

    # Both nodes have identical brightness=0.5, so scores should be equal
    assert abs(result["low_sat"]["score"] - result["high_sat"]["score"]) < 0.001


def test_uncollapsed_not_in_breakdown():
    """Uncollapsed contrasts do not appear in breakdown."""
    sigil = _make_sigil([("c1", "brightness", "right", 1.0)])
    library = _make_library([
        ("c1", "brightness", 0.0, 1.0),
        ("c2", "saturation", 0.0, 1.0),
    ])
    coords = {
        "brightness": {"a": 0.8},
        "saturation": {"a": 0.3},
    }
    nodes = _make_nodes([("n_0", ["a"])])

    result = compute_sigil_scores(sigil, library, coords, nodes)

    contrast_names = [e["contrast_name"] for e in result["n_0"]["breakdown"]]
    assert "brightness" in contrast_names
    assert "saturation" not in contrast_names


def test_strength_weighting():
    """Strength scales contribution proportionally."""
    library = _make_library([("c1", "brightness", 0.0, 1.0)])
    coords = {"brightness": {"a": 1.0}}
    nodes = _make_nodes([("n_0", ["a"])])

    # Full strength
    sigil_full = _make_sigil([("c1", "brightness", "right", 1.0)])
    result_full = compute_sigil_scores(sigil_full, library, coords, nodes)

    # Half strength
    sigil_half = _make_sigil([("c1", "brightness", "right", 0.5)])
    result_half = compute_sigil_scores(sigil_half, library, coords, nodes)

    # Full: contribution = 1.0 * 1.0 = 1.0, score = 1.0
    # Half: contribution = 1.0 * 0.5 = 0.5, score = 0.5
    assert abs(result_full["n_0"]["score"] - 1.0) < 0.01
    assert abs(result_half["n_0"]["score"] - 0.5) < 0.01


def test_quantile_normalization():
    """p10 maps to 0.0, p90 maps to 1.0, midpoint maps to 0.5."""
    sigil = _make_sigil([("c1", "temp", "right", 1.0)])
    library = _make_library([("c1", "temp", 0.2, 0.8)])
    nodes = _make_nodes([
        ("at_p10", ["a"]),
        ("at_p90", ["b"]),
        ("at_mid", ["c"]),
    ])
    coords = {"temp": {"a": 0.2, "b": 0.8, "c": 0.5}}

    result = compute_sigil_scores(sigil, library, coords, nodes)

    assert abs(result["at_p10"]["score"] - 0.0) < 0.01
    assert abs(result["at_p90"]["score"] - 1.0) < 0.01
    assert abs(result["at_mid"]["score"] - 0.5) < 0.01


def test_missing_image_ids_graceful():
    """Nodes with image_ids not in coordinates are handled gracefully."""
    sigil = _make_sigil([("c1", "brightness", "right", 1.0)])
    library = _make_library([("c1", "brightness", 0.0, 1.0)])
    coords = {"brightness": {"a": 0.8}}  # only 'a' exists
    nodes = _make_nodes([("n_0", ["a", "missing1", "missing2"])])

    result = compute_sigil_scores(sigil, library, coords, nodes)

    # Should use only 'a' (0.8), not crash
    assert result["n_0"]["score"] > 0.7
    assert len(result["n_0"]["breakdown"]) == 1


def test_score_range():
    """All scores are in [0, 1] across a variety of inputs."""
    sigil = _make_sigil([
        ("c1", "brightness", "right", 1.0),
        ("c2", "saturation", "left", 0.7),
    ])
    library = _make_library([
        ("c1", "brightness", 0.1, 0.9),
        ("c2", "saturation", 0.0, 1.0),
    ])
    coords = {
        "brightness": {f"img_{i}": i * 0.1 for i in range(11)},
        "saturation": {f"img_{i}": 1.0 - i * 0.1 for i in range(11)},
    }
    nodes = _make_nodes([
        (f"n_{i}", [f"img_{i}"]) for i in range(11)
    ])

    result = compute_sigil_scores(sigil, library, coords, nodes)

    for nid, data in result.items():
        assert 0.0 <= data["score"] <= 1.0, f"Node {nid} score {data['score']} out of range"


def test_multiple_contrasts_averaging():
    """Final score is mean of per-contrast contributions."""
    sigil = _make_sigil([
        ("c1", "a", "right", 1.0),
        ("c2", "b", "right", 1.0),
        ("c3", "c", "right", 1.0),
    ])
    library = _make_library([
        ("c1", "a", 0.0, 1.0),
        ("c2", "b", 0.0, 1.0),
        ("c3", "c", 0.0, 1.0),
    ])
    coords = {
        "a": {"x": 0.8},
        "b": {"x": 0.4},
        "c": {"x": 0.6},
    }
    nodes = _make_nodes([("n_0", ["x"])])

    result = compute_sigil_scores(sigil, library, coords, nodes)

    # Contributions: 0.8, 0.4, 0.6 -> mean = 0.6
    assert abs(result["n_0"]["score"] - 0.6) < 0.01


def test_invariant_4_3_no_sigil_mutation():
    """compute_sigil_scores does not mutate the input sigil dict."""
    sigil = _make_sigil([("c1", "brightness", "right", 1.0)])
    library = _make_library([("c1", "brightness", 0.0, 1.0)])
    coords = {"brightness": {"a": 0.5}}
    nodes = _make_nodes([("n_0", ["a"])])

    sigil_copy = copy.deepcopy(sigil)
    compute_sigil_scores(sigil, library, coords, nodes)

    assert sigil == sigil_copy, "Sigil dict was mutated by compute_sigil_scores"
