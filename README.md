# SigilAtlas

A local-first tool for exploring image corpora through personal aesthetic preference.

SigilAtlas ingests a folder of images, computes multiple embedding families (semantic, structural, texture), discovers contrasts that actually exist in the corpus, and builds a multiscale zoomable atlas — a rectangular mosaic of neighborhoods you can drive through continuously.

A calibration system (the "arcade" and "contrast rides") lets you express which visual contrasts you care about. Your collapsed preferences form a **sigil** — a sparse vector of aesthetic biases that overlays onto the atlas as a gravity field, brightening aligned regions and dimming the rest. The atlas topology never changes; the sigil only affects what glows.

## Principles

- **No passive profiling.** Preference is recorded only from explicit actions. Dwell time, hovering, and viewport exposure are never used.
- **Superposition is default.** Choosing "center" or "skip" records nothing. Uncollapsed contrasts remain in superposition — they are not zero, they are unmeasured.
- **Honest axes.** When contrasts are correlated, the system either restricts the ride to a clean subregion, promotes to a two-axis ride with consent, or honestly rejects the axis. It never silently presents a multi-axis ride as single-axis.
- **No event horizons.** From any depth, one action returns to a wider view. The system never creates stickiness.

## What it does

1. **Index** — catalogs images, generates multi-resolution thumbnails
2. **Embed** — computes CLIP (semantic), DINOv2 (structural), and multiscale texture embeddings
3. **Discover contrasts** — finds perceptual, semantic, and emergent (PCA) axes with mass and stability in the corpus; selects a compact library
4. **Build atlas** — fuses neighbor graphs across embedding families, clusters into neighborhoods, lays out as a squarified treemap, recurses into a 4-level pyramid
5. **Calibrate** — three-door arcade (left/right/center) collapses preferences; contrast rides sweep a single axis low-to-high through sorted neighborhoods
6. **Render sigil** — overlays beauty gravity as dim/brighten/halo on the atlas, driven only by collapsed preferences

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Build artifacts (each step is incremental)
sigiltree index /path/to/images artifacts
sigiltree embed artifacts
sigiltree contrasts artifacts
sigiltree atlas artifacts --levels 4 --seed 42
sigiltree ride-stats artifacts

# Launch viewer
sigiltree serve artifacts --port 8888
```

Then open:
- `http://127.0.0.1:8888/atlas` — multiscale atlas with driving, sigil overlay, and contrast rides
- `http://127.0.0.1:8888/calibrate` — calibration arcade

## Atlas controls

| Key | Action |
|-----|--------|
| W/S/A/D or Arrows | Drive (pan) |
| Q/E | Zoom in/out |
| Enter/Space | Enter hovered neighborhood |
| ESC | Exit to parent level |
| H/Home | Return to root |
| G | Toggle sigil overlay |
| R | Open contrast ride picker |

During a ride: **Right** = more like this, **Left** = less like this, **Space** = skip, **ESC** = abort.

## Tests

```bash
pytest tests/ -v
```

120 tests across indexing, embeddings, contrasts, arcade, atlas, sigil scoring, and rides.

## Architecture

```
sigiltree/
  db.py              SQLite catalog
  indexer.py          Corpus scanner, checksums, thumbnails
  embeddings.py       CLIP, DINOv2, texture embeddings + nearest neighbors
  contrasts.py        Contrast discovery, mass/stability selection, exemplars
  arcade.py           Calibration session, door triplets, sigil construction
  atlas.py            Fused graph, Louvain clustering, squarified treemap, recursive pyramid
  sigil_scoring.py    Per-node sigil compatibility scores
  ride_stats.py       Precomputed z-summaries and inter-contrast correlations
  ride_engine.py      Ride planning with drift policy cascade
  ride_session.py     Ride state, band construction, sigil merging
  viewer_server.py    aiohttp server, all UI (atlas viewer, calibration arcade)
  cli.py              CLI entry point
```

All artifacts are local files. No cloud dependencies. No telemetry.

## Requirements

- Python 3.11+
- PyTorch (for CLIP and DINOv2 inference)
- Dependencies: `pillow`, `aiohttp`, `numpy`, `scipy`, `scikit-learn`, `networkx`, `open_clip_torch`
