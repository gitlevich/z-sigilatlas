"""Embedding families: CLIP (semantic), DINOv2 (structural), texture (multiscale)."""

import json
import logging
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image

# Allow large panoramas
Image.MAX_IMAGE_PIXELS = 500_000_000

from sigiltree import db

log = logging.getLogger(__name__)

FAMILIES = {
    "clip": {"dim": 512, "description": "Semantic (CLIP ViT-B-32)"},
    "dino": {"dim": 384, "description": "Structural (DINOv2 ViT-S/14)"},
    "texture": {"dim": 97, "description": "Multiscale texture descriptor"},
}


def _get_device() -> torch.device:
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


# ---------------------------------------------------------------------------
# Embedding store: numpy mmap files per family
# ---------------------------------------------------------------------------

class EmbeddingStore:
    """Memory-mappable embedding store. One .npy + one index.json per family."""

    def __init__(self, artifact_dir: Path, family: str, dim: int):
        self.dir = artifact_dir / "embeddings" / family
        self.dir.mkdir(parents=True, exist_ok=True)
        self.family = family
        self.dim = dim
        self.data_path = self.dir / "vectors.npy"
        self.index_path = self.dir / "index.json"
        self._index: dict[str, int] | None = None
        self._data: np.ndarray | None = None

    def _load_index(self) -> dict[str, int]:
        if self._index is None:
            if self.index_path.exists():
                self._index = json.loads(self.index_path.read_text())
            else:
                self._index = {}
        return self._index

    def _load_data(self) -> np.ndarray | None:
        if self._data is None and self.data_path.exists():
            self._data = np.load(str(self.data_path), mmap_mode="r")
        return self._data

    def has(self, image_id: str) -> bool:
        return image_id in self._load_index()

    def get(self, image_id: str) -> np.ndarray | None:
        idx = self._load_index()
        if image_id not in idx:
            return None
        data = self._load_data()
        if data is None:
            return None
        return np.array(data[idx[image_id]])

    def get_batch(self, image_ids: list[str]) -> np.ndarray:
        idx = self._load_index()
        data = self._load_data()
        rows = [idx[iid] for iid in image_ids if iid in idx]
        return np.array(data[rows]) if data is not None and rows else np.zeros((0, self.dim))

    def existing_ids(self) -> set[str]:
        return set(self._load_index().keys())

    def save(self, image_ids: list[str], vectors: np.ndarray) -> None:
        """Append or rebuild store with new vectors merged with existing."""
        idx = self._load_index()
        old_data = self._load_data()

        # Merge: keep old, overwrite/add new
        all_ids = list(idx.keys())
        all_vecs = []
        if old_data is not None:
            all_vecs = [np.array(old_data)]

        # Find truly new ids
        new_mask = []
        update_map = {}
        for i, iid in enumerate(image_ids):
            if iid in idx:
                update_map[idx[iid]] = i
            else:
                new_mask.append(i)
                all_ids.append(iid)

        # Build merged array
        if old_data is not None:
            base = np.array(old_data)  # copy from mmap
            for old_row, new_i in update_map.items():
                base[old_row] = vectors[new_i]
            if new_mask:
                base = np.vstack([base, vectors[new_mask]])
        else:
            base = vectors

        # Rebuild index
        new_idx = {iid: i for i, iid in enumerate(all_ids)}

        # Close mmap before writing
        self._data = None

        np.save(str(self.data_path), base)
        self.index_path.write_text(json.dumps(new_idx))
        self._index = new_idx

    @property
    def count(self) -> int:
        return len(self._load_index())


# ---------------------------------------------------------------------------
# CLIP embedder
# ---------------------------------------------------------------------------

class ClipEmbedder:
    def __init__(self, device: torch.device):
        import open_clip
        self.device = device
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(
            "ViT-B-32", pretrained="laion2b_s34b_b79k", device=device
        )
        self.model.eval()

    @torch.no_grad()
    def embed_batch(self, images: list[Image.Image]) -> np.ndarray:
        tensors = torch.stack([self.preprocess(img) for img in images]).to(self.device)
        features = self.model.encode_image(tensors)
        features = features / features.norm(dim=-1, keepdim=True)
        return features.cpu().float().numpy()


# ---------------------------------------------------------------------------
# DINOv2 embedder
# ---------------------------------------------------------------------------

class DinoEmbedder:
    def __init__(self, device: torch.device):
        self.device = device
        self.model = torch.hub.load("facebookresearch/dinov2", "dinov2_vits14", verbose=False)
        self.model = self.model.to(device)
        self.model.eval()

        from torchvision import transforms
        self.preprocess = transforms.Compose([
            transforms.Resize(256, interpolation=transforms.InterpolationMode.BICUBIC),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])

    @torch.no_grad()
    def embed_batch(self, images: list[Image.Image]) -> np.ndarray:
        tensors = torch.stack([self.preprocess(img) for img in images]).to(self.device)
        features = self.model(tensors)
        features = features / features.norm(dim=-1, keepdim=True)
        return features.cpu().float().numpy()


# ---------------------------------------------------------------------------
# Texture descriptor (multiscale, hand-engineered)
# ---------------------------------------------------------------------------

class TextureEmbedder:
    """Multiscale texture descriptor using Laplacian pyramid statistics.

    For each of several scales, compute per-channel statistics (mean, std,
    energy, directional gradients) to capture texture grain and scale.
    No model needed — pure image processing.
    """

    SCALES = [1, 2, 4, 8, 16]  # downscale factors
    TARGET_SIZE = 256

    def embed_batch(self, images: list[Image.Image]) -> np.ndarray:
        return np.stack([self._embed_one(img) for img in images])

    def _embed_one(self, img: Image.Image) -> np.ndarray:
        img_rgb = img.convert("RGB").resize(
            (self.TARGET_SIZE, self.TARGET_SIZE), Image.LANCZOS
        )
        arr = np.array(img_rgb, dtype=np.float32) / 255.0

        features = []
        for scale in self.SCALES:
            if scale > 1:
                from PIL import ImageFilter
                scaled = img_rgb.resize(
                    (self.TARGET_SIZE // scale, self.TARGET_SIZE // scale), Image.LANCZOS
                )
                scaled = scaled.resize((self.TARGET_SIZE, self.TARGET_SIZE), Image.LANCZOS)
                s_arr = np.array(scaled, dtype=np.float32) / 255.0
                # Laplacian band: detail at this scale
                band = arr - s_arr
            else:
                band = arr

            for c in range(3):
                ch = band[:, :, c]
                features.extend([
                    ch.mean(),
                    ch.std(),
                    np.sqrt((ch ** 2).mean()),  # RMS energy
                    np.abs(np.diff(ch, axis=1)).mean(),  # horizontal gradient
                    np.abs(np.diff(ch, axis=0)).mean(),  # vertical gradient
                ])

            # Grayscale stats for this band
            gray = band.mean(axis=2)
            features.extend([
                np.percentile(gray, 10),
                np.percentile(gray, 90),
                (gray > gray.mean() + gray.std()).mean(),  # high-energy fraction
            ])

        # Global color features
        hsv_proxy = arr.mean(axis=(0, 1))
        features.extend(hsv_proxy.tolist())

        # Spatial frequency via FFT magnitude spectrum
        gray_full = np.array(img_rgb.convert("L"), dtype=np.float32) / 255.0
        fft_mag = np.abs(np.fft.fftshift(np.fft.fft2(gray_full)))
        h, w = fft_mag.shape
        cy, cx = h // 2, w // 2
        # Radial energy in frequency bands
        for r_lo, r_hi in [(0, 16), (16, 48), (48, 96), (96, 128)]:
            y, x = np.ogrid[:h, :w]
            r = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
            mask = (r >= r_lo) & (r < r_hi)
            features.append(np.log1p(fft_mag[mask].mean()) if mask.any() else 0.0)

        vec = np.array(features, dtype=np.float32)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec


# ---------------------------------------------------------------------------
# Main embed pipeline
# ---------------------------------------------------------------------------

def compute_embeddings(artifact_dir: Path, batch_size: int = 32) -> dict:
    """Compute all embedding families incrementally. Returns stats."""
    conn = db.open_db(artifact_dir)
    all_images = db.get_all_images(conn)
    conn.close()

    if not all_images:
        log.warning("No images in catalog")
        return {"total": 0}

    all_ids = [img["image_id"] for img in all_images]
    all_paths = {img["image_id"]: img["path"] for img in all_images}

    device = _get_device()
    log.info("Using device: %s", device)

    stats = {}

    for family_name, family_info in FAMILIES.items():
        store = EmbeddingStore(artifact_dir, family_name, family_info["dim"])
        existing = store.existing_ids()
        needed_ids = [iid for iid in all_ids if iid not in existing]

        if not needed_ids:
            log.info("[%s] All %d embeddings up to date", family_name, store.count)
            stats[family_name] = {"computed": 0, "total": store.count}
            continue

        log.info("[%s] Computing %d new embeddings (%d existing)",
                 family_name, len(needed_ids), len(existing))

        # Load embedder
        if family_name == "clip":
            embedder = ClipEmbedder(device)
        elif family_name == "dino":
            embedder = DinoEmbedder(device)
        elif family_name == "texture":
            embedder = TextureEmbedder()
        else:
            raise ValueError(f"Unknown family: {family_name}")

        t0 = time.monotonic()
        computed_ids = []
        computed_vecs = []

        for batch_start in range(0, len(needed_ids), batch_size):
            batch_ids = needed_ids[batch_start:batch_start + batch_size]
            images = []
            valid_ids = []

            for iid in batch_ids:
                try:
                    img = Image.open(all_paths[iid]).convert("RGB")
                    images.append(img)
                    valid_ids.append(iid)
                except Exception as e:
                    log.error("[%s] Failed to load %s: %s", family_name, iid, e)

            if not images:
                continue

            try:
                vecs = embedder.embed_batch(images)
                computed_ids.extend(valid_ids)
                computed_vecs.append(vecs)
            except Exception as e:
                log.error("[%s] Batch embedding failed: %s", family_name, e)
                # Fall back to one-by-one
                for img, iid in zip(images, valid_ids):
                    try:
                        vec = embedder.embed_batch([img])
                        computed_ids.append(iid)
                        computed_vecs.append(vec)
                    except Exception as e2:
                        log.error("[%s] Single embed failed %s: %s", family_name, iid, e2)

            done = batch_start + len(batch_ids)
            if done % (batch_size * 4) == 0 or done == len(needed_ids):
                elapsed = time.monotonic() - t0
                rate = done / elapsed if elapsed > 0 else 0
                log.info("[%s] Progress: %d/%d (%.1f img/s)",
                         family_name, done, len(needed_ids), rate)

        if computed_vecs:
            all_vecs = np.vstack(computed_vecs)
            # Verify dimension
            actual_dim = all_vecs.shape[1]
            expected_dim = family_info["dim"]
            if actual_dim != expected_dim:
                log.warning("[%s] Dimension mismatch: got %d, expected %d. Updating.",
                            family_name, actual_dim, expected_dim)
                FAMILIES[family_name]["dim"] = actual_dim

            store.save(computed_ids, all_vecs)

        elapsed = time.monotonic() - t0
        stats[family_name] = {
            "computed": len(computed_ids),
            "total": store.count,
            "elapsed": elapsed,
        }
        log.info("[%s] Done: %d computed in %.1fs. Total: %d",
                 family_name, len(computed_ids), elapsed, store.count)

        # Free model memory
        del embedder
        if device.type in ("mps", "cuda"):
            torch.mps.empty_cache() if device.type == "mps" else torch.cuda.empty_cache()

    return stats


# ---------------------------------------------------------------------------
# Nearest-neighbor query
# ---------------------------------------------------------------------------

def nearest_neighbors(artifact_dir: Path, family: str, image_id: str,
                      k: int = 20) -> list[tuple[str, float]]:
    """Return k nearest neighbors for image_id in the given family.

    Returns list of (image_id, cosine_similarity) sorted by similarity descending.
    """
    info = FAMILIES.get(family)
    if info is None:
        raise ValueError(f"Unknown family: {family}. Known: {list(FAMILIES.keys())}")

    store = EmbeddingStore(artifact_dir, family, info["dim"])
    query_vec = store.get(image_id)
    if query_vec is None:
        raise ValueError(f"No embedding for {image_id} in family {family}")

    idx = store._load_index()
    data = store._load_data()
    if data is None:
        return []

    # Cosine similarity (vectors are already normalized)
    query_vec = query_vec.reshape(1, -1)
    all_data = np.array(data)  # load from mmap
    sims = (all_data @ query_vec.T).squeeze()

    # Get top-k+1 (excluding self)
    top_indices = np.argsort(-sims)[:k + 1]

    id_list = list(idx.keys())
    results = []
    for i in top_indices:
        nid = id_list[i]
        if nid == image_id:
            continue
        results.append((nid, float(sims[i])))
        if len(results) >= k:
            break

    return results
