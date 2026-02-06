"""Silent calibration from navigation history + flow graph.

The flythrough IS the calibration. User navigates the atlas freely — clicking
into neighborhoods they find attractive — and the system records which nodes
they visit. Preferences are inferred from the z-profiles of visited nodes.

Flow graph: for each leaf node, ordered list of flow-neighbors by cosine
similarity of z-profiles. Enables continuous navigation without dead ends.

Pure computation. No I/O.
"""

import hashlib
import json
import logging
import math
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

MIN_VISITS = 5


@dataclass
class FlythroughSession:
    """Tracks navigation and infers preferences silently."""

    user_id: str
    visited: list[dict] = field(default_factory=list)

    def record_visit(self, node_id: str, level: int) -> None:
        """Record a node entry. Deduplicates consecutive visits to same node."""
        if self.visited and self.visited[-1]["node_id"] == node_id:
            return
        self.visited.append({
            "node_id": node_id,
            "level": level,
            "timestamp": time.time(),
        })

    @property
    def distinct_nodes(self) -> set[str]:
        """Unique node_ids visited."""
        return {v["node_id"] for v in self.visited}

    @property
    def is_ready(self) -> bool:
        """True if enough distinct visits to compute preferences."""
        return len(self.distinct_nodes) >= MIN_VISITS


def infer_preferences(
    visited_node_ids: list[str],
    zsummaries: dict,
    all_node_ids: list[str],
    contrast_library: dict,
    min_bias: float = 0.4,
) -> dict:
    """Infer sigil entries from visited nodes.

    For each contrast, computes mean z-score across visited nodes. If the
    absolute bias exceeds min_bias, the contrast collapses with direction
    and strength proportional to the magnitude.

    Args:
        visited_node_ids: node_ids the user navigated into.
        zsummaries: {contrast_name: {node_id: {z_mean, z_std, n}}}
        all_node_ids: all node_ids at this level (for reference).
        contrast_library: {contrasts: [{contrast_id, name, ...}]}
        min_bias: minimum |mean_z| to collapse a contrast.

    Returns:
        {contrast_id: sigil_entry_dict} for collapsed contrasts.
    """
    if not visited_node_ids:
        return {}

    contrasts = contrast_library.get("contrasts", [])
    entries = {}

    for contrast in contrasts:
        cname = contrast["name"]
        cid = contrast["contrast_id"]
        cz = zsummaries.get(cname, {})

        z_values = []
        for nid in visited_node_ids:
            node_z = cz.get(nid)
            if node_z is not None:
                z_values.append(node_z.get("z_mean", 0.0))

        if not z_values:
            continue

        visited_mean = sum(z_values) / len(z_values)

        if abs(visited_mean) < min_bias:
            continue

        direction = "right" if visited_mean > 0 else "left"
        strength = min(abs(visited_mean) / 2.0, 1.0)
        strength = max(strength, 0.5)

        entries[cid] = {
            "contrast_id": cid,
            "contrast_name": cname,
            "direction": direction,
            "strength": round(strength, 6),
            "n_presentations": len(visited_node_ids),
            "n_agreements": len([z for z in z_values
                                 if (z > 0) == (visited_mean > 0)]),
        }

    return entries


def flythrough_to_sigil(
    session: FlythroughSession,
    zsummaries: dict,
    contrast_library: dict,
    all_level_nodes: dict,
) -> dict:
    """Build a complete sigil from flythrough session.

    Uses the level where most visits occurred. Packages inferred preferences
    into a sigil dict compatible with save_sigil().

    Args:
        session: FlythroughSession with recorded visits.
        zsummaries: {level_str: {contrast_name: {node_id: {...}}}}
        contrast_library: full contrast library dict.
        all_level_nodes: {level_str: [node_id, ...]}

    Returns:
        Sigil dict compatible with arcade.save_sigil().
    """
    if not session.visited:
        return _empty_sigil(session.user_id, contrast_library)

    # Determine primary level (most visits)
    level_counts: dict[int, int] = {}
    for v in session.visited:
        lvl = v["level"]
        level_counts[lvl] = level_counts.get(lvl, 0) + 1
    primary_level = max(level_counts, key=level_counts.get)
    level_key = str(primary_level)

    # Collect visited node_ids at primary level
    visited_ids = list({
        v["node_id"] for v in session.visited
        if v["level"] == primary_level
    })

    level_zsummaries = zsummaries.get(level_key, {})
    all_ids = all_level_nodes.get(level_key, [])

    entries = infer_preferences(
        visited_ids, level_zsummaries, all_ids, contrast_library,
    )

    library_version = contrast_library.get("version", "unknown")

    sigil = {
        "version": f"sigil_v1_{hashlib.md5(json.dumps(entries, sort_keys=True).encode()).hexdigest()[:8]}",
        "contrast_library_version": library_version,
        "user_id": session.user_id,
        "created_at": time.time(),
        "entries": entries,
        "total_choices": len(session.visited),
        "collapsed_count": len(entries),
        "superposed_count": len(contrast_library.get("contrasts", [])) - len(entries),
    }

    return sigil


def _empty_sigil(user_id: str, contrast_library: dict) -> dict:
    """Return an empty sigil with no collapsed contrasts."""
    return {
        "version": "sigil_v1_empty",
        "contrast_library_version": contrast_library.get("version", "unknown"),
        "user_id": user_id,
        "created_at": time.time(),
        "entries": {},
        "total_choices": 0,
        "collapsed_count": 0,
        "superposed_count": len(contrast_library.get("contrasts", [])),
    }


# ---------------------------------------------------------------------------
# Flow graph: continuous navigation between leaves
# ---------------------------------------------------------------------------

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
