"""Emergent taste axis: materialize the personal good-bad axis as a first-class contrast.

The calibration walk discovers N contrast preferences. Scoring computes a dot
product transiently. This module materializes that dot product as a per-image
scalar — the user's emergent taste coordinate — with its own quantiles,
exemplars, and z-summaries.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

from sigiltree.contrasts import _compute_exemplars

log = logging.getLogger(__name__)


def compute_taste_coordinates(
    sigil: dict,
    contrast_library: dict,
    coordinates: dict[str, dict[str, float]],
    n_exemplars: int = 12,
) -> dict | None:
    """Project every image onto the user's taste axis.

    Same formula as compute_sigil_scores but at the image level:
    taste[i] = mean over collapsed contrasts of (aligned_c(i) * strength_c).

    Args:
        sigil: User's taste sigil with entries.
        contrast_library: Full contrast library with quantiles.
        coordinates: {contrast_name: {image_id: float}}.
        n_exemplars: How many exemplar images per band.

    Returns:
        Dict with coordinates, quantiles, exemplars, components.
        None if sigil has no usable entries.
    """
    if sigil is None:
        return None
    entries = sigil.get("entries", {})
    if not entries:
        return None

    # Build quantile lookup
    quantile_lookup = {}
    for c in contrast_library.get("contrasts", []):
        quantile_lookup[c["contrast_id"]] = c["quantiles"]

    # Prepare collapsed contrast specs (same logic as sigil_scoring.py)
    collapsed = []
    for cid, entry in entries.items():
        contrast_name = entry["contrast_name"]
        if contrast_name not in coordinates:
            log.warning("Taste axis: contrast %s not in coordinates, skipping", contrast_name)
            continue
        quantiles = quantile_lookup.get(entry.get("contrast_id", cid))
        if quantiles is None:
            log.warning("Taste axis: no quantiles for %s, skipping", cid)
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
        return None

    # Collect all image IDs across all collapsed contrasts
    all_image_ids = set()
    for spec in collapsed:
        all_image_ids.update(spec["coords"].keys())
    all_image_ids = sorted(all_image_ids)

    # Compute per-image taste coordinate
    taste_coords = {}
    for iid in all_image_ids:
        total = 0.0
        count = 0
        for spec in collapsed:
            val = spec["coords"].get(iid)
            if val is None:
                continue
            span = spec["p90"] - spec["p10"]
            if span > 0:
                normalized = max(0.0, min(1.0, (val - spec["p10"]) / span))
            else:
                normalized = 0.5
            aligned = (1.0 - normalized) if spec["direction"] == "left" else normalized
            total += aligned * spec["strength"]
            count += 1
        if count > 0:
            taste_coords[iid] = round(total / count, 6)

    if not taste_coords:
        return None

    # Quantiles
    scores = np.array(list(taste_coords.values()))
    image_ids = list(taste_coords.keys())
    q = np.percentile(scores, [10, 25, 50, 75, 90])
    quantiles = {
        "p10": round(float(q[0]), 6),
        "p25": round(float(q[1]), 6),
        "p50": round(float(q[2]), 6),
        "p75": round(float(q[3]), 6),
        "p90": round(float(q[4]), 6),
    }

    # Exemplars
    scores_for_exemplars = np.array([taste_coords[iid] for iid in image_ids])
    exemplars = _compute_exemplars(scores_for_exemplars, image_ids, n_exemplars)

    # Components record
    components = [
        {
            "contrast_name": spec["contrast_name"],
            "direction": spec["direction"],
            "strength": spec["strength"],
        }
        for spec in collapsed
    ]

    return {
        "coordinates": taste_coords,
        "quantiles": quantiles,
        "exemplars": exemplars,
        "components": components,
    }


def materialize_taste_axis(sigil: dict, artifact_dir: Path) -> Path | None:
    """Compute and persist the emergent taste axis for a user's sigil.

    Loads contrast library and coordinates, computes taste coordinates,
    z-summaries at all atlas levels, and saves the result.

    Returns:
        Path to saved file, or None if sigil has no entries.
    """
    from sigiltree.arcade import save_taste_axis
    from sigiltree.atlas import load_atlas_meta
    from sigiltree.ride_stats import compute_node_zsummaries

    lib_path = artifact_dir / "contrasts" / "contrast_library.json"
    coords_path = artifact_dir / "contrasts" / "coordinates.json"
    if not lib_path.exists() or not coords_path.exists():
        log.warning("Taste axis: missing contrast library or coordinates")
        return None

    library = json.loads(lib_path.read_text())
    coordinates = json.loads(coords_path.read_text())

    result = compute_taste_coordinates(sigil, library, coordinates)
    if result is None:
        return None

    # Compute z-summaries for each atlas level
    manifest_path = artifact_dir / "atlas" / "manifest.json"
    zsummaries = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        max_level = manifest.get("max_level", 0)
        taste_coords_dict = {"taste_axis": result["coordinates"]}
        for level in range(max_level + 1):
            meta = load_atlas_meta(artifact_dir, level=level)
            if meta is None:
                continue
            zs = compute_node_zsummaries(taste_coords_dict, meta["nodes"])
            zsummaries[str(level)] = zs.get("taste_axis", {})

    user_id = sigil.get("user_id", "default")
    taste_data = {
        "contrast_id": f"taste_{sigil.get('version', 'unknown')[:16]}",
        "name": "taste_axis",
        "sigil_version": sigil.get("version", ""),
        "coordinates": result["coordinates"],
        "quantiles": result["quantiles"],
        "exemplars": result["exemplars"],
        "components": result["components"],
        "zsummaries": zsummaries,
    }

    path = save_taste_axis(taste_data, artifact_dir, user_id)
    n_images = len(result["coordinates"])
    n_components = len(result["components"])
    log.info("Materialized taste axis: %d images, %d components -> %s", n_images, n_components, path)
    return path
