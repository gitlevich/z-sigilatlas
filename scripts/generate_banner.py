"""Generate a random 3x3 grid banner from docs/tiles/."""

import os
import random
import sys
from PIL import Image

def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else random.randint(0, 2**32)
    rng = random.Random(seed)

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tiles_dir = os.path.join(repo_root, "docs", "tiles")
    out_path = os.path.join(repo_root, "docs", "banner.jpg")

    files = sorted(f for f in os.listdir(tiles_dir) if f.lower().endswith((".jpg", ".jpeg", ".png")))
    if len(files) < 9:
        print(f"Need at least 9 tiles, found {len(files)}")
        sys.exit(1)

    picked = rng.sample(files, 9)
    cell = 400
    gap = 4
    grid_size = cell * 3 + gap * 2

    grid = Image.new("RGB", (grid_size, grid_size), (20, 20, 20))
    for i, f in enumerate(picked):
        tile = Image.open(os.path.join(tiles_dir, f)).convert("RGB")
        tile = tile.resize((cell, cell), Image.LANCZOS)
        row, col = i // 3, i % 3
        x = col * (cell + gap)
        y = row * (cell + gap)
        grid.paste(tile, (x, y))

    grid.save(out_path, quality=92)
    print(f"Banner saved: seed={seed}, tiles={[os.path.splitext(f)[0] for f in picked]}")

if __name__ == "__main__":
    main()
