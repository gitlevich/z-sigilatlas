"""Sigil rendering: compute per-node compatibility scores for overlay rendering.

Given a user's sigil (collapsed contrasts with direction/strength), per-image
contrast coordinates, and atlas nodes, compute how well each node aligns with
the user's preferences. Scores drive brighten/dim overlays in the viewer.

Design invariants:
- Only collapsed contrasts influence scores (uncollapsed = superposed = invisible)
- Scores are overlay data only; they never alter atlas topology or tile content
- This module performs pure computation with no I/O or side effects
"""

import logging

log = logging.getLogger(__name__)


def compute_sigil_scores(
    sigil: dict,
    contrast_library: dict,
    coordinates: dict[str, dict[str, float]],
    nodes: list[dict],
) -> dict[str, dict]:
    """Compute per-node sigil compatibility scores.

    Args:
        sigil: User sigil with entries keyed by contrast_id.
        contrast_library: Full contrast library with quantiles.
        coordinates: {contrast_name: {image_id: float}} per-image scores.
        nodes: List of atlas node dicts, each with node_id and image_ids.

    Returns:
        {node_id: {"score": float, "breakdown": [...]}}
        score in [0, 1]: 1 = perfectly aligned with sigil, 0 = opposite.
    """
    entries = sigil.get("entries", {})
    if not entries:
        return {
            node["node_id"]: {"score": 0.5, "breakdown": []}
            for node in nodes
        }

    # Build quantile lookup: contrast_id -> {p10, p90}
    quantile_lookup = {}
    for c in contrast_library.get("contrasts", []):
        quantile_lookup[c["contrast_id"]] = c["quantiles"]

    # Prepare collapsed contrast specs
    collapsed = []
    for cid, entry in entries.items():
        contrast_name = entry["contrast_name"]
        if contrast_name not in coordinates:
            log.warning("Sigil contrast %s not in coordinates, skipping", contrast_name)
            continue
        quantiles = quantile_lookup.get(entry["contrast_id"])
        if quantiles is None:
            log.warning("No quantiles for contrast %s, skipping", cid)
            continue
        collapsed.append({
            "contrast_name": contrast_name,
            "direction": entry["direction"],
            "strength": entry.get("strength", 1.0),
            "coords": coordinates[contrast_name],
            "p10": quantiles["p10"],
            "p90": quantiles["p90"],
        })

    if not collapsed:
        return {
            node["node_id"]: {"score": 0.5, "breakdown": []}
            for node in nodes
        }

    result = {}
    for node in nodes:
        image_ids = node.get("image_ids", [])
        breakdown = []
        total_contribution = 0.0

        for spec in collapsed:
            # Compute node mean for this contrast
            values = []
            for iid in image_ids:
                val = spec["coords"].get(iid)
                if val is not None:
                    values.append(val)

            if not values:
                # No data for this contrast on this node
                breakdown.append({
                    "contrast_name": spec["contrast_name"],
                    "direction": spec["direction"],
                    "strength": spec["strength"],
                    "node_mean": 0.0,
                    "normalized": 0.5,
                    "contribution": 0.5 * spec["strength"],
                })
                total_contribution += 0.5 * spec["strength"]
                continue

            node_mean = sum(values) / len(values)

            # Normalize to [0, 1] using p10/p90 range
            p10 = spec["p10"]
            p90 = spec["p90"]
            span = p90 - p10
            if span > 0:
                normalized = max(0.0, min(1.0, (node_mean - p10) / span))
            else:
                normalized = 0.5

            # Align with direction
            if spec["direction"] == "right":
                aligned = normalized
            else:
                aligned = 1.0 - normalized

            contribution = aligned * spec["strength"]
            total_contribution += contribution

            breakdown.append({
                "contrast_name": spec["contrast_name"],
                "direction": spec["direction"],
                "strength": spec["strength"],
                "node_mean": round(node_mean, 6),
                "normalized": round(normalized, 6),
                "contribution": round(contribution, 6),
            })

        score = total_contribution / len(collapsed) if collapsed else 0.5
        score = max(0.0, min(1.0, score))

        result[node["node_id"]] = {
            "score": round(score, 6),
            "breakdown": breakdown,
        }

    return result
