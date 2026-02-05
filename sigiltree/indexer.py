"""Corpus indexer: scans images, computes checksums, generates thumbnails."""

import hashlib
import logging
import time
import uuid
from pathlib import Path

from PIL import Image, ExifTags

# Allow large panoramas (up to ~500 megapixels)
Image.MAX_IMAGE_PIXELS = 500_000_000

from sigiltree import db

log = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif",
    ".bmp", ".gif", ".heic",
}

THUMBNAIL_SIZES = [64, 128, 256, 512]


def file_checksum(path: Path, chunk_size: int = 65536) -> str:
    h = hashlib.blake2b(digest_size=16)
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def extract_exif_time(img: Image.Image) -> str | None:
    try:
        exif = img.getexif()
        if exif:
            for tag_id, value in exif.items():
                tag = ExifTags.TAGS.get(tag_id, "")
                if tag == "DateTimeOriginal":
                    return str(value)
    except Exception:
        pass
    return None


def scan_corpus(corpus_path: Path) -> list[Path]:
    paths = []
    for p in sorted(corpus_path.rglob("*")):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS and not p.name.endswith("~"):
            paths.append(p)
    return paths


def generate_thumbnail(img: Image.Image, size: int, dest: Path) -> None:
    thumb = img.copy()
    thumb.thumbnail((size, size), Image.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    thumb.save(str(dest), "JPEG", quality=85)


def index_corpus(corpus_path: Path, artifact_dir: Path) -> dict:
    """Index a corpus directory. Returns stats dict."""
    artifact_dir.mkdir(parents=True, exist_ok=True)
    thumb_dir = artifact_dir / "thumbnails"
    thumb_dir.mkdir(exist_ok=True)

    conn = db.open_db(artifact_dir)
    existing_paths = db.get_all_paths(conn)

    image_files = scan_corpus(corpus_path)
    current_paths = {str(p) for p in image_files}

    stats = {
        "scanned": len(image_files),
        "added": 0,
        "unchanged": 0,
        "updated": 0,
        "removed": 0,
        "errors": 0,
    }

    # Remove images no longer in corpus
    removed_paths = existing_paths - current_paths
    for rp in removed_paths:
        image_id = db.delete_image(conn, rp)
        if image_id:
            # Clean up thumbnail files
            for size in THUMBNAIL_SIZES:
                tp = thumb_dir / str(size) / f"{image_id}.jpg"
                if tp.exists():
                    tp.unlink()
            stats["removed"] += 1
            log.info("Removed: %s", rp)

    # Index current images
    t0 = time.monotonic()
    for i, img_path in enumerate(image_files):
        path_str = str(img_path)
        try:
            checksum = file_checksum(img_path)
            exists, old_checksum = db.image_exists_by_path(conn, path_str)

            if exists and old_checksum == checksum:
                stats["unchanged"] += 1
                continue

            # New or changed file - process it
            with Image.open(img_path) as img:
                img.load()
                width, height = img.size
                exif_time = extract_exif_time(img)

                if exists:
                    # Reuse existing image_id for updated files
                    cur = conn.execute(
                        "SELECT image_id FROM images WHERE path = ?", (path_str,)
                    )
                    image_id = cur.fetchone()[0]
                    action = "updated"
                    stats["updated"] += 1
                else:
                    image_id = uuid.uuid4().hex[:16]
                    action = "added"
                    stats["added"] += 1

                db.upsert_image(
                    conn, image_id, path_str, img_path.name,
                    width, height, checksum, img_path.stat().st_size, exif_time
                )

                # Generate thumbnails
                # Convert to RGB for JPEG output
                if img.mode in ("RGBA", "P", "LA"):
                    rgb = img.convert("RGB")
                elif img.mode != "RGB":
                    rgb = img.convert("RGB")
                else:
                    rgb = img

                for size in THUMBNAIL_SIZES:
                    rel = f"{size}/{image_id}.jpg"
                    dest = thumb_dir / rel
                    generate_thumbnail(rgb, size, dest)
                    db.upsert_thumbnail(conn, image_id, size, rel)

                log.info("%s [%d/%d]: %s", action.capitalize(), i + 1, len(image_files), img_path.name)

        except Exception as e:
            stats["errors"] += 1
            log.error("Error processing %s: %s", img_path.name, e)

        if (i + 1) % 100 == 0:
            conn.commit()
            elapsed = time.monotonic() - t0
            rate = (i + 1) / elapsed
            log.info("Progress: %d/%d (%.1f img/s)", i + 1, len(image_files), rate)

    conn.commit()
    elapsed = time.monotonic() - t0

    total = db.count_images(conn)
    conn.close()

    log.info(
        "Index complete in %.1fs: %d scanned, %d added, %d unchanged, "
        "%d updated, %d removed, %d errors. Total in catalog: %d",
        elapsed, stats["scanned"], stats["added"], stats["unchanged"],
        stats["updated"], stats["removed"], stats["errors"], total,
    )
    stats["total"] = total
    stats["elapsed"] = elapsed
    return stats
