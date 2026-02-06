"""Lightweight aiohttp server for the thumbnail grid viewer."""

import json
import logging
from pathlib import Path

from aiohttp import web

from sigiltree import db

log = logging.getLogger(__name__)


def _preheat_caches(app, artifact_dir: Path) -> None:
    """Load all atlas metadata, ride stats, and flow graphs at startup."""
    import time
    start = time.perf_counter()

    manifest_path = artifact_dir / "atlas" / "manifest.json"
    if not manifest_path.exists():
        return

    manifest = json.loads(manifest_path.read_text())
    max_level = manifest.get("max_level", 0)

    # Load stats first (needed for flow graphs)
    _cached_stats(app, artifact_dir)

    # Load meta and flow graph for every level
    for level in range(max_level + 1):
        _cached_meta(app, artifact_dir, level)
        _cached_flow(app, artifact_dir, level)

    elapsed = (time.perf_counter() - start) * 1000
    log.info("Cache preheated: %d levels in %.0fms", max_level + 1, elapsed)


def create_app(artifact_dir: Path) -> web.Application:
    app = web.Application()
    app["artifact_dir"] = artifact_dir
    app["arcade_sessions"] = {}  # user_id -> ArcadeSession
    app["flythrough_sessions"] = {}  # user_id -> FlythroughSession
    app["_flow_cache"] = {}  # level -> flow_graph
    app["_meta_cache"] = {}  # level -> meta dict
    app["_stats_cache"] = None  # ride stats

    # Preheat caches at startup so first request is fast
    _preheat_caches(app, artifact_dir)

    app.router.add_get("/", lambda r: web.HTTPFound("/atlas"))
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
    app.router.add_get("/api/atlas/sigil_scores", handle_atlas_sigil_scores)
    app.router.add_get("/api/ride/stats", handle_ride_stats)  # z-summaries (kept)
    app.router.add_post("/api/flythrough/record", handle_flythrough_record)
    app.router.add_get("/api/atlas/flow_neighbors", handle_flow_neighbors)
    app.router.add_get("/api/atlas/node/{node_id}/doors", handle_atlas_node_doors)
    app.router.add_get("/api/atlas/node_labels", handle_atlas_node_labels)
    app.router.add_get("/api/image/{image_id}/full", handle_image_full)
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
    artifact_dir = request.app["artifact_dir"]
    level = int(request.query.get("level", "0"))
    meta = _cached_meta(request.app, artifact_dir, level)
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
    artifact_dir = request.app["artifact_dir"]
    level = int(request.match_info["level"])
    meta = _cached_meta(request.app, artifact_dir, level)
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


async def handle_atlas_sigil_scores(request: web.Request) -> web.Response:
    from sigiltree.arcade import load_sigil
    from sigiltree.atlas import load_atlas_meta
    from sigiltree.sigil_scoring import compute_sigil_scores

    artifact_dir = request.app["artifact_dir"]
    user_id = request.query.get("user_id", "default")
    level = int(request.query.get("level", "0"))

    sigil = load_sigil(artifact_dir, user_id)
    if sigil is None:
        return web.json_response({"error": "No sigil found"}, status=404)

    lib_path = artifact_dir / "contrasts" / "contrast_library.json"
    if not lib_path.exists():
        return web.json_response({"error": "No contrast library"}, status=404)
    library = json.loads(lib_path.read_text())

    coords_path = artifact_dir / "contrasts" / "coordinates.json"
    if not coords_path.exists():
        return web.json_response({"error": "No coordinates"}, status=404)
    coordinates = json.loads(coords_path.read_text())

    meta = load_atlas_meta(artifact_dir, level=level)
    if meta is None:
        return web.json_response({"error": f"No atlas level {level}"}, status=404)

    scores = compute_sigil_scores(sigil, library, coordinates, meta["nodes"])

    collapsed_names = [e["contrast_name"] for e in sigil.get("entries", {}).values()]

    return web.json_response({
        "user_id": user_id,
        "sigil_version": sigil.get("version", ""),
        "collapsed_contrasts": collapsed_names,
        "level": level,
        "scores": scores,
    })


async def handle_flythrough_record(request: web.Request) -> web.Response:
    """Record flythrough visits and compute sigil from navigation."""
    from sigiltree.arcade import save_sigil
    from sigiltree.ride_stats import load_ride_stats
    from sigiltree.flythrough import FlythroughSession, flythrough_to_sigil

    artifact_dir = request.app["artifact_dir"]
    body = await request.json()
    user_id = body.get("user_id", "default")
    visits = body.get("visits", [])

    if not visits:
        return web.json_response({"error": "No visits provided"}, status=400)

    # Build session from visits
    session = FlythroughSession(user_id=user_id)
    for v in visits:
        session.record_visit(v.get("node_id", ""), v.get("level", 0))

    if not session.is_ready:
        return web.json_response({
            "status": "not_ready",
            "visited_count": len(session.distinct_nodes),
            "preferences_count": 0,
        })

    # Load z-summaries and contrast library
    stats = load_ride_stats(artifact_dir)
    if stats is None:
        return web.json_response({"error": "Stats not precomputed"}, status=404)

    lib_path = artifact_dir / "contrasts" / "contrast_library.json"
    if not lib_path.exists():
        return web.json_response({"error": "No contrast library"}, status=404)
    library = json.loads(lib_path.read_text())

    # Build all_level_nodes from manifest
    from sigiltree.atlas import load_atlas_manifest
    manifest = load_atlas_manifest(artifact_dir)
    all_level_nodes = {}
    if manifest:
        for lvl_info in manifest.get("levels", []):
            lvl = str(lvl_info["level"])
            meta_path = artifact_dir / "atlas" / f"level{lvl_info['level']}" / "meta.json"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text())
                all_level_nodes[lvl] = [n["node_id"] for n in meta.get("nodes", [])]

    sigil = flythrough_to_sigil(session, stats["zsummaries"], library, all_level_nodes)
    save_sigil(sigil, artifact_dir)

    return web.json_response({
        "status": "ok",
        "visited_count": len(session.distinct_nodes),
        "preferences_count": sigil["collapsed_count"],
    })


async def handle_flow_neighbors(request: web.Request) -> web.Response:
    """Return flow-neighbor ordering for a node."""
    from sigiltree.ride_stats import load_ride_stats
    from sigiltree.atlas import load_atlas_meta
    from sigiltree.flythrough import compute_flow_graph

    artifact_dir = request.app["artifact_dir"]
    node_id = request.query.get("node_id")
    level = request.query.get("level", "0")

    if not node_id:
        return web.json_response({"error": "node_id required"}, status=400)

    stats = load_ride_stats(artifact_dir)
    if stats is None:
        return web.json_response({"error": "Stats not computed"}, status=404)

    level_zs = stats["zsummaries"].get(str(level), {})

    meta = load_atlas_meta(artifact_dir, level=int(level))
    if meta is None:
        return web.json_response({"error": f"No atlas level {level}"}, status=404)

    node_map = {n["node_id"]: n for n in meta["nodes"]}
    node_ids = list(node_map.keys())

    flow = compute_flow_graph(node_ids, level_zs)
    neighbors = flow.get(node_id, [])

    # Return with enough info for the client to construct node objects
    result = []
    for nid in neighbors[:10]:  # top 10 most similar
        n = node_map.get(nid, {})
        result.append({
            "node_id": nid,
            "rect": n.get("rect", [0, 0, 0, 0]),
            "level": int(level),
            "is_leaf": n.get("is_leaf", True),
            "size": n.get("size", 0),
            "tile_path": n.get("tile_path", ""),
        })

    return web.json_response({"node_id": node_id, "neighbors": result})


def _cached_meta(app, artifact_dir, level):
    """Load atlas meta with app-level caching. Enriches nodes with tile dimensions."""
    from sigiltree.atlas import load_atlas_meta, load_root_meta
    cache = app["_meta_cache"]
    if level not in cache:
        if level == -1:
            meta = load_root_meta(artifact_dir)
        else:
            meta = load_atlas_meta(artifact_dir, level=level)
        if meta:
            _enrich_tile_dimensions(meta, artifact_dir, level)
        cache[level] = meta
    return cache[level]


def _enrich_tile_dimensions(meta, artifact_dir, level):
    """Add tile_w and tile_h to each node by reading tile image headers."""
    from PIL import Image
    level_dir = "root" if level == -1 else f"level{level}"
    for node in meta.get("nodes", []):
        tile_path = node.get("tile_path", "")
        if not tile_path:
            continue
        full_path = artifact_dir / "atlas" / level_dir / tile_path
        if not full_path.exists():
            continue
        try:
            with Image.open(full_path) as im:
                node["tile_w"], node["tile_h"] = im.size
        except Exception:
            pass


def _cached_stats(app, artifact_dir):
    """Load ride stats with app-level caching."""
    from sigiltree.ride_stats import load_ride_stats
    if app["_stats_cache"] is None:
        app["_stats_cache"] = load_ride_stats(artifact_dir)
    return app["_stats_cache"]


def _cached_flow(app, artifact_dir, level):
    """Compute flow graph with app-level caching."""
    from sigiltree.flythrough import compute_flow_graph
    cache = app["_flow_cache"]
    if level not in cache:
        stats = _cached_stats(app, artifact_dir)
        if not stats:
            cache[level] = {}
            return cache[level]
        level_zs = stats["zsummaries"].get(str(level), {})
        meta = _cached_meta(app, artifact_dir, level)
        if meta and level_zs:
            node_ids = [n["node_id"] for n in meta["nodes"]]
            cache[level] = compute_flow_graph(node_ids, level_zs)
        else:
            cache[level] = {}
    return cache[level]


async def handle_atlas_node_doors(request: web.Request) -> web.Response:
    """Return all doors for a sigil: back + down + lateral.

    Unified endpoint that combines children (down doors) and flow-neighbors
    (lateral doors) into a single response. Every sigil always has doors.
    """
    artifact_dir = request.app["artifact_dir"]
    node_id = request.match_info["node_id"]
    level = int(request.query.get("level", "0"))
    from_node = request.query.get("from_node", "")
    from_level = request.query.get("from_level", "")

    doors = []

    # Back door: the sigil we came from (may be at a different level).
    # Every view always has a back door — if from_node is not provided
    # or not found, the back door is the root sigil (the entire corpus).
    back_found = False
    if from_node:
        back_level = int(from_level) if from_level else level
        for search_level in ([back_level, level] if back_level != level else [level]):
            from_meta = _cached_meta(request.app, artifact_dir, search_level)
            if from_meta:
                back_node = next(
                    (n for n in from_meta["nodes"] if n["node_id"] == from_node),
                    None,
                )
                if back_node:
                    doors.append({**back_node, "door_type": "back"})
                    back_found = True
                    break

    if not back_found:
        # Root back door: the corpus sigil, loaded from atlas/root/meta.json
        root_meta = _cached_meta(request.app, artifact_dir, -1)
        if root_meta and root_meta.get("nodes"):
            root_node = root_meta["nodes"][0]
            doors.append({**root_node, "door_type": "back"})

    # Down doors: children of this node
    parent_meta = _cached_meta(request.app, artifact_dir, level)
    if parent_meta:
        parent_node = next(
            (n for n in parent_meta["nodes"] if n["node_id"] == node_id), None
        )
        if parent_node and parent_node.get("child_ids"):
            child_level = level + 1
            child_meta = _cached_meta(request.app, artifact_dir, child_level)
            if child_meta:
                children = [
                    n for n in child_meta["nodes"]
                    if n.get("parent_id") == node_id
                ]
                for child in children:
                    doors.append({**child, "door_type": "down"})

    # Member images: expose the node's actual photographs so the client
    # can display them as clickable tiles. Works at every level, not just leaves.
    members = []
    if parent_node and parent_node.get("size", 0) > 1:
        image_ids = parent_node.get("image_ids", [])
        # Batch-fetch original dimensions from DB for aspect-ratio-aware layout
        dims: dict[str, tuple[int, int]] = {}
        if image_ids:
            try:
                conn = db.open_db(artifact_dir)
                try:
                    placeholders = ",".join("?" * len(image_ids))
                    cur = conn.execute(
                        f"SELECT image_id, width, height FROM images "
                        f"WHERE image_id IN ({placeholders})",
                        image_ids,
                    )
                    for row in cur.fetchall():
                        if row[1] and row[2]:
                            dims[row[0]] = (row[1], row[2])
                finally:
                    conn.close()
            except Exception:
                pass  # Graceful fallback: members without dimensions

        for iid in image_ids:
            orig_w, orig_h = dims.get(iid, (512, 512))
            # Thumbnail has long side = 512, preserve aspect ratio
            if orig_w >= orig_h:
                thumb_w = 512
                thumb_h = max(1, round(512 * orig_h / orig_w))
            else:
                thumb_h = 512
                thumb_w = max(1, round(512 * orig_w / orig_h))
            members.append({
                "image_id": iid,
                "thumb_url": f"/thumbs/512/{iid}.jpg",
                "door_type": "member",
                "thumb_w": thumb_w,
                "thumb_h": thumb_h,
            })

    # Lateral doors: flow-neighbors at same level
    flow = _cached_flow(request.app, artifact_dir, level)
    if flow:
        meta = _cached_meta(request.app, artifact_dir, level)
        if meta:
            node_map = {n["node_id"]: n for n in meta["nodes"]}
            neighbors = flow.get(node_id, [])
            seen = {d["node_id"] for d in doors}
            for nid in neighbors[:8]:
                if nid not in seen:
                    n = node_map.get(nid, {})
                    doors.append({**n, "door_type": "lateral"})

    return web.json_response({
        "doors": doors,
        "members": members,
        "node_id": node_id,
        "level": level,
    })


async def handle_ride_stats(request: web.Request) -> web.Response:
    from sigiltree.ride_stats import load_ride_stats

    artifact_dir = request.app["artifact_dir"]
    level = request.query.get("level")

    stats = load_ride_stats(artifact_dir)
    if stats is None:
        return web.json_response({"error": "Ride stats not computed"}, status=404)

    if level is not None:
        zsummaries = stats["zsummaries"].get(str(level), {})
        return web.json_response({"level": int(level), "zsummaries": zsummaries, "correlations": stats["correlations"]})

    return web.json_response(stats)


async def handle_atlas_node_labels(request: web.Request) -> web.Response:
    """Compute descriptive labels for atlas nodes from z-summaries.

    For each node, finds the semantic or perceptual contrast with the most
    extreme z_mean and derives a human-readable label from it.
    """
    import re
    from sigiltree.ride_stats import load_ride_stats

    artifact_dir = request.app["artifact_dir"]
    level = request.query.get("level", "0")

    stats = load_ride_stats(artifact_dir)
    if stats is None:
        return web.json_response({"error": "Ride stats not computed"}, status=404)

    level_zs = stats["zsummaries"].get(str(level), {})
    if not level_zs:
        return web.json_response({"error": f"No z-summaries for level {level}"}, status=404)

    # Collect all node_ids
    node_ids = set()
    for cname, node_dict in level_zs.items():
        node_ids.update(node_dict.keys())

    def contrast_priority(cname):
        if cname.startswith("sem_"):
            return 0
        if cname.startswith("pca_"):
            return 2
        return 1

    def derive_label(cname, z):
        m = re.match(r"^sem_(.+)_vs_(.+)$", cname)
        if m:
            return m.group(2).replace("_", " ") if z > 0 else m.group(1).replace("_", " ")
        m = re.match(r"^sem_(.+)$", cname)
        if m:
            name = m.group(1).replace("_", " ")
            return name if z > 0 else None
        if not cname.startswith("pca_"):
            if cname == "brightness":
                return "bright" if z > 0 else "dark"
            return cname if z > 0 else f"low {cname}"
        return None

    labels = {}
    for nid in node_ids:
        candidates = []
        for cname, node_dict in level_zs.items():
            zm = node_dict.get(nid, {}).get("z_mean", 0)
            pri = contrast_priority(cname)
            label = derive_label(cname, zm)
            if label:
                candidates.append((pri, -abs(zm), label, cname, zm))
        candidates.sort()
        if candidates:
            labels[nid] = candidates[0][2]

    return web.json_response({"level": int(level), "labels": labels})


async def handle_image_full(request: web.Request) -> web.Response:
    """Serve the original corpus image for full-size viewing."""
    artifact_dir = request.app["artifact_dir"]
    image_id = request.match_info["image_id"]
    conn = db.open_db(artifact_dir)
    cur = conn.execute("SELECT path FROM images WHERE image_id = ?", (image_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return web.Response(status=404, text="Image not found")
    image_path = Path(row[0])
    if not image_path.is_absolute():
        image_path = Path.cwd() / image_path
    if not image_path.exists():
        return web.Response(status=404, text="Image file not found")
    return web.FileResponse(image_path)


async def handle_atlas_tile(request: web.Request) -> web.Response:
    artifact_dir = request.app["artifact_dir"]
    tile_rel = request.match_info["path"]
    # Map level-1 (root sigil) to the root directory
    if tile_rel.startswith("level-1/"):
        tile_rel = "root/" + tile_rel[len("level-1/"):]
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
  /* Sigil indicator */
  #sigilIndicator {
    display: none; margin-left: 12px; padding: 2px 8px; border-radius: 3px;
    font-size: 11px; font-weight: 600;
    background: rgba(255,170,0,0.15); color: #fa6;
    border: 1px solid rgba(255,170,0,0.3);
  }
  #sigilIndicator.active { display: inline; }
  #flythroughIndicator {
    display: none; margin-left: 8px; padding: 2px 8px; border-radius: 3px;
    font-size: 11px; font-weight: 600;
    background: rgba(100,200,255,0.15); color: #6cf;
    border: 1px solid rgba(100,200,255,0.3);
  }
  #flythroughIndicator.active { display: inline; }
  #flythrough-toast {
    display: none; position: fixed; bottom: 60px; left: 50%;
    transform: translateX(-50%);
    background: rgba(20,20,20,0.9); border: 1px solid #2a5; border-radius: 6px;
    padding: 10px 20px; z-index: 50; font-size: 13px; color: #ddd;
    transition: opacity 0.5s;
  }
  #flythrough-toast.active { display: block; }
  /* Help overlay */
  #help-overlay {
    display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0;
    z-index: 100; background: rgba(0,0,0,0.82);
    justify-content: center; align-items: center;
  }
  #help-overlay.active { display: flex; }
  #help-content {
    background: #1e1e1e; border: 1px solid #444; border-radius: 10px;
    padding: 28px 36px; max-width: 520px; width: 90%;
    color: #ccc; font-size: 13px; line-height: 1.7;
    max-height: 90vh; overflow-y: auto;
  }
  #help-content h2 {
    margin: 0 0 6px; color: #eee; font-size: 18px; font-weight: 600;
  }
  #help-content .intro {
    color: #aaa; font-size: 13px; line-height: 1.65; margin-bottom: 18px;
  }
  #help-content .intro p { margin: 0 0 10px; }
  #help-content .intro em { color: #ccc; font-style: normal; }
  #help-content .section-label {
    color: #4a8; font-weight: 600; font-size: 12px; text-transform: uppercase;
    letter-spacing: 0.5px; margin: 14px 0 6px; display: block;
  }
  #help-content .section-label:first-of-type { margin-top: 0; }
  #help-content .key-row {
    display: flex; align-items: baseline; margin: 3px 0;
  }
  #help-content kbd {
    display: inline-block; min-width: 52px; padding: 1px 7px;
    background: #2a2a2a; border: 1px solid #444; border-radius: 3px;
    font-family: system-ui, sans-serif; font-size: 12px; color: #ddd;
    text-align: center; margin-right: 10px; white-space: nowrap;
  }
  #help-content .key-desc { color: #999; font-size: 12px; }
  #help-content .dismiss {
    margin-top: 20px; text-align: center; color: #666; font-size: 11px;
  }
  /* Help badge removed — help is now in toolbar */
  /* Floating toolbar */
  #toolbar {
    position: fixed; bottom: 16px; left: 16px; z-index: 15;
    display: flex; gap: 8px; align-items: center;
  }
  #toolbar button {
    width: 36px; height: 36px; border-radius: 50%;
    background: rgba(30,30,30,0.85); border: 1px solid #444;
    color: #aaa; font-size: 16px; cursor: pointer;
    display: flex; align-items: center; justify-content: center;
    transition: all 0.15s; padding: 0;
  }
  #toolbar button:hover {
    background: #333; color: #eee; border-color: #4a8;
  }
  #toolbar button.active {
    background: rgba(100,200,255,0.15); border-color: #6cf; color: #6cf;
  }
</style>
</head>
<body>
<div id="header">
  <span class="title">Sigil Tree Atlas</span>
  <span class="stats" id="stats">Loading...</span>
  <span class="breadcrumb" id="breadcrumb"></span>
  <span id="sigilIndicator">SIGIL</span>
  <span id="flythroughIndicator">Exploring (0)</span>
  <span class="mode" id="modeLabel">L0</span>
</div>
<canvas id="atlas-canvas"></canvas>
<canvas id="minimap" width="120" height="120"></canvas>
<div id="debug-overlay"></div>
<div id="flythrough-toast"></div>
<div id="toolbar">
  <button id="toolbar-back" title="Back" onclick="exitToParent()" style="opacity:0.3">&#x21A9;</button>
  <button id="toolbar-home" title="Home" onclick="goHome()" style="opacity:0.3">&#x2302;</button>
  <button id="toolbar-explore" title="Explore" onclick="toggleFlythrough()">&#x25CE;</button>
  <button id="toolbar-sigil" title="Sigil overlay" onclick="toggleSigil()">&#x2606;</button>
  <button id="toolbar-help" title="Help" onclick="toggleHelp()">?</button>
</div>

<div id="help-overlay">
  <div id="help-content">
    <h2>Sigil Atlas</h2>
    <div class="intro">
      <p>A labyrinth of photographs. Every image is grouped with the ones it most resembles &mdash; not by category, but by what it <em>looks and feels like</em>.</p>
      <p>Click any tile to enter it. Inside, you see doors: some lead deeper into detail, some lead sideways to similar neighborhoods. There are no dead ends. The space loops.</p>
      <p>Navigate toward what attracts you. The system silently learns your preferences and builds a personal <em>sigil</em> that reshapes what the atlas highlights for you.</p>
    </div>
    <span class="section-label">Navigate</span>
    <div class="key-row"><kbd>Click</kbd><span class="key-desc">Enter a sigil (any tile is a door)</span></div>
    <div class="key-row"><kbd>Drag</kbd><span class="key-desc">Pan around the atlas</span></div>
    <span class="section-label">Toolbar</span>
    <div class="key-row"><kbd>&#x21A9;</kbd><span class="key-desc">Back one level</span></div>
    <div class="key-row"><kbd>&#x2302;</kbd><span class="key-desc">Animated return home</span></div>
    <div class="key-row"><kbd>&#x25CE;</kbd><span class="key-desc">Start / finish exploration</span></div>
    <div class="key-row"><kbd>&#x2606;</kbd><span class="key-desc">Toggle your sigil overlay</span></div>
    <div class="dismiss">Click anywhere to begin</div>
  </div>
</div>

<script>
const canvas = document.getElementById('atlas-canvas');
const ctx = canvas.getContext('2d');
const minimapCanvas = document.getElementById('minimap');
const minimapCtx = minimapCanvas.getContext('2d');

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PREFETCH_MARGIN = 1.5;
const PREFETCH_INTERVAL = 10;

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let manifest = null;
let cam = { x: 0, y: 0, zoom: 1 };
let camTarget = { x: 0, y: 0, zoom: 1 };
let debugMode = false;

// Level stack: each entry = { level, nodes, camera, parentNode }
// viewStack[0] is always level 0 root
let viewStack = [];

// Tile cache: node_id -> { img, loaded, lastUsed }
// LRU eviction keeps memory bounded.
let tileCache = {};

// Level 0 nodes (for minimap)
let level0Nodes = [];

// Interaction
let hoveredNode = null;

// Sigil overlay
let sigilActive = false;
let sigilScores = {};       // {level: {node_id: {score, breakdown}}}
let sigilVisual = {};       // {level: {node_id: float}} rank-stretched to [0,1]
let sigilMeta = null;       // {sigil_version, collapsed_contrasts}
let sigilFetching = false;

// Node labels: descriptive text per node from z-summaries
let nodeLabels = {};        // {level: {node_id: string}}

// Z-summaries for radar chart: {level: {contrast: {node_id: {z_mean, z_std, n}}}}
let nodeZsummaries = {};
// Radar axes: curated subset of contrasts for the radar chart
const RADAR_AXES = [
  { key: 'brightness',                label: 'bright' },
  { key: 'temperature',               label: 'warm' },
  { key: 'sharpness',                 label: 'sharp' },
  { key: 'saturation',                label: 'saturated' },
  { key: 'contrast',                  label: 'contrast' },
  { key: 'texture_scale',             label: 'coarse' },
  { key: 'sem_simple_vs_complex',     label: 'complex' },
  { key: 'sem_natural_vs_manmade',    label: 'manmade' },
  { key: 'sem_closeup_vs_wide',       label: 'wide' },
  { key: 'sem_abstract_vs_representational', label: 'repr.' },
];

async function fetchZsummaries(level) {
  if (nodeZsummaries[level]) return;
  try {
    const r = await fetch(`/api/ride/stats?level=${level}`);
    if (!r.ok) return;
    const data = await r.json();
    nodeZsummaries[level] = data.zsummaries || {};
    scheduleFrame();
  } catch (e) { /* z-summaries are optional */ }
}

async function fetchNodeLabels(level) {
  if (nodeLabels[level]) return;
  try {
    const r = await fetch(`/api/atlas/node_labels?level=${level}`);
    if (!r.ok) return;
    const data = await r.json();
    nodeLabels[level] = data.labels || {};
    scheduleFrame();
  } catch (e) { /* labels are optional */ }
}

// Flythrough (silent calibration) state
let flythroughActive = false;
let flythroughVisits = [];   // [{node_id, level, timestamp}]
const MIN_FLYTHROUGH_VISITS = 5;
let doorsCache = {};  // {cacheKey: doors[]}

// Animation
let animFrameId = null;
let frameCount = 0;
let lastTickTime = 0;
let fpsCounter = { frames: 0, lastTime: 0, fps: 0 };

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

function setCameraImmediate(newCam) {
  cam.x = newCam.x;
  cam.y = newCam.y;
  cam.zoom = newCam.zoom;
  camTarget.x = newCam.x;
  camTarget.y = newCam.y;
  camTarget.zoom = newCam.zoom;
  scheduleFrame();
}

function setCameraTarget(newCam) {
  setCameraImmediate(newCam);
  scheduleFrame();
}

// ---------------------------------------------------------------------------
// Animation loop
// ---------------------------------------------------------------------------

function scheduleFrame() {
  if (animFrameId === null) {
    animFrameId = requestAnimationFrame(tick);
  }
}

function tick(timestamp) {
  animFrameId = null;
  frameCount++;

  // FPS tracking
  fpsCounter.frames++;
  if (timestamp - fpsCounter.lastTime >= 1000) {
    fpsCounter.fps = fpsCounter.frames;
    fpsCounter.frames = 0;
    fpsCounter.lastTime = timestamp;
  }

  lastTickTime = timestamp;

  updateCamera();

  if (frameCount % PREFETCH_INTERVAL === 0) {
    prefetchTiles();
  }

  draw();

  // Continue if still moving
  if (isMoving()) {
    animFrameId = requestAnimationFrame(tick);
  }
}

function isMoving() {
  return false;  // Camera is always locked; no animation loop needed
}

function updateCamera() {
  // Camera is locked to target — no lerp, no velocity
  cam.x = camTarget.x;
  cam.y = camTarget.y;
  cam.zoom = camTarget.zoom;
}

// ---------------------------------------------------------------------------
// Sigil overlay
// ---------------------------------------------------------------------------

async function fetchSigilScores(level) {
  if (sigilFetching) return;
  const cacheKey = sigilMeta ? `${sigilMeta.sigil_version}_${level}` : null;
  if (sigilScores[level] && cacheKey && sigilScores[`_key_${level}`] === cacheKey) return;

  sigilFetching = true;
  try {
    const r = await fetch(`/api/atlas/sigil_scores?user_id=default&level=${level}`);
    if (!r.ok) {
      if (r.status === 404) {
        // No sigil exists — deactivate silently
        sigilActive = false;
        updateSigilIndicator();
      }
      sigilFetching = false;
      return;
    }
    const data = await r.json();
    sigilMeta = {
      sigil_version: data.sigil_version,
      collapsed_contrasts: data.collapsed_contrasts,
    };
    sigilScores[level] = data.scores;
    sigilScores[`_key_${level}`] = `${data.sigil_version}_${level}`;
    stretchSigilScores(level);
    scheduleFrame();
  } catch (e) {
    sigilActive = false;
    updateSigilIndicator();
  }
  sigilFetching = false;
}

function stretchSigilScores(level) {
  // Rank-normalize raw scores to spread across full [0,1] visual range.
  // Raw scores stay in sigilScores for debug readout; visual scores go to sigilVisual.
  const raw = sigilScores[level];
  if (!raw) return;
  const entries = Object.entries(raw);
  if (entries.length <= 1) {
    sigilVisual[level] = {};
    for (const [nid, d] of entries) sigilVisual[level][nid] = 0.5;
    return;
  }
  const vals = entries.map(([_, d]) => d.score);
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const range = hi - lo;
  sigilVisual[level] = {};
  for (const [nid, d] of entries) {
    sigilVisual[level][nid] = range > 0.001 ? (d.score - lo) / range : 0.5;
  }
}

function updateSigilIndicator() {
  const el = document.getElementById('sigilIndicator');
  if (sigilActive) {
    el.classList.add('active');
  } else {
    el.classList.remove('active');
  }
}

// ---------------------------------------------------------------------------
// Flythrough: silent calibration via navigation
// ---------------------------------------------------------------------------

function toggleFlythrough() {
  if (!flythroughActive) {
    startFlythrough();
  } else {
    finishFlythrough();
  }
}

function startFlythrough() {
  flythroughActive = true;
  flythroughVisits = [];
  updateFlythroughIndicator();
  showFlythroughToast('Exploring. Navigate toward what attracts you.');
}

async function finishFlythrough() {
  const distinctCount = new Set(flythroughVisits.map(v => v.node_id)).size;
  if (distinctCount < MIN_FLYTHROUGH_VISITS) {
    showFlythroughToast(`Keep exploring (${distinctCount}/${MIN_FLYTHROUGH_VISITS} neighborhoods)`);
    return;
  }

  // POST visits to server
  try {
    const r = await fetch('/api/flythrough/record', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({user_id: 'default', visits: flythroughVisits}),
    });
    if (!r.ok) {
      showFlythroughToast('Error recording preferences');
      return;
    }
    const data = await r.json();

    flythroughActive = false;
    flythroughVisits = [];
    updateFlythroughIndicator();

    // Invalidate sigil caches so G overlay refreshes
    sigilScores = {};
    sigilVisual = {};

    if (data.preferences_count > 0) {
      showFlythroughToast(`${data.preferences_count} preferences recorded. Tap the star to see them.`);
    } else {
      showFlythroughToast('No clear preferences detected. Try exploring more distinctly.');
    }
  } catch (e) {
    showFlythroughToast('Error recording preferences');
  }
}

function cancelFlythrough() {
  flythroughActive = false;
  flythroughVisits = [];
  updateFlythroughIndicator();
}

function recordFlythroughVisit(node) {
  if (!flythroughActive) return;
  const lastVisit = flythroughVisits[flythroughVisits.length - 1];
  if (lastVisit && lastVisit.node_id === node.node_id) return;
  flythroughVisits.push({
    node_id: node.node_id,
    level: node.level !== undefined ? node.level : currentLevel(),
    timestamp: Date.now(),
  });
  updateFlythroughIndicator();
}

function updateFlythroughIndicator() {
  const el = document.getElementById('flythroughIndicator');
  const btn = document.getElementById('toolbar-explore');
  if (flythroughActive) {
    const count = new Set(flythroughVisits.map(v => v.node_id)).size;
    el.textContent = `Exploring (${count})`;
    el.classList.add('active');
    if (btn) btn.classList.add('active');
  } else {
    el.classList.remove('active');
    if (btn) btn.classList.remove('active');
  }
}

function showFlythroughToast(msg) {
  const el = document.getElementById('flythrough-toast');
  el.textContent = msg;
  el.classList.add('active');
  clearTimeout(el._timeout);
  el._timeout = setTimeout(() => {
    el.classList.remove('active');
  }, 4000);
}

// ---------------------------------------------------------------------------
// Tile loading & prefetching
// ---------------------------------------------------------------------------

function tilePath(node) {
  if (node.thumb_url) return node.thumb_url;
  return `/atlas_tiles/level${node.level}/${node.tile_path}`;
}

function tileCacheKey(node) {
  return node._snapshotKey || node.image_id || node.node_id;
}

function ensureTile(node) {
  const key = tileCacheKey(node);
  if (tileCache[key]) return;
  // Snapshot tiles are pre-built — just register them
  if (node._snapshotImg) {
    tileCache[key] = { img: node._snapshotImg, loaded: true };
    return;
  }
  const img = new window.Image();
  tileCache[key] = { img, loaded: false };
  img.onload = () => { tileCache[key].loaded = true; scheduleFrame(); };
  img.onerror = () => {};
  img.src = tilePath(node);
}

function captureSnapshot() {
  // Capture the current canvas as an Image for use as a back door tile
  const img = new window.Image();
  img.src = canvas.toDataURL('image/jpeg', 0.7);
  return img;
}

function prefetchTiles() {
  const cw = canvas.clientWidth, ch = canvas.clientHeight;
  const marginX = cw * (PREFETCH_MARGIN - 1) / 2;
  const marginY = ch * (PREFETCH_MARGIN - 1) / 2;
  const nodes = currentNodes();
  for (const node of nodes) {
    const [rx, ry, rw, rh] = node.rect;
    const tl = worldToScreen(rx, ry);
    const sw = rw * cam.zoom;
    const sh = rh * cam.zoom;
    if (tl.x + sw < -marginX || tl.y + sh < -marginY ||
        tl.x > cw + marginX || tl.y > ch + marginY) continue;
    ensureTile(node);
  }
}

// ---------------------------------------------------------------------------
// Drawing
// ---------------------------------------------------------------------------

function resize() {
  canvas.width = canvas.clientWidth * devicePixelRatio;
  canvas.height = canvas.clientHeight * devicePixelRatio;
  ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
  // Refit camera to fill viewport after resize
  fitOverview();
  scheduleFrame();
}

function draw() {
  const cw = canvas.clientWidth;
  const ch = canvas.clientHeight;
  ctx.clearRect(0, 0, cw, ch);
  ctx.fillStyle = '#111';
  ctx.fillRect(0, 0, cw, ch);

  const nodes = currentNodes();
  if (!nodes.length) return;

  // Gap between neighborhoods scales with zoom but stays visible
  const gap = Math.max(2, Math.min(6, cam.zoom * 0.003));

  for (const node of nodes) {
    const [rx, ry, rw, rh] = node.rect;
    const tl = worldToScreen(rx, ry);
    const sw = rw * cam.zoom;
    const sh = rh * cam.zoom;

    if (tl.x + sw < 0 || tl.y + sh < 0 || tl.x > cw || tl.y > ch) continue;

    // Inset by gap to create visible separation between neighborhoods
    const ix = tl.x + gap;
    const iy = tl.y + gap;
    const iw = Math.max(1, sw - gap * 2);
    const ih = Math.max(1, sh - gap * 2);

    ensureTile(node);
    const tc = tileCache[tileCacheKey(node)];
    if (tc && tc.loaded) {
      const imgW = tc.img.naturalWidth;
      const imgH = tc.img.naturalHeight;
      if (node.door_type === 'showcase') {
        // Full-size showcase: contain-fit, no cropping
        const scale = Math.min(iw / imgW, ih / imgH);
        const dw = imgW * scale;
        const dh = imgH * scale;
        const dx = ix + (iw - dw) / 2;
        const dy = iy + (ih - dh) / 2;
        if (dw < iw || dh < ih) {
          ctx.fillStyle = '#1a1a1a';
          ctx.fillRect(ix, iy, iw, ih);
        }
        ctx.drawImage(tc.img, 0, 0, imgW, imgH, dx, dy, dw, dh);
      } else if (node.door_type === 'member') {
        // Member in grid: cover-fit, fill cell with minor center-crop
        const scale = Math.max(iw / imgW, ih / imgH);
        const sw = iw / scale;
        const sh = ih / scale;
        const sx = (imgW - sw) / 2;
        const sy = (imgH - sh) / 2;
        ctx.drawImage(tc.img, sx, sy, sw, sh, ix, iy, iw, ih);
      } else {
        // Cover-fit: fill cell completely, center-crop excess.
        // Montage grids tolerate slight cropping; no black bars.
        const scale = Math.max(iw / imgW, ih / imgH);
        const sw = iw / scale;
        const sh = ih / scale;
        const sx = (imgW - sw) / 2;
        const sy = (imgH - sh) / 2;
        ctx.drawImage(tc.img, sx, sy, sw, sh, ix, iy, iw, ih);
      }
    } else {
      ctx.fillStyle = '#1a1a1a';
      ctx.fillRect(ix, iy, iw, ih);
    }

    // Sigil overlay: dim non-aligned, brighten aligned
    // Uses rank-stretched visual scores for perceptible contrast
    if (sigilActive) {
      const lvl = currentLevel();
      const vis = sigilVisual[lvl];
      if (vis !== undefined) {
        const vs = vis[node.node_id];
        if (vs !== undefined) {
          // Dim: stronger dimming for low-scoring nodes
          const dimAlpha = (1.0 - vs) * 0.65;
          if (dimAlpha > 0.01) {
            ctx.fillStyle = `rgba(0,0,0,${dimAlpha.toFixed(3)})`;
            ctx.fillRect(ix, iy, iw, ih);
          }
          // Halo: double-stroke amber glow for top-ranked nodes
          if (vs > 0.55) {
            const t = (vs - 0.55) / 0.45;  // 0..1 over the top half
            // Inner glow
            const innerAlpha = t * 0.7;
            ctx.strokeStyle = `rgba(255,170,0,${innerAlpha.toFixed(3)})`;
            ctx.lineWidth = Math.max(2, Math.min(5, iw * 0.012));
            ctx.strokeRect(ix + 1, iy + 1, iw - 2, ih - 2);
            // Outer glow (wider, more transparent)
            if (vs > 0.75) {
              const outerAlpha = (vs - 0.75) / 0.25 * 0.35;
              ctx.strokeStyle = `rgba(255,200,50,${outerAlpha.toFixed(3)})`;
              ctx.lineWidth = Math.max(3, Math.min(8, iw * 0.02));
              ctx.strokeRect(ix - 1, iy - 1, iw + 2, ih + 2);
            }
          }
        }
      }
    }

    // Flythrough: subtle highlight on visited nodes
    if (flythroughActive && flythroughVisits.some(v => v.node_id === node.node_id)) {
      ctx.strokeStyle = 'rgba(100,200,255,0.4)';
      ctx.lineWidth = Math.max(1, Math.min(3, iw * 0.008));
      ctx.strokeRect(ix + 1, iy + 1, iw - 2, ih - 2);
    }

    // Navigation arrow: pill badge with arrow icon
    if (iw > 30 && ih > 30 && node.door_type && node.door_type !== 'self' && node.door_type !== 'member' && node.door_type !== 'showcase') {
      ctx.save();
      const badgeSz = Math.max(16, Math.min(28, Math.min(iw, ih) * 0.18));
      const pad = 3;
      let bx, by, arrow;
      if (node.door_type === 'back') {
        bx = ix + pad; by = iy + pad; arrow = '\u2191';
      } else if (node.door_type === 'down') {
        bx = ix + iw - badgeSz - pad; by = iy + ih - badgeSz - pad; arrow = '\u2193';
      } else if (node.door_type === 'lateral') {
        bx = ix + iw - badgeSz - pad; by = iy + pad; arrow = '\u2192';
      }
      if (arrow) {
        // Dark pill background
        const r = badgeSz * 0.3;
        ctx.fillStyle = 'rgba(0,0,0,0.55)';
        ctx.beginPath();
        ctx.roundRect(bx, by, badgeSz, badgeSz, r);
        ctx.fill();
        // White arrow
        ctx.font = `bold ${badgeSz * 0.65}px system-ui`;
        ctx.fillStyle = 'rgba(255,255,255,0.9)';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(arrow, bx + badgeSz / 2, by + badgeSz / 2);
      }
      ctx.restore();
    }

    // Hover highlight: bright border when mouse is over this node
    const isHovered = hoveredNode && hoveredNode.node_id === node.node_id;
    if (isHovered) {
      ctx.strokeStyle = 'rgba(100,200,255,0.7)';
      ctx.lineWidth = Math.max(2, Math.min(4, iw * 0.01));
      ctx.strokeRect(ix, iy, iw, ih);
    }
  }

  // Radar: show for hovered node
  const radarNode = hoveredNode ? hoveredNode : null;
  if (radarNode) drawRadar(radarNode);
  drawMinimap();
  drawDebug();
}

// ---------------------------------------------------------------------------
// Radar chart: neighborhood contrast profile on hover
// ---------------------------------------------------------------------------

function drawRadar(node) {
  const lvl = currentLevel();
  const zs = nodeZsummaries[lvl];
  if (!zs) return;

  // Gather values for this node across radar axes
  const values = [];
  const labels = [];
  for (const axis of RADAR_AXES) {
    const contrastData = zs[axis.key];
    if (!contrastData) continue;
    const nodeData = contrastData[node.node_id];
    if (!nodeData) continue;
    // Clamp z_mean to [-2.5, 2.5] and normalize to [0, 1]
    const clamped = Math.max(-2.5, Math.min(2.5, nodeData.z_mean));
    values.push((clamped + 2.5) / 5.0);
    labels.push(axis.label);
  }
  if (values.length < 3) return;

  const n = values.length;
  const cw = canvas.clientWidth;
  const ch = canvas.clientHeight;

  // Position: top-left with breathing room (not crammed in corner, not covering center)
  const radius = 70;
  const centerX = radius + 40;
  const centerY = radius + 50;
  const angleStep = (2 * Math.PI) / n;
  const startAngle = -Math.PI / 2;  // 12 o'clock

  // Background disc
  ctx.save();
  ctx.globalAlpha = 0.85;
  ctx.fillStyle = '#111';
  ctx.beginPath();
  ctx.arc(centerX, centerY, radius + 30, 0, 2 * Math.PI);
  ctx.fill();
  ctx.globalAlpha = 1.0;

  // Grid rings
  ctx.strokeStyle = 'rgba(255,255,255,0.08)';
  ctx.lineWidth = 0.5;
  for (const r of [0.25, 0.5, 0.75, 1.0]) {
    ctx.beginPath();
    ctx.arc(centerX, centerY, radius * r, 0, 2 * Math.PI);
    ctx.stroke();
  }

  // Middle ring (z=0) slightly brighter
  ctx.strokeStyle = 'rgba(255,255,255,0.2)';
  ctx.lineWidth = 0.75;
  ctx.beginPath();
  ctx.arc(centerX, centerY, radius * 0.5, 0, 2 * Math.PI);
  ctx.stroke();

  // Spokes
  ctx.strokeStyle = 'rgba(255,255,255,0.06)';
  ctx.lineWidth = 0.5;
  for (let i = 0; i < n; i++) {
    const angle = startAngle + i * angleStep;
    ctx.beginPath();
    ctx.moveTo(centerX, centerY);
    ctx.lineTo(centerX + Math.cos(angle) * radius, centerY + Math.sin(angle) * radius);
    ctx.stroke();
  }

  // Data polygon
  ctx.beginPath();
  for (let i = 0; i < n; i++) {
    const angle = startAngle + i * angleStep;
    const r = values[i] * radius;
    const x = centerX + Math.cos(angle) * r;
    const y = centerY + Math.sin(angle) * r;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.closePath();
  ctx.fillStyle = 'rgba(100,200,255,0.15)';
  ctx.fill();
  ctx.strokeStyle = 'rgba(100,200,255,0.6)';
  ctx.lineWidth = 1.5;
  ctx.stroke();

  // Data points
  for (let i = 0; i < n; i++) {
    const angle = startAngle + i * angleStep;
    const r = values[i] * radius;
    const x = centerX + Math.cos(angle) * r;
    const y = centerY + Math.sin(angle) * r;
    ctx.fillStyle = 'rgba(100,200,255,0.8)';
    ctx.beginPath();
    ctx.arc(x, y, 2.5, 0, 2 * Math.PI);
    ctx.fill();
  }

  // Axis labels
  ctx.font = '10px system-ui';
  ctx.textBaseline = 'middle';
  ctx.fillStyle = 'rgba(200,200,200,0.7)';
  for (let i = 0; i < n; i++) {
    const angle = startAngle + i * angleStep;
    const lx = centerX + Math.cos(angle) * (radius + 16);
    const ly = centerY + Math.sin(angle) * (radius + 16);
    // Align text based on position
    if (Math.abs(Math.cos(angle)) < 0.3) ctx.textAlign = 'center';
    else if (Math.cos(angle) > 0) ctx.textAlign = 'left';
    else ctx.textAlign = 'right';
    ctx.fillText(labels[i], lx, ly);
  }

  // Node label below
  const lvlLabels = nodeLabels[lvl];
  const descLabel = lvlLabels ? lvlLabels[node.node_id] : node.node_id;
  ctx.font = 'bold 11px system-ui';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillStyle = 'rgba(255,255,255,0.5)';
  ctx.fillText(descLabel || node.node_id, centerX, centerY + radius + 24);

  ctx.restore();
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
    // Tint minimap rects by visual sigil score when active
    if (sigilActive && sigilVisual[0]) {
      const vs = sigilVisual[0][node.node_id];
      if (vs !== undefined) {
        const r = Math.round(42 + vs * 40);
        const g = Math.round(42 + vs * 30);
        const b = Math.round(42 - vs * 10);
        minimapCtx.fillStyle = `rgb(${r},${g},${b})`;
      } else {
        minimapCtx.fillStyle = '#2a2a2a';
      }
    } else {
      minimapCtx.fillStyle = '#2a2a2a';
    }
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

// Minimap click: navigate to clicked world position
minimapCanvas.addEventListener('click', (e) => {
  const rect = minimapCanvas.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;
  // Map minimap pixel to world coords [0,1]
  const wx = mx / 120;
  const wy = my / 120;
  // Center viewport on this world point
  const cw = canvas.clientWidth, ch = canvas.clientHeight;
  camTarget.x = cw / 2 - wx * camTarget.zoom;
  camTarget.y = ch / 2 - wy * camTarget.zoom;
  scheduleFrame();
});

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

  let html = `<b>FPS:</b> ${fpsCounter.fps}<br>`;
  html += `<b>Level:</b> ${f.level}<br>`;
  html += `<b>Stack depth:</b> ${viewStack.length}<br>`;
  html += `<b>Nodes:</b> ${f.nodes.length}<br>`;
  html += `<b>Camera:</b> x=${cam.x.toFixed(0)} y=${cam.y.toFixed(0)} z=${cam.zoom.toFixed(0)}<br>`;
  html += `<b>Target:</b> x=${camTarget.x.toFixed(0)} y=${camTarget.y.toFixed(0)} z=${camTarget.zoom.toFixed(0)}<br>`;
  html += `<b>Camera locked:</b> yes<br>`;
  html += `<b>Center:</b> (${center.x.toFixed(4)}, ${center.y.toFixed(4)})<br>`;
  html += `<b>Flythrough:</b> ${flythroughActive ? 'active' : 'off'}<br>`;

  if (f.parentNode) {
    const pn = f.parentNode;
    html += `<b>Parent:</b> ${pn.node_id} [${pn.rect.map(v => v.toFixed(3)).join(', ')}]<br>`;
    html += `<b>Parent size:</b> ${pn.size} images<br>`;
  }

  if (hoveredNode) {
    html += `<b>Hover:</b> ${hoveredNode.node_id} (${hoveredNode.size} imgs)<br>`;
  }

  html += `<b>Tile cache:</b> ${Object.keys(tileCache).length} entries<br>`;
  html += `<b>Max level:</b> ${manifest ? manifest.max_level : '?'}<br>`;

  // Sigil "why" readout
  if (sigilActive && hoveredNode) {
    const lvl = currentLevel();
    const scores = sigilScores[lvl];
    if (scores) {
      const ns = scores[hoveredNode.node_id];
      if (ns) {
        html += `<br><b>--- Sigil ---</b><br>`;
        html += `<b>Score:</b> ${ns.score.toFixed(3)}<br>`;
        for (const entry of ns.breakdown) {
          const arrow = entry.direction === 'right' ? 'HIGH' : 'LOW';
          html += `<b>${entry.contrast_name}</b>: `;
          html += `mean=${entry.node_mean.toFixed(3)} `;
          html += `norm=${entry.normalized.toFixed(2)} `;
          html += `(${arrow} x${entry.strength.toFixed(1)}) `;
          html += `= ${entry.contribution.toFixed(3)}<br>`;
        }
      }
    }
  } else if (sigilActive) {
    html += `<br><b>Sigil:</b> active (hover node for detail)<br>`;
  }

  // Flythrough debug info
  if (flythroughActive) {
    const distinctCount = new Set(flythroughVisits.map(v => v.node_id)).size;
    html += `<br><b>--- Flythrough ---</b><br>`;
    html += `<b>Visits:</b> ${flythroughVisits.length} (${distinctCount} distinct)<br>`;
    html += `<b>Ready:</b> ${distinctCount >= MIN_FLYTHROUGH_VISITS ? 'yes' : 'no'}<br>`;
  }

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
  document.getElementById('modeLabel').textContent = `L${lvl}`;
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

    // Push root frame — nodes already carry treemap rects from atlas build
    viewStack = [{
      level: 0,
      nodes: meta.nodes,
      camera: null,
      parentNode: null,
    }];

    fitOverview();
    updateBreadcrumb();
    fetchNodeLabels(0);
    fetchZsummaries(0);
    scheduleFrame();
  } catch (e) {
    document.getElementById('stats').textContent = 'Error loading atlas: ' + e.message;
  }
}

function fitOverview() {
  const cw = canvas.clientWidth;
  const ch = canvas.clientHeight;
  // Compute tight bounding rect of all current nodes
  const nodes = currentNodes();
  if (nodes.length === 0) return;
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const n of nodes) {
    if (n.rect[0] < minX) minX = n.rect[0];
    if (n.rect[1] < minY) minY = n.rect[1];
    const ex = n.rect[0] + n.rect[2];
    const ey = n.rect[1] + n.rect[3];
    if (ex > maxX) maxX = ex;
    if (ey > maxY) maxY = ey;
  }
  const bw = maxX - minX;
  const bh = maxY - minY;
  // Force square bounding box so the grid is always compact and centered.
  // Content is centered within the square; fitToRect centers the square in viewport.
  const side = Math.max(bw, bh);
  const sx = minX - (side - bw) / 2;
  const sy = minY - (side - bh) / 2;
  setCameraImmediate(fitToRect(sx, sy, side, side, cw, ch, 0));
}

function hitTest(sx, sy) {
  const w = screenToWorld(sx, sy);
  const nodes = currentNodes();
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
  // Back door: always just pops the view stack
  if (node.door_type === 'back') {
    exitToParent();
    return;
  }

  // Showcase: clicking the full-size image goes back (exits the showcase view)
  if (node.door_type === 'showcase') {
    exitToParent();
    return;
  }

  // Member image: fixed layout — back door left strip, image fills the rest
  if (node.door_type === 'member') {
    const memberSnapshot = captureSnapshot();
    const curFrame = currentFrame();
    const backNode = curFrame?.parentNode;
    const backStrip = 0.08; // 8% width for back door strip on left
    const frameTiles = [];
    // Showcase image fills space to the right of the back strip
    frameTiles.push({
      node_id: node.node_id || node.image_id,
      image_id: node.image_id,
      level: node.level,
      is_leaf: false,
      size: 1,
      tile_path: '',
      thumb_url: `/api/image/${node.image_id}/full`,
      door_type: 'showcase',
      tile_w: 1024,
      tile_h: 1024,
      rect: [backNode ? backStrip : 0, 0, backNode ? 1 - backStrip : 1, 1],
    });
    if (backNode) {
      const snapshotKey = '__snapshot_' + viewStack.length + '__';
      frameTiles.push({
        ...backNode,
        door_type: 'back',
        size: 1,
        rect: [0, 0, backStrip, backStrip],
        _snapshotKey: snapshotKey,
        _snapshotImg: memberSnapshot,
      });
    }
    viewStack.push({
      level: curFrame ? curFrame.level : 0,
      nodes: frameTiles,
      camera: null,
      parentNode: backNode || null,
    });
    fitOverview();
    updateBreadcrumb();
    updateToolbarState();
    return;
  }

  // Self tile click: don't re-enter the same node.
  // Instead, find the largest child (down door) and enter it.
  if (node.door_type === 'self') {
    const curFrame = currentFrame();
    if (curFrame) {
      const downDoors = curFrame.nodes.filter(n => n.door_type === 'down');
      if (downDoors.length > 0) {
        // Enter the largest child
        const biggest = downDoors.reduce((a, b) => (b.size || 0) > (a.size || 0) ? b : a, downDoors[0]);
        enterNode(biggest);
        return;
      }
    }
    // No children — nowhere deeper to go
    return;
  }

  // Silent calibration: record every node entry
  recordFlythroughVisit(node);

  // Capture current view as snapshot before transitioning
  const snapshot = captureSnapshot();

  const curFrame = currentFrame();

  // Fetch doors: back + down (children) + lateral (flow-neighbors)
  const level = node.level !== undefined ? node.level : currentLevel();
  const fromNode = curFrame?.parentNode?.node_id || '';
  const fromLevel = curFrame?.parentNode?.level !== undefined ? curFrame.parentNode.level : (curFrame ? curFrame.level : level);
  const r = await fetch(`/api/atlas/node/${node.node_id}/doors?level=${level}&from_node=${fromNode}&from_level=${fromLevel}`);
  const data = await r.json();

  if (!data.doors || !data.doors.length) return;

  // Determine the primary level for the new frame:
  // If there are "down" doors, the frame level is level+1
  // Otherwise (lateral only), stay at same level
  const hasDown = data.doors.some(d => d.door_type === 'down');
  const frameLevel = hasDown ? level + 1 : level;

  // Layout: back door fixed top-left, everything else in remaining space.
  // The server always returns a back door (root sigil if no from_node).
  const backDoor = data.doors.find(d => d.door_type === 'back');
  const otherDoors = data.doors.filter(d => d.door_type !== 'back');

  const totalDoorWeight = otherDoors.reduce((s, d) => s + Math.max(1, d.size || 1), 0);
  const selfWeight = Math.max(totalDoorWeight * 3, 10);

  // Build content tiles (members or self + other doors)
  let contentTiles;
  const members = data.members || [];
  if (members.length > 0) {
    const perMember = Math.max(1, Math.floor(selfWeight / members.length));
    const memberTiles = members.map(m => {
      const tw = m.thumb_w || 512;
      const th = m.thumb_h || 512;
      // Weight proportional to pixel area — wider images get wider cells
      const aspectWeight = Math.round(perMember * (tw / th));
      return {
        node_id: m.image_id,
        image_id: m.image_id,
        level: node.level,
        is_leaf: false,
        size: Math.max(1, aspectWeight),
        tile_path: '',
        thumb_url: m.thumb_url,
        door_type: 'member',
        tile_w: tw,
        tile_h: th,
      };
    });
    contentTiles = [...memberTiles, ...otherDoors];
  } else {
    const selfTile = {
      node_id: node.node_id,
      level: node.level,
      is_leaf: node.is_leaf || false,
      size: selfWeight,
      tile_path: node.tile_path || '',
      door_type: 'self',
      child_ids: node.child_ids,
      tile_w: node.tile_w,
      tile_h: node.tile_h,
    };
    contentTiles = [selfTile, ...otherDoors];
  }

  // Layout: back door gets a dedicated left strip, content fills the rest
  const backStrip = backDoor ? 0.08 : 0;
  let frameTiles = layoutAsTreemap(contentTiles, [backStrip, 0, 1 - backStrip, 1]);

  if (backDoor) {
    const snapshotKey = '__snapshot_' + viewStack.length + '__';
    frameTiles.push({
      ...backDoor,
      door_type: 'back',
      rect: [0, 0, backStrip, backStrip],
      _snapshotKey: snapshotKey,
      _snapshotImg: snapshot,
    });
  }

  viewStack.push({
    level: frameLevel,
    nodes: frameTiles,
    camera: null,
    parentNode: node,
  });

  // Snap camera to fit the door grid (fills viewport)
  fitOverview();

  updateBreadcrumb();
  updateToolbarState();

  // Fetch metadata for the new level
  if (sigilActive) {
    fetchSigilScores(frameLevel);
  }
  fetchNodeLabels(frameLevel);
  fetchZsummaries(frameLevel);
}

function layoutAsGrid(doors) {
  // Justified row layout producing a roughly square grid.
  //
  // Algorithm:
  // 1. Compute clamped aspect ratios (with layout weight support).
  // 2. Greedy row partition targeting equal row aspect sums.
  // 3. Balanced last row: if too sparse, merge with previous row.
  // 4. fitOverview forces square bounding box and centers in viewport.
  const n = doors.length;
  if (n === 0) return [];

  const ASPECT_MIN = 0.75;
  const ASPECT_MAX = 1.5;
  const aspects = doors.map(d => {
    const tw = d.tile_w || 1;
    const th = d.tile_h || 1;
    const natural = Math.max(ASPECT_MIN, Math.min(ASPECT_MAX, tw / th));
    const weight = d._layout_weight || 1.0;
    return natural * weight;
  });

  const worldW = 1.0;
  const totalAspect = aspects.reduce((s, a) => s + a, 0);

  // Target: square grid. With k equal rows: totalH = k^2/totalAspect = worldW.
  // So k = sqrt(totalAspect).
  const idealRows = Math.max(1, Math.round(Math.sqrt(totalAspect)));
  const targetRowAspect = totalAspect / idealRows;

  // Greedy partition
  const rows = [];
  let rowStart = 0;
  let rowAspectSum = 0;
  for (let i = 0; i < n; i++) {
    rowAspectSum += aspects[i];
    const remaining = n - i - 1;
    const rowsLeft = idealRows - rows.length - 1;
    if (rowAspectSum >= targetRowAspect && rowsLeft > 0 && remaining >= rowsLeft) {
      rows.push({ start: rowStart, end: i + 1, aspectSum: rowAspectSum });
      rowStart = i + 1;
      rowAspectSum = 0;
    }
  }
  if (rowStart < n) {
    rows.push({ start: rowStart, end: n, aspectSum: rowAspectSum });
  }

  // Balance: if last row aspect sum is less than half the target,
  // merge it with the previous row to prevent a disproportionately tall last row.
  while (rows.length > 1) {
    const last = rows[rows.length - 1];
    if (last.aspectSum < targetRowAspect * 0.5) {
      const prev = rows[rows.length - 2];
      prev.end = last.end;
      prev.aspectSum += last.aspectSum;
      rows.pop();
    } else {
      break;
    }
  }

  // Compute world coordinates. Each row height = worldW / rowAspectSum.
  const rowHeights = rows.map(r => r.aspectSum > 0 ? worldW / r.aspectSum : 0.1);

  const result = [];
  let y = 0;
  for (let ri = 0; ri < rows.length; ri++) {
    const row = rows[ri];
    const rh = rowHeights[ri];
    let x = 0;
    for (let i = row.start; i < row.end; i++) {
      const d = doors[i];
      const tileW = (aspects[i] / row.aspectSum) * worldW;
      const entry = {
        node_id: d.node_id,
        rect: [x, y, tileW, rh],
        level: d.level,
        is_leaf: false,
        size: d.size || 0,
        tile_path: d.tile_path || '',
        door_type: d.door_type,
        child_ids: d.child_ids,
        tile_w: d.tile_w,
        tile_h: d.tile_h,
      };
      if (d.thumb_url) entry.thumb_url = d.thumb_url;
      if (d.image_id) entry.image_id = d.image_id;
      result.push(entry);
      x += tileW;
    }
    y += rh;
  }
  return result;
}

// ---- Squarified treemap (Bruls-Huizing-van Wijk 2000) ----
// Ported from sigiltree/atlas.py. Partitions a rect into sub-rects
// with area proportional to values and aspect ratios close to 1.

function _worstRatio(areas, side) {
  if (!areas.length || side <= 0) return Infinity;
  const total = areas.reduce((s, a) => s + a, 0);
  const stripLen = total / side;
  if (stripLen <= 0) return Infinity;
  let worst = 0;
  for (const a of areas) {
    const itemSide = a / stripLen;
    if (itemSide <= 0) return Infinity;
    const r = Math.max(stripLen / itemSide, itemSide / stripLen);
    if (r > worst) worst = r;
  }
  return worst;
}

function _squarify(areas, x, y, w, h) {
  if (areas.length === 0) return [];
  if (areas.length === 1) return [[x, y, w, h]];

  const horizontal = w >= h;
  const side = Math.min(w, h);

  let strip = [areas[0]];
  let remaining = areas.slice(1);

  while (remaining.length) {
    const candidate = [...strip, remaining[0]];
    if (_worstRatio(candidate, side) <= _worstRatio(strip, side)) {
      strip = candidate;
      remaining = remaining.slice(1);
    } else {
      break;
    }
  }

  const stripTotal = strip.reduce((s, a) => s + a, 0);
  const rects = [];

  if (horizontal) {
    const stripW = h > 0 ? stripTotal / h : 0;
    let cy = y;
    for (const a of strip) {
      const rh = stripW > 0 ? a / stripW : h;
      rects.push([x, cy, stripW, rh]);
      cy += rh;
    }
    return rects.concat(_squarify(remaining, x + stripW, y, w - stripW, h));
  } else {
    const stripH = w > 0 ? stripTotal / w : 0;
    let cx = x;
    for (const a of strip) {
      const rw = stripH > 0 ? a / stripH : w;
      rects.push([cx, y, rw, stripH]);
      cx += rw;
    }
    return rects.concat(_squarify(remaining, x, y + stripH, w, h - stripH));
  }
}

function squarifiedTreemap(values, rect) {
  if (!values.length) return [];
  if (values.length === 1) return [rect];
  const [rx, ry, rw, rh] = rect;
  const total = values.reduce((s, v) => s + v, 0);
  if (total <= 0) return values.map(() => [rx, ry, rw / values.length, rh]);
  const area = rw * rh;
  const areas = values.map(v => v / total * area);
  return _squarify(areas, rx, ry, rw, rh);
}

function layoutAsTreemap(nodes, bounds) {
  const n = nodes.length;
  if (n === 0) return [];
  const weights = nodes.map(d => Math.max(1, d.size || 1));
  const rects = squarifiedTreemap(weights, bounds || [0, 0, 1, 1]);
  return nodes.map((d, i) => {
    const entry = {
      node_id: d.node_id,
      rect: rects[i],
      level: d.level,
      is_leaf: d.is_leaf || false,
      size: d.size || 0,
      tile_path: d.tile_path || '',
      door_type: d.door_type,
      child_ids: d.child_ids,
      tile_w: d.tile_w,
      tile_h: d.tile_h,
    };
    if (d.thumb_url) entry.thumb_url = d.thumb_url;
    if (d.image_id) entry.image_id = d.image_id;
    return entry;
  });
}

function exitToParent() {
  if (viewStack.length <= 1) {
    fitOverview();
    updateBreadcrumb();
    updateToolbarState();
    return;
  }

  viewStack.pop();
  fitOverview();
  updateBreadcrumb();
  updateToolbarState();
}

function popToLevel(stackIndex) {
  while (viewStack.length > stackIndex + 1) {
    viewStack.pop();
  }
  fitOverview();
  updateBreadcrumb();
  updateToolbarState();
}

// ---------------------------------------------------------------------------
// Toolbar actions
// ---------------------------------------------------------------------------

function updateToolbarState() {
  const backBtn = document.getElementById('toolbar-back');
  const homeBtn = document.getElementById('toolbar-home');
  if (backBtn) {
    backBtn.style.opacity = viewStack.length > 1 ? '1' : '0.3';
  }
  if (homeBtn) {
    homeBtn.style.opacity = viewStack.length > 1 ? '1' : '0.3';
  }
}

async function goHome() {
  if (viewStack.length <= 1) return;

  // Animated reverse: pop one level at a time with brief delay
  const popStep = () => {
    if (viewStack.length <= 1) {
      fitOverview();
      updateBreadcrumb();
      updateToolbarState();
      return;
    }
    viewStack.pop();
    fitOverview();
    updateBreadcrumb();
    updateToolbarState();
    if (viewStack.length > 1) {
      setTimeout(popStep, 300);
    }
  };
  popStep();
}

// ---------------------------------------------------------------------------
// Mouse interaction
// ---------------------------------------------------------------------------

canvas.addEventListener('mousemove', (e) => {
  // Update hovered node and cursor
  const rect = canvas.getBoundingClientRect();
  const prevHovered = hoveredNode;
  hoveredNode = hitTest(e.clientX - rect.left, e.clientY - rect.top);
  canvas.style.cursor = hoveredNode ? 'pointer' : 'default';
  if (hoveredNode !== prevHovered) scheduleFrame();
});

canvas.addEventListener('click', (e) => {
  const rect = canvas.getBoundingClientRect();
  const sx = e.clientX - rect.left;
  const sy = e.clientY - rect.top;
  const node = hitTest(sx, sy);
  if (node) {
    enterNode(node);
  }
});

// ---------------------------------------------------------------------------
// Keyboard: minimal — only debug toggle
// ---------------------------------------------------------------------------

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    exitToParent();
  } else if (e.key === '`' || e.key === 'F3') {
    debugMode = !debugMode;
    scheduleFrame();
  }
});

// ---------------------------------------------------------------------------
// Touch support
// ---------------------------------------------------------------------------

canvas.addEventListener('touchend', (e) => {
  if (e.changedTouches.length === 1) {
    const t = e.changedTouches[0];
    const rect = canvas.getBoundingClientRect();
    const sx = t.clientX - rect.left;
    const sy = t.clientY - rect.top;
    const node = hitTest(sx, sy);
    if (node) enterNode(node);
  }
});

// ---------------------------------------------------------------------------
// Help overlay
// ---------------------------------------------------------------------------

const helpOverlay = document.getElementById('help-overlay');

function showHelp() {
  helpOverlay.classList.add('active');
}
function hideHelp() {
  helpOverlay.classList.remove('active');
  sessionStorage.setItem('sigilatlas_help_seen', '1');
}
function toggleHelp() {
  if (helpOverlay.classList.contains('active')) hideHelp();
  else showHelp();
}

function toggleSigil() {
  sigilActive = !sigilActive;
  if (sigilActive) {
    fetchSigilScores(currentLevel());
  }
  updateSigilIndicator();
  const btn = document.getElementById('toolbar-sigil');
  if (btn) btn.classList.toggle('active', sigilActive);
  scheduleFrame();
}

helpOverlay.addEventListener('click', (e) => {
  if (e.target === helpOverlay || e.target.closest('#help-content')) hideHelp();
});

if (!sessionStorage.getItem('sigilatlas_help_seen')) {
  showHelp();
}

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
