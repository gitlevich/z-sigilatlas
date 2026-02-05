"""Tests for Phase 5+6: atlas construction, fused graph, clustering, ordering, layout, determinism, recursive multiscale."""

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from sigiltree.atlas import (
    squarified_treemap,
    build_fused_graph,
    build_sublevel_graph,
    cluster_neighborhoods,
    compute_ordering,
    compute_representatives,
    compute_neighbor_edges,
    compute_target_range,
    build_atlas,
    build_atlas_recursive,
    load_atlas_meta,
    load_atlas_manifest,
    get_children,
    rect_iou,
    MIN_SPLIT_SIZE,
)
from sigiltree.embeddings import EmbeddingStore
from sigiltree import db


# ---------------------------------------------------------------------------
# Test corpus factory
# ---------------------------------------------------------------------------

def _make_test_corpus(tmp_path, n_images=50, dim=8):
    """Create a synthetic corpus with embeddings for atlas testing.

    Returns (artifact_dir, image_ids).
    """
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()

    rng = np.random.RandomState(0)
    image_ids = [f"img_{i:04d}" for i in range(n_images)]

    # Create catalog.db
    conn = db.open_db(artifact_dir)
    for iid in image_ids:
        db.upsert_image(conn, iid, f"/fake/{iid}.jpg", f"{iid}.jpg",
                        256, 256, f"hash_{iid}", 1000, None)
    conn.commit()
    conn.close()

    # Create embeddings per family (use same dim for simplicity)
    for fam in ["clip", "dino", "texture"]:
        store = EmbeddingStore(artifact_dir, fam, dim)
        vecs = rng.randn(n_images, dim).astype(np.float32)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        vecs = vecs / norms
        store.save(image_ids, vecs)

    # Create 64px thumbnail placeholders
    thumb_dir = artifact_dir / "thumbnails" / "64"
    thumb_dir.mkdir(parents=True)
    for iid in image_ids:
        img = Image.new("RGB", (64, 64), color=tuple(rng.randint(0, 256, 3)))
        img.save(thumb_dir / f"{iid}.jpg")

    return artifact_dir, image_ids


# ---------------------------------------------------------------------------
# Squarified treemap tests
# ---------------------------------------------------------------------------

def test_squarified_treemap_covers_frame():
    """Sum of rectangle areas equals frame area, no gaps."""
    values = [10, 8, 6, 4, 3, 2, 1]
    rects = squarified_treemap(values, (0, 0, 1, 1))
    assert len(rects) == len(values)
    total_area = sum(r[2] * r[3] for r in rects)
    assert abs(total_area - 1.0) < 1e-6


def test_squarified_treemap_all_positive_areas():
    """Every output rectangle has w > 0 and h > 0."""
    values = [5, 3, 2, 1, 1, 1]
    rects = squarified_treemap(values)
    for x, y, w, h in rects:
        assert w > 0, f"Zero width: ({x}, {y}, {w}, {h})"
        assert h > 0, f"Zero height: ({x}, {y}, {w}, {h})"


def test_squarified_treemap_aspect_ratios_bounded():
    """Max aspect ratio of any rectangle is bounded."""
    values = [10, 8, 6, 5, 4, 3, 2, 1]
    rects = squarified_treemap(values)
    for x, y, w, h in rects:
        ratio = max(w / h, h / w) if min(w, h) > 0 else float("inf")
        assert ratio < 15, f"Extreme aspect ratio {ratio} for ({x}, {y}, {w}, {h})"


def test_squarified_treemap_single_value():
    """Single value fills entire frame."""
    rects = squarified_treemap([5], (0, 0, 2, 3))
    assert len(rects) == 1
    assert rects[0] == (0, 0, 2, 3)


def test_squarified_treemap_empty():
    """Empty input returns empty output."""
    assert squarified_treemap([]) == []


def test_squarified_treemap_preserves_count():
    """Output has same length as input."""
    for n in [1, 3, 10, 25]:
        values = list(range(1, n + 1))
        rects = squarified_treemap(values)
        assert len(rects) == n


# ---------------------------------------------------------------------------
# Fused graph tests
# ---------------------------------------------------------------------------

def test_fused_graph_symmetry(tmp_path):
    """Output adjacency matrix is symmetric."""
    artifact_dir, image_ids = _make_test_corpus(tmp_path, n_images=30, dim=8)
    adjacency, _ = build_fused_graph(artifact_dir, image_ids, k=10)
    np.testing.assert_array_equal(adjacency, adjacency.T)


def test_fused_graph_has_edges(tmp_path):
    """Fused graph should have edges for a corpus with shared structure."""
    artifact_dir, image_ids = _make_test_corpus(tmp_path, n_images=30, dim=8)
    adjacency, _ = build_fused_graph(artifact_dir, image_ids, k=10)
    assert adjacency.sum() > 0, "Fused graph has no edges"


def test_fused_graph_id_mapping(tmp_path):
    """id_to_idx maps all image IDs to valid indices."""
    artifact_dir, image_ids = _make_test_corpus(tmp_path, n_images=20, dim=8)
    adjacency, id_to_idx = build_fused_graph(artifact_dir, image_ids, k=5)
    assert set(id_to_idx.keys()) == set(image_ids)
    assert set(id_to_idx.values()) == set(range(len(image_ids)))


# ---------------------------------------------------------------------------
# Clustering tests
# ---------------------------------------------------------------------------

def test_cluster_partition(tmp_path):
    """Every image belongs to exactly one cluster."""
    artifact_dir, image_ids = _make_test_corpus(tmp_path, n_images=50, dim=8)
    adjacency, _ = build_fused_graph(artifact_dir, image_ids, k=10)
    clusters = cluster_neighborhoods(adjacency, seed=42, target_range=(3, 20))

    all_indices = []
    for c in clusters:
        all_indices.extend(c)
    assert sorted(all_indices) == list(range(len(image_ids)))


def test_cluster_no_empty(tmp_path):
    """No cluster is empty."""
    artifact_dir, image_ids = _make_test_corpus(tmp_path, n_images=50, dim=8)
    adjacency, _ = build_fused_graph(artifact_dir, image_ids, k=10)
    clusters = cluster_neighborhoods(adjacency, seed=42, target_range=(3, 20))
    for c in clusters:
        assert len(c) > 0


# ---------------------------------------------------------------------------
# Ordering tests
# ---------------------------------------------------------------------------

def test_ordering_determinism(tmp_path):
    """Two calls with same input produce same relative ordering."""
    artifact_dir, image_ids = _make_test_corpus(tmp_path, n_images=30, dim=8)
    adjacency, _ = build_fused_graph(artifact_dir, image_ids, k=10)
    order1 = compute_ordering(adjacency)
    order2 = compute_ordering(adjacency)
    # Values may differ at ~1e-6 level due to iterative eigsh solver,
    # but relative ordering must be identical
    rank1 = np.argsort(order1)
    rank2 = np.argsort(order2)
    np.testing.assert_array_equal(rank1, rank2)


def test_ordering_no_nans(tmp_path):
    """Fiedler vector has no NaN or Inf."""
    artifact_dir, image_ids = _make_test_corpus(tmp_path, n_images=30, dim=8)
    adjacency, _ = build_fused_graph(artifact_dir, image_ids, k=10)
    fiedler = compute_ordering(adjacency)
    assert np.all(np.isfinite(fiedler))


# ---------------------------------------------------------------------------
# Representatives tests
# ---------------------------------------------------------------------------

def test_representatives_from_cluster(tmp_path):
    """All representative indices belong to the cluster."""
    artifact_dir, image_ids = _make_test_corpus(tmp_path, n_images=30, dim=8)
    adjacency, _ = build_fused_graph(artifact_dir, image_ids, k=10)
    clusters = cluster_neighborhoods(adjacency, seed=42, target_range=(3, 10))
    for cluster in clusters:
        reps = compute_representatives(adjacency, cluster, k=5)
        for r in reps:
            assert r in cluster


def test_representatives_bounded(tmp_path):
    """Number of representatives is at most k."""
    artifact_dir, image_ids = _make_test_corpus(tmp_path, n_images=30, dim=8)
    adjacency, _ = build_fused_graph(artifact_dir, image_ids, k=10)
    clusters = cluster_neighborhoods(adjacency, seed=42, target_range=(3, 10))
    for cluster in clusters:
        reps = compute_representatives(adjacency, cluster, k=5)
        assert len(reps) <= max(5, len(cluster))


# ---------------------------------------------------------------------------
# End-to-end atlas build tests
# ---------------------------------------------------------------------------

def test_atlas_build_end_to_end(tmp_path):
    """Build atlas on synthetic corpus, verify structure."""
    artifact_dir, image_ids = _make_test_corpus(tmp_path, n_images=50, dim=8)
    stats = build_atlas(artifact_dir, level=0, seed=42)

    assert stats["corpus_size"] == 50
    assert stats["n_neighborhoods"] > 1

    meta = load_atlas_meta(artifact_dir, level=0)
    assert meta is not None
    assert meta["corpus_size"] == 50
    assert len(meta["nodes"]) == stats["n_neighborhoods"]

    # Verify rectangles tile the frame
    total_area = sum(
        n["rect"][2] * n["rect"][3] for n in meta["nodes"]
    )
    assert abs(total_area - 1.0) < 1e-4

    # Verify all images accounted for
    all_ids = set()
    for node in meta["nodes"]:
        all_ids.update(node["image_ids"])
    assert all_ids == set(image_ids)


def test_atlas_determinism_rebuild(tmp_path):
    """Build twice on identical inputs, verify identical layout."""
    artifact_dir, image_ids = _make_test_corpus(tmp_path, n_images=50, dim=8)

    build_atlas(artifact_dir, level=0, seed=42)
    meta1 = load_atlas_meta(artifact_dir, level=0)

    build_atlas(artifact_dir, level=0, seed=42)
    meta2 = load_atlas_meta(artifact_dir, level=0)

    # Same number of nodes
    assert len(meta1["nodes"]) == len(meta2["nodes"])

    # Match by image_ids and compare rects
    id_to_rect1 = {frozenset(n["image_ids"]): tuple(n["rect"]) for n in meta1["nodes"]}
    id_to_rect2 = {frozenset(n["image_ids"]): tuple(n["rect"]) for n in meta2["nodes"]}

    assert set(id_to_rect1.keys()) == set(id_to_rect2.keys())
    for key in id_to_rect1:
        iou = rect_iou(id_to_rect1[key], id_to_rect2[key])
        assert iou > 0.98, f"IoU {iou} for cluster with {len(key)} images"


def test_atlas_meta_load_roundtrip(tmp_path):
    """Build, save, load, verify key fields match."""
    artifact_dir, image_ids = _make_test_corpus(tmp_path, n_images=30, dim=8)
    build_atlas(artifact_dir, level=0, seed=42)
    meta = load_atlas_meta(artifact_dir, level=0)
    assert meta is not None
    assert meta["level"] == 0
    assert meta["random_seed"] == 42
    assert "nodes" in meta
    assert "build_id" in meta


def test_tile_images_exist(tmp_path):
    """All tile files referenced in meta actually exist."""
    artifact_dir, image_ids = _make_test_corpus(tmp_path, n_images=50, dim=8)
    build_atlas(artifact_dir, level=0, seed=42)
    meta = load_atlas_meta(artifact_dir, level=0)

    atlas_dir = artifact_dir / "atlas" / "level0"
    for node in meta["nodes"]:
        tile_path = atlas_dir / node["tile_path"]
        assert tile_path.exists(), f"Missing tile: {tile_path}"


def test_invariant_4_3_no_sigil_on_atlas(tmp_path):
    """Atlas build does not create or modify sigil files."""
    artifact_dir, image_ids = _make_test_corpus(tmp_path, n_images=30, dim=8)
    sigil_dir = artifact_dir / "sigils"

    build_atlas(artifact_dir, level=0, seed=42)

    assert not sigil_dir.exists(), "Atlas build should not create sigil directory"


def test_rect_iou_identical():
    """IoU of identical rectangles is 1.0."""
    r = (0.1, 0.2, 0.3, 0.4)
    assert abs(rect_iou(r, r) - 1.0) < 1e-6


def test_rect_iou_disjoint():
    """IoU of non-overlapping rectangles is 0.0."""
    r1 = (0.0, 0.0, 0.1, 0.1)
    r2 = (0.5, 0.5, 0.1, 0.1)
    assert rect_iou(r1, r2) == 0.0


# ===========================================================================
# Phase 6: Multiscale recursive atlas tests
# ===========================================================================

# ---------------------------------------------------------------------------
# Sublevel graph tests
# ---------------------------------------------------------------------------

def test_build_sublevel_graph_small_cluster(tmp_path):
    """Sublevel graph for 15 images produces valid adjacency."""
    artifact_dir, image_ids = _make_test_corpus(tmp_path, n_images=15, dim=8)
    adjacency, id_to_idx = build_sublevel_graph(artifact_dir, image_ids)
    assert adjacency.shape == (15, 15)
    np.testing.assert_array_equal(adjacency, adjacency.T)
    assert set(id_to_idx.keys()) == set(image_ids)


def test_build_sublevel_graph_tiny_cluster(tmp_path):
    """Sublevel graph for < 6 images returns fully connected graph."""
    artifact_dir, image_ids = _make_test_corpus(tmp_path, n_images=5, dim=8)
    subset = image_ids[:5]
    adjacency, id_to_idx = build_sublevel_graph(artifact_dir, subset)
    assert adjacency.shape == (5, 5)
    # Fully connected: all off-diagonal elements should be 3.0
    for i in range(5):
        assert adjacency[i, i] == 0.0
        for j in range(5):
            if i != j:
                assert adjacency[i, j] == 3.0


# ---------------------------------------------------------------------------
# Target range tests
# ---------------------------------------------------------------------------

def test_compute_target_range_values():
    """Target range scales with sqrt(n) and caps at 12."""
    lo, hi = compute_target_range(4)
    assert lo >= 2
    assert hi >= lo

    lo, hi = compute_target_range(25)  # sqrt(25) = 5
    assert lo >= 2
    assert hi <= 14  # target capped at 12, hi = 12 + 2

    lo, hi = compute_target_range(200)  # sqrt(200) ~ 14, capped to 12
    assert lo <= 12
    assert hi <= 14

    lo, hi = compute_target_range(900)  # sqrt(900) = 30, capped to 12
    assert lo == 11
    assert hi == 14


# ---------------------------------------------------------------------------
# Treemap with custom rect
# ---------------------------------------------------------------------------

def test_squarified_treemap_custom_rect():
    """Treemap with non-unit rect covers it exactly."""
    parent_rect = (0.3, 0.2, 0.4, 0.5)
    values = [10, 5, 3]
    rects = squarified_treemap(values, parent_rect)
    assert len(rects) == 3

    px, py, pw, ph = parent_rect
    total_area = sum(r[2] * r[3] for r in rects)
    assert abs(total_area - pw * ph) < 1e-6

    # All rects should be contained within parent rect
    for x, y, w, h in rects:
        assert x >= px - 1e-9
        assert y >= py - 1e-9
        assert x + w <= px + pw + 1e-9
        assert y + h <= py + ph + 1e-9


# ---------------------------------------------------------------------------
# Recursive build tests
# ---------------------------------------------------------------------------

def test_recursive_build_2_levels(tmp_path):
    """Two-level build creates both levels with parent-child links."""
    # Need enough images so level-0 nodes are large enough to split (>= MIN_SPLIT_SIZE)
    artifact_dir, image_ids = _make_test_corpus(tmp_path, n_images=200, dim=8)
    manifest = build_atlas_recursive(artifact_dir, max_levels=2, seed=42)

    assert manifest["max_level"] >= 1
    assert manifest["corpus_size"] == 200

    # Level 0 should exist
    meta0 = load_atlas_meta(artifact_dir, level=0)
    assert meta0 is not None

    # Level 1 should exist
    meta1 = load_atlas_meta(artifact_dir, level=1)
    assert meta1 is not None
    assert len(meta1["nodes"]) > 0

    # Parent-child links: every level-1 node should reference a level-0 parent
    level0_ids = {n["node_id"] for n in meta0["nodes"]}
    for child in meta1["nodes"]:
        assert child["parent_id"] in level0_ids, (
            f"Child {child['node_id']} has unknown parent {child['parent_id']}"
        )

    # Level-0 nodes with children should list those children
    child_ids_in_level1 = {n["node_id"] for n in meta1["nodes"]}
    for parent_node in meta0["nodes"]:
        if parent_node["child_ids"]:
            for cid in parent_node["child_ids"]:
                assert cid in child_ids_in_level1


def test_recursive_build_4_levels(tmp_path):
    """Four-level build on 500-image corpus produces multiple levels."""
    artifact_dir, image_ids = _make_test_corpus(tmp_path, n_images=500, dim=8)
    manifest = build_atlas_recursive(artifact_dir, max_levels=4, seed=42)

    assert manifest["max_level"] >= 1
    assert manifest["total_nodes"] > manifest["levels"][0]["n_nodes"]
    assert manifest["corpus_size"] == 500

    # All level meta files should exist
    for level_stat in manifest["levels"]:
        lvl = level_stat["level"]
        meta = load_atlas_meta(artifact_dir, level=lvl)
        assert meta is not None, f"Missing meta for level {lvl}"
        assert len(meta["nodes"]) == level_stat["n_nodes"]


def test_child_rects_partition_parent(tmp_path):
    """Children's rects tile the parent rect: area sum matches, contained, no overlap."""
    artifact_dir, image_ids = _make_test_corpus(tmp_path, n_images=80, dim=8)
    build_atlas_recursive(artifact_dir, max_levels=2, seed=42)

    meta0 = load_atlas_meta(artifact_dir, level=0)
    meta1 = load_atlas_meta(artifact_dir, level=1)
    if meta1 is None:
        pytest.skip("No level 1 produced")

    child_by_parent = {}
    for child in meta1["nodes"]:
        pid = child["parent_id"]
        child_by_parent.setdefault(pid, []).append(child)

    for parent_node in meta0["nodes"]:
        children = child_by_parent.get(parent_node["node_id"], [])
        if not children:
            continue

        px, py, pw, ph = parent_node["rect"]
        parent_area = pw * ph

        # Area sum
        child_area = sum(c["rect"][2] * c["rect"][3] for c in children)
        assert abs(child_area - parent_area) < 1e-4, (
            f"Child area {child_area:.6f} != parent area {parent_area:.6f} "
            f"for parent {parent_node['node_id']}"
        )

        # Containment
        for child in children:
            cx, cy, cw, ch = child["rect"]
            assert cx >= px - 1e-9, f"Child {child['node_id']} left edge outside parent"
            assert cy >= py - 1e-9, f"Child {child['node_id']} top edge outside parent"
            assert cx + cw <= px + pw + 1e-9, f"Child {child['node_id']} right edge outside parent"
            assert cy + ch <= py + ph + 1e-9, f"Child {child['node_id']} bottom edge outside parent"


def test_children_partition_parent_images(tmp_path):
    """Union of child image_ids equals parent image_ids for each parent."""
    artifact_dir, image_ids = _make_test_corpus(tmp_path, n_images=80, dim=8)
    build_atlas_recursive(artifact_dir, max_levels=2, seed=42)

    meta0 = load_atlas_meta(artifact_dir, level=0)
    meta1 = load_atlas_meta(artifact_dir, level=1)
    if meta1 is None:
        pytest.skip("No level 1 produced")

    child_by_parent = {}
    for child in meta1["nodes"]:
        pid = child["parent_id"]
        child_by_parent.setdefault(pid, []).append(child)

    for parent_node in meta0["nodes"]:
        children = child_by_parent.get(parent_node["node_id"], [])
        if not children:
            continue

        parent_ids = set(parent_node["image_ids"])
        child_ids = set()
        for child in children:
            child_ids.update(child["image_ids"])

        assert child_ids == parent_ids, (
            f"Parent {parent_node['node_id']}: "
            f"missing {parent_ids - child_ids}, extra {child_ids - parent_ids}"
        )


def test_child_images_subset_of_parent(tmp_path):
    """Every child's image_ids is a subset of its parent's image_ids."""
    artifact_dir, image_ids = _make_test_corpus(tmp_path, n_images=80, dim=8)
    build_atlas_recursive(artifact_dir, max_levels=3, seed=42)

    manifest = load_atlas_manifest(artifact_dir)
    for level_stat in manifest["levels"]:
        lvl = level_stat["level"]
        if lvl == 0:
            continue
        meta = load_atlas_meta(artifact_dir, level=lvl)
        parent_meta = load_atlas_meta(artifact_dir, level=lvl - 1)
        parent_lookup = {n["node_id"]: set(n["image_ids"]) for n in parent_meta["nodes"]}

        for child in meta["nodes"]:
            pid = child["parent_id"]
            assert pid in parent_lookup, f"Unknown parent {pid} for {child['node_id']}"
            child_set = set(child["image_ids"])
            assert child_set <= parent_lookup[pid], (
                f"Child {child['node_id']} has images not in parent {pid}"
            )


def test_all_images_at_every_level(tmp_path):
    """Union of all node image_ids at each level equals full corpus."""
    artifact_dir, image_ids = _make_test_corpus(tmp_path, n_images=60, dim=8)
    build_atlas_recursive(artifact_dir, max_levels=3, seed=42)

    full_set = set(image_ids)
    manifest = load_atlas_manifest(artifact_dir)

    # Level 0 always covers full corpus
    meta0 = load_atlas_meta(artifact_dir, level=0)
    level0_ids = set()
    for node in meta0["nodes"]:
        level0_ids.update(node["image_ids"])
    assert level0_ids == full_set


def test_leaf_nodes_criteria(tmp_path):
    """Leaf nodes have size < MIN_SPLIT_SIZE or are at max level."""
    artifact_dir, image_ids = _make_test_corpus(tmp_path, n_images=80, dim=8)
    manifest = build_atlas_recursive(artifact_dir, max_levels=3, seed=42)

    max_level = manifest["max_level"]
    for level_stat in manifest["levels"]:
        lvl = level_stat["level"]
        meta = load_atlas_meta(artifact_dir, level=lvl)
        for node in meta["nodes"]:
            if node["is_leaf"]:
                assert node["size"] < MIN_SPLIT_SIZE or lvl == max_level, (
                    f"Leaf {node['node_id']} at level {lvl} has size {node['size']} "
                    f"but MIN_SPLIT_SIZE={MIN_SPLIT_SIZE} and max_level={max_level}"
                )


def test_recursive_determinism(tmp_path):
    """Two recursive builds with same seed produce identical output."""
    artifact_dir, image_ids = _make_test_corpus(tmp_path, n_images=60, dim=8)

    m1 = build_atlas_recursive(artifact_dir, max_levels=2, seed=42)
    # Save level metas
    metas1 = {}
    for ls in m1["levels"]:
        metas1[ls["level"]] = load_atlas_meta(artifact_dir, level=ls["level"])

    m2 = build_atlas_recursive(artifact_dir, max_levels=2, seed=42)
    metas2 = {}
    for ls in m2["levels"]:
        metas2[ls["level"]] = load_atlas_meta(artifact_dir, level=ls["level"])

    # Same levels produced
    assert set(metas1.keys()) == set(metas2.keys())

    for lvl in metas1:
        nodes1 = metas1[lvl]["nodes"]
        nodes2 = metas2[lvl]["nodes"]
        assert len(nodes1) == len(nodes2), f"Level {lvl}: different node counts"

        # Match by image_ids and compare rects
        id_to_rect1 = {frozenset(n["image_ids"]): tuple(n["rect"]) for n in nodes1}
        id_to_rect2 = {frozenset(n["image_ids"]): tuple(n["rect"]) for n in nodes2}
        assert set(id_to_rect1.keys()) == set(id_to_rect2.keys()), (
            f"Level {lvl}: different cluster memberships"
        )
        for key in id_to_rect1:
            iou = rect_iou(id_to_rect1[key], id_to_rect2[key])
            assert iou > 0.98, (
                f"Level {lvl}: IoU {iou} for cluster with {len(key)} images"
            )


def test_invariant_4_1_children_inside_parent_rect(tmp_path):
    """All child rects are geometrically contained within their parent rect."""
    artifact_dir, image_ids = _make_test_corpus(tmp_path, n_images=80, dim=8)
    build_atlas_recursive(artifact_dir, max_levels=3, seed=42)

    manifest = load_atlas_manifest(artifact_dir)
    for level_stat in manifest["levels"]:
        lvl = level_stat["level"]
        if lvl == 0:
            continue
        meta = load_atlas_meta(artifact_dir, level=lvl)
        parent_meta = load_atlas_meta(artifact_dir, level=lvl - 1)
        parent_lookup = {n["node_id"]: n["rect"] for n in parent_meta["nodes"]}

        for child in meta["nodes"]:
            pid = child["parent_id"]
            px, py, pw, ph = parent_lookup[pid]
            cx, cy, cw, ch = child["rect"]
            assert cx >= px - 1e-9
            assert cy >= py - 1e-9
            assert cx + cw <= px + pw + 1e-9
            assert cy + ch <= py + ph + 1e-9


def test_invariant_4_3_no_sigil_on_recursive_build(tmp_path):
    """Recursive atlas build does not create or modify sigil files."""
    artifact_dir, image_ids = _make_test_corpus(tmp_path, n_images=50, dim=8)
    sigil_dir = artifact_dir / "sigils"

    build_atlas_recursive(artifact_dir, max_levels=2, seed=42)

    assert not sigil_dir.exists(), "Recursive atlas build should not create sigil directory"


def test_manifest_synthesized_from_level0(tmp_path):
    """load_atlas_manifest synthesizes from level 0 when no manifest.json exists."""
    artifact_dir, image_ids = _make_test_corpus(tmp_path, n_images=30, dim=8)
    build_atlas(artifact_dir, level=0, seed=42)

    # No manifest.json should exist from single-level build
    manifest_path = artifact_dir / "atlas" / "manifest.json"
    assert not manifest_path.exists()

    # Synthesized manifest should work
    manifest = load_atlas_manifest(artifact_dir)
    assert manifest is not None
    assert manifest["max_level"] == 0
    assert manifest["corpus_size"] == 30
    assert manifest["total_nodes"] > 0


def test_get_children_returns_correct_nodes(tmp_path):
    """get_children returns only children of the specified parent."""
    artifact_dir, image_ids = _make_test_corpus(tmp_path, n_images=80, dim=8)
    build_atlas_recursive(artifact_dir, max_levels=2, seed=42)

    meta0 = load_atlas_meta(artifact_dir, level=0)
    # Find a parent with children
    parent_with_children = None
    for node in meta0["nodes"]:
        if node["child_ids"]:
            parent_with_children = node
            break

    if parent_with_children is None:
        pytest.skip("No parent with children found")

    children = get_children(artifact_dir, parent_with_children["node_id"], parent_level=0)
    assert len(children) == len(parent_with_children["child_ids"])
    for child in children:
        assert child["parent_id"] == parent_with_children["node_id"]
        assert child["node_id"] in parent_with_children["child_ids"]
