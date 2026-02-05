"""Contrast discovery, selection, and library construction.

Three sources of contrasts:
1. Perceptual: image-level color/tone/texture statistics
2. Semantic: CLIP zero-shot similarity to curated category prompts
3. Emergent: top PCA directions from each embedding family
"""

import json
import hashlib
import logging
import time
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
from PIL import Image

from sigiltree import db
from sigiltree.embeddings import EmbeddingStore, FAMILIES

log = logging.getLogger(__name__)

# Allow large panoramas
Image.MAX_IMAGE_PIXELS = 500_000_000


# ---------------------------------------------------------------------------
# Perceptual contrast extractors
# ---------------------------------------------------------------------------

def _compute_perceptual_scores(image_path: str) -> dict[str, float]:
    """Compute perceptual scalar scores for a single image."""
    try:
        img = Image.open(image_path).convert("RGB")
        img_small = img.resize((256, 256), Image.LANCZOS)
        arr = np.array(img_small, dtype=np.float32) / 255.0
    except Exception:
        return {}

    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    gray = 0.299 * r + 0.587 * g + 0.114 * b

    scores = {}

    # Temperature: warm (red-yellow) vs cool (blue)
    # Approximation: (R - B) channel difference
    scores["temperature"] = float((r - b).mean())

    # Tint: green vs magenta
    scores["tint"] = float((g - 0.5 * (r + b)).mean())

    # Brightness / tonality (high-key vs low-key)
    scores["brightness"] = float(gray.mean())

    # Saturation: distance from gray in RGB space
    mean_rgb = (r + g + b) / 3.0
    sat = np.sqrt(((r - mean_rgb) ** 2 + (g - mean_rgb) ** 2 + (b - mean_rgb) ** 2) / 3.0)
    scores["saturation"] = float(sat.mean())

    # Global contrast: std of luminance
    scores["contrast"] = float(gray.std())

    # Sharpness: Laplacian variance
    from PIL import ImageFilter
    gray_img = img_small.convert("L")
    lap = gray_img.filter(ImageFilter.Kernel(
        (3, 3), [-1, -1, -1, -1, 8, -1, -1, -1, -1], scale=1, offset=128
    ))
    lap_arr = np.array(lap, dtype=np.float32)
    scores["sharpness"] = float(lap_arr.var() / 1000.0)

    # Texture scale: ratio of high-freq to low-freq energy
    gray_arr = np.array(gray_img, dtype=np.float32) / 255.0
    fft_mag = np.abs(np.fft.fftshift(np.fft.fft2(gray_arr)))
    h, w = fft_mag.shape
    cy, cx = h // 2, w // 2
    y, x = np.ogrid[:h, :w]
    radius = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
    low_mask = radius < 32
    high_mask = radius >= 32
    low_energy = fft_mag[low_mask].sum()
    high_energy = fft_mag[high_mask].sum()
    scores["texture_scale"] = float(np.log1p(high_energy) / (np.log1p(low_energy) + 1e-8))

    # Color dominant hue (simplified via max channel ratios)
    r_dom = float((r > g).astype(float).mean() * (r > b).astype(float).mean())
    g_dom = float((g > r).astype(float).mean() * (g > b).astype(float).mean())
    b_dom = float((b > r).astype(float).mean() * (b > g).astype(float).mean())
    scores["red_dominance"] = r_dom
    scores["green_dominance"] = g_dom
    scores["blue_dominance"] = b_dom

    return scores


PERCEPTUAL_NAMES = [
    "temperature", "tint", "brightness", "saturation", "contrast",
    "sharpness", "texture_scale", "red_dominance", "green_dominance", "blue_dominance",
]


# ---------------------------------------------------------------------------
# Semantic contrast extractors (CLIP zero-shot, multi-term averaging)
# ---------------------------------------------------------------------------

# Unipolar categories: each has multiple descriptive terms whose CLIP text
# embeddings are averaged into a single centroid. Score = cosine(image, centroid).
SEMANTIC_CATEGORIES = {
    "portrait": [
        "portrait photograph", "portrait photo", "person portrait",
        "posed portrait", "studio portrait", "fashion shoot", "headshot",
    ],
    "landscape": [
        "landscape photograph", "landscape photo", "scenic landscape",
    ],
    "cityscape": [
        "cityscape photograph", "urban cityscape", "city skyline",
        "urban panorama", "city vista", "skyline at night",
    ],
    "architecture": [
        "architectural photograph", "architecture photo", "building photograph",
        "architecture facade", "building exterior", "architectural detail",
        "modern architecture",
    ],
    "still_life": [
        "still life photograph", "still life photo", "arranged objects",
    ],
    "abstract": [
        "abstract photograph", "abstract photo", "non-representational image",
    ],
    "macro": [
        "macro photograph", "close-up detail", "macro photography",
    ],
    "nature": [
        "nature photograph", "natural scene", "nature photography",
    ],
    "street": [
        "street photography", "candid street photo", "urban candid",
        "candid pedestrian", "people in public", "everyday city life",
        "city sidewalk", "crosswalk", "subway platform", "bus stop",
        "market street", "street vendor", "downtown street", "alleyway",
        "night street", "rainy street", "neon street",
    ],
    "night": [
        "nighttime photograph", "night scene", "dark scene",
        "night photography", "low light photograph",
    ],
    "interior": [
        "indoor photograph", "interior scene", "inside a building",
        "room interior", "interior design photograph",
    ],
}

# Bipolar contrasts: two poles, each with multiple terms. Score = sim(pole_b) - sim(pole_a).
SEMANTIC_CONTRASTS = {
    "bw_vs_color": {
        "pole_a": [
            "black and white photo", "monochrome photograph", "grayscale image",
        ],
        "pole_b": [
            "color photo", "full color photograph", "vibrant color image",
        ],
    },
    "interior_vs_exterior": {
        "pole_a": [
            "indoor photograph", "interior scene", "inside a building",
        ],
        "pole_b": [
            "outdoor photograph", "exterior scene", "outside",
        ],
    },
    "people_vs_empty": {
        "pole_a": [
            "photograph with people", "photo showing humans", "image with person",
        ],
        "pole_b": [
            "photograph without people", "empty scene", "no humans visible",
        ],
    },
    "abstract_vs_representational": {
        "pole_a": [
            "abstract photograph", "non-representational image", "abstract composition",
        ],
        "pole_b": [
            "representational photograph", "realistic image", "recognizable subject",
        ],
    },
    "closeup_vs_wide": {
        "pole_a": [
            "close-up photograph", "tight crop", "detail shot", "macro view",
        ],
        "pole_b": [
            "wide shot photograph", "environmental view", "establishing shot",
            "wide angle scene",
        ],
    },
    "natural_vs_manmade": {
        "pole_a": [
            "natural environment photo", "nature photograph", "organic setting",
        ],
        "pole_b": [
            "man-made environment photo", "urban photograph", "built environment",
            "artificial setting",
        ],
    },
    "simple_vs_complex": {
        "pole_a": [
            "single subject photograph", "isolated subject", "minimal composition",
            "one main element",
        ],
        "pole_b": [
            "complex scene photograph", "busy composition", "multiple elements",
            "layered image",
        ],
    },
}


def _encode_term_centroid(terms: list[str], model, tokenizer, device) -> np.ndarray:
    """Encode multiple text terms and return their L2-normalized mean embedding."""
    import torch
    with torch.no_grad():
        tokens = tokenizer(terms).to(device)
        features = model.encode_text(tokens)
        features = features / features.norm(dim=-1, keepdim=True)
        centroid = features.mean(dim=0)
        centroid = centroid / centroid.norm()
    return centroid.cpu().float().numpy()


def _compute_semantic_scores(artifact_dir: Path, image_ids: list[str]) -> dict[str, np.ndarray]:
    """Compute CLIP zero-shot scores using multi-term averaged centroids.

    Unipolar categories: score = cosine(image, category_centroid)
    Bipolar contrasts: score = cosine(image, pole_b_centroid) - cosine(image, pole_a_centroid)
    """
    import torch
    import open_clip

    device = torch.device("mps") if torch.backends.mps.is_available() else torch.device("cpu")

    model, _, preprocess = open_clip.create_model_and_transforms(
        "ViT-B-32", pretrained="laion2b_s34b_b79k", device=device
    )
    tokenizer = open_clip.get_tokenizer("ViT-B-32")
    model.eval()

    # Load all image embeddings as a matrix for vectorized scoring
    store = EmbeddingStore(artifact_dir, "clip", FAMILIES["clip"]["dim"])
    image_vecs = store.get_batch(image_ids)  # (N, 512)

    results = {}

    # --- Unipolar categories ---
    for name, terms in SEMANTIC_CATEGORIES.items():
        centroid = _encode_term_centroid(terms, model, tokenizer, device)
        scores = image_vecs @ centroid  # (N,)
        results[f"sem_{name}"] = scores.astype(np.float32)
        log.info("  Semantic category %s: %d terms, score range [%.4f, %.4f]",
                 name, len(terms), scores.min(), scores.max())

    # --- Bipolar contrasts ---
    for name, poles in SEMANTIC_CONTRASTS.items():
        centroid_a = _encode_term_centroid(poles["pole_a"], model, tokenizer, device)
        centroid_b = _encode_term_centroid(poles["pole_b"], model, tokenizer, device)
        scores = (image_vecs @ centroid_b) - (image_vecs @ centroid_a)
        results[f"sem_{name}"] = scores.astype(np.float32)
        log.info("  Semantic contrast %s: score range [%.4f, %.4f]",
                 name, scores.min(), scores.max())

    del model
    if device.type == "mps":
        torch.mps.empty_cache()

    return results


# ---------------------------------------------------------------------------
# Emergent contrasts (PCA directions from embeddings)
# ---------------------------------------------------------------------------

def _compute_emergent_contrasts(artifact_dir: Path, image_ids: list[str],
                                n_components: int = 5) -> dict[str, np.ndarray]:
    """Extract top PCA directions from each embedding family."""
    from sklearn.decomposition import PCA

    results = {}
    for family_name, family_info in FAMILIES.items():
        store = EmbeddingStore(artifact_dir, family_name, family_info["dim"])
        vecs = store.get_batch(image_ids)
        if vecs.shape[0] == 0:
            continue

        # Center and PCA
        pca = PCA(n_components=min(n_components, vecs.shape[1]))
        projections = pca.fit_transform(vecs)

        for i in range(projections.shape[1]):
            var_ratio = pca.explained_variance_ratio_[i]
            if var_ratio < 0.01:
                continue
            results[f"pca_{family_name}_{i}"] = projections[:, i].astype(np.float32)

    return results


# ---------------------------------------------------------------------------
# Mass and stability selection
# ---------------------------------------------------------------------------

def _score_mass(scores: np.ndarray) -> float:
    """Quantify distributional spread (mass). Higher = more informative."""
    q10, q50, q90 = np.percentile(scores, [10, 50, 90])
    iqr = q90 - q10
    std = scores.std()
    return float(iqr * std)


def _check_stability(scores: np.ndarray, n_trials: int = 5, threshold: float = 0.9) -> float:
    """Check stability under subsampling. Returns min correlation across trials."""
    rng = np.random.RandomState(42)
    correlations = []
    n = len(scores)
    for _ in range(n_trials):
        mask = rng.random(n) < 0.5
        if mask.sum() < 10 or (~mask).sum() < 10:
            continue
        # Correlation between full scores and subsample-reranked scores
        # We check if the ordering is stable
        sub_scores = scores.copy()
        # Compute correlation between full and subsample
        corr = np.corrcoef(scores[mask], scores[mask])[0, 1]
        # More meaningful: correlation between indices in full vs subsample ranking
        full_rank = np.argsort(np.argsort(scores))
        sub_rank = np.argsort(np.argsort(scores[mask]))
        # Use rank correlation on the shared subset
        correlations.append(float(np.corrcoef(full_rank[mask], sub_rank)[0, 1]))

    return min(correlations) if correlations else 0.0


def _check_stability_subsample(all_scores: np.ndarray, n_trials: int = 5) -> float:
    """Stability: correlation of per-image scores between full corpus and 50% subsample-derived contrast.

    For perceptual/semantic contrasts (not data-derived directions), this is trivially 1.0
    since the measure doesn't depend on other images. For PCA-derived contrasts, we
    re-derive the direction on a subsample and check correlation.
    """
    # For non-PCA contrasts, scores are deterministic per-image, so stability is inherent.
    # We approximate by checking rank correlation between random halves.
    rng = np.random.RandomState(42)
    correlations = []
    n = len(all_scores)
    for _ in range(n_trials):
        idx = rng.permutation(n)
        half1 = idx[:n // 2]
        half2 = idx[n // 2:]
        if len(half1) < 10 or len(half2) < 10:
            continue
        # Pearson correlation of scores between the two halves when evaluated on overlapping images
        # Since perceptual scores are per-image, just check that a random 50% of images
        # has high correlation with the full set
        corr = np.corrcoef(all_scores[half1], all_scores[half1])[0, 1]
        # Actually: what matters is that if we recompute on 50% of corpus, the per-image
        # scores for images in both sets agree.
        # For perceptual: trivially 1.0 (scores don't depend on corpus composition)
        # For semantic: trivially 1.0 (CLIP scores don't depend on corpus)
        # For PCA: need to re-derive. We'll handle this below.
        correlations.append(1.0)
    return min(correlations) if correlations else 1.0


def _stability_pca(artifact_dir: Path, family_name: str, component_idx: int,
                   image_ids: list[str], full_scores: np.ndarray,
                   n_trials: int = 5) -> float:
    """Re-derive PCA direction on 50% subsample, project all images, check correlation."""
    from sklearn.decomposition import PCA

    store = EmbeddingStore(artifact_dir, family_name, FAMILIES[family_name]["dim"])
    vecs = store.get_batch(image_ids)
    if vecs.shape[0] == 0:
        return 0.0

    rng = np.random.RandomState(42)
    correlations = []
    n = len(image_ids)

    for _ in range(n_trials):
        mask = rng.random(n) > 0.5
        if mask.sum() < 20:
            continue
        sub_vecs = vecs[mask]
        pca_sub = PCA(n_components=component_idx + 1)
        pca_sub.fit(sub_vecs)

        # Project ALL images onto subsample-derived direction
        sub_scores = vecs @ pca_sub.components_[component_idx]

        # Check correlation (sign may flip, so use abs)
        corr = abs(float(np.corrcoef(full_scores, sub_scores)[0, 1]))
        correlations.append(corr)

    return min(correlations) if correlations else 0.0


# ---------------------------------------------------------------------------
# Exemplar sets
# ---------------------------------------------------------------------------

def _compute_exemplars(scores: np.ndarray, image_ids: list[str],
                       n_exemplars: int = 12) -> dict:
    """Compute exemplar sets for low/median/high bands.

    Uses the most extreme images (closest to actual min/max) rather than
    random samples from a broad percentile band. This ensures exemplars
    are visually representative even for low-mass contrasts.
    """
    sorted_idx = np.argsort(scores)
    n = len(sorted_idx)

    # Take the most extreme images directly
    low_idx = sorted_idx[:n_exemplars]
    high_idx = sorted_idx[-n_exemplars:]

    # Median band: centered around the median
    mid_start = max(0, n // 2 - n_exemplars // 2)
    mid_end = min(n, mid_start + n_exemplars)
    mid_idx = sorted_idx[mid_start:mid_end]

    return {
        "low": [image_ids[i] for i in low_idx],
        "median": [image_ids[i] for i in mid_idx],
        "high": [image_ids[i] for i in high_idx],
    }


# ---------------------------------------------------------------------------
# Main contrast build pipeline
# ---------------------------------------------------------------------------

@dataclass
class ContrastEntry:
    contrast_id: str
    name: str
    source: str  # "perceptual", "semantic", "emergent"
    description: str
    mass: float
    stability: float
    quantiles: dict  # {"p10": float, "p25": float, "p50": float, "p75": float, "p90": float}
    exemplars: dict  # {"low": [...], "median": [...], "high": [...]}


def build_contrasts(artifact_dir: Path) -> dict:
    """Discover, evaluate, and select contrasts. Returns stats."""
    conn = db.open_db(artifact_dir)
    all_images = db.get_all_images(conn)
    conn.close()

    if not all_images:
        log.warning("No images in catalog")
        return {}

    image_ids = [img["image_id"] for img in all_images]
    image_paths = {img["image_id"]: img["path"] for img in all_images}
    n = len(image_ids)

    all_scores: dict[str, np.ndarray] = {}
    all_meta: dict[str, dict] = {}

    # --- 1. Perceptual contrasts ---
    log.info("Computing perceptual contrasts for %d images...", n)
    t0 = time.monotonic()
    perceptual_data = {name: [] for name in PERCEPTUAL_NAMES}

    for i, iid in enumerate(image_ids):
        scores = _compute_perceptual_scores(image_paths[iid])
        for name in PERCEPTUAL_NAMES:
            perceptual_data[name].append(scores.get(name, 0.0))
        if (i + 1) % 200 == 0:
            log.info("  Perceptual: %d/%d", i + 1, n)

    for name in PERCEPTUAL_NAMES:
        arr = np.array(perceptual_data[name], dtype=np.float32)
        all_scores[name] = arr
        all_meta[name] = {"source": "perceptual", "description": f"Perceptual: {name}"}

    log.info("  Perceptual done in %.1fs", time.monotonic() - t0)

    # --- 2. Semantic contrasts (CLIP zero-shot) ---
    log.info("Computing semantic contrasts...")
    t0 = time.monotonic()
    semantic_scores = _compute_semantic_scores(artifact_dir, image_ids)
    for name, arr in semantic_scores.items():
        all_scores[name] = arr
        short_name = name.replace("sem_", "")
        all_meta[name] = {
            "source": "semantic",
            "description": f"Semantic: {short_name}",
        }
    log.info("  Semantic done in %.1fs", time.monotonic() - t0)

    # --- 3. Emergent contrasts (PCA) ---
    log.info("Computing emergent contrasts (PCA)...")
    t0 = time.monotonic()
    emergent_scores = _compute_emergent_contrasts(artifact_dir, image_ids, n_components=5)
    for name, arr in emergent_scores.items():
        all_scores[name] = arr
        all_meta[name] = {"source": "emergent", "description": f"Emergent: {name}"}
    log.info("  Emergent done in %.1fs (%d candidates)", time.monotonic() - t0, len(emergent_scores))

    # --- 4. Evaluate mass and stability, select ---
    log.info("Evaluating %d candidate contrasts...", len(all_scores))
    candidates = []

    for name, scores in all_scores.items():
        mass = _score_mass(scores)
        meta = all_meta[name]

        # Stability
        if name.startswith("pca_"):
            parts = name.split("_")
            family = parts[1]
            comp_idx = int(parts[2])
            stability = _stability_pca(artifact_dir, family, comp_idx, image_ids, scores)
        else:
            # Perceptual and semantic contrasts are deterministic per-image
            stability = 1.0

        q = np.percentile(scores, [10, 25, 50, 75, 90])
        quantiles = {"p10": float(q[0]), "p25": float(q[1]), "p50": float(q[2]),
                     "p75": float(q[3]), "p90": float(q[4])}

        exemplars = _compute_exemplars(scores, image_ids)

        contrast_id = hashlib.md5(name.encode()).hexdigest()[:12]

        candidates.append(ContrastEntry(
            contrast_id=contrast_id,
            name=name,
            source=meta["source"],
            description=meta["description"],
            mass=mass,
            stability=stability,
            quantiles=quantiles,
            exemplars=exemplars,
        ))

    # Filter: stability > 0.9 for PCA, keep all perceptual/semantic
    # Then sort by mass and take top 60
    kept = []
    dropped_stability = 0
    for c in candidates:
        if c.source == "emergent" and c.stability < 0.9:
            dropped_stability += 1
            log.info("  Dropped %s: stability=%.3f < 0.9", c.name, c.stability)
            continue
        kept.append(c)

    # Sort by mass descending, cap at 60
    kept.sort(key=lambda c: c.mass, reverse=True)
    if len(kept) > 60:
        kept = kept[:60]

    log.info("Selected %d contrasts (%d dropped for stability)", len(kept), dropped_stability)

    # --- 5. Save artifacts ---
    contrast_dir = artifact_dir / "contrasts"
    contrast_dir.mkdir(exist_ok=True)

    # Version based on content hash
    content_hash = hashlib.md5(
        json.dumps([c.name for c in kept], sort_keys=True).encode()
    ).hexdigest()[:8]
    version = f"v1_{content_hash}"

    library = {
        "version": version,
        "count": len(kept),
        "contrasts": [asdict(c) for c in kept],
    }

    lib_path = contrast_dir / "contrast_library.json"
    lib_path.write_text(json.dumps(library, indent=2))
    log.info("Saved contrast library: %s (%d contrasts)", lib_path, len(kept))

    # Save per-image coordinates
    coords = {}
    for c in kept:
        scores = all_scores[c.name]
        coords[c.name] = {iid: float(scores[i]) for i, iid in enumerate(image_ids)}

    coords_path = contrast_dir / "coordinates.json"
    coords_path.write_text(json.dumps(coords))
    log.info("Saved per-image coordinates: %s", coords_path)

    return {
        "version": version,
        "total_candidates": len(all_scores),
        "selected": len(kept),
        "dropped_stability": dropped_stability,
        "sources": {
            "perceptual": sum(1 for c in kept if c.source == "perceptual"),
            "semantic": sum(1 for c in kept if c.source == "semantic"),
            "emergent": sum(1 for c in kept if c.source == "emergent"),
        },
    }
