"""Tests for Phase 3: contrast discovery, mass, stability, selection."""

import numpy as np
import pytest

from sigiltree.contrasts import (
    _score_mass,
    _compute_exemplars,
    _compute_perceptual_scores,
    PERCEPTUAL_NAMES,
)


def test_score_mass_uniform_is_low():
    scores = np.ones(100, dtype=np.float32)
    mass = _score_mass(scores)
    assert mass < 0.001


def test_score_mass_spread_is_high():
    scores = np.linspace(0, 10, 100).astype(np.float32)
    mass = _score_mass(scores)
    assert mass > 1.0


def test_score_mass_bimodal():
    scores = np.concatenate([np.zeros(50), np.ones(50)]).astype(np.float32)
    mass = _score_mass(scores)
    assert mass > 0.1


def test_exemplars_structure():
    rng = np.random.RandomState(0)
    scores = rng.randn(200).astype(np.float32)
    ids = [f"img_{i}" for i in range(200)]
    exemplars = _compute_exemplars(scores, ids, n_exemplars=12)

    assert "low" in exemplars
    assert "median" in exemplars
    assert "high" in exemplars
    assert len(exemplars["low"]) == 12
    assert len(exemplars["high"]) == 12

    # Low exemplars should have lower scores than high
    low_idx = [ids.index(eid) for eid in exemplars["low"]]
    high_idx = [ids.index(eid) for eid in exemplars["high"]]
    assert np.mean(scores[low_idx]) < np.mean(scores[high_idx])


def test_exemplars_no_overlap():
    scores = np.linspace(0, 1, 100).astype(np.float32)
    ids = [f"img_{i}" for i in range(100)]
    exemplars = _compute_exemplars(scores, ids, n_exemplars=8)

    low_set = set(exemplars["low"])
    high_set = set(exemplars["high"])
    # Low and high should not overlap
    assert len(low_set & high_set) == 0


def test_perceptual_scores_returns_all_keys(tmp_path):
    from PIL import Image
    img = Image.new("RGB", (200, 200), color=(200, 100, 50))
    path = tmp_path / "test.jpg"
    img.save(path)

    scores = _compute_perceptual_scores(str(path))
    for name in PERCEPTUAL_NAMES:
        assert name in scores, f"Missing perceptual score: {name}"
        assert isinstance(scores[name], float)


def test_perceptual_brightness_warm_vs_cool(tmp_path):
    from PIL import Image
    # Warm image (red)
    warm = Image.new("RGB", (200, 200), color=(255, 100, 50))
    warm_path = tmp_path / "warm.jpg"
    warm.save(warm_path)

    # Cool image (blue)
    cool = Image.new("RGB", (200, 200), color=(50, 100, 255))
    cool_path = tmp_path / "cool.jpg"
    cool.save(cool_path)

    warm_scores = _compute_perceptual_scores(str(warm_path))
    cool_scores = _compute_perceptual_scores(str(cool_path))

    assert warm_scores["temperature"] > cool_scores["temperature"]


def test_perceptual_brightness_bright_vs_dark(tmp_path):
    from PIL import Image
    bright = Image.new("RGB", (200, 200), color=(240, 240, 240))
    bright_path = tmp_path / "bright.jpg"
    bright.save(bright_path)

    dark = Image.new("RGB", (200, 200), color=(20, 20, 20))
    dark_path = tmp_path / "dark.jpg"
    dark.save(dark_path)

    bright_scores = _compute_perceptual_scores(str(bright_path))
    dark_scores = _compute_perceptual_scores(str(dark_path))

    assert bright_scores["brightness"] > dark_scores["brightness"]
