"""Tests for Phase 2: embedding store, texture embedder, incremental behavior."""

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from sigiltree.embeddings import (
    EmbeddingStore,
    TextureEmbedder,
    FAMILIES,
)


@pytest.fixture
def store_dir(tmp_path):
    return tmp_path / "artifacts"


def test_embedding_store_save_and_load(store_dir):
    store = EmbeddingStore(store_dir, "test", dim=8)
    ids = ["a", "b", "c"]
    vecs = np.random.randn(3, 8).astype(np.float32)
    store.save(ids, vecs)

    assert store.count == 3
    assert store.has("a")
    assert not store.has("z")

    v = store.get("b")
    assert v is not None
    np.testing.assert_allclose(v, vecs[1], atol=1e-6)


def test_embedding_store_incremental(store_dir):
    store = EmbeddingStore(store_dir, "test", dim=4)
    store.save(["a", "b"], np.array([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=np.float32))
    assert store.count == 2

    # Add new, keep old
    store2 = EmbeddingStore(store_dir, "test", dim=4)
    store2.save(["c"], np.array([[0, 0, 1, 0]], dtype=np.float32))
    assert store2.count == 3

    va = store2.get("a")
    np.testing.assert_allclose(va, [1, 0, 0, 0], atol=1e-6)
    vc = store2.get("c")
    np.testing.assert_allclose(vc, [0, 0, 1, 0], atol=1e-6)


def test_embedding_store_update_existing(store_dir):
    store = EmbeddingStore(store_dir, "test", dim=4)
    store.save(["a"], np.array([[1, 0, 0, 0]], dtype=np.float32))

    store2 = EmbeddingStore(store_dir, "test", dim=4)
    store2.save(["a"], np.array([[0, 0, 0, 1]], dtype=np.float32))
    assert store2.count == 1
    va = store2.get("a")
    np.testing.assert_allclose(va, [0, 0, 0, 1], atol=1e-6)


def test_embedding_store_mmap_mode(store_dir):
    store = EmbeddingStore(store_dir, "test", dim=4)
    vecs = np.random.randn(100, 4).astype(np.float32)
    ids = [f"img_{i}" for i in range(100)]
    store.save(ids, vecs)

    # Fresh store reads via mmap
    store2 = EmbeddingStore(store_dir, "test", dim=4)
    data = store2._load_data()
    assert data is not None
    assert data.shape == (100, 4)


def test_texture_embedder_output_shape():
    embedder = TextureEmbedder()
    img = Image.new("RGB", (300, 200), color=(128, 64, 32))
    result = embedder.embed_batch([img])
    assert result.shape[0] == 1
    assert result.shape[1] > 50  # Should be ~120-dimensional
    # Check normalized
    norm = np.linalg.norm(result[0])
    assert abs(norm - 1.0) < 0.01


def test_texture_embedder_distinct_textures():
    """Verify that visually different textures produce different embeddings."""
    embedder = TextureEmbedder()

    # Smooth gradient
    arr1 = np.zeros((256, 256, 3), dtype=np.uint8)
    for i in range(256):
        arr1[i, :] = i
    img1 = Image.fromarray(arr1)

    # High-frequency noise
    arr2 = np.random.randint(0, 256, (256, 256, 3), dtype=np.uint8)
    img2 = Image.fromarray(arr2)

    vecs = embedder.embed_batch([img1, img2])
    similarity = np.dot(vecs[0], vecs[1])
    # Should be quite different
    assert similarity < 0.9, f"Smooth and noisy textures too similar: {similarity}"


def test_embedding_store_get_batch(store_dir):
    store = EmbeddingStore(store_dir, "test", dim=4)
    vecs = np.eye(4, dtype=np.float32)
    store.save(["a", "b", "c", "d"], vecs)

    batch = store.get_batch(["b", "d"])
    assert batch.shape == (2, 4)
    np.testing.assert_allclose(batch[0], [0, 1, 0, 0], atol=1e-6)
    np.testing.assert_allclose(batch[1], [0, 0, 0, 1], atol=1e-6)


def test_existing_ids(store_dir):
    store = EmbeddingStore(store_dir, "test", dim=4)
    store.save(["x", "y"], np.random.randn(2, 4).astype(np.float32))
    assert store.existing_ids() == {"x", "y"}
