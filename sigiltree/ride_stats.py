"""Precompute per-node z-score summaries and inter-contrast correlations.

Used by the ride engine for cheap runtime drift measurement. Pure computation
functions have no I/O; thin wrappers handle persistence.
"""

import json
import logging
import math
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)


def compute_node_zsummaries(
    coordinates: dict[str, dict[str, float]],
    nodes: list[dict],
) -> dict[str, dict[str, dict[str, float]]]:
    """Compute per-node z-score summaries for each contrast.

    For each contrast, compute the global (corpus-wide) mean and stddev across
    all images, then for each node compute:
        z_mean = mean((val - global_mean) / global_std)
        z_std  = std((val - global_mean) / global_std)

    Args:
        coordinates: {contrast_name: {image_id: float}}
        nodes: list of node dicts with "node_id" and "image_ids"

    Returns:
        {contrast_name: {node_id: {"z_mean": float, "z_std": float, "n": int}}}
    """
    result = {}
    for cname, cvals in coordinates.items():
        all_vals = list(cvals.values())
        if not all_vals:
            continue
        gmean = sum(all_vals) / len(all_vals)
        gvar = sum((v - gmean) ** 2 for v in all_vals) / len(all_vals)
        gstd = math.sqrt(gvar) if gvar > 0 else 1.0

        node_summaries = {}
        for node in nodes:
            zscores = []
            for iid in node.get("image_ids", []):
                val = cvals.get(iid)
                if val is not None:
                    zscores.append((val - gmean) / gstd)
            if not zscores:
                node_summaries[node["node_id"]] = {"z_mean": 0.0, "z_std": 0.0, "n": 0}
                continue
            zmean = sum(zscores) / len(zscores)
            if len(zscores) > 1:
                zvar = sum((z - zmean) ** 2 for z in zscores) / len(zscores)
                zstd = math.sqrt(zvar)
            else:
                zstd = 0.0
            node_summaries[node["node_id"]] = {
                "z_mean": round(zmean, 6),
                "z_std": round(zstd, 6),
                "n": len(zscores),
            }
        result[cname] = node_summaries
    return result


def compute_contrast_correlations(
    coordinates: dict[str, dict[str, float]],
) -> dict[str, dict[str, float]]:
    """Compute Pearson correlation matrix for all contrasts.

    Aligns image_ids across contrasts (uses intersection of all contrasts),
    builds numpy matrix, computes corrcoef.

    Returns:
        {contrast_a: {contrast_b: float}} -- symmetric, diagonal = 1.0
    """
    contrast_names = sorted(coordinates.keys())
    if not contrast_names:
        return {}

    # Find common image_ids
    common_ids = None
    for cname in contrast_names:
        ids = set(coordinates[cname].keys())
        common_ids = ids if common_ids is None else common_ids & ids
    common_ids = sorted(common_ids) if common_ids else []

    if len(common_ids) < 2:
        # Not enough data for correlation
        return {a: {b: (1.0 if a == b else 0.0) for b in contrast_names} for a in contrast_names}

    # Build matrix: rows = contrasts, cols = images
    matrix = np.zeros((len(contrast_names), len(common_ids)))
    for i, cname in enumerate(contrast_names):
        for j, iid in enumerate(common_ids):
            matrix[i, j] = coordinates[cname][iid]

    corr = np.corrcoef(matrix)

    result = {}
    for i, ca in enumerate(contrast_names):
        result[ca] = {}
        for j, cb in enumerate(contrast_names):
            result[ca][cb] = round(float(corr[i, j]), 6)
    return result


def compute_ride_stats(
    coordinates: dict[str, dict[str, float]],
    all_level_nodes: list[list[dict]],
) -> dict:
    """Compute z-summaries for all levels and correlation matrix.

    Args:
        coordinates: {contrast_name: {image_id: float}}
        all_level_nodes: list of node lists, index = level

    Returns:
        {
            "zsummaries": {"0": {...}, "1": {...}, ...},
            "correlations": {contrast_a: {contrast_b: float}},
        }
    """
    zsummaries = {}
    for level, nodes in enumerate(all_level_nodes):
        log.info("Computing z-summaries for level %d (%d nodes)", level, len(nodes))
        zsummaries[str(level)] = compute_node_zsummaries(coordinates, nodes)

    log.info("Computing inter-contrast correlation matrix")
    correlations = compute_contrast_correlations(coordinates)

    return {"zsummaries": zsummaries, "correlations": correlations}


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_ride_stats(stats: dict, artifact_dir: Path) -> None:
    """Save precomputed ride stats to atlas artifact directory."""
    atlas_dir = artifact_dir / "atlas"
    atlas_dir.mkdir(parents=True, exist_ok=True)

    zsum_path = atlas_dir / "node_zsummaries.json"
    corr_path = atlas_dir / "contrast_correlations.json"

    zsum_path.write_text(json.dumps(stats["zsummaries"], indent=1))
    corr_path.write_text(json.dumps(stats["correlations"], indent=1))

    log.info("Saved z-summaries to %s", zsum_path)
    log.info("Saved correlations to %s", corr_path)


def load_ride_stats(artifact_dir: Path) -> dict | None:
    """Load precomputed ride stats. Returns None if not yet computed."""
    zsum_path = artifact_dir / "atlas" / "node_zsummaries.json"
    corr_path = artifact_dir / "atlas" / "contrast_correlations.json"

    if not zsum_path.exists() or not corr_path.exists():
        return None

    return {
        "zsummaries": json.loads(zsum_path.read_text()),
        "correlations": json.loads(corr_path.read_text()),
    }
