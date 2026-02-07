"""Flow graph: continuous navigation between atlas nodes.

For each node, computes ordered list of flow-neighbors by cosine
similarity of z-profiles. Enables lateral navigation without dead ends.

Pure computation. No I/O.
"""

import logging
import math

log = logging.getLogger(__name__)


def _z_profile(node_id: str, zsummaries: dict) -> list[float]:
    """Extract z-mean vector for a node across all contrasts.

    Returns list of z_mean values in sorted-contrast-name order.
    """
    profile = []
    for cname in sorted(zsummaries.keys()):
        z = zsummaries[cname].get(node_id, {}).get("z_mean", 0.0)
        profile.append(z)
    return profile


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a < 1e-12 or norm_b < 1e-12:
        return 0.0
    return dot / (norm_a * norm_b)


def compute_flow_graph(
    node_ids: list[str],
    zsummaries: dict,
    node_rects: dict[str, tuple[float, float, float, float]] | None = None,
) -> dict[str, list[str]]:
    """Compute flow-neighbor ordering for each node by z-profile similarity.

    For each node, returns all other nodes sorted by descending cosine
    similarity of their z-profiles (z_mean across all contrasts).

    Args:
        node_ids: list of node_ids to include in the flow graph.
        zsummaries: {contrast_name: {node_id: {z_mean, ...}}}
        node_rects: optional {node_id: (x, y, w, h)} for spatial tie-breaking.

    Returns:
        {node_id: [neighbor_id_1, neighbor_id_2, ...]} sorted by similarity desc.
    """
    if len(node_ids) < 2:
        return {nid: [] for nid in node_ids}

    profiles = {nid: _z_profile(nid, zsummaries) for nid in node_ids}

    flow = {}
    for nid in node_ids:
        similarities = []
        for other in node_ids:
            if other == nid:
                continue
            sim = _cosine_similarity(profiles[nid], profiles[other])
            similarities.append((other, sim))
        similarities.sort(key=lambda x: -x[1])
        flow[nid] = [s[0] for s in similarities]

    return flow


def flow_in_direction(
    current_id: str,
    direction: str,
    flow_graph: dict[str, list[str]],
    node_rects: dict[str, tuple[float, float, float, float]],
) -> str | None:
    """Pick the best flow-neighbor in a spatial direction.

    From the current node's rect center, finds the flow-neighbor whose rect
    center is most aligned with the requested direction. Falls back to the
    nearest flow-neighbor if none are in the exact direction.

    Args:
        current_id: current node_id.
        direction: "right", "left", "up", or "down".
        flow_graph: {node_id: [ordered neighbor_ids]}.
        node_rects: {node_id: (x, y, w, h)}.

    Returns:
        Best neighbor node_id, or None if no neighbors.
    """
    neighbors = flow_graph.get(current_id, [])
    if not neighbors:
        return None

    cur_rect = node_rects.get(current_id)
    if not cur_rect:
        return neighbors[0]

    cx = cur_rect[0] + cur_rect[2] / 2
    cy = cur_rect[1] + cur_rect[3] / 2

    def is_in_direction(nid: str) -> bool:
        """True if nid's rect center is in the requested direction from current."""
        r = node_rects.get(nid)
        if not r:
            return False
        nx = r[0] + r[2] / 2
        ny = r[1] + r[3] / 2
        dx = nx - cx
        dy = ny - cy

        if direction == "right":
            return dx > 0
        elif direction == "left":
            return dx < 0
        elif direction == "up":
            return dy < 0  # screen coords: up = lower y
        elif direction == "down":
            return dy > 0
        return False

    def distance(nid: str) -> float:
        """Euclidean distance from current center to nid center."""
        r = node_rects.get(nid)
        if not r:
            return float("inf")
        nx = r[0] + r[2] / 2
        ny = r[1] + r[3] / 2
        return math.sqrt((nx - cx) ** 2 + (ny - cy) ** 2)

    # Among flow-neighbors, find those in the requested direction
    # Pick the nearest one (not the furthest)
    in_dir = [nid for nid in neighbors if is_in_direction(nid)]

    if in_dir:
        return min(in_dir, key=distance)

    # No neighbor in that direction: wrap to most similar (first in flow list)
    return neighbors[0]
