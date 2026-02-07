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


def compute_category_gate(
    category_weights: dict[str, float],
    contrast_library: dict,
    coordinates: dict[str, dict[str, float]],
    nodes: list[dict],
) -> dict[str, float]:
    """Compute per-node category gate values for multiplicative filtering.

    Each category weight (0 to 1) controls how much that category contributes.
    Gate = weighted average of normalized category coordinates across active
    categories. Nodes matching active categories get higher gates.

    Args:
        category_weights: {contrast_id: weight} where weight in [0, 1].
        contrast_library: Full contrast library with quantiles.
        coordinates: {contrast_name: {image_id: float}} per-image scores.
        nodes: List of atlas node dicts, each with node_id and image_ids.

    Returns:
        {node_id: gate_value} where gate_value in [0, 1].
        Returns all 1.0 if no active categories.
    """
    if not category_weights:
        return {node["node_id"]: 1.0 for node in nodes}

    # Filter to active categories (weight > 0)
    active = {cid: w for cid, w in category_weights.items() if w > 0.01}
    if not active:
        return {node["node_id"]: 0.0 for node in nodes}

    # Build lookup: contrast_id -> {name, quantiles, coords}
    id_to_info = {}
    for c in contrast_library.get("contrasts", []):
        cid = c["contrast_id"]
        if cid not in active:
            continue
        cname = c["name"]
        if cname not in coordinates:
            log.warning("Category %s not in coordinates, skipping", cname)
            continue
        id_to_info[cid] = {
            "name": cname,
            "p10": c["quantiles"]["p10"],
            "p90": c["quantiles"]["p90"],
            "coords": coordinates[cname],
        }

    if not id_to_info:
        return {node["node_id"]: 0.0 for node in nodes}

    total_weight = sum(active[cid] for cid in id_to_info)

    result = {}
    for node in nodes:
        image_ids = node.get("image_ids", [])
        weighted_sum = 0.0

        for cid, info in id_to_info.items():
            weight = active[cid]

            # Compute node mean for this category
            values = []
            for iid in image_ids:
                val = info["coords"].get(iid)
                if val is not None:
                    values.append(val)

            if not values:
                normalized = 0.5
            else:
                node_mean = sum(values) / len(values)
                span = info["p90"] - info["p10"]
                if span > 0:
                    normalized = max(0.0, min(1.0, (node_mean - info["p10"]) / span))
                else:
                    normalized = 0.5

            weighted_sum += weight * normalized

        gate = weighted_sum / total_weight if total_weight > 0 else 0.0
        result[node["node_id"]] = max(0.0, min(1.0, gate))

    return result


def compute_sigil_scores(
    sigil: dict,
    contrast_library: dict,
    coordinates: dict[str, dict[str, float]],
    nodes: list[dict],
    category_weights: dict[str, float] | None = None,
) -> dict[str, dict]:
    """Compute per-node sigil compatibility scores.

    Args:
        sigil: User sigil with entries keyed by contrast_id.
        contrast_library: Full contrast library with quantiles.
        coordinates: {contrast_name: {image_id: float}} per-image scores.
        nodes: List of atlas node dicts, each with node_id and image_ids.
        category_weights: Optional {contrast_id: weight} for multiplicative
            category filter. If provided, final score = walk_score * gate.

    Returns:
        {node_id: {"score": float, "breakdown": [...]}}
        score in [0, 1]: 1 = perfectly aligned with sigil, 0 = opposite.
    """
    entries = sigil.get("entries", {}) if sigil else {}

    # Compute category gates if weights provided
    gates = None
    if category_weights is not None:
        gates = compute_category_gate(
            category_weights, contrast_library, coordinates, nodes
        )

    if not entries:
        base = {
            node["node_id"]: {"score": 0.5, "breakdown": []}
            for node in nodes
        }
        if gates is not None:
            for nid in base:
                base[nid]["score"] = round(0.5 * gates.get(nid, 1.0), 6)
                base[nid]["gate"] = round(gates.get(nid, 1.0), 6)
        return base

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

        # Apply multiplicative category gate
        gate = gates.get(node["node_id"], 1.0) if gates else 1.0
        final_score = score * gate

        entry = {
            "score": round(final_score, 6),
            "breakdown": breakdown,
        }
        if gates is not None:
            entry["gate"] = round(gate, 6)
        result[node["node_id"]] = entry

    return result
