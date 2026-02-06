"""Ride planning with drift policy cascade.

Given a ride contrast, lock-set, precomputed z-summaries, and correlations,
produce a ride plan that enforces honest single-axis presentation. The drift
policy cascade is: single -> condition -> compound -> reject.

Pure computation, no I/O.
"""

import logging
import statistics
from dataclasses import dataclass, field, asdict

log = logging.getLogger(__name__)


@dataclass
class RidePlan:
    """Immutable plan for a contrast ride."""

    ride_contrast: str          # contrast_name being swept
    ride_contrast_id: str       # contrast_id for sigil integration
    resolution: str             # "single" | "compound" | "condition" | "reject"
    path: list[str]             # ordered node_ids (ascending z_mean in ride contrast)
    locked: list[str]           # locked contrast_names
    drift_estimates: dict       # {locked_contrast: expected_z_drift}
    condition_info: dict | None = None   # {contrast_name, z_band, original_len, restricted_len}
    compound_info: dict | None = None    # {drifting_contrast, drift_magnitude}
    reject_reason: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def derive_lock_set(ride_contrast_name: str, sigil: dict) -> list[str]:
    """Derive default lock-set from sigil.

    Returns all collapsed contrast_names in the sigil except the ride contrast.
    """
    entries = sigil.get("entries", {})
    return [
        entry["contrast_name"]
        for entry in entries.values()
        if entry["contrast_name"] != ride_contrast_name
    ]


def plan_ride(
    ride_contrast: str,
    ride_contrast_id: str,
    lock_set: list[str],
    zsummaries: dict[str, dict[str, dict]],
    correlations: dict[str, dict[str, float]],
    nodes: list[dict],
    tolerance: float = 2.0,
    condition_band_width: float = 0.5,
    min_path_length: int = 5,
) -> RidePlan:
    """Plan a ride for ride_contrast with drift policy.

    Steps:
    1. Sort nodes by z_mean for ride_contrast (ascending).
    2. For each locked contrast, compute expected drift:
       drift = abs(z_mean[last_node] - z_mean[first_node])
    3. Apply drift policy cascade:
       a. If all drift < tolerance -> resolution="single"
       b. For each drifting contrast:
          i.  Try condition: restrict to nodes in narrow z_mean band
          ii. Try compound: if exactly 1 drifter
          iii. reject

    Does NOT mutate any inputs.
    """
    ride_zs = zsummaries.get(ride_contrast, {})

    # 1. Sort nodes by z_mean for ride contrast
    node_ids = [n["node_id"] for n in nodes]
    node_zmeans = {nid: ride_zs.get(nid, {}).get("z_mean", 0.0) for nid in node_ids}
    sorted_ids = sorted(node_ids, key=lambda nid: node_zmeans[nid])

    if len(sorted_ids) < 2:
        return RidePlan(
            ride_contrast=ride_contrast,
            ride_contrast_id=ride_contrast_id,
            resolution="reject",
            path=sorted_ids,
            locked=list(lock_set),
            drift_estimates={},
            reject_reason="Too few nodes for a ride",
        )

    # 2. Compute expected drift for each locked contrast
    drift_estimates = {}
    drifters = []
    for lc in lock_set:
        lc_zs = zsummaries.get(lc, {})
        z_first = lc_zs.get(sorted_ids[0], {}).get("z_mean", 0.0)
        z_last = lc_zs.get(sorted_ids[-1], {}).get("z_mean", 0.0)
        drift = abs(z_last - z_first)
        drift_estimates[lc] = round(drift, 6)
        if drift > tolerance:
            drifters.append((lc, drift))

    # 3. Apply drift policy
    if not drifters:
        # All within tolerance -> single-axis ride
        return RidePlan(
            ride_contrast=ride_contrast,
            ride_contrast_id=ride_contrast_id,
            resolution="single",
            path=sorted_ids,
            locked=list(lock_set),
            drift_estimates=drift_estimates,
        )

    # Try condition: restrict path for the worst drifter
    worst_lc, worst_drift = max(drifters, key=lambda x: x[1])
    conditioned_path = _try_condition(
        sorted_ids, worst_lc, zsummaries, ride_contrast,
        condition_band_width, min_path_length,
    )
    if conditioned_path is not None:
        # Recheck drift on conditioned path
        cond_drift = {}
        cond_drifters = []
        for lc in lock_set:
            lc_zs = zsummaries.get(lc, {})
            z_first = lc_zs.get(conditioned_path[0], {}).get("z_mean", 0.0)
            z_last = lc_zs.get(conditioned_path[-1], {}).get("z_mean", 0.0)
            d = abs(z_last - z_first)
            cond_drift[lc] = round(d, 6)
            if d > tolerance:
                cond_drifters.append(lc)

        if not cond_drifters:
            lc_zs_full = zsummaries.get(worst_lc, {})
            band_vals = [lc_zs_full.get(nid, {}).get("z_mean", 0.0) for nid in conditioned_path]
            return RidePlan(
                ride_contrast=ride_contrast,
                ride_contrast_id=ride_contrast_id,
                resolution="condition",
                path=conditioned_path,
                locked=list(lock_set),
                drift_estimates=cond_drift,
                condition_info={
                    "contrast_name": worst_lc,
                    "z_band": [round(min(band_vals), 4), round(max(band_vals), 4)],
                    "original_len": len(sorted_ids),
                    "restricted_len": len(conditioned_path),
                },
            )

    # Try compound: only if exactly 1 drifter
    if len(drifters) == 1:
        return RidePlan(
            ride_contrast=ride_contrast,
            ride_contrast_id=ride_contrast_id,
            resolution="compound",
            path=sorted_ids,
            locked=list(lock_set),
            drift_estimates=drift_estimates,
            compound_info={
                "drifting_contrast": drifters[0][0],
                "drift_magnitude": round(drifters[0][1], 4),
            },
        )

    # Reject: multiple drifters, conditioning failed
    drifter_names = [d[0] for d in drifters]
    return RidePlan(
        ride_contrast=ride_contrast,
        ride_contrast_id=ride_contrast_id,
        resolution="reject",
        path=sorted_ids,
        locked=list(lock_set),
        drift_estimates=drift_estimates,
        reject_reason=(
            f"Multiple correlated contrasts drift beyond tolerance: "
            f"{', '.join(drifter_names)}"
        ),
    )


def _try_condition(
    sorted_ids: list[str],
    drifting_contrast: str,
    zsummaries: dict,
    ride_contrast: str,
    band_width: float,
    min_path_length: int,
) -> list[str] | None:
    """Try to restrict the ride path to a z_mean band for the drifting contrast.

    Returns conditioned path (sorted by ride contrast z_mean) or None if
    the restricted set is too small.
    """
    dc_zs = zsummaries.get(drifting_contrast, {})
    rc_zs = zsummaries.get(ride_contrast, {})

    # Compute median z_mean for drifting contrast across all sorted nodes
    dc_zmeans = [dc_zs.get(nid, {}).get("z_mean", 0.0) for nid in sorted_ids]
    if not dc_zmeans:
        return None
    median_z = statistics.median(dc_zmeans)
    lo = median_z - band_width / 2
    hi = median_z + band_width / 2

    # Filter nodes within band
    conditioned = [
        nid for nid in sorted_ids
        if lo <= dc_zs.get(nid, {}).get("z_mean", 0.0) <= hi
    ]

    if len(conditioned) < min_path_length:
        return None

    # Re-sort by ride contrast z_mean
    conditioned.sort(key=lambda nid: rc_zs.get(nid, {}).get("z_mean", 0.0))
    return conditioned


def compute_ride_drift_at_position(
    path: list[str],
    position: int,
    lock_set: list[str],
    zsummaries: dict[str, dict[str, dict]],
) -> dict[str, float]:
    """Compute current drift for each locked contrast at ride position.

    drift[c] = abs(z_mean[path[position]] - z_mean[path[0]]) for contrast c.
    Used during ride for real-time drift monitoring.
    """
    if position < 0 or position >= len(path):
        return {lc: 0.0 for lc in lock_set}

    start_id = path[0]
    current_id = path[position]
    result = {}
    for lc in lock_set:
        lc_zs = zsummaries.get(lc, {})
        z_start = lc_zs.get(start_id, {}).get("z_mean", 0.0)
        z_current = lc_zs.get(current_id, {}).get("z_mean", 0.0)
        result[lc] = round(abs(z_current - z_start), 6)
    return result
