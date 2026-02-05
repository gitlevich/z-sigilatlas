"""Lightweight aiohttp server for the thumbnail grid viewer."""

import json
import logging
from pathlib import Path

from aiohttp import web

from sigiltree import db

log = logging.getLogger(__name__)


def create_app(artifact_dir: Path) -> web.Application:
    app = web.Application()
    app["artifact_dir"] = artifact_dir
    app["arcade_sessions"] = {}  # user_id -> ArcadeSession
    app.router.add_get("/", handle_index)
    app.router.add_get("/nn", handle_nn_page)
    app.router.add_get("/contrasts", handle_contrasts_page)
    app.router.add_get("/calibrate", handle_calibrate_page)
    app.router.add_get("/api/images", handle_images)
    app.router.add_get("/api/count", handle_count)
    app.router.add_get("/api/nn", handle_nn_api)
    app.router.add_get("/api/random_id", handle_random_id)
    app.router.add_get("/api/contrasts", handle_contrasts_api)
    app.router.add_post("/api/arcade/start", handle_arcade_start)
    app.router.add_get("/api/arcade/prompt", handle_arcade_prompt)
    app.router.add_post("/api/arcade/choose", handle_arcade_choose)
    app.router.add_get("/api/arcade/summary", handle_arcade_summary)
    app.router.add_get("/api/sigil", handle_sigil_api)
    app.router.add_get("/atlas", handle_atlas_page)
    app.router.add_get("/api/atlas/meta", handle_atlas_meta)
    app.router.add_get("/api/atlas/manifest", handle_atlas_manifest)
    app.router.add_get("/api/atlas/level/{level}/meta", handle_atlas_level_meta)
    app.router.add_get("/api/atlas/node/{node_id}/children", handle_atlas_node_children)
    app.router.add_get("/api/atlas/neighborhood/{node_id}", handle_atlas_neighborhood)
    app.router.add_get("/atlas_tiles/{path:.*}", handle_atlas_tile)
    app.router.add_static(
        "/thumbs", str(artifact_dir / "thumbnails"), show_index=False
    )
    return app


async def handle_index(request: web.Request) -> web.Response:
    return web.Response(text=VIEWER_HTML, content_type="text/html")


async def handle_count(request: web.Request) -> web.Response:
    artifact_dir = request.app["artifact_dir"]
    conn = db.open_db(artifact_dir)
    try:
        count = db.count_images(conn)
        return web.json_response({"count": count})
    finally:
        conn.close()


async def handle_images(request: web.Request) -> web.Response:
    artifact_dir = request.app["artifact_dir"]
    limit = int(request.query.get("limit", "200"))
    offset = int(request.query.get("offset", "0"))
    conn = db.open_db(artifact_dir)
    try:
        images = db.get_all_images(conn, limit=limit, offset=offset)
        # Attach thumbnail URL
        for img in images:
            img["thumb_url"] = f"/thumbs/256/{img['image_id']}.jpg"
        return web.json_response(images)
    finally:
        conn.close()


async def handle_nn_page(request: web.Request) -> web.Response:
    return web.Response(text=NN_VIEWER_HTML, content_type="text/html")


async def handle_random_id(request: web.Request) -> web.Response:
    import random
    artifact_dir = request.app["artifact_dir"]
    conn = db.open_db(artifact_dir)
    try:
        images = db.get_all_images(conn)
        img = random.choice(images)
        return web.json_response({"image_id": img["image_id"], "filename": img["filename"]})
    finally:
        conn.close()


async def handle_nn_api(request: web.Request) -> web.Response:
    from sigiltree.embeddings import nearest_neighbors
    artifact_dir = request.app["artifact_dir"]
    family = request.query.get("family", "clip")
    image_id = request.query.get("image_id", "")
    k = int(request.query.get("k", "20"))

    if not image_id:
        return web.json_response({"error": "image_id required"}, status=400)

    try:
        results = nearest_neighbors(artifact_dir, family, image_id, k=k)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)

    conn = db.open_db(artifact_dir)
    try:
        neighbors = []
        for nid, sim in results:
            cur = conn.execute("SELECT filename FROM images WHERE image_id = ?", (nid,))
            row = cur.fetchone()
            neighbors.append({
                "image_id": nid,
                "filename": row[0] if row else nid,
                "similarity": round(sim, 4),
                "thumb_url": f"/thumbs/256/{nid}.jpg",
            })
        return web.json_response({
            "query_id": image_id,
            "family": family,
            "neighbors": neighbors,
        })
    finally:
        conn.close()


async def handle_contrasts_page(request: web.Request) -> web.Response:
    return web.Response(text=CONTRASTS_VIEWER_HTML, content_type="text/html")


async def handle_contrasts_api(request: web.Request) -> web.Response:
    artifact_dir = request.app["artifact_dir"]
    lib_path = artifact_dir / "contrasts" / "contrast_library.json"
    if not lib_path.exists():
        return web.json_response({"error": "No contrast library found"}, status=404)
    library = json.loads(lib_path.read_text())
    return web.json_response(library)


async def handle_calibrate_page(request: web.Request) -> web.Response:
    return web.Response(text=CALIBRATE_HTML, content_type="text/html")


async def handle_arcade_start(request: web.Request) -> web.Response:
    from sigiltree.arcade import ArcadeSession
    artifact_dir = request.app["artifact_dir"]
    lib_path = artifact_dir / "contrasts" / "contrast_library.json"
    if not lib_path.exists():
        return web.json_response({"error": "No contrast library found"}, status=404)

    body = await request.json() if request.content_length else {}
    user_id = body.get("user_id", "default")

    library = json.loads(lib_path.read_text())
    session = ArcadeSession(library, user_id=user_id)
    request.app["arcade_sessions"][user_id] = session

    prompt = session.current_prompt
    from dataclasses import asdict
    return web.json_response({
        "status": "started",
        "prompt": asdict(prompt) if prompt else None,
        "progress": session.progress,
    })


async def handle_arcade_prompt(request: web.Request) -> web.Response:
    user_id = request.query.get("user_id", "default")
    session = request.app["arcade_sessions"].get(user_id)
    if session is None:
        return web.json_response({"error": "No active session"}, status=404)

    prompt = session.current_prompt
    from dataclasses import asdict
    return web.json_response({
        "status": "complete" if session.is_complete else "continue",
        "prompt": asdict(prompt) if prompt else None,
        "progress": session.progress,
    })


async def handle_arcade_choose(request: web.Request) -> web.Response:
    body = await request.json()
    user_id = body.get("user_id", "default")
    direction = body.get("direction")

    if direction not in ("left", "right", "center"):
        return web.json_response({"error": "direction must be left/right/center"}, status=400)

    session = request.app["arcade_sessions"].get(user_id)
    if session is None:
        return web.json_response({"error": "No active session"}, status=404)

    result = session.record_choice(direction)

    # Auto-save sigil when complete
    if result["status"] == "complete":
        from sigiltree.arcade import save_sigil
        artifact_dir = request.app["artifact_dir"]
        sigil = result["sigil"]
        save_sigil(sigil, artifact_dir)

    return web.json_response(result)


async def handle_arcade_summary(request: web.Request) -> web.Response:
    user_id = request.query.get("user_id", "default")
    session = request.app["arcade_sessions"].get(user_id)
    if session is None:
        return web.json_response({"error": "No active session"}, status=404)

    from sigiltree.arcade import build_sigil
    from dataclasses import asdict
    sigil = build_sigil(session.choices, session.library_version, session.user_id)

    return web.json_response({
        "sigil": sigil,
        "choices": [asdict(c) for c in session.choices],
        "progress": session.progress,
    })


async def handle_sigil_api(request: web.Request) -> web.Response:
    from sigiltree.arcade import load_sigil
    artifact_dir = request.app["artifact_dir"]
    user_id = request.query.get("user_id", "default")
    sigil = load_sigil(artifact_dir, user_id)
    if sigil is None:
        return web.json_response({"error": "No sigil found"}, status=404)
    return web.json_response(sigil)


async def handle_atlas_page(request: web.Request) -> web.Response:
    return web.Response(text=ATLAS_VIEWER_HTML, content_type="text/html")


async def handle_atlas_meta(request: web.Request) -> web.Response:
    from sigiltree.atlas import load_atlas_meta
    artifact_dir = request.app["artifact_dir"]
    level = int(request.query.get("level", "0"))
    meta = load_atlas_meta(artifact_dir, level=level)
    if meta is None:
        return web.json_response({"error": "No atlas built. Run: sigiltree atlas <artifact_dir>"}, status=404)
    return web.json_response(meta)


async def handle_atlas_manifest(request: web.Request) -> web.Response:
    from sigiltree.atlas import load_atlas_manifest
    artifact_dir = request.app["artifact_dir"]
    manifest = load_atlas_manifest(artifact_dir)
    if manifest is None:
        return web.json_response({"error": "No atlas built"}, status=404)
    return web.json_response(manifest)


async def handle_atlas_level_meta(request: web.Request) -> web.Response:
    from sigiltree.atlas import load_atlas_meta
    artifact_dir = request.app["artifact_dir"]
    level = int(request.match_info["level"])
    meta = load_atlas_meta(artifact_dir, level=level)
    if meta is None:
        return web.json_response({"error": f"No atlas at level {level}"}, status=404)
    return web.json_response(meta)


async def handle_atlas_node_children(request: web.Request) -> web.Response:
    from sigiltree.atlas import load_atlas_meta
    artifact_dir = request.app["artifact_dir"]
    node_id = request.match_info["node_id"]
    parent_level = int(request.query.get("level", "0"))

    parent_meta = load_atlas_meta(artifact_dir, level=parent_level)
    if parent_meta is None:
        return web.json_response({"error": "Parent level not found"}, status=404)

    parent_node = next((n for n in parent_meta["nodes"] if n["node_id"] == node_id), None)
    if parent_node is None:
        return web.json_response({"error": "Node not found"}, status=404)

    if not parent_node.get("child_ids"):
        return web.json_response({"children": [], "is_leaf": True})

    child_level = parent_level + 1
    child_meta = load_atlas_meta(artifact_dir, level=child_level)
    if child_meta is None:
        return web.json_response({"children": [], "is_leaf": True})

    children = [n for n in child_meta["nodes"] if n.get("parent_id") == node_id]
    return web.json_response({"children": children, "is_leaf": False})


async def handle_atlas_neighborhood(request: web.Request) -> web.Response:
    from sigiltree.atlas import load_atlas_meta
    node_id = request.match_info["node_id"]
    artifact_dir = request.app["artifact_dir"]
    level = int(request.query.get("level", "0"))
    meta = load_atlas_meta(artifact_dir, level=level)
    if meta is None:
        # Fall back: scan all levels to find the node
        for lvl in range(10):
            meta = load_atlas_meta(artifact_dir, level=lvl)
            if meta is None:
                break
            node = next((n for n in meta["nodes"] if n["node_id"] == node_id), None)
            if node:
                break
        else:
            return web.json_response({"error": "No atlas built"}, status=404)
    else:
        node = next((n for n in meta["nodes"] if n["node_id"] == node_id), None)
    if node is None:
        return web.json_response({"error": "Node not found"}, status=404)
    conn = db.open_db(artifact_dir)
    try:
        members = []
        for iid in node["image_ids"]:
            cur = conn.execute("SELECT filename FROM images WHERE image_id = ?", (iid,))
            row = cur.fetchone()
            members.append({
                "image_id": iid,
                "filename": row[0] if row else iid,
                "thumb_url": f"/thumbs/256/{iid}.jpg",
            })
    finally:
        conn.close()
    return web.json_response({
        "node_id": node_id,
        "level": node.get("level", level),
        "size": node["size"],
        "is_leaf": node.get("is_leaf", False),
        "child_ids": node.get("child_ids", []),
        "parent_id": node.get("parent_id"),
        "representative_ids": node["representative_ids"],
        "members": members,
    })


async def handle_atlas_tile(request: web.Request) -> web.Response:
    artifact_dir = request.app["artifact_dir"]
    tile_rel = request.match_info["path"]
    # Support multi-level tile paths: level{L}/tiles/...
    tile_path = artifact_dir / "atlas" / tile_rel
    if not tile_path.exists():
        # Fall back to old level0 structure
        tile_path = artifact_dir / "atlas" / "level0" / tile_rel
    if not tile_path.exists():
        return web.Response(status=404, text="Tile not found")
    return web.FileResponse(tile_path)


def run_server(artifact_dir: Path, host: str = "127.0.0.1", port: int = 8777):
    app = create_app(artifact_dir)
    log.info("Starting viewer at http://%s:%d", host, port)
    web.run_app(app, host=host, port=port, print=lambda msg: log.info(msg))


VIEWER_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Sigil Tree - Corpus Viewer</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    background: #111; color: #ccc; font-family: system-ui, sans-serif;
    overflow: hidden; height: 100vh;
  }
  #header {
    position: fixed; top: 0; left: 0; right: 0; height: 40px;
    background: #1a1a1a; display: flex; align-items: center;
    padding: 0 16px; z-index: 10; border-bottom: 1px solid #333;
    font-size: 13px;
  }
  #header .title { font-weight: 600; margin-right: 20px; }
  #header .stats { color: #888; }
  #grid-container {
    position: absolute; top: 40px; bottom: 0; left: 0; right: 0;
    overflow-y: auto; padding: 8px;
  }
  #grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(128px, 1fr));
    gap: 4px;
  }
  .cell {
    aspect-ratio: 1;
    background: #222;
    overflow: hidden;
    border-radius: 2px;
    cursor: pointer;
    position: relative;
  }
  .cell img {
    width: 100%; height: 100%; object-fit: cover;
    transition: transform 0.15s;
  }
  .cell:hover img { transform: scale(1.05); }
  .cell.placeholder { background: #1a1a1a; }

  /* Lightbox */
  #lightbox {
    display: none; position: fixed; inset: 0; z-index: 100;
    background: rgba(0,0,0,0.92); align-items: center; justify-content: center;
  }
  #lightbox.active { display: flex; }
  #lightbox img {
    max-width: 90vw; max-height: 90vh; object-fit: contain;
    border-radius: 4px;
  }
  #lightbox .info {
    position: absolute; bottom: 20px; left: 50%;
    transform: translateX(-50%);
    color: #888; font-size: 12px; text-align: center;
  }
</style>
</head>
<body>
<div id="header">
  <span class="title">Sigil Tree Corpus</span>
  <span class="stats" id="stats">Loading...</span>
</div>
<div id="grid-container">
  <div id="grid"></div>
</div>
<div id="lightbox" onclick="closeLightbox()">
  <img id="lb-img" src="">
  <div class="info" id="lb-info"></div>
</div>

<script>
const BATCH = 200;
let offset = 0;
let total = 0;
let loading = false;
let allLoaded = false;

async function loadCount() {
  const r = await fetch('/api/count');
  const d = await r.json();
  total = d.count;
  document.getElementById('stats').textContent = total + ' images';
}

async function loadBatch() {
  if (loading || allLoaded) return;
  loading = true;
  const r = await fetch(`/api/images?limit=${BATCH}&offset=${offset}`);
  const images = await r.json();
  if (images.length === 0) { allLoaded = true; loading = false; return; }
  const grid = document.getElementById('grid');
  for (const img of images) {
    const cell = document.createElement('div');
    cell.className = 'cell';
    const el = document.createElement('img');
    el.loading = 'lazy';
    el.src = img.thumb_url;
    el.alt = img.filename;
    el.onclick = () => openLightbox(img);
    cell.appendChild(el);
    grid.appendChild(cell);
  }
  offset += images.length;
  document.getElementById('stats').textContent =
    offset + ' / ' + total + ' images loaded';
  loading = false;
}

function openLightbox(img) {
  const lb = document.getElementById('lightbox');
  document.getElementById('lb-img').src = `/thumbs/512/${img.image_id}.jpg`;
  document.getElementById('lb-info').textContent =
    `${img.filename} (${img.width}x${img.height})`;
  lb.classList.add('active');
}

function closeLightbox() {
  document.getElementById('lightbox').classList.remove('active');
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeLightbox();
});

const container = document.getElementById('grid-container');
container.addEventListener('scroll', () => {
  if (container.scrollTop + container.clientHeight >= container.scrollHeight - 400) {
    loadBatch();
  }
});

loadCount().then(() => loadBatch());
</script>
</body>
</html>
"""

NN_VIEWER_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Sigil Tree - NN Explorer</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    background: #111; color: #ccc; font-family: system-ui, sans-serif;
    padding: 16px; overflow-y: auto;
  }
  h2 { font-size: 14px; color: #888; margin: 16px 0 8px; }
  .controls {
    display: flex; gap: 12px; align-items: center; margin-bottom: 16px;
    flex-wrap: wrap;
  }
  button {
    background: #333; color: #ccc; border: 1px solid #555;
    padding: 6px 14px; border-radius: 4px; cursor: pointer; font-size: 13px;
  }
  button:hover { background: #444; }
  button.active { background: #2a6; color: #fff; border-color: #2a6; }
  .query-section {
    display: flex; gap: 16px; align-items: flex-start; margin-bottom: 24px;
  }
  .query-img {
    width: 200px; height: 200px; object-fit: cover; border-radius: 4px;
    border: 2px solid #555;
  }
  .query-info { font-size: 12px; color: #888; margin-top: 4px; }
  .family-section { margin-bottom: 24px; }
  .family-label {
    font-size: 13px; font-weight: 600; margin-bottom: 8px;
    padding: 4px 8px; background: #1a1a1a; border-radius: 3px;
    display: inline-block;
  }
  .family-label.clip { color: #6af; }
  .family-label.dino { color: #fa6; }
  .family-label.texture { color: #6fa; }
  .nn-row {
    display: flex; gap: 4px; overflow-x: auto; padding-bottom: 8px;
  }
  .nn-cell {
    flex-shrink: 0; width: 100px; text-align: center;
  }
  .nn-cell img {
    width: 100px; height: 100px; object-fit: cover; border-radius: 3px;
    cursor: pointer;
  }
  .nn-cell img:hover { outline: 2px solid #fff; }
  .nn-cell .sim { font-size: 10px; color: #888; margin-top: 2px; }
  .nn-cell .fname { font-size: 9px; color: #666; overflow: hidden;
    text-overflow: ellipsis; white-space: nowrap; max-width: 100px; }
</style>
</head>
<body>
<div class="controls">
  <button onclick="loadRandom()">Random Image</button>
  <span style="color:#666">k=20 nearest neighbors per family</span>
</div>

<div id="content"></div>

<script>
let currentId = null;

async function loadRandom() {
  const r = await fetch('/api/random_id');
  const d = await r.json();
  currentId = d.image_id;
  await renderAll(d.image_id, d.filename);
}

async function renderAll(imageId, filename) {
  const content = document.getElementById('content');
  content.innerHTML = '<p>Loading...</p>';

  const queryHtml = `
    <div class="query-section">
      <img class="query-img" src="/thumbs/512/${imageId}.jpg">
      <div>
        <h2>Query Image</h2>
        <div class="query-info">${filename}<br>ID: ${imageId}</div>
      </div>
    </div>
  `;

  const families = ['clip', 'dino', 'texture'];
  const labels = {clip: 'CLIP (semantic)', dino: 'DINOv2 (structural)', texture: 'Texture (multiscale)'};
  let html = queryHtml;

  for (const fam of families) {
    const r = await fetch(`/api/nn?family=${fam}&image_id=${imageId}&k=20`);
    const data = await r.json();
    if (data.error) { html += `<p>Error: ${data.error}</p>`; continue; }

    html += `<div class="family-section">`;
    html += `<span class="family-label ${fam}">${labels[fam]}</span>`;
    html += `<div class="nn-row">`;
    for (const n of data.neighbors) {
      html += `
        <div class="nn-cell" onclick="renderAll('${n.image_id}', '${n.filename.replace(/'/g, "\\'")}')">
          <img src="${n.thumb_url}" loading="lazy">
          <div class="sim">${n.similarity}</div>
          <div class="fname">${n.filename}</div>
        </div>`;
    }
    html += `</div></div>`;
  }

  content.innerHTML = html;
}

loadRandom();
</script>
</body>
</html>
"""

CONTRASTS_VIEWER_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Sigil Tree - Contrast Library</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    background: #111; color: #ccc; font-family: system-ui, sans-serif;
    padding: 16px; overflow-y: auto;
  }
  h1 { font-size: 16px; margin-bottom: 8px; }
  .meta { font-size: 12px; color: #888; margin-bottom: 24px; }
  .contrast-card {
    margin-bottom: 32px; border: 1px solid #333; border-radius: 6px;
    padding: 12px; background: #1a1a1a;
  }
  .contrast-header {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 8px;
  }
  .contrast-name { font-size: 14px; font-weight: 600; }
  .contrast-meta { font-size: 11px; color: #888; }
  .source-tag {
    font-size: 10px; padding: 2px 6px; border-radius: 3px; display: inline-block;
  }
  .source-tag.perceptual { background: #2a3a2a; color: #6fa; }
  .source-tag.semantic { background: #2a2a3a; color: #6af; }
  .source-tag.emergent { background: #3a2a2a; color: #fa6; }
  .bands { display: flex; gap: 16px; }
  .band { flex: 1; }
  .band-label {
    font-size: 11px; color: #888; margin-bottom: 4px; text-align: center;
    font-weight: 600;
  }
  .band-label.low { color: #68f; }
  .band-label.high { color: #f86; }
  .band-label.median { color: #888; }
  .band-grid {
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 2px;
  }
  .band-grid img {
    width: 100%; aspect-ratio: 1; object-fit: cover; border-radius: 2px;
  }
</style>
</head>
<body>
<h1>Contrast Library</h1>
<div class="meta" id="meta">Loading...</div>
<div id="content"></div>

<script>
async function load() {
  const r = await fetch('/api/contrasts');
  const lib = await r.json();
  if (lib.error) { document.getElementById('meta').textContent = lib.error; return; }

  document.getElementById('meta').textContent =
    `Version: ${lib.version} | ${lib.count} contrasts`;

  let html = '';
  for (const c of lib.contrasts) {
    html += `<div class="contrast-card">`;
    html += `<div class="contrast-header">`;
    html += `<div>`;
    html += `<span class="contrast-name">${c.name}</span> `;
    html += `<span class="source-tag ${c.source}">${c.source}</span>`;
    html += `</div>`;
    html += `<div class="contrast-meta">mass: ${c.mass.toFixed(4)} | stability: ${c.stability.toFixed(3)}</div>`;
    html += `</div>`;
    html += `<div class="bands">`;

    for (const [band, label] of [['low', 'LOW'], ['median', 'MEDIAN'], ['high', 'HIGH']]) {
      html += `<div class="band">`;
      html += `<div class="band-label ${band}">${label}</div>`;
      html += `<div class="band-grid">`;
      const ids = c.exemplars[band] || [];
      for (const id of ids.slice(0, 12)) {
        html += `<img src="/thumbs/128/${id}.jpg" loading="lazy">`;
      }
      html += `</div></div>`;
    }
    html += `</div></div>`;
  }
  document.getElementById('content').innerHTML = html;
}
load();
</script>
</body>
</html>
"""

CALIBRATE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Sigil Tree - Calibration Arcade</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    background: #111; color: #ccc; font-family: system-ui, sans-serif;
    height: 100vh; overflow: hidden; display: flex; flex-direction: column;
    user-select: none;
  }

  .header {
    display: flex; justify-content: space-between; align-items: center;
    padding: 12px 20px; background: #1a1a1a; border-bottom: 1px solid #333;
  }
  .header h1 { font-size: 16px; }
  .progress-bar {
    width: 200px; height: 6px; background: #333; border-radius: 3px;
    overflow: hidden;
  }
  .progress-fill {
    height: 100%; background: #4a8; border-radius: 3px; transition: width 0.3s;
  }
  .progress-text { font-size: 11px; color: #888; margin-left: 8px; }

  .arena {
    flex: 1; display: flex; align-items: stretch; gap: 0;
    padding: 16px; overflow: hidden;
  }

  .door {
    flex: 1; display: flex; flex-direction: column; align-items: center;
    justify-content: center; cursor: pointer; border-radius: 8px;
    margin: 0 8px; transition: all 0.15s; position: relative;
    border: 2px solid transparent;
  }
  .door:hover { border-color: #666; }
  .door.left:hover { border-color: #68f; background: rgba(102,136,255,0.05); }
  .door.center:hover { border-color: #888; background: rgba(136,136,136,0.05); }
  .door.right:hover { border-color: #f86; background: rgba(255,136,102,0.05); }

  .door.flash-left { border-color: #68f; background: rgba(102,136,255,0.15); }
  .door.flash-center { border-color: #888; background: rgba(136,136,136,0.15); }
  .door.flash-right { border-color: #f86; background: rgba(255,136,102,0.15); }

  .door-label {
    font-size: 12px; font-weight: 600; margin-bottom: 8px; letter-spacing: 1px;
  }
  .door.left .door-label { color: #68f; }
  .door.center .door-label { color: #888; }
  .door.right .door-label { color: #f86; }

  .door-grid {
    display: grid; grid-template-columns: repeat(3, 1fr); gap: 3px;
    max-width: 320px; width: 100%;
  }
  .door-grid img {
    width: 100%; aspect-ratio: 1; object-fit: cover; border-radius: 3px;
  }

  .door-key {
    margin-top: 10px; font-size: 20px; color: #555;
    border: 1px solid #444; border-radius: 4px; padding: 2px 12px;
  }

  .contrast-info {
    text-align: center; padding: 6px; font-size: 12px; color: #666;
  }
  .contrast-info .name { color: #aaa; font-weight: 600; }
  .contrast-info .repeat-badge {
    font-size: 10px; color: #fa6; margin-left: 4px;
  }

  .footer {
    padding: 12px 20px; background: #1a1a1a; border-top: 1px solid #333;
    text-align: center; font-size: 12px; color: #666;
  }

  /* Start screen */
  .start-screen {
    flex: 1; display: flex; flex-direction: column; align-items: center;
    justify-content: center; gap: 20px;
  }
  .start-screen h2 { font-size: 22px; color: #ddd; }
  .start-screen p { max-width: 500px; text-align: center; line-height: 1.6; color: #999; }
  .start-btn {
    background: #2a6; color: #fff; border: none; padding: 12px 32px;
    border-radius: 6px; font-size: 16px; cursor: pointer;
  }
  .start-btn:hover { background: #3b7; }

  /* Summary screen */
  .summary {
    flex: 1; overflow-y: auto; padding: 32px;
  }
  .summary h2 { font-size: 18px; margin-bottom: 16px; }
  .summary-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 12px;
  }
  .sigil-card {
    background: #1a1a1a; border: 1px solid #333; border-radius: 6px;
    padding: 12px;
  }
  .sigil-card .name { font-weight: 600; font-size: 13px; }
  .sigil-card .dir {
    display: inline-block; padding: 2px 8px; border-radius: 3px;
    font-size: 11px; margin-left: 8px;
  }
  .sigil-card .dir.left { background: #1a2a4a; color: #68f; }
  .sigil-card .dir.right { background: #4a2a1a; color: #f86; }
  .sigil-card .strength { font-size: 11px; color: #888; margin-top: 4px; }
  .superposed-card {
    background: #1a1a1a; border: 1px solid #222; border-radius: 6px;
    padding: 12px; opacity: 0.5;
  }
  .superposed-card .name { font-size: 13px; }
  .superposed-card .status { font-size: 11px; color: #666; }
</style>
</head>
<body>

<div class="header">
  <h1>Calibration Arcade</h1>
  <div style="display:flex;align-items:center;">
    <div class="progress-bar"><div class="progress-fill" id="progressFill"></div></div>
    <span class="progress-text" id="progressText">0 / 0</span>
  </div>
</div>

<div id="content">
  <div class="start-screen" id="startScreen">
    <h2>Calibration Arcade</h2>
    <p>
      You will see three image mosaics for each contrast axis.
      Choose LEFT or RIGHT if you feel a clear preference.
      Choose CENTER (straight) to skip -- this records nothing.
    </p>
    <p>
      Keyboard: Arrow Left / Arrow Right / Arrow Up (or A / D / W).
      Target: under 3 minutes for a full pass.
    </p>
    <button class="start-btn" onclick="startArcade()">Begin Calibration</button>
  </div>
</div>

<div class="footer" id="footer">
  Keys: LEFT arrow = choose left | UP arrow = center/skip | RIGHT arrow = choose right | ESC = abort
</div>

<script>
let sessionActive = false;
let startTime = null;

async function startArcade() {
  const r = await fetch('/api/arcade/start', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({user_id: 'default'}),
  });
  const data = await r.json();
  if (data.error) { alert(data.error); return; }

  sessionActive = true;
  startTime = Date.now();
  renderPrompt(data.prompt, data.progress);
}

function renderPrompt(prompt, progress) {
  if (!prompt) { showSummary(); return; }

  const pct = progress.total > 0 ? (progress.current / progress.total * 100) : 0;
  document.getElementById('progressFill').style.width = pct + '%';
  document.getElementById('progressText').textContent =
    `${progress.current + 1} / ${progress.total}`;

  const elapsed = ((Date.now() - startTime) / 1000).toFixed(0);

  let html = `<div class="contrast-info">
    <span class="name">${prompt.contrast_name}</span>
    ${prompt.is_repeat ? '<span class="repeat-badge">(repeat)</span>' : ''}
    <span style="margin-left:12px;color:#555;">${elapsed}s elapsed</span>
  </div>`;

  html += `<div class="arena">`;

  // Left door
  html += `<div class="door left" onclick="choose('left')">`;
  html += `<div class="door-label">LOW</div>`;
  html += `<div class="door-grid">`;
  for (const id of prompt.left_ids) {
    html += `<img src="/thumbs/128/${id}.jpg" loading="lazy">`;
  }
  html += `</div>`;
  html += `<div class="door-key">&larr;</div>`;
  html += `</div>`;

  // Center door
  html += `<div class="door center" onclick="choose('center')">`;
  html += `<div class="door-label">SKIP</div>`;
  html += `<div class="door-grid">`;
  for (const id of prompt.center_ids) {
    html += `<img src="/thumbs/128/${id}.jpg" loading="lazy">`;
  }
  html += `</div>`;
  html += `<div class="door-key">&uarr;</div>`;
  html += `</div>`;

  // Right door
  html += `<div class="door right" onclick="choose('right')">`;
  html += `<div class="door-label">HIGH</div>`;
  html += `<div class="door-grid">`;
  for (const id of prompt.right_ids) {
    html += `<img src="/thumbs/128/${id}.jpg" loading="lazy">`;
  }
  html += `</div>`;
  html += `<div class="door-key">&rarr;</div>`;
  html += `</div>`;

  html += `</div>`;

  document.getElementById('content').innerHTML = html;
}

async function choose(direction) {
  if (!sessionActive) return;

  // Visual flash
  const doors = document.querySelectorAll('.door');
  doors.forEach(d => {
    d.classList.remove('flash-left', 'flash-center', 'flash-right');
    if (d.classList.contains(direction)) {
      d.classList.add('flash-' + direction);
    }
  });

  const r = await fetch('/api/arcade/choose', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({user_id: 'default', direction}),
  });
  const data = await r.json();

  if (data.status === 'complete') {
    sessionActive = false;
    showSummary();
  } else {
    renderPrompt(data.prompt, data.progress);
  }
}

async function showSummary() {
  const elapsed = startTime ? ((Date.now() - startTime) / 1000).toFixed(1) : '?';
  document.getElementById('progressFill').style.width = '100%';
  document.getElementById('progressText').textContent = 'Complete';

  const r = await fetch('/api/arcade/summary?user_id=default');
  const data = await r.json();
  const sigil = data.sigil;

  let html = `<div class="summary">`;
  html += `<h2>Calibration Complete</h2>`;
  html += `<p style="color:#888;margin-bottom:16px;">
    ${data.choices.length} choices in ${elapsed}s |
    ${sigil.collapsed_count} collapsed |
    ${sigil.superposed_count} superposed (uncollapsed)
  </p>`;

  // Collapsed contrasts
  if (Object.keys(sigil.entries).length > 0) {
    html += `<h3 style="font-size:14px;margin:12px 0 8px;color:#aaa;">Collapsed Contrasts</h3>`;
    html += `<div class="summary-grid">`;
    for (const [cid, entry] of Object.entries(sigil.entries)) {
      html += `<div class="sigil-card">`;
      html += `<span class="name">${entry.contrast_name}</span>`;
      html += `<span class="dir ${entry.direction}">${entry.direction.toUpperCase()}</span>`;
      html += `<div class="strength">Strength: ${(entry.strength * 100).toFixed(0)}% | Presentations: ${entry.n_presentations} | Agreements: ${entry.n_agreements}</div>`;
      html += `</div>`;
    }
    html += `</div>`;
  }

  // Superposed (uncollapsed) contrasts
  const collapsed_ids = new Set(Object.keys(sigil.entries));
  const all_seen = new Set(data.choices.map(c => c.contrast_id));
  const superposed = [...all_seen].filter(id => !collapsed_ids.has(id));

  if (superposed.length > 0) {
    html += `<h3 style="font-size:14px;margin:16px 0 8px;color:#666;">Superposed (Uncollapsed)</h3>`;
    html += `<div class="summary-grid">`;
    for (const cid of superposed) {
      const choice = data.choices.find(c => c.contrast_id === cid);
      html += `<div class="superposed-card">`;
      html += `<span class="name">${choice ? choice.contrast_name : cid}</span>`;
      html += `<div class="status">Not collapsed (center or cooled)</div>`;
      html += `</div>`;
    }
    html += `</div>`;
  }

  html += `<div style="margin-top:24px;">`;
  html += `<button class="start-btn" onclick="startArcade()">Recalibrate</button>`;
  html += `</div>`;
  html += `</div>`;

  document.getElementById('content').innerHTML = html;
}

// Keyboard controls
document.addEventListener('keydown', (e) => {
  if (!sessionActive) return;
  if (e.key === 'ArrowLeft' || e.key === 'a' || e.key === 'A') {
    e.preventDefault(); choose('left');
  } else if (e.key === 'ArrowUp' || e.key === 'w' || e.key === 'W') {
    e.preventDefault(); choose('center');
  } else if (e.key === 'ArrowRight' || e.key === 'd' || e.key === 'D') {
    e.preventDefault(); choose('right');
  }
});
</script>
</body>
</html>
"""

ATLAS_VIEWER_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Sigil Tree - Atlas</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    background: #111; color: #ccc; font-family: system-ui, sans-serif;
    overflow: hidden; height: 100vh; display: flex; flex-direction: column;
    user-select: none;
  }
  #header {
    position: fixed; top: 0; left: 0; right: 0; height: 40px;
    background: #1a1a1a; display: flex; align-items: center;
    padding: 0 16px; z-index: 10; border-bottom: 1px solid #333;
    font-size: 13px;
  }
  #header .title { font-weight: 600; margin-right: 20px; }
  #header .stats { color: #888; }
  #header .breadcrumb { margin-left: 16px; color: #888; font-size: 12px; }
  #header .breadcrumb span { cursor: pointer; }
  #header .breadcrumb span:hover { color: #4a8; }
  #header .breadcrumb .current { color: #4a8; font-weight: 600; }
  #header .mode { margin-left: auto; color: #4a8; font-weight: 600; }
  #atlas-canvas {
    position: absolute; top: 40px; left: 0; right: 0; bottom: 0;
    width: 100%; height: calc(100vh - 40px);
  }
  /* Minimap */
  #minimap {
    position: fixed; bottom: 12px; right: 12px; z-index: 15;
    border: 1px solid #444; border-radius: 4px; background: #1a1a1a;
    cursor: pointer;
  }
  /* Debug overlay */
  #debug-overlay {
    display: none; position: fixed; top: 48px; left: 12px; z-index: 15;
    background: rgba(0,0,0,0.85); border: 1px solid #444; border-radius: 4px;
    padding: 8px 12px; font-size: 11px; font-family: monospace; color: #aaa;
    line-height: 1.5; max-width: 350px;
  }
  #debug-overlay.active { display: block; }
  /* Member panel */
  #neighborhood-panel {
    display: none; position: fixed; bottom: 0; left: 0; right: 0;
    max-height: 50vh; background: #1a1a1a; border-top: 2px solid #4a8;
    overflow-y: auto; z-index: 20; padding: 12px;
  }
  #neighborhood-panel.active { display: block; }
  #neighborhood-panel .panel-header {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 8px;
  }
  #neighborhood-panel .panel-title { font-size: 14px; font-weight: 600; }
  #neighborhood-panel .panel-close {
    background: #333; border: 1px solid #555; color: #ccc;
    padding: 4px 12px; border-radius: 3px; cursor: pointer; font-size: 12px;
  }
  #neighborhood-panel .member-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
    gap: 4px;
  }
  #neighborhood-panel .member-grid img {
    width: 100%; aspect-ratio: 1; object-fit: cover; border-radius: 2px;
  }
</style>
</head>
<body>
<div id="header">
  <span class="title">Sigil Tree Atlas</span>
  <span class="stats" id="stats">Loading...</span>
  <span class="breadcrumb" id="breadcrumb"></span>
  <span class="mode" id="modeLabel">L0</span>
</div>
<canvas id="atlas-canvas"></canvas>
<canvas id="minimap" width="120" height="120"></canvas>
<div id="debug-overlay"></div>
<div id="neighborhood-panel">
  <div class="panel-header">
    <span class="panel-title" id="panelTitle">Neighborhood</span>
    <button class="panel-close" onclick="exitToParent()">ESC Back</button>
  </div>
  <div class="member-grid" id="memberGrid"></div>
</div>

<script>
const canvas = document.getElementById('atlas-canvas');
const ctx = canvas.getContext('2d');
const minimapCanvas = document.getElementById('minimap');
const minimapCtx = minimapCanvas.getContext('2d');

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let manifest = null;
let cam = { x: 0, y: 0, zoom: 1 };
let debugMode = false;
let showingMembers = false;

// Level stack: each entry = { level, nodes, camera, parentNode }
// viewStack[0] is always level 0 root
let viewStack = [];

// Tile cache: node_id -> { img, loaded }
let tileCache = {};

// Level 0 nodes (for minimap)
let level0Nodes = [];

// Interaction
let dragging = false;
let dragStart = { x: 0, y: 0 };
let camStart = { x: 0, y: 0 };

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function currentFrame() {
  return viewStack.length > 0 ? viewStack[viewStack.length - 1] : null;
}

function currentNodes() {
  const f = currentFrame();
  return f ? f.nodes : [];
}

function currentLevel() {
  const f = currentFrame();
  return f ? f.level : 0;
}

function worldToScreen(wx, wy) {
  return { x: cam.x + wx * cam.zoom, y: cam.y + wy * cam.zoom };
}

function screenToWorld(sx, sy) {
  return { x: (sx - cam.x) / cam.zoom, y: (sy - cam.y) / cam.zoom };
}

function fitToRect(rx, ry, rw, rh, viewW, viewH, padding) {
  const zoom = Math.min((viewW - padding * 2) / rw, (viewH - padding * 2) / rh);
  const cx = viewW / 2 - (rx + rw / 2) * zoom;
  const cy = viewH / 2 - (ry + rh / 2) * zoom;
  return { x: cx, y: cy, zoom: zoom };
}

// ---------------------------------------------------------------------------
// Tile loading
// ---------------------------------------------------------------------------

function tilePath(node) {
  // Multi-level: tiles are at atlas_tiles/level{L}/tiles/...
  return `/atlas_tiles/level${node.level}/${node.tile_path}`;
}

function ensureTile(node) {
  if (tileCache[node.node_id]) return;
  const img = new window.Image();
  tileCache[node.node_id] = { img: img, loaded: false };
  img.onload = () => { tileCache[node.node_id].loaded = true; draw(); };
  img.onerror = () => {};
  img.src = tilePath(node);
}

// ---------------------------------------------------------------------------
// Drawing
// ---------------------------------------------------------------------------

function resize() {
  canvas.width = canvas.clientWidth * devicePixelRatio;
  canvas.height = canvas.clientHeight * devicePixelRatio;
  ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
  draw();
}

function draw() {
  const cw = canvas.clientWidth;
  const ch = canvas.clientHeight;
  ctx.clearRect(0, 0, cw, ch);
  ctx.fillStyle = '#111';
  ctx.fillRect(0, 0, cw, ch);

  const nodes = currentNodes();
  if (!nodes.length) return;

  for (const node of nodes) {
    const [rx, ry, rw, rh] = node.rect;
    const tl = worldToScreen(rx, ry);
    const sw = rw * cam.zoom;
    const sh = rh * cam.zoom;

    if (tl.x + sw < 0 || tl.y + sh < 0 || tl.x > cw || tl.y > ch) continue;

    ensureTile(node);
    const tc = tileCache[node.node_id];
    if (tc && tc.loaded) {
      ctx.drawImage(tc.img, tl.x, tl.y, sw, sh);
    } else {
      ctx.fillStyle = '#1a1a1a';
      ctx.fillRect(tl.x, tl.y, sw, sh);
    }

    // Border
    const hasChildren = node.child_ids && node.child_ids.length > 0;
    ctx.strokeStyle = hasChildren ? '#555' : '#333';
    ctx.lineWidth = 0.5;
    ctx.strokeRect(tl.x, tl.y, sw, sh);

    // Label
    if (sw > 60 && sh > 24) {
      ctx.fillStyle = hasChildren ? 'rgba(200,200,200,0.7)' : 'rgba(200,200,200,0.4)';
      ctx.font = `${Math.max(9, Math.min(13, sw / 8))}px system-ui`;
      ctx.textAlign = 'center';
      const label = `${node.size}`;
      ctx.fillText(label, tl.x + sw / 2, tl.y + sh / 2 + 4);
    }
  }

  drawMinimap();
  drawDebug();
}

// ---------------------------------------------------------------------------
// Minimap
// ---------------------------------------------------------------------------

function drawMinimap() {
  if (!level0Nodes.length) return;
  const mw = 120, mh = 120;
  minimapCtx.clearRect(0, 0, mw, mh);
  minimapCtx.fillStyle = '#1a1a1a';
  minimapCtx.fillRect(0, 0, mw, mh);

  // Draw level 0 rects
  for (const node of level0Nodes) {
    const [rx, ry, rw, rh] = node.rect;
    minimapCtx.fillStyle = '#2a2a2a';
    minimapCtx.fillRect(rx * mw, ry * mh, rw * mw, rh * mh);
    minimapCtx.strokeStyle = '#444';
    minimapCtx.lineWidth = 0.5;
    minimapCtx.strokeRect(rx * mw, ry * mh, rw * mw, rh * mh);
  }

  // Highlight current viewport in world coords
  const cw = canvas.clientWidth, ch = canvas.clientHeight;
  const topLeft = screenToWorld(0, 0);
  const botRight = screenToWorld(cw, ch);
  const vx = topLeft.x * mw;
  const vy = topLeft.y * mh;
  const vw = (botRight.x - topLeft.x) * mw;
  const vh = (botRight.y - topLeft.y) * mh;

  minimapCtx.strokeStyle = '#4a8';
  minimapCtx.lineWidth = 1.5;
  minimapCtx.strokeRect(
    Math.max(0, vx), Math.max(0, vy),
    Math.min(mw, vw), Math.min(mh, vh)
  );

  // Highlight active parent rect if zoomed in
  if (viewStack.length > 1) {
    const parentNode = viewStack[viewStack.length - 1].parentNode;
    if (parentNode) {
      const [px, py, pw, ph] = parentNode.rect;
      minimapCtx.strokeStyle = '#f86';
      minimapCtx.lineWidth = 1;
      minimapCtx.strokeRect(px * mw, py * mh, pw * mw, ph * mh);
    }
  }
}

// ---------------------------------------------------------------------------
// Debug overlay
// ---------------------------------------------------------------------------

function drawDebug() {
  const el = document.getElementById('debug-overlay');
  if (!debugMode) { el.classList.remove('active'); return; }
  el.classList.add('active');

  const f = currentFrame();
  if (!f) { el.textContent = 'No frame'; return; }

  const cw = canvas.clientWidth, ch = canvas.clientHeight;
  const center = screenToWorld(cw / 2, ch / 2);

  let html = `<b>Level:</b> ${f.level}<br>`;
  html += `<b>Stack depth:</b> ${viewStack.length}<br>`;
  html += `<b>Nodes:</b> ${f.nodes.length}<br>`;
  html += `<b>Camera:</b> x=${cam.x.toFixed(0)} y=${cam.y.toFixed(0)} z=${cam.zoom.toFixed(0)}<br>`;
  html += `<b>Center:</b> (${center.x.toFixed(4)}, ${center.y.toFixed(4)})<br>`;

  if (f.parentNode) {
    const pn = f.parentNode;
    html += `<b>Parent:</b> ${pn.node_id} [${pn.rect.map(v => v.toFixed(3)).join(', ')}]<br>`;
    html += `<b>Parent size:</b> ${pn.size} images<br>`;
  }

  html += `<b>Tile cache:</b> ${Object.keys(tileCache).length} entries<br>`;
  html += `<b>Max level:</b> ${manifest ? manifest.max_level : '?'}<br>`;
  el.innerHTML = html;
}

// ---------------------------------------------------------------------------
// Breadcrumb
// ---------------------------------------------------------------------------

function updateBreadcrumb() {
  const el = document.getElementById('breadcrumb');
  let parts = [];
  for (let i = 0; i < viewStack.length; i++) {
    const f = viewStack[i];
    const isCurrent = (i === viewStack.length - 1);
    const label = i === 0 ? 'Root' : (f.parentNode ? f.parentNode.node_id : `L${f.level}`);
    if (isCurrent) {
      parts.push(`<span class="current">${label}</span>`);
    } else {
      parts.push(`<span onclick="popToLevel(${i})">${label}</span>`);
    }
  }
  el.innerHTML = parts.join(' > ');

  const lvl = currentLevel();
  document.getElementById('modeLabel').textContent =
    showingMembers ? 'MEMBERS' : `L${lvl}`;
}

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------

async function init() {
  try {
    const mr = await fetch('/api/atlas/manifest');
    if (mr.ok) {
      manifest = await mr.json();
    }

    const r = await fetch('/api/atlas/meta?level=0');
    if (!r.ok) {
      document.getElementById('stats').textContent = 'No atlas built. Run: sigiltree atlas <artifact_dir>';
      return;
    }
    const meta = await r.json();
    level0Nodes = meta.nodes;

    document.getElementById('stats').textContent =
      `${meta.corpus_size} images, ${meta.n_neighborhoods} neighborhoods` +
      (manifest && manifest.max_level > 0 ? `, ${manifest.max_level + 1} levels` : '');

    // Push root frame
    viewStack = [{
      level: 0,
      nodes: meta.nodes,
      camera: null,
      parentNode: null,
    }];

    fitOverview();
    updateBreadcrumb();
    draw();
  } catch (e) {
    document.getElementById('stats').textContent = 'Error loading atlas: ' + e.message;
  }
}

function fitOverview() {
  const cw = canvas.clientWidth;
  const ch = canvas.clientHeight;
  const padding = 20;
  cam = fitToRect(0, 0, 1, 1, cw, ch, padding);
}

function hitTest(sx, sy) {
  const w = screenToWorld(sx, sy);
  const nodes = currentNodes();
  // Return the smallest node containing the point (deepest match)
  let best = null;
  let bestArea = Infinity;
  for (const node of nodes) {
    const [rx, ry, rw, rh] = node.rect;
    if (w.x >= rx && w.x < rx + rw && w.y >= ry && w.y < ry + rh) {
      const area = rw * rh;
      if (area < bestArea) {
        bestArea = area;
        best = node;
      }
    }
  }
  return best;
}

async function enterNode(node) {
  // If leaf or has no children, show member panel
  if (node.is_leaf || !node.child_ids || node.child_ids.length === 0) {
    showMembers(node);
    return;
  }

  // Save current camera
  const curFrame = currentFrame();
  if (curFrame) {
    curFrame.camera = { x: cam.x, y: cam.y, zoom: cam.zoom };
  }

  // Fetch children
  const r = await fetch(`/api/atlas/node/${node.node_id}/children?level=${node.level}`);
  const data = await r.json();

  if (data.is_leaf || !data.children || data.children.length === 0) {
    showMembers(node);
    return;
  }

  // Push new frame
  viewStack.push({
    level: node.level + 1,
    nodes: data.children,
    camera: null,
    parentNode: node,
  });

  // Zoom camera into parent rect
  const [rx, ry, rw, rh] = node.rect;
  const cw = canvas.clientWidth;
  const ch = canvas.clientHeight;
  cam = fitToRect(rx, ry, rw, rh, cw, ch, 20);

  closeMembers();
  updateBreadcrumb();
  draw();
}

function exitToParent() {
  if (showingMembers) {
    closeMembers();
    draw();
    return;
  }

  if (viewStack.length <= 1) {
    // Already at root, just fit overview
    fitOverview();
    updateBreadcrumb();
    draw();
    return;
  }

  // Pop current frame
  viewStack.pop();

  // Restore camera from parent frame (instant, no network request)
  const parentFrame = currentFrame();
  if (parentFrame && parentFrame.camera) {
    cam = { ...parentFrame.camera };
  } else {
    fitOverview();
  }

  closeMembers();
  updateBreadcrumb();
  draw();
}

function popToLevel(stackIndex) {
  while (viewStack.length > stackIndex + 1) {
    viewStack.pop();
  }
  const frame = currentFrame();
  if (frame && frame.camera) {
    cam = { ...frame.camera };
  } else {
    fitOverview();
  }
  closeMembers();
  updateBreadcrumb();
  draw();
}

// ---------------------------------------------------------------------------
// Member panel
// ---------------------------------------------------------------------------

async function showMembers(node) {
  showingMembers = true;
  updateBreadcrumb();

  // Zoom to node rect
  const [rx, ry, rw, rh] = node.rect;
  const cw = canvas.clientWidth;
  const ch = canvas.clientHeight;
  const panelH = Math.min(ch * 0.5, 300);
  const viewH = ch - panelH;
  cam = fitToRect(rx, ry, rw, rh, cw, viewH, 30);
  draw();

  const level = node.level !== undefined ? node.level : currentLevel();
  const r = await fetch(`/api/atlas/neighborhood/${node.node_id}?level=${level}`);
  const data = await r.json();
  document.getElementById('panelTitle').textContent =
    `${node.node_id} - ${data.size} images`;
  const grid = document.getElementById('memberGrid');
  grid.innerHTML = '';
  for (const m of data.members) {
    const img = document.createElement('img');
    img.src = m.thumb_url;
    img.alt = m.filename;
    img.loading = 'lazy';
    img.title = m.filename;
    grid.appendChild(img);
  }
  document.getElementById('neighborhood-panel').classList.add('active');
}

function closeMembers() {
  showingMembers = false;
  document.getElementById('neighborhood-panel').classList.remove('active');
  updateBreadcrumb();
}

// ---------------------------------------------------------------------------
// Mouse interaction
// ---------------------------------------------------------------------------

canvas.addEventListener('mousedown', (e) => {
  dragging = true;
  dragStart = { x: e.clientX, y: e.clientY };
  camStart = { x: cam.x, y: cam.y };
});

canvas.addEventListener('mousemove', (e) => {
  if (!dragging) return;
  cam.x = camStart.x + (e.clientX - dragStart.x);
  cam.y = camStart.y + (e.clientY - dragStart.y);
  draw();
});

canvas.addEventListener('mouseup', (e) => {
  const dx = Math.abs(e.clientX - dragStart.x);
  const dy = Math.abs(e.clientY - dragStart.y);
  dragging = false;
  if (dx < 5 && dy < 5) {
    const rect = canvas.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    const node = hitTest(sx, sy);
    if (node) {
      enterNode(node);
    }
  }
});

canvas.addEventListener('wheel', (e) => {
  e.preventDefault();
  if (e.ctrlKey) {
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    cam.x = mx - (mx - cam.x) * factor;
    cam.y = my - (my - cam.y) * factor;
    cam.zoom *= factor;
  } else {
    cam.x -= e.deltaX;
    cam.y -= e.deltaY;
  }
  draw();
}, { passive: false });

// ---------------------------------------------------------------------------
// Keyboard
// ---------------------------------------------------------------------------

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    exitToParent();
  } else if (e.key === 'Home' || e.key === 'h' || e.key === 'H') {
    // Pop all to root
    while (viewStack.length > 1) viewStack.pop();
    fitOverview();
    closeMembers();
    updateBreadcrumb();
    draw();
  } else if (e.key === 'd' || e.key === 'D') {
    debugMode = !debugMode;
    draw();
  }
});

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

window.addEventListener('resize', resize);
resize();
init();
</script>
</body>
</html>
"""
