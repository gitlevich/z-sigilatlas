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

Sigil Atlas is a tool for learning to see what you're already looking at.

Photographs have properties you respond to before you can name them. Warm or cool. Tight or loose. Dense or sparse. Still or restless. You feel these things instantly, but the vocabulary for talking about them barely exists — and the tools for measuring them don't exist at all.

This project builds that vocabulary and those tools.

We call it **[attention language](https://sigilsnotspells.com)**: a way of describing visual preference that's precise enough to compute with but honest enough to respect what remains unknown.

## How it works

Sigil Atlas takes a collection of photographs and organizes them into a zoomable map. Images are placed near the ones they most resemble — not by subject or category, but by what they *look and feel like*. Three kinds of visual similarity are fused together:

- **Semantic** — what things mean (a bridge, a face, a forest)
- **Structural** — how things are composed (symmetry, depth, negative space)
- **Textural** — what surfaces feel like (grain, sharpness, color temperature)

Where all three agree, the groupings are strong. Similar images cluster into neighborhoods; neighborhoods nest into larger regions. The result is a four-level hierarchy you can zoom through, from a bird's-eye overview down to individual photographs.

## What you can do with it

### Navigate

Click any neighborhood to zoom in. Press Escape to zoom back out. Pan with WASD or drag. Scroll to zoom. Press H to return to the top. The map is always the same shape — it never rearranges itself.

### Calibrate

Press R to start a **contrast ride**. The system walks you through the atlas along one visual axis — warm to cool, sharp to soft, simple to complex — and asks which direction you prefer. Your answers are voluntary and explicit: you choose "more like this," "less like this," or skip. Skipping records nothing. There is no passive tracking.

### Build a sigil

Your calibration choices accumulate into a **sigil** — a personal vector of aesthetic biases. Press G to project it onto the atlas: neighborhoods aligned with your preferences brighten; others dim. The atlas topology stays fixed. Only the lighting changes.

A sigil is not a profile. It records only what you have explicitly chosen to collapse. Axes you haven't ridden remain in **superposition** — they are not zero, they are unmeasured.

## Why

Most recommendation systems watch what you do and infer what you want. They profile passively, optimize for engagement, and flatten taste into a consumption pattern.

Attention language works the other way around. It gives you a vocabulary for your own visual preferences — axes you can name, ride, and collapse on your own terms. Nothing is measured until you choose to measure it. Nothing is inferred. The goal is not to predict what you'll look at next, but to help you understand what you've been looking at all along.

**[Read the full attention language reference](docs/attention-language.md)** for the vocabulary, principles, and mechanics.

## Try it

**[Open the live atlas](https://sigilatlas.fly.dev)** — 250 photographs from San Francisco, organized into 35 neighborhoods across 4 levels. Click to explore, press R to ride a contrast, press G to see your sigil.

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
