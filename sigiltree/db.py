"""SQLite catalog for the sigil tree corpus."""

import sqlite3
import logging
from pathlib import Path

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS images (
    image_id    TEXT PRIMARY KEY,
    path        TEXT NOT NULL UNIQUE,
    filename    TEXT NOT NULL,
    width       INTEGER,
    height      INTEGER,
    checksum    TEXT NOT NULL,
    file_size   INTEGER NOT NULL,
    exif_time   TEXT,
    indexed_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS thumbnails (
    image_id    TEXT NOT NULL,
    size        INTEGER NOT NULL,
    rel_path    TEXT NOT NULL,
    PRIMARY KEY (image_id, size),
    FOREIGN KEY (image_id) REFERENCES images(image_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_images_checksum ON images(checksum);
"""


def open_db(artifact_dir: Path) -> sqlite3.Connection:
    db_path = artifact_dir / "catalog.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)

    cur = conn.execute("SELECT value FROM meta WHERE key='schema_version'")
    row = cur.fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()
    return conn


def image_exists(conn: sqlite3.Connection, checksum: str) -> bool:
    cur = conn.execute("SELECT 1 FROM images WHERE checksum = ?", (checksum,))
    return cur.fetchone() is not None


def image_exists_by_path(conn: sqlite3.Connection, path: str) -> tuple[bool, str | None]:
    """Check if an image exists by path. Returns (exists, checksum)."""
    cur = conn.execute("SELECT checksum FROM images WHERE path = ?", (path,))
    row = cur.fetchone()
    if row is None:
        return False, None
    return True, row[0]


def upsert_image(conn: sqlite3.Connection, image_id: str, path: str,
                 filename: str, width: int, height: int, checksum: str,
                 file_size: int, exif_time: str | None) -> None:
    conn.execute("""
        INSERT INTO images (image_id, path, filename, width, height, checksum, file_size, exif_time)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(image_id) DO UPDATE SET
            path=excluded.path, filename=excluded.filename,
            width=excluded.width, height=excluded.height,
            checksum=excluded.checksum, file_size=excluded.file_size,
            exif_time=excluded.exif_time, indexed_at=datetime('now')
    """, (image_id, path, filename, width, height, checksum, file_size, exif_time))


def upsert_thumbnail(conn: sqlite3.Connection, image_id: str, size: int,
                     rel_path: str) -> None:
    conn.execute("""
        INSERT INTO thumbnails (image_id, size, rel_path)
        VALUES (?, ?, ?)
        ON CONFLICT(image_id, size) DO UPDATE SET rel_path=excluded.rel_path
    """, (image_id, size, rel_path))


def get_all_paths(conn: sqlite3.Connection) -> set[str]:
    cur = conn.execute("SELECT path FROM images")
    return {row[0] for row in cur.fetchall()}


def delete_image(conn: sqlite3.Connection, path: str) -> str | None:
    """Delete image by path. Returns the image_id if deleted."""
    cur = conn.execute("SELECT image_id FROM images WHERE path = ?", (path,))
    row = cur.fetchone()
    if row is None:
        return None
    image_id = row[0]
    conn.execute("DELETE FROM thumbnails WHERE image_id = ?", (image_id,))
    conn.execute("DELETE FROM images WHERE image_id = ?", (image_id,))
    return image_id


def count_images(conn: sqlite3.Connection) -> int:
    cur = conn.execute("SELECT COUNT(*) FROM images")
    return cur.fetchone()[0]


def get_all_images(conn: sqlite3.Connection, limit: int | None = None,
                   offset: int = 0) -> list[dict]:
    query = "SELECT image_id, path, filename, width, height FROM images ORDER BY filename"
    if limit is not None:
        query += f" LIMIT {limit} OFFSET {offset}"
    cur = conn.execute(query)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_thumbnail_path(conn: sqlite3.Connection, image_id: str,
                       size: int) -> str | None:
    cur = conn.execute(
        "SELECT rel_path FROM thumbnails WHERE image_id = ? AND size = ?",
        (image_id, size),
    )
    row = cur.fetchone()
    return row[0] if row else None
