"""Tests for Phase 1: corpus indexing, delta behavior, and thumbnail correctness."""

import shutil
import tempfile
from pathlib import Path

import pytest
from PIL import Image

from sigiltree import db
from sigiltree.indexer import (
    file_checksum,
    index_corpus,
    scan_corpus,
    THUMBNAIL_SIZES,
)


@pytest.fixture
def tmp_corpus(tmp_path):
    """Create a small synthetic corpus."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for i in range(50):
        img = Image.new("RGB", (640, 480), color=(i * 5 % 256, i * 3 % 256, i * 7 % 256))
        img.save(corpus / f"img_{i:04d}.jpg", "JPEG")
    return corpus


@pytest.fixture
def artifact_dir(tmp_path):
    return tmp_path / "artifacts"


def test_scan_corpus_finds_images(tmp_corpus):
    paths = scan_corpus(tmp_corpus)
    assert len(paths) == 50
    assert all(p.suffix == ".jpg" for p in paths)


def test_scan_ignores_tilde_files(tmp_corpus):
    (tmp_corpus / "backup.jpg~").write_bytes(b"not an image")
    paths = scan_corpus(tmp_corpus)
    assert len(paths) == 50


def test_file_checksum_deterministic(tmp_corpus):
    first = list(tmp_corpus.iterdir())[0]
    c1 = file_checksum(first)
    c2 = file_checksum(first)
    assert c1 == c2
    assert len(c1) == 32  # blake2b with 16 byte digest = 32 hex chars


def test_index_creates_catalog_and_thumbnails(tmp_corpus, artifact_dir):
    stats = index_corpus(tmp_corpus, artifact_dir)
    assert stats["added"] == 50
    assert stats["unchanged"] == 0
    assert stats["errors"] == 0
    assert (artifact_dir / "catalog.db").exists()

    # Check thumbnails
    for size in THUMBNAIL_SIZES:
        thumbs = list((artifact_dir / "thumbnails" / str(size)).iterdir())
        assert len(thumbs) == 50, f"Expected 50 thumbnails at size {size}, got {len(thumbs)}"


def test_index_idempotent_second_run(tmp_corpus, artifact_dir):
    stats1 = index_corpus(tmp_corpus, artifact_dir)
    assert stats1["added"] == 50

    stats2 = index_corpus(tmp_corpus, artifact_dir)
    assert stats2["added"] == 0
    assert stats2["unchanged"] == 50
    assert stats2["updated"] == 0


def test_index_delta_add_images(tmp_corpus, artifact_dir):
    index_corpus(tmp_corpus, artifact_dir)

    # Add 10 new images
    for i in range(50, 60):
        img = Image.new("RGB", (320, 240), color=(100, 100, 100))
        img.save(tmp_corpus / f"img_{i:04d}.jpg", "JPEG")

    stats = index_corpus(tmp_corpus, artifact_dir)
    assert stats["added"] == 10
    assert stats["unchanged"] == 50
    assert stats["total"] == 60


def test_index_delta_remove_images(tmp_corpus, artifact_dir):
    index_corpus(tmp_corpus, artifact_dir)

    # Remove 5 images
    removed = sorted(tmp_corpus.iterdir())[:5]
    for p in removed:
        p.unlink()

    stats = index_corpus(tmp_corpus, artifact_dir)
    assert stats["removed"] == 5
    assert stats["total"] == 45


def test_index_delta_modify_image(tmp_corpus, artifact_dir):
    index_corpus(tmp_corpus, artifact_dir)

    # Modify an image (change content, so checksum changes)
    target = sorted(tmp_corpus.iterdir())[0]
    img = Image.new("RGB", (800, 600), color=(255, 0, 0))
    img.save(target, "JPEG")

    stats = index_corpus(tmp_corpus, artifact_dir)
    assert stats["updated"] == 1
    assert stats["unchanged"] == 49


def test_thumbnails_are_valid_images(tmp_corpus, artifact_dir):
    index_corpus(tmp_corpus, artifact_dir)
    conn = db.open_db(artifact_dir)
    images = db.get_all_images(conn, limit=5)
    conn.close()

    for img_row in images:
        for size in THUMBNAIL_SIZES:
            thumb_path = artifact_dir / "thumbnails" / str(size) / f"{img_row['image_id']}.jpg"
            assert thumb_path.exists()
            with Image.open(thumb_path) as t:
                assert max(t.size) <= size


def test_db_count_matches(tmp_corpus, artifact_dir):
    index_corpus(tmp_corpus, artifact_dir)
    conn = db.open_db(artifact_dir)
    assert db.count_images(conn) == 50
    conn.close()


def test_handles_rgba_png(tmp_corpus, artifact_dir):
    """Test that RGBA PNGs index correctly."""
    img = Image.new("RGBA", (200, 200), color=(255, 0, 0, 128))
    img.save(tmp_corpus / "alpha_test.png", "PNG")
    stats = index_corpus(tmp_corpus, artifact_dir)
    assert stats["errors"] == 0
    assert stats["total"] == 51  # 50 jpg + 1 png
