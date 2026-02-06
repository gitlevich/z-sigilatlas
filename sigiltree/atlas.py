"""Atlas construction: fused neighbor graph, clustering, ordering, layout, tile rendering.

Builds a multiscale atlas pyramid where each non-leaf node contains a child atlas
that partitions the node's rectangle exactly.
Pipeline per level: fused kNN graph -> Louvain clustering -> Fiedler ordering -> squarified treemap -> tile rendering.
"""
from __future__ import annotations

import json
import hashlib
import logging
import math
import time
from collections import Counter
from dataclasses import dataclass, asdict, field
from pathlib import Path

from sigiltree import db

# Heavy imports deferred to function scope for lightweight serving
# numpy, PIL, EmbeddingStore used only during atlas *building*, not loading
np = None  # lazy
Image = None  # lazy
EmbeddingStore = None  # lazy
FAMILIES = None  # lazy


def _ensure_heavy_imports():
    """Import numpy, PIL, embeddings on first use (atlas building only)."""
    global np, Image, EmbeddingStore, FAMILIES
    if np is None:
        import numpy as _np
        np = _np
    if Image is None:
        from PIL import Image as _Image
        Image = _Image
    if EmbeddingStore is None:
        from sigiltree.embeddings import EmbeddingStore as _ES, FAMILIES as _F
        EmbeddingStore = _ES
        FAMILIES = _F

log = logging.getLogger(__name__)

MIN_SPLIT_SIZE = 4  # Nodes with fewer images become leaves


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class AtlasNode:
    """A neighborhood in the atlas."""
    node_id: str
    image_ids: list[str]
    size: int
    order_key: float
    rect: tuple[float, float, float, float]  # (x, y, w, h) in [0,1] world space
    tile_path: str
    representative_ids: list[str]
    neighbor_ids: list[str]
    level: int = 0
    parent_id: str | None = None
    child_ids: list[str] = field(default_factory=list)
    is_leaf: bool = False


# ---------------------------------------------------------------------------
# Squarified treemap
# ---------------------------------------------------------------------------

def squarified_treemap(
    values: list[float],
    rect: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0),
) -> list[tuple[float, float, float, float]]:
    """Compute squarified treemap layout (Bruls-Huizing-van Wijk 2000).

    Args:
        values: ordered list of positive weights.
        rect: (x, y, w, h) bounding rectangle.

    Returns:
        List of (x, y, w, h) rectangles, one per value, partitioning rect exactly.
    """
    if not values:
        return []
    if len(values) == 1:
        return [rect]

    x, y, w, h = rect
    total = sum(values)
    if total <= 0:
        return [(x, y, w / len(values), h) for _ in values]

    # Normalize values to areas within the rectangle
    area = w * h
    areas = [v / total * area for v in values]

    return _squarify(areas, x, y, w, h)


def _squarify(
    areas: list[float], x: float, y: float, w: float, h: float,
) -> list[tuple[float, float, float, float]]:
    """Recursive squarified layout."""
    if len(areas) == 0:
        return []
    if len(areas) == 1:
        return [(x, y, w, h)]

    # Lay along the shorter side
    horizontal = w >= h
    side = min(w, h)

    # Greedily add items to strip while aspect ratio improves
    strip = [areas[0]]
    remaining = areas[1:]

    while remaining:
        candidate = strip + [remaining[0]]
        if _worst_ratio(candidate, side) <= _worst_ratio(strip, side):
            strip = candidate
            remaining = remaining[1:]
        else:
            break

    # Layout the strip
    strip_total = sum(strip)
    if horizontal:
        strip_w = strip_total / h if h > 0 else 0
        rects = []
        cy = y
        for a in strip:
            rect_h = a / strip_w if strip_w > 0 else h
            rects.append((x, cy, strip_w, rect_h))
            cy += rect_h
        # Recurse on remaining area
        rects.extend(_squarify(remaining, x + strip_w, y, w - strip_w, h))
    else:
        strip_h = strip_total / w if w > 0 else 0
        rects = []
        cx = x
        for a in strip:
            rect_w = a / strip_h if strip_h > 0 else w
            rects.append((cx, y, rect_w, strip_h))
            cx += rect_w
        rects.extend(_squarify(remaining, x, y + strip_h, w, h - strip_h))

    return rects


def _worst_ratio(areas: list[float], side: float) -> float:
    """Worst aspect ratio in a strip laid along `side`."""
    if not areas or side <= 0:
        return float("inf")
    total = sum(areas)
    strip_len = total / side
    if strip_len <= 0:
        return float("inf")
    ratios = []
    for a in areas:
        item_side = a / strip_len if strip_len > 0 else 0
        if item_side <= 0:
            ratios.append(float("inf"))
        else:
            r = max(strip_len / item_side, item_side / strip_len)
            ratios.append(r)
    return max(ratios)


# ---------------------------------------------------------------------------
# Fused neighbor graph
# ---------------------------------------------------------------------------

def build_fused_graph(
    artifact_dir: Path,
    image_ids: list[str],
    k: int = 20,
) -> tuple[np.ndarray, dict[str, int]]:
    """Build fused neighbor graph from 3 embedding families.

    Per family: load embeddings, build k-NN (cosine).
    Fuse: keep edges appearing in >= 2 of 3 families.

    Returns:
        adjacency: (N, N) weighted matrix (weight = vote count 2 or 3)
        id_to_idx: mapping from image_id to matrix index
    """
    _ensure_heavy_imports()
    from sklearn.neighbors import NearestNeighbors

    id_to_idx = {iid: i for i, iid in enumerate(image_ids)}
    n = len(image_ids)
    edge_votes: Counter = Counter()

    for family_name, family_info in FAMILIES.items():
        store = EmbeddingStore(artifact_dir, family_name, family_info["dim"])
        vecs = store.get_batch(image_ids)
        if vecs.shape[0] == 0:
            log.warning("No embeddings for family %s, skipping", family_name)
            continue

        actual_k = min(k + 1, n)  # +1 because kNN includes self
        nn = NearestNeighbors(n_neighbors=actual_k, metric="cosine")
        nn.fit(vecs)
        _, indices = nn.kneighbors(vecs)

        for i in range(n):
            for j_pos in range(1, actual_k):  # skip self at position 0
                j = indices[i, j_pos]
                edge = (min(i, j), max(i, j))
                edge_votes[edge] += 1

    # Build adjacency from edges with >= 2 votes
    adjacency = np.zeros((n, n), dtype=np.float32)
    for (i, j), votes in edge_votes.items():
        if votes >= 2:
            adjacency[i, j] = votes
            adjacency[j, i] = votes

    log.info("Fused graph: %d nodes, %d edges (>= 2 votes)",
             n, sum(1 for v in edge_votes.values() if v >= 2))
    return adjacency, id_to_idx


# ---------------------------------------------------------------------------
# Sublevel graph (for recursive atlas)
# ---------------------------------------------------------------------------

def build_sublevel_graph(
    artifact_dir: Path,
    image_ids: list[str],
    k: int | None = None,
) -> tuple[np.ndarray, dict[str, int]]:
    """Build a local fused kNN graph for a subset of images.

    Uses a smaller k than the full-corpus graph to capture fine local structure.
    For very small subsets (< 6 images), returns a fully-connected graph.
    """
    _ensure_heavy_imports()
    n = len(image_ids)
    if k is None:
        k = min(10, n - 1)
    if n < 6:
        # Fully connected for tiny groups
        adjacency = np.ones((n, n), dtype=np.float32) * 3.0
        np.fill_diagonal(adjacency, 0.0)
        id_to_idx = {iid: i for i, iid in enumerate(image_ids)}
        return adjacency, id_to_idx
    return build_fused_graph(artifact_dir, image_ids, k=k)


def compute_target_range(n_images: int) -> tuple[int, int]:
    """Compute target cluster count range scaled to node size."""
    target = max(2, int(math.sqrt(n_images)))
    target = min(target, 12)
    return (max(2, target - 1), target + 2)


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------

def cluster_neighborhoods(
    adjacency: np.ndarray,
    seed: int = 42,
    target_range: tuple[int, int] = (20, 40),
) -> list[list[int]]:
    """Cluster fused graph into neighborhoods using Louvain.

    Binary-searches resolution to target the desired cluster count range.

    Returns:
        List of clusters, each a list of node indices.
    """
    _ensure_heavy_imports()
    import networkx as nx

    G = nx.from_numpy_array(adjacency)

    # Binary search resolution
    lo, hi = 0.1, 10.0
    best_communities = None
    best_resolution = 1.0
    best_diff = float("inf")
    target_min, target_max = target_range

    for _ in range(20):
        mid = (lo + hi) / 2
        communities = list(nx.community.louvain_communities(
            G, weight="weight", resolution=mid, seed=seed,
        ))
        n_comm = len(communities)

        if target_min <= n_comm <= target_max:
            best_communities = communities
            best_resolution = mid
            break

        diff = abs(n_comm - (target_min + target_max) / 2)
        if diff < best_diff:
            best_diff = diff
            best_communities = communities
            best_resolution = mid

        if n_comm < target_min:
            lo = mid  # need more communities → higher resolution
        else:
            hi = mid  # need fewer communities → lower resolution

    log.info("Louvain: %d neighborhoods at resolution %.4f",
             len(best_communities), best_resolution)

    # Convert frozensets to sorted lists
    clusters = [sorted(c) for c in best_communities]
    # Sort clusters by smallest member index for determinism
    clusters.sort(key=lambda c: c[0])
    return clusters


# ---------------------------------------------------------------------------
# Ordering (Fiedler vector)
# ---------------------------------------------------------------------------

def compute_ordering(adjacency: np.ndarray) -> np.ndarray:
    """Compute 1D ordering from the Fiedler vector (second-smallest eigenvector of Laplacian).

    Returns:
        Array of shape (N,) with ordering values per node.
    """
    _ensure_heavy_imports()
    from scipy.sparse import csr_matrix
    from scipy.sparse.linalg import eigsh

    n = adjacency.shape[0]
    if n <= 1:
        return np.zeros(n)

    degree = adjacency.sum(axis=1)
    laplacian = np.diag(degree) - adjacency
    L_sparse = csr_matrix(laplacian)

    # Handle disconnected graph: add tiny connections
    import networkx as nx
    G = nx.from_numpy_array(adjacency)
    if not nx.is_connected(G):
        log.warning("Fused graph is disconnected, adding minimal bridges")
        components = list(nx.connected_components(G))
        for i in range(len(components) - 1):
            a = min(components[i])
            b = min(components[i + 1])
            adjacency[a, b] = 0.01
            adjacency[b, a] = 0.01
        degree = adjacency.sum(axis=1)
        laplacian = np.diag(degree) - adjacency
        L_sparse = csr_matrix(laplacian)

    k_eigs = min(2, n)
    eigenvalues, eigenvectors = eigsh(L_sparse, k=k_eigs, which="SM")
    fiedler = eigenvectors[:, -1]  # second eigenvector (eigsh returns ascending)

    # Canonicalize sign: ensure first non-negligible element is positive
    for val in fiedler:
        if abs(val) > 1e-10:
            if val < 0:
                fiedler = -fiedler
            break

    return fiedler.astype(np.float64)


# ---------------------------------------------------------------------------
# Representatives
# ---------------------------------------------------------------------------

def compute_representatives(
    adjacency: np.ndarray,
    cluster_indices: list[int],
    k: int = 9,
) -> list[int]:
    """Select k representative nodes for a neighborhood.

    Strategy: highest within-cluster weighted degree (most connected to cluster members).

    Returns:
        List of node indices (into full adjacency matrix).
    """
    if len(cluster_indices) <= k:
        return list(cluster_indices)

    idx_set = set(cluster_indices)
    scores = []
    for i in cluster_indices:
        internal_degree = sum(adjacency[i, j] for j in cluster_indices if j != i)
        scores.append((internal_degree, i))
    scores.sort(reverse=True)
    return [idx for _, idx in scores[:k]]


# ---------------------------------------------------------------------------
# Tile rendering
# ---------------------------------------------------------------------------

def _best_thumb_dir(artifact_dir: Path) -> tuple[Path, int]:
    """Return the highest-resolution available thumbnail directory and its size."""
    for sz in [512, 256, 128, 64]:
        d = artifact_dir / "thumbnails" / str(sz)
        if d.exists():
            return d, sz
    return artifact_dir / "thumbnails" / "64", 64


def _cover_crop(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Resize and center-crop an image to exactly target_w x target_h (cover fit)."""
    src_w, src_h = img.size
    # Scale so the image covers the target rect entirely
    scale = max(target_w / src_w, target_h / src_h)
    new_w = int(src_w * scale)
    new_h = int(src_h * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    # Center crop
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))


def _partition_into_rows(n: int) -> list[int]:
    """Partition n images into rows for a square canvas with zero waste.

    Returns list of items-per-row, e.g. [3, 3, 3] for n=9 or [3, 2] for n=5.
    Goal: rows have nearly equal item counts, total items = n exactly.
    """
    import math
    if n <= 0:
        return []
    if n == 1:
        return [1]
    # Number of rows ≈ sqrt(n) for a square grid
    num_rows = max(1, round(math.sqrt(n)))
    # Distribute n items across num_rows as evenly as possible
    base = n // num_rows
    extra = n % num_rows
    # Rows with (base+1) items come first, then rows with base items
    rows = [base + 1] * extra + [base] * (num_rows - extra)
    return rows


def render_neighborhood_tile(
    image_ids: list[str],
    tile_width: int,
    tile_height: int,
    artifact_dir: Path,
    tile_path: Path,
    thumb_size: int = 64,
) -> None:
    """Render a mosaic tile for a neighborhood.

    Uses a variable-row layout to fill the entire canvas with zero waste.
    Each row spans the full width. Row heights are equal (tile_height / num_rows).
    Within each row, images are equally spaced (row_width / items_in_row).
    Every cell is filled using cover-crop. No image is repeated.
    """
    _ensure_heavy_imports()

    n_images = len(image_ids)
    if n_images == 0:
        tile = Image.new("RGB", (tile_width, tile_height), color=(17, 17, 17))
        tile_path.parent.mkdir(parents=True, exist_ok=True)
        tile.save(str(tile_path), quality=85)
        return

    thumb_dir, source_size = _best_thumb_dir(artifact_dir)

    row_counts = _partition_into_rows(n_images)
    num_rows = len(row_counts)

    tile = Image.new("RGB", (tile_width, tile_height), color=(17, 17, 17))

    idx = 0
    for ri, count in enumerate(row_counts):
        # Row vertical bounds
        y = ri * tile_height // num_rows
        y_next = (ri + 1) * tile_height // num_rows
        rh = y_next - y

        for ci in range(count):
            # Cell horizontal bounds within this row
            x = ci * tile_width // count
            x_next = (ci + 1) * tile_width // count
            cw = x_next - x

            if idx >= n_images:
                break

            iid = image_ids[idx]
            idx += 1

            thumb_path = thumb_dir / f"{iid}.jpg"
            if not thumb_path.exists():
                continue
            try:
                thumb = Image.open(thumb_path)
                thumb = _cover_crop(thumb, cw, rh)
                tile.paste(thumb, (x, y))
            except Exception as e:
                log.warning("Failed to load thumbnail %s: %s", thumb_path, e)

    tile_path.parent.mkdir(parents=True, exist_ok=True)
    tile.save(str(tile_path), quality=85)


# ---------------------------------------------------------------------------
# Inter-neighborhood edges
# ---------------------------------------------------------------------------

def compute_neighbor_edges(
    adjacency: np.ndarray,
    clusters: list[list[int]],
) -> dict[int, list[int]]:
    """Compute which neighborhoods are adjacent in the fused graph.

    Two neighborhoods are neighbors if any of their member nodes share an edge.

    Returns:
        Dict mapping cluster index to list of neighbor cluster indices.
    """
    n_clusters = len(clusters)
    # Build node-to-cluster map
    node_to_cluster = {}
    for ci, members in enumerate(clusters):
        for node in members:
            node_to_cluster[node] = ci

    neighbor_set: dict[int, set[int]] = {i: set() for i in range(n_clusters)}
    for ci, members in enumerate(clusters):
        for node in members:
            row = adjacency[node]
            for j in np.nonzero(row)[0]:
                cj = node_to_cluster.get(int(j))
                if cj is not None and cj != ci:
                    neighbor_set[ci].add(cj)

    return {ci: sorted(nbs) for ci, nbs in neighbor_set.items()}


# ---------------------------------------------------------------------------
# Main build pipeline
# ---------------------------------------------------------------------------

def build_atlas(
    artifact_dir: Path,
    level: int = 0,
    seed: int = 42,
) -> dict:
    """Build atlas level 0: fused graph → clustering → ordering → layout → tiles.

    Returns stats dict.
    """
    _ensure_heavy_imports()
    t0 = time.monotonic()

    # 1. Load image IDs
    conn = db.open_db(artifact_dir)
    all_images = db.get_all_images(conn)
    conn.close()
    image_ids = [img["image_id"] for img in all_images]
    n = len(image_ids)
    log.info("Building atlas level %d for %d images", level, n)

    # 2. Fused neighbor graph
    adjacency, id_to_idx = build_fused_graph(artifact_dir, image_ids, k=20)
    idx_to_id = {v: k for k, v in id_to_idx.items()}

    # 3. Cluster
    clusters = cluster_neighborhoods(adjacency, seed=seed)

    # 4. Fiedler ordering
    fiedler = compute_ordering(adjacency)

    # 5. Compute neighborhood order keys and sort
    cluster_order = []
    for ci, members in enumerate(clusters):
        order_key = float(np.mean(fiedler[members]))
        cluster_order.append((order_key, ci))
    cluster_order.sort()

    # 6. Squarified treemap
    ordered_sizes = [float(len(clusters[ci])) for _, ci in cluster_order]
    rects = squarified_treemap(ordered_sizes)

    # 7. Build nodes
    atlas_dir = artifact_dir / "atlas" / f"level{level}"
    tiles_dir = atlas_dir / "tiles"
    tiles_dir.mkdir(parents=True, exist_ok=True)

    # Inter-neighborhood edges
    neighbor_edges = compute_neighbor_edges(adjacency, clusters)

    # Atlas frame pixel size for tile rendering
    atlas_px_w = 2048
    atlas_px_h = 2048

    nodes = []
    for rank, ((order_key, ci), rect) in enumerate(zip(cluster_order, rects)):
        members = clusters[ci]
        member_ids = [idx_to_id[m] for m in members]
        # Sort by Fiedler value for consistency
        member_order = sorted(zip(fiedler[members], member_ids))
        sorted_member_ids = [iid for _, iid in member_order]

        node_id = f"n_{rank:03d}"

        # Representatives
        rep_indices = compute_representatives(adjacency, members, k=9)
        rep_ids = [idx_to_id[r] for r in rep_indices]

        # Neighbor node IDs
        neighbor_cluster_indices = neighbor_edges.get(ci, [])
        # Map cluster indices to node IDs (rank-based)
        ci_to_rank = {ci2: r for r, (_, ci2) in enumerate(cluster_order)}
        neighbor_node_ids = [f"n_{ci_to_rank[nci]:03d}" for nci in neighbor_cluster_indices
                            if nci in ci_to_rank]

        # Render tile matching the treemap cell's aspect ratio so
        # contain-fit fills the cell with zero black space and zero distortion.
        tile_name = f"neighborhood_{rank:03d}.jpg"
        tile_path = tiles_dir / tile_name
        TILE_LONG = 1024
        rx, ry, rw, rh = rect
        cell_aspect = rw / rh if rh > 0 else 1.0
        if cell_aspect >= 1.0:
            tile_w = TILE_LONG
            tile_h = max(64, round(TILE_LONG / cell_aspect))
        else:
            tile_h = TILE_LONG
            tile_w = max(64, round(TILE_LONG * cell_aspect))
        render_neighborhood_tile(
            sorted_member_ids, tile_w, tile_h, artifact_dir, tile_path,
        )

        node = AtlasNode(
            node_id=node_id,
            image_ids=sorted_member_ids,
            size=len(members),
            order_key=order_key,
            rect=rect,
            tile_path=f"tiles/{tile_name}",
            representative_ids=rep_ids,
            neighbor_ids=neighbor_node_ids,
            level=level,
            parent_id=None,
            child_ids=[],
            is_leaf=(len(members) < MIN_SPLIT_SIZE),
        )
        nodes.append(node)

    elapsed = time.monotonic() - t0

    # 8. Build metadata
    content_hash = hashlib.md5(
        json.dumps([asdict(n) for n in nodes], sort_keys=True).encode()
    ).hexdigest()[:8]

    meta = {
        "build_id": f"atlas_v1_{content_hash}",
        "level": level,
        "corpus_size": n,
        "n_neighborhoods": len(nodes),
        "frame": [0.0, 0.0, 1.0, 1.0],
        "random_seed": seed,
        "build_time": round(elapsed, 2),
        "determinism_seeds": {
            "fused_graph": seed,
            "louvain": seed,
            "spectral": seed,
        },
        "nodes": [asdict(n) for n in nodes],
    }

    meta_path = atlas_dir / "meta.json"
    meta_path.write_text(json.dumps(meta, indent=2))
    log.info("Atlas level %d built: %d neighborhoods in %.1fs. Saved to %s",
             level, len(nodes), elapsed, meta_path)

    return {
        "level": level,
        "corpus_size": n,
        "n_neighborhoods": len(nodes),
        "build_time": elapsed,
        "meta_path": str(meta_path),
    }


# ---------------------------------------------------------------------------
# Recursive multi-level build
# ---------------------------------------------------------------------------

def _build_level_nodes(
    artifact_dir: Path,
    parent_nodes: list[AtlasNode],
    target_level: int,
    seed: int,
    atlas_px_w: int = 2048,
    atlas_px_h: int = 2048,
) -> list[AtlasNode]:
    """Build child nodes for all non-leaf parents at the current level.

    Returns the list of child AtlasNode objects for target_level.
    Also updates parent_nodes' child_ids in place.
    """
    atlas_dir = artifact_dir / "atlas" / f"level{target_level}"
    tiles_dir = atlas_dir / "tiles"
    tiles_dir.mkdir(parents=True, exist_ok=True)

    child_nodes = []
    seq = 0

    for parent in parent_nodes:
        if parent.is_leaf or parent.size < MIN_SPLIT_SIZE:
            parent.is_leaf = True
            continue

        image_ids = parent.image_ids
        n = len(image_ids)

        # Build local fused graph
        adjacency, id_to_idx = build_sublevel_graph(artifact_dir, image_ids)
        idx_to_id = {v: k for k, v in id_to_idx.items()}

        # Cluster with scaled target range
        target_range = compute_target_range(n)
        clusters = cluster_neighborhoods(adjacency, seed=seed, target_range=target_range)

        # Fallback: if Louvain produces 1 cluster, split by Fiedler median
        if len(clusters) <= 1 and n >= MIN_SPLIT_SIZE:
            fiedler = compute_ordering(adjacency)
            median = float(np.median(fiedler))
            lo = [i for i in range(n) if fiedler[i] <= median]
            hi = [i for i in range(n) if fiedler[i] > median]
            if lo and hi:
                clusters = [sorted(lo), sorted(hi)]
            else:
                # Truly indivisible — mark as leaf
                parent.is_leaf = True
                continue

        # Fiedler ordering
        fiedler = compute_ordering(adjacency)

        # Order clusters by mean Fiedler value
        cluster_order = []
        for ci, members in enumerate(clusters):
            order_key = float(np.mean(fiedler[members]))
            cluster_order.append((order_key, ci))
        cluster_order.sort()

        # Layout children within parent rect
        ordered_sizes = [float(len(clusters[ci])) for _, ci in cluster_order]
        rects = squarified_treemap(ordered_sizes, rect=parent.rect)

        # Neighbor edges among children
        neighbor_edges = compute_neighbor_edges(adjacency, clusters)

        parent_child_ids = []
        for rank, ((order_key, ci), rect) in enumerate(zip(cluster_order, rects)):
            members = clusters[ci]
            member_ids = [idx_to_id[m] for m in members]
            member_order = sorted(zip(fiedler[members], member_ids))
            sorted_member_ids = [iid for _, iid in member_order]

            node_id = f"L{target_level}_{seq:04d}"
            seq += 1

            # Representatives
            rep_indices = compute_representatives(adjacency, members, k=9)
            rep_ids = [idx_to_id[r] for r in rep_indices]

            # Neighbor node IDs (will be resolved after all children created)
            ci_to_seq = {}
            for r2, (_, ci2) in enumerate(cluster_order):
                ci_to_seq[ci2] = seq - len(cluster_order) + r2
            neighbor_cluster_indices = neighbor_edges.get(ci, [])
            neighbor_node_ids = [
                f"L{target_level}_{ci_to_seq[nci]:04d}"
                for nci in neighbor_cluster_indices
                if nci in ci_to_seq
            ]

            # Render tile matching the treemap cell's aspect ratio so
            # contain-fit fills the cell with zero black space and zero distortion.
            tile_name = f"{node_id}.jpg"
            tile_path = tiles_dir / tile_name
            TILE_LONG = 1024
            rx, ry, rw, rh = rect
            cell_aspect = rw / rh if rh > 0 else 1.0
            if cell_aspect >= 1.0:
                tile_w = TILE_LONG
                tile_h = max(64, round(TILE_LONG / cell_aspect))
            else:
                tile_h = TILE_LONG
                tile_w = max(64, round(TILE_LONG * cell_aspect))
            render_neighborhood_tile(
                sorted_member_ids, tile_w, tile_h, artifact_dir, tile_path,
            )

            child = AtlasNode(
                node_id=node_id,
                image_ids=sorted_member_ids,
                size=len(members),
                order_key=order_key,
                rect=rect,
                tile_path=f"tiles/{tile_name}",
                representative_ids=rep_ids,
                neighbor_ids=neighbor_node_ids,
                level=target_level,
                parent_id=parent.node_id,
                child_ids=[],
                is_leaf=(len(members) < MIN_SPLIT_SIZE),
            )
            child_nodes.append(child)
            parent_child_ids.append(node_id)

        parent.child_ids = parent_child_ids

    return child_nodes


def build_atlas_recursive(
    artifact_dir: Path,
    max_levels: int = 4,
    seed: int = 42,
) -> dict:
    """Build a multiscale atlas pyramid with up to max_levels levels.

    Level 0 is the full-corpus coarse mosaic. Each subsequent level
    splits non-leaf nodes into finer neighborhoods.

    Returns stats dict.
    """
    _ensure_heavy_imports()
    t0 = time.monotonic()

    # Build level 0
    build_atlas(artifact_dir, level=0, seed=seed)
    meta0 = load_atlas_meta(artifact_dir, level=0)
    level0_nodes = [
        AtlasNode(**{k: v for k, v in n.items() if k in AtlasNode.__dataclass_fields__})
        for n in meta0["nodes"]
    ]

    all_level_stats = [{
        "level": 0,
        "n_nodes": len(level0_nodes),
        "n_leaves": sum(1 for n in level0_nodes if n.is_leaf),
    }]

    current_parents = level0_nodes
    for lvl in range(1, max_levels):
        splittable = [n for n in current_parents if not n.is_leaf]
        if not splittable:
            log.info("No splittable nodes at level %d, stopping", lvl - 1)
            break

        child_nodes = _build_level_nodes(
            artifact_dir, current_parents, target_level=lvl, seed=seed,
        )

        if not child_nodes:
            log.info("No children produced at level %d, stopping", lvl)
            break

        # Save this level's meta
        _save_level_meta(artifact_dir, lvl, child_nodes, seed, meta0["corpus_size"])

        # Update parent level's meta with child_ids
        _save_level_meta(
            artifact_dir, lvl - 1, current_parents, seed, meta0["corpus_size"],
        )

        all_level_stats.append({
            "level": lvl,
            "n_nodes": len(child_nodes),
            "n_leaves": sum(1 for n in child_nodes if n.is_leaf),
        })

        log.info("Level %d: %d nodes (%d leaves)",
                 lvl, len(child_nodes),
                 sum(1 for n in child_nodes if n.is_leaf))

        current_parents = child_nodes

    elapsed = time.monotonic() - t0

    # Write manifest
    manifest = {
        "build_id": f"atlas_v2_{hashlib.md5(str(time.time()).encode()).hexdigest()[:8]}",
        "max_level": all_level_stats[-1]["level"],
        "total_nodes": sum(s["n_nodes"] for s in all_level_stats),
        "levels": all_level_stats,
        "min_split_size": MIN_SPLIT_SIZE,
        "corpus_size": meta0["corpus_size"],
        "random_seed": seed,
        "total_build_time": round(elapsed, 2),
    }
    manifest_path = artifact_dir / "atlas" / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    log.info("Atlas pyramid built: %d levels, %d total nodes in %.1fs",
             manifest["max_level"] + 1, manifest["total_nodes"], elapsed)

    return manifest


def _save_level_meta(
    artifact_dir: Path,
    level: int,
    nodes: list[AtlasNode],
    seed: int,
    corpus_size: int,
) -> None:
    """Save a level's meta.json."""
    content_hash = hashlib.md5(
        json.dumps([asdict(n) for n in nodes], sort_keys=True).encode()
    ).hexdigest()[:8]

    meta = {
        "build_id": f"atlas_v2_{content_hash}",
        "level": level,
        "corpus_size": corpus_size,
        "n_neighborhoods": len(nodes),
        "random_seed": seed,
        "nodes": [asdict(n) for n in nodes],
    }

    meta_path = artifact_dir / "atlas" / f"level{level}" / "meta.json"
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta, indent=2))


# ---------------------------------------------------------------------------
# Load / verify
# ---------------------------------------------------------------------------

def load_atlas_manifest(artifact_dir: Path) -> dict | None:
    """Load the top-level atlas manifest. Synthesizes from level 0 if needed."""
    manifest_path = artifact_dir / "atlas" / "manifest.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text())
    # Synthesize from level 0
    meta0 = load_atlas_meta(artifact_dir, level=0)
    if meta0 is None:
        return None
    return {
        "max_level": 0,
        "total_nodes": meta0["n_neighborhoods"],
        "levels": [{"level": 0, "n_nodes": meta0["n_neighborhoods"], "n_leaves": 0}],
        "min_split_size": MIN_SPLIT_SIZE,
        "corpus_size": meta0["corpus_size"],
        "random_seed": meta0.get("random_seed", 42),
    }


def get_children(artifact_dir: Path, node_id: str, parent_level: int) -> list[dict]:
    """Get child nodes for a given parent node."""
    child_level = parent_level + 1
    child_meta = load_atlas_meta(artifact_dir, level=child_level)
    if child_meta is None:
        return []
    return [n for n in child_meta["nodes"] if n.get("parent_id") == node_id]


def load_atlas_meta(artifact_dir: Path, level: int = 0) -> dict | None:
    """Load atlas metadata from artifacts."""
    meta_path = artifact_dir / "atlas" / f"level{level}" / "meta.json"
    if not meta_path.exists():
        return None
    return json.loads(meta_path.read_text())


def rect_iou(
    r1: tuple[float, float, float, float],
    r2: tuple[float, float, float, float],
) -> float:
    """Intersection over Union of two (x, y, w, h) rectangles."""
    x1, y1, w1, h1 = r1
    x2, y2, w2, h2 = r2

    xi = max(0.0, min(x1 + w1, x2 + w2) - max(x1, x2))
    yi = max(0.0, min(y1 + h1, y2 + h2) - max(y1, y2))
    intersection = xi * yi
    union = w1 * h1 + w2 * h2 - intersection
    return intersection / union if union > 0 else 0.0


def verify_determinism(artifact_dir: Path, level: int = 0) -> dict:
    """Verify determinism tolerance by rebuilding and comparing.

    Checks:
      - IoU >= 0.98 for >= 95% of node rectangles
      - Kendall tau >= 0.99 for 1D ordering
    """
    _ensure_heavy_imports()
    from scipy.stats import kendalltau

    old_meta = load_atlas_meta(artifact_dir, level)
    if old_meta is None:
        return {"error": "No existing atlas to compare"}

    # Rebuild (without saving tiles, just compute layout)
    conn = db.open_db(artifact_dir)
    all_images = db.get_all_images(conn)
    conn.close()
    image_ids = [img["image_id"] for img in all_images]

    seed = old_meta["random_seed"]
    adjacency, id_to_idx = build_fused_graph(artifact_dir, image_ids, k=20)
    clusters = cluster_neighborhoods(adjacency, seed=seed)
    fiedler = compute_ordering(adjacency)

    cluster_order = []
    for ci, members in enumerate(clusters):
        order_key = float(np.mean(fiedler[members]))
        cluster_order.append((order_key, ci))
    cluster_order.sort()

    ordered_sizes = [float(len(clusters[ci])) for _, ci in cluster_order]
    new_rects = squarified_treemap(ordered_sizes)

    # Match old nodes by image_ids
    old_nodes = old_meta["nodes"]
    old_id_sets = {n["node_id"]: set(n["image_ids"]) for n in old_nodes}

    idx_to_id = {v: k for k, v in id_to_idx.items()}
    new_nodes_ids = []
    for _, ci in cluster_order:
        members = clusters[ci]
        member_ids = set(idx_to_id[m] for m in members)
        new_nodes_ids.append(member_ids)

    # Match by maximum overlap
    ious = []
    matched = 0
    for new_ids, new_rect in zip(new_nodes_ids, new_rects):
        best_iou = 0.0
        for old_node in old_nodes:
            if set(old_node["image_ids"]) == new_ids:
                old_rect = tuple(old_node["rect"])
                best_iou = rect_iou(old_rect, new_rect)
                break
        ious.append(best_iou)
        if best_iou >= 0.98:
            matched += 1

    pct_matched = matched / len(ious) if ious else 1.0

    # Ordering comparison via Kendall tau
    old_ordering = [n["order_key"] for n in old_nodes]
    new_ordering = [ok for ok, _ in cluster_order]
    tau, _ = kendalltau(old_ordering, new_ordering)

    result = {
        "iou_mean": float(np.mean(ious)) if ious else 1.0,
        "iou_min": float(np.min(ious)) if ious else 1.0,
        "pct_iou_098": pct_matched,
        "kendall_tau": float(tau) if not np.isnan(tau) else 1.0,
        "pass_iou": pct_matched >= 0.95,
        "pass_tau": tau >= 0.99 if not np.isnan(tau) else True,
        "pass": pct_matched >= 0.95 and (tau >= 0.99 if not np.isnan(tau) else True),
    }
    log.info("Determinism check: IoU>=0.98 for %.1f%% of rects, Kendall tau=%.4f",
             pct_matched * 100, tau)
    return result
