"""Tests for the emergent taste axis materialization."""

import json
import pytest
import numpy as np
from pathlib import Path

from sigiltree.taste_axis import compute_taste_coordinates, materialize_taste_axis
from sigiltree.arcade import save_taste_axis, load_taste_axis


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_library(contrast_names):
    """Minimal contrast library."""
    contrasts = []
    for i, name in enumerate(contrast_names):
        contrasts.append({
            "contrast_id": f"c_{i:03d}",
            "name": name,
            "source": "test",
            "mass": 1.0,
            "stability": 1.0,
            "quantiles": {"p10": 0.1, "p25": 0.25, "p50": 0.5, "p75": 0.75, "p90": 0.9},
            "exemplars": {"low": [], "median": [], "high": []},
        })
    return {"version": "v1_test", "count": len(contrasts), "contrasts": contrasts}


def _make_coordinates(contrast_names, image_profiles):
    """Build coordinates from {image_id: {contrast_name: float}}."""
    coords = {name: {} for name in contrast_names}
    for iid, profile in image_profiles.items():
        for name in contrast_names:
            coords[name][iid] = profile.get(name, 0.5)
    return coords


def _make_sigil(entries):
    """Minimal sigil with given entries dict."""
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
# TestComputeTasteCoordinates
# ---------------------------------------------------------------------------

class TestComputeTasteCoordinates:
    def test_single_contrast_right(self):
        """Right direction: taste = normalized coordinate."""
        lib = _make_library(["brightness"])
        coords = _make_coordinates(["brightness"], {
            "img_hi": {"brightness": 0.9},
            "img_lo": {"brightness": 0.1},
        })
        sigil = _make_sigil({
            "c_000": {"contrast_id": "c_000", "contrast_name": "brightness",
                       "direction": "right", "strength": 1.0},
        })

        result = compute_taste_coordinates(sigil, lib, coords)
        assert result is not None
        # (0.9 - 0.1) / (0.9 - 0.1) = 1.0
        assert result["coordinates"]["img_hi"] == pytest.approx(1.0, abs=0.01)
        # (0.1 - 0.1) / (0.9 - 0.1) = 0.0
        assert result["coordinates"]["img_lo"] == pytest.approx(0.0, abs=0.01)

    def test_single_contrast_left(self):
        """Left direction: taste = 1 - normalized."""
        lib = _make_library(["brightness"])
        coords = _make_coordinates(["brightness"], {
            "img_hi": {"brightness": 0.9},
            "img_lo": {"brightness": 0.1},
        })
        sigil = _make_sigil({
            "c_000": {"contrast_id": "c_000", "contrast_name": "brightness",
                       "direction": "left", "strength": 1.0},
        })

        result = compute_taste_coordinates(sigil, lib, coords)
        # Left inverts: high raw -> low taste
        assert result["coordinates"]["img_hi"] == pytest.approx(0.0, abs=0.01)
        assert result["coordinates"]["img_lo"] == pytest.approx(1.0, abs=0.01)

    def test_two_contrasts_averaging(self):
        """Two contrasts at full strength: taste = mean of aligned values."""
        lib = _make_library(["brightness", "sharpness"])
        coords = _make_coordinates(["brightness", "sharpness"], {
            "img_a": {"brightness": 0.9, "sharpness": 0.9},
            "img_b": {"brightness": 0.1, "sharpness": 0.1},
        })
        sigil = _make_sigil({
            "c_000": {"contrast_id": "c_000", "contrast_name": "brightness",
                       "direction": "right", "strength": 1.0},
            "c_001": {"contrast_id": "c_001", "contrast_name": "sharpness",
                       "direction": "right", "strength": 1.0},
        })

        result = compute_taste_coordinates(sigil, lib, coords)
        # Both aligned right, both high -> taste ~1.0
        assert result["coordinates"]["img_a"] == pytest.approx(1.0, abs=0.01)
        assert result["coordinates"]["img_b"] == pytest.approx(0.0, abs=0.01)

    def test_strength_weighting(self):
        """Half strength contributes half."""
        lib = _make_library(["brightness"])
        coords = _make_coordinates(["brightness"], {
            "img": {"brightness": 0.9},
        })
        sigil_full = _make_sigil({
            "c_000": {"contrast_id": "c_000", "contrast_name": "brightness",
                       "direction": "right", "strength": 1.0},
        })
        sigil_half = _make_sigil({
            "c_000": {"contrast_id": "c_000", "contrast_name": "brightness",
                       "direction": "right", "strength": 0.5},
        })

        full = compute_taste_coordinates(sigil_full, lib, coords)
        half = compute_taste_coordinates(sigil_half, lib, coords)
        # normalized = 1.0, aligned = 1.0
        # full: 1.0 * 1.0 = 1.0; half: 1.0 * 0.5 = 0.5
        assert full["coordinates"]["img"] == pytest.approx(1.0, abs=0.01)
        assert half["coordinates"]["img"] == pytest.approx(0.5, abs=0.01)

    def test_empty_sigil_returns_none(self):
        lib = _make_library(["brightness"])
        coords = _make_coordinates(["brightness"], {"img": {"brightness": 0.5}})

        assert compute_taste_coordinates(None, lib, coords) is None
        assert compute_taste_coordinates(_make_sigil({}), lib, coords) is None

    def test_quantiles_correct(self):
        """Quantiles match numpy percentile of computed coordinates."""
        lib = _make_library(["brightness"])
        # Create 100 images with spread scores
        profiles = {f"img_{i:03d}": {"brightness": 0.1 + 0.8 * i / 99} for i in range(100)}
        coords = _make_coordinates(["brightness"], profiles)
        sigil = _make_sigil({
            "c_000": {"contrast_id": "c_000", "contrast_name": "brightness",
                       "direction": "right", "strength": 1.0},
        })

        result = compute_taste_coordinates(sigil, lib, coords)
        vals = np.array(list(result["coordinates"].values()))
        expected = np.percentile(vals, [10, 50, 90])
        assert result["quantiles"]["p10"] == pytest.approx(expected[0], abs=0.001)
        assert result["quantiles"]["p50"] == pytest.approx(expected[1], abs=0.001)
        assert result["quantiles"]["p90"] == pytest.approx(expected[2], abs=0.001)

    def test_exemplars_correct(self):
        """Low exemplars are lowest-scoring images, high are highest."""
        lib = _make_library(["brightness"])
        profiles = {f"img_{i:03d}": {"brightness": 0.1 + 0.8 * i / 49} for i in range(50)}
        coords = _make_coordinates(["brightness"], profiles)
        sigil = _make_sigil({
            "c_000": {"contrast_id": "c_000", "contrast_name": "brightness",
                       "direction": "right", "strength": 1.0},
        })

        result = compute_taste_coordinates(sigil, lib, coords, n_exemplars=5)
        tc = result["coordinates"]

        # Low exemplars should have the 5 lowest taste scores
        low_scores = [tc[iid] for iid in result["exemplars"]["low"]]
        other_scores = [tc[iid] for iid in tc if iid not in result["exemplars"]["low"]]
        assert max(low_scores) <= min(other_scores)

        # High exemplars should have the 5 highest
        high_scores = [tc[iid] for iid in result["exemplars"]["high"]]
        other_scores = [tc[iid] for iid in tc if iid not in result["exemplars"]["high"]]
        assert min(high_scores) >= max(other_scores)

    def test_components_recorded(self):
        """Components list matches the sigil entries used."""
        lib = _make_library(["brightness", "sharpness"])
        coords = _make_coordinates(["brightness", "sharpness"], {
            "img": {"brightness": 0.5, "sharpness": 0.5},
        })
        sigil = _make_sigil({
            "c_000": {"contrast_id": "c_000", "contrast_name": "brightness",
                       "direction": "right", "strength": 0.8},
            "c_001": {"contrast_id": "c_001", "contrast_name": "sharpness",
                       "direction": "left", "strength": 0.6},
        })

        result = compute_taste_coordinates(sigil, lib, coords)
        names = {c["contrast_name"] for c in result["components"]}
        assert names == {"brightness", "sharpness"}
        for comp in result["components"]:
            if comp["contrast_name"] == "brightness":
                assert comp["direction"] == "right"
                assert comp["strength"] == 0.8

    def test_missing_contrast_skipped(self):
        """Sigil referencing a contrast not in coordinates is skipped."""
        lib = _make_library(["brightness", "missing"])
        coords = _make_coordinates(["brightness"], {
            "img": {"brightness": 0.9},
        })
        sigil = _make_sigil({
            "c_000": {"contrast_id": "c_000", "contrast_name": "brightness",
                       "direction": "right", "strength": 1.0},
            "c_001": {"contrast_id": "c_001", "contrast_name": "missing",
                       "direction": "right", "strength": 1.0},
        })

        result = compute_taste_coordinates(sigil, lib, coords)
        assert result is not None
        assert len(result["components"]) == 1
        assert result["components"][0]["contrast_name"] == "brightness"


# ---------------------------------------------------------------------------
# TestPersistence
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_round_trip(self, tmp_path):
        """Save then load produces identical data."""
        taste = {
            "contrast_id": "taste_test",
            "name": "taste_axis",
            "coordinates": {"img_a": 0.8, "img_b": 0.2},
            "quantiles": {"p10": 0.2, "p50": 0.5, "p90": 0.8},
            "exemplars": {"low": ["img_b"], "median": [], "high": ["img_a"]},
            "components": [{"contrast_name": "brightness", "direction": "right", "strength": 1.0}],
        }
        save_taste_axis(taste, tmp_path)
        loaded = load_taste_axis(tmp_path)
        assert loaded["coordinates"] == taste["coordinates"]
        assert loaded["exemplars"] == taste["exemplars"]
        assert loaded["quantiles"] == taste["quantiles"]

    def test_load_missing_returns_none(self, tmp_path):
        assert load_taste_axis(tmp_path) is None


# ---------------------------------------------------------------------------
# TestMaterialize
# ---------------------------------------------------------------------------

def _setup_artifacts(tmp_path, sigil_entries, image_profiles, contrast_names):
    """Set up minimal artifact directory for materialization tests."""
    contrasts_dir = tmp_path / "contrasts"
    contrasts_dir.mkdir()
    atlas_dir = tmp_path / "atlas"
    atlas_dir.mkdir()
    sigils_dir = tmp_path / "sigils"
    sigils_dir.mkdir()

    lib = _make_library(contrast_names)
    (contrasts_dir / "contrast_library.json").write_text(json.dumps(lib))

    coords = _make_coordinates(contrast_names, image_profiles)
    (contrasts_dir / "coordinates.json").write_text(json.dumps(coords))

    # Atlas with one level, two nodes
    image_ids = list(image_profiles.keys())
    mid = len(image_ids) // 2
    nodes = [
        {"node_id": "n_000", "image_ids": image_ids[:mid], "rect": [0, 0, 0.5, 1]},
        {"node_id": "n_001", "image_ids": image_ids[mid:], "rect": [0.5, 0, 0.5, 1]},
    ]
    level_dir = atlas_dir / "level0"
    level_dir.mkdir()
    (level_dir / "meta.json").write_text(json.dumps({"nodes": nodes}))
    (atlas_dir / "manifest.json").write_text(json.dumps({"max_level": 0}))

    sigil = _make_sigil(sigil_entries)
    return sigil


class TestMaterialize:
    def test_creates_file(self, tmp_path):
        """Materialization creates taste_axis_default.json."""
        sigil = _setup_artifacts(tmp_path, {
            "c_000": {"contrast_id": "c_000", "contrast_name": "brightness",
                       "direction": "right", "strength": 1.0},
        }, {
            "img_a": {"brightness": 0.9},
            "img_b": {"brightness": 0.1},
            "img_c": {"brightness": 0.5},
            "img_d": {"brightness": 0.7},
        }, ["brightness"])

        path = materialize_taste_axis(sigil, tmp_path)
        assert path is not None
        assert path.exists()

        loaded = load_taste_axis(tmp_path)
        assert "coordinates" in loaded
        assert "quantiles" in loaded
        assert "exemplars" in loaded
        assert "zsummaries" in loaded

    def test_zsummaries_computed(self, tmp_path):
        """Z-summaries present for each atlas level."""
        sigil = _setup_artifacts(tmp_path, {
            "c_000": {"contrast_id": "c_000", "contrast_name": "brightness",
                       "direction": "right", "strength": 1.0},
        }, {
            f"img_{i}": {"brightness": 0.1 + 0.8 * i / 19} for i in range(20)
        }, ["brightness"])

        materialize_taste_axis(sigil, tmp_path)
        loaded = load_taste_axis(tmp_path)

        assert "0" in loaded["zsummaries"]
        level0_zs = loaded["zsummaries"]["0"]
        assert "n_000" in level0_zs
        assert "n_001" in level0_zs
        assert "z_mean" in level0_zs["n_000"]
        assert "z_std" in level0_zs["n_000"]

    def test_zsummary_differentiation(self, tmp_path):
        """Nodes with different taste profiles get different z-means."""
        sigil = _setup_artifacts(tmp_path, {
            "c_000": {"contrast_id": "c_000", "contrast_name": "brightness",
                       "direction": "right", "strength": 1.0},
        }, {
            # First 10 images: low brightness -> low taste
            **{f"img_{i:02d}": {"brightness": 0.15} for i in range(10)},
            # Last 10 images: high brightness -> high taste
            **{f"img_{i:02d}": {"brightness": 0.85} for i in range(10, 20)},
        }, ["brightness"])

        materialize_taste_axis(sigil, tmp_path)
        loaded = load_taste_axis(tmp_path)
        zs = loaded["zsummaries"]["0"]

        # n_000 gets first 10 (low), n_001 gets last 10 (high)
        assert zs["n_000"]["z_mean"] < zs["n_001"]["z_mean"]

    def test_idempotent(self, tmp_path):
        """Calling materialize twice produces identical output."""
        sigil = _setup_artifacts(tmp_path, {
            "c_000": {"contrast_id": "c_000", "contrast_name": "brightness",
                       "direction": "right", "strength": 1.0},
        }, {f"img_{i}": {"brightness": 0.1 + 0.8 * i / 9} for i in range(10)},
        ["brightness"])

        materialize_taste_axis(sigil, tmp_path)
        first = load_taste_axis(tmp_path)
        materialize_taste_axis(sigil, tmp_path)
        second = load_taste_axis(tmp_path)

        assert first["coordinates"] == second["coordinates"]
        assert first["quantiles"] == second["quantiles"]

    def test_empty_sigil_no_file(self, tmp_path):
        """Empty sigil produces no taste axis file."""
        sigil = _setup_artifacts(tmp_path, {}, {
            "img_a": {"brightness": 0.5},
        }, ["brightness"])

        path = materialize_taste_axis(sigil, tmp_path)
        assert path is None
        assert load_taste_axis(tmp_path) is None
