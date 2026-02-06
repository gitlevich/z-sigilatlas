# Sigil Atlas

<p align="center">
  <img src="docs/banner.jpg" alt="SigilAtlas — a neighborhood from the atlas, showing images organized by visual temperature" width="600">
</p>

<p align="center">
  <strong><a href="https://sigilatlas.fly.dev">Explore the live atlas</a></strong>
  &nbsp;&middot;&nbsp;
  <a href="docs/attention-language.md">Attention language reference</a>
</p>

---

## What is this

Sigil Atlas organizes a collection of photographs into a zoomable map based on visual similarity. Images are placed near the ones they most resemble — not by subject or category, but by what they look and feel like.

The tool also lets you measure and record your own visual preferences along specific axes (warm–cool, sharp–soft, simple–complex, and others). The recorded preferences form a **sigil** — a sparse vector that can be projected onto the map as a brightness overlay.

The vocabulary for this comes from **[attention language](https://sigilsnotspells.com)**, a way of describing visual preference precisely enough to compute with.

## How it works

Three kinds of visual similarity are fused together:

- **Semantic** — what things mean (a bridge, a face, a forest)
- **Structural** — how things are composed (symmetry, depth, negative space)
- **Textural** — what surfaces feel like (grain, sharpness, color temperature)

Where all three agree, the groupings are strong. Similar images cluster into neighborhoods; neighborhoods nest into larger regions. The result is a four-level hierarchy you can zoom through.

## What you can do with it

### Navigate

Click any neighborhood to zoom in. Press Escape to zoom back out. Pan with WASD or drag. Scroll to zoom. Press H to return to the top. The map layout is fixed — it does not rearrange.

### Calibrate

Press R to start a **contrast ride**. The system walks you through the atlas along one visual axis and asks which direction you prefer. You choose "more like this," "less like this," or skip. Skipping records nothing.

### Build a sigil

Your choices accumulate into a **sigil**. Press G to project it onto the atlas: neighborhoods aligned with your preferences brighten; others dim. The map stays the same; the brightness changes.

Axes you haven't ridden remain in **superposition** — they are not zero, they are unmeasured. The [attention language reference](docs/attention-language.md) explains this distinction and the rest of the vocabulary.

## Why

Photographs have properties that are easy to respond to but hard to talk about. Warm or cool. Dense or sparse. Still or restless. There is no standard vocabulary for these properties and no standard way to measure preference along them.

Sigil Atlas is an attempt to build both. Preference is recorded only from explicit choices — never inferred from viewing behavior. Unmeasured axes stay unmeasured. Correlated axes are disclosed, not hidden.

**[Read the full attention language reference](docs/attention-language.md)** for the vocabulary, principles, and mechanics.

## Try it

**[Open the live atlas](https://sigilatlas.fly.dev)** — 250 photographs from San Francisco, organized into 35 neighborhoods across 4 levels.

## Run your own

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

sigiltree index /path/to/images artifacts
sigiltree embed artifacts
sigiltree contrasts artifacts
sigiltree atlas artifacts --levels 4 --seed 42
sigiltree ride-stats artifacts
sigiltree serve artifacts --port 8888
```

Requires Python 3.11+ and PyTorch for the embedding step. Serving requires only `pillow`, `aiohttp`, `numpy`.

## Tests

```bash
pytest tests/ -v    # 120 tests
```

## Architecture

```
sigiltree/
  indexer.py          Corpus scanner, thumbnails
  embeddings.py       CLIP, DINOv2, texture embeddings
  contrasts.py        Contrast discovery and selection
  atlas.py            Fused graph, clustering, treemap pyramid
  arcade.py           Calibration arcade
  ride_stats.py       Precomputed z-summaries and correlations
  ride_engine.py      Ride planning with drift policy
  ride_session.py     Ride state and sigil merging
  sigil_scoring.py    Per-node sigil compatibility
  viewer_server.py    Server and all UI
  cli.py              CLI entry point
```

All artifacts are local files. No cloud dependencies. No telemetry.
