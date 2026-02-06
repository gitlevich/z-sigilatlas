#!/usr/bin/env python3
"""Select a diverse demo subset from the SigilAtlas corpus.

Exclusion criteria:
    - High scores on sem_portrait and sem_people_vs_empty

Inclusion criteria:
    - Good coverage of all 36 contrast axes (images at both extremes)
    - Visual diversity via CLIP embedding space
    - Target: 150-300 images

Algorithm:
    1. Exclude people/portrait images using thresholds on semantic axes.
    2. Seed the selection with extreme exemplars from every contrast axis
       (top-K and bottom-K by coordinate value) to guarantee coverage.
    3. Fill remaining budget via greedy farthest-point sampling in CLIP
       embedding space to maximise visual diversity.
    4. Report coverage statistics and save the selected IDs.

Usage:
    python scripts/select_demo_subset.py [--target 200] [--portrait-threshold 0.85]
"""

import argparse
import json
import logging
import sqlite3
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

ROOT = Path(__file__).resolve().parent.parent
CATALOG_DB = ROOT / "artifacts" / "catalog.db"
COORDINATES_JSON = ROOT / "artifacts" / "contrasts" / "coordinates.json"
CONTRAST_LIBRARY_JSON = ROOT / "artifacts" / "contrasts" / "contrast_library.json"
CLIP_INDEX_JSON = ROOT / "artifacts" / "embeddings" / "clip" / "index.json"
CLIP_VECTORS_NPY = ROOT / "artifacts" / "embeddings" / "clip" / "vectors.npy"
OUTPUT_JSON = ROOT / "scripts" / "demo_image_ids.json"

# Contrasts used to detect people/portrait images
PEOPLE_CONTRASTS = ["sem_portrait", "sem_people_vs_empty"]

# Percentile above which an image is considered "has people"
# Applied independently to each people-contrast; union of flagged sets is excluded.
DEFAULT_PORTRAIT_PERCENTILE = 0.85

# How many extreme images to seed per axis per pole (low + high)
EXTREMES_PER_POLE = 5

DEFAULT_TARGET = 200


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_image_ids_from_catalog() -> list[str]:
    """Return all image_ids from catalog.db."""
    conn = sqlite3.connect(str(CATALOG_DB))
    cur = conn.cursor()
    cur.execute("SELECT image_id FROM images")
    ids = [row[0] for row in cur.fetchall()]
    conn.close()
    log.info("Catalog: %d images", len(ids))
    return ids


def load_coordinates() -> dict[str, dict[str, float]]:
    """Load coordinates.json -> {contrast_name: {image_id: score}}."""
    with open(COORDINATES_JSON) as f:
        coords = json.load(f)
    log.info("Coordinates: %d contrasts, %d images per contrast",
             len(coords), len(next(iter(coords.values()))))
    return coords


def load_contrast_library() -> list[dict]:
    """Load the contrast library for metadata."""
    with open(CONTRAST_LIBRARY_JSON) as f:
        lib = json.load(f)
    return lib["contrasts"]


def load_clip_embeddings() -> tuple[dict[str, int], np.ndarray]:
    """Load CLIP index and vectors. Returns (id_to_row, vectors)."""
    with open(CLIP_INDEX_JSON) as f:
        id_to_row = json.load(f)
    vectors = np.load(str(CLIP_VECTORS_NPY))
    log.info("CLIP embeddings: %d images, %d dims", vectors.shape[0], vectors.shape[1])
    return id_to_row, vectors


# ---------------------------------------------------------------------------
# People exclusion
# ---------------------------------------------------------------------------

def find_people_images(
    coords: dict[str, dict[str, float]],
    all_ids: list[str],
    percentile: float,
) -> set[str]:
    """Identify images scoring above `percentile` on any people-related contrast."""
    excluded = set()
    for contrast_name in PEOPLE_CONTRASTS:
        if contrast_name not in coords:
            log.warning("People contrast %r not found in coordinates", contrast_name)
            continue
        scores = coords[contrast_name]
        values = np.array([scores.get(iid, 0.0) for iid in all_ids])
        threshold = np.percentile(values, percentile * 100)
        flagged = {iid for iid, v in zip(all_ids, values) if v >= threshold}
        log.info("  %s: threshold=%.4f (p%.0f), flagged %d images",
                 contrast_name, threshold, percentile * 100, len(flagged))
        excluded |= flagged
    log.info("Total excluded (people): %d images", len(excluded))
    return excluded


# ---------------------------------------------------------------------------
# Axis-coverage seeding
# ---------------------------------------------------------------------------

def seed_extreme_images(
    coords: dict[str, dict[str, float]],
    eligible: set[str],
    per_pole: int,
) -> set[str]:
    """For every contrast axis, pick the top and bottom `per_pole` images."""
    seeded = set()
    eligible_list = list(eligible)
    for contrast_name, scores in coords.items():
        ranked = sorted(eligible_list, key=lambda iid: scores.get(iid, 0.0))
        low_set = set(ranked[:per_pole])
        high_set = set(ranked[-per_pole:])
        seeded |= low_set | high_set
    log.info("Seeded %d images from axis extremes (%d axes x %d per pole x 2)",
             len(seeded), len(coords), per_pole)
    return seeded


# ---------------------------------------------------------------------------
# Diversity fill via farthest-point sampling in CLIP space
# ---------------------------------------------------------------------------

def farthest_point_sample(
    seed_ids: set[str],
    eligible: set[str],
    id_to_row: dict[str, int],
    vectors: np.ndarray,
    target: int,
) -> list[str]:
    """Greedily add images that are farthest from the current selection.

    Uses cosine distance in CLIP embedding space.
    Returns the full ordered selection (seeds first, then diversity fills).
    """
    # Normalise vectors for cosine similarity
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1, norms)
    normed = vectors / norms

    # Build index arrays
    seed_list = list(seed_ids)
    remaining = list(eligible - seed_ids)

    if not remaining or len(seed_list) >= target:
        return seed_list[:target]

    # Row indices for seeds and candidates
    seed_rows = np.array([id_to_row[iid] for iid in seed_list if iid in id_to_row])
    cand_ids = [iid for iid in remaining if iid in id_to_row]
    cand_rows = np.array([id_to_row[iid] for iid in cand_ids])

    if len(cand_rows) == 0:
        return seed_list

    # Initial min-distance from each candidate to nearest seed
    # Cosine distance = 1 - cosine_similarity
    seed_vecs = normed[seed_rows]  # (S, D)
    cand_vecs = normed[cand_rows]  # (C, D)
    # Similarity matrix: (C, S)
    sim = cand_vecs @ seed_vecs.T
    min_dist = 1.0 - sim.max(axis=1)  # (C,) closest seed distance

    selected = list(seed_list)
    budget = target - len(selected)

    for _ in range(min(budget, len(cand_ids))):
        # Pick candidate with largest min distance to any selected
        best_idx = int(np.argmax(min_dist))
        best_id = cand_ids[best_idx]
        selected.append(best_id)

        # Update min distances with the newly added point
        new_vec = normed[id_to_row[best_id]].reshape(1, -1)  # (1, D)
        new_sim = (cand_vecs @ new_vec.T).squeeze()  # (C,)
        new_dist = 1.0 - new_sim
        min_dist = np.minimum(min_dist, new_dist)

        # Mark chosen candidate as unavailable
        min_dist[best_idx] = -1.0

    log.info("Diversity fill: %d seeds + %d filled = %d total",
             len(seed_list), len(selected) - len(seed_list), len(selected))
    return selected


# ---------------------------------------------------------------------------
# Coverage report
# ---------------------------------------------------------------------------

def coverage_report(
    selected_ids: list[str],
    coords: dict[str, dict[str, float]],
    all_ids: list[str],
) -> dict:
    """Compute per-axis coverage statistics for the selection."""
    stats = {}
    selected_set = set(selected_ids)
    for contrast_name, scores in coords.items():
        all_values = np.array([scores.get(iid, 0.0) for iid in all_ids])
        sel_values = np.array([scores.get(iid, 0.0) for iid in selected_ids])

        global_p10 = np.percentile(all_values, 10)
        global_p90 = np.percentile(all_values, 90)

        low_count = int(np.sum(sel_values <= global_p10))
        high_count = int(np.sum(sel_values >= global_p90))

        stats[contrast_name] = {
            "selected_min": float(sel_values.min()),
            "selected_max": float(sel_values.max()),
            "global_p10": float(global_p10),
            "global_p90": float(global_p90),
            "count_at_low_extreme": low_count,
            "count_at_high_extreme": high_count,
            "both_extremes_covered": low_count > 0 and high_count > 0,
        }
    return stats


def print_coverage_summary(stats: dict):
    """Print a readable coverage table."""
    total = len(stats)
    covered = sum(1 for s in stats.values() if s["both_extremes_covered"])
    print(f"\n{'='*70}")
    print(f"AXIS COVERAGE: {covered}/{total} axes have both extremes represented")
    print(f"{'='*70}")
    print(f"{'Contrast':<35} {'Low#':>5} {'High#':>5} {'Covered':>8}")
    print(f"{'-'*35} {'-'*5} {'-'*5} {'-'*8}")
    for name, s in sorted(stats.items()):
        mark = "YES" if s["both_extremes_covered"] else "---"
        print(f"{name:<35} {s['count_at_low_extreme']:>5} {s['count_at_high_extreme']:>5} {mark:>8}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Select diverse demo subset")
    parser.add_argument("--target", type=int, default=DEFAULT_TARGET,
                        help="Target number of images (default: %(default)s)")
    parser.add_argument("--portrait-threshold", type=float,
                        default=DEFAULT_PORTRAIT_PERCENTILE,
                        help="Percentile threshold for people exclusion (default: %(default)s)")
    parser.add_argument("--extremes-per-pole", type=int, default=EXTREMES_PER_POLE,
                        help="Extreme images per axis per pole (default: %(default)s)")
    args = parser.parse_args()

    # Load data
    all_ids = load_image_ids_from_catalog()
    coords = load_coordinates()
    id_to_row, vectors = load_clip_embeddings()

    # Step 1: Exclude people
    excluded = find_people_images(coords, all_ids, args.portrait_threshold)
    eligible = set(all_ids) - excluded
    # Also restrict to images that have CLIP embeddings
    eligible = eligible & set(id_to_row.keys())
    log.info("Eligible after exclusion: %d images", len(eligible))

    # Step 2: Seed with axis extremes
    seeds = seed_extreme_images(coords, eligible, args.extremes_per_pole)
    log.info("Seed count (axis extremes): %d", len(seeds))

    # Step 3: Diversity fill
    selected = farthest_point_sample(
        seed_ids=seeds,
        eligible=eligible,
        id_to_row=id_to_row,
        vectors=vectors,
        target=args.target,
    )

    # Step 4: Coverage report
    stats = coverage_report(selected, coords, all_ids)
    print_coverage_summary(stats)

    print(f"\nSelected {len(selected)} images (from {len(all_ids)} total, "
          f"{len(excluded)} excluded as people)")

    # Save output
    output = {
        "count": len(selected),
        "excluded_people_count": len(excluded),
        "target": args.target,
        "portrait_threshold_percentile": args.portrait_threshold,
        "image_ids": selected,
    }
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSON, "w") as f:
        json.dump(output, f, indent=2)
    log.info("Saved %d image IDs to %s", len(selected), OUTPUT_JSON)


if __name__ == "__main__":
    main()
