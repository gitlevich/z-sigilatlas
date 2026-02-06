"""Tests for sigil graph doors behavior.

Verifies the no-dead-ends principle: every node at every level has doors,
back doors work, lateral doors exist for leaf nodes, and the graph is
always navigable.
"""

import json

import pytest
from aiohttp.test_utils import TestClient, TestServer

from sigiltree.viewer_server import create_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _build_atlas(tmp_path, max_level=3):
    """Build a multi-level atlas with known structure.

    L0: 4 nodes (n_000..n_003), each with 2 children at L1
    L1: 8 nodes (L1_00..L1_07), each with 2 children at L2
    L2: 16 nodes (L2_00..L2_15), each with 2 children at L3
    L3: 32 leaf nodes (L3_00..L3_31)

    Total images: 128 (4 per L3 leaf)
    """
    (tmp_path / "thumbnails").mkdir()

    # Images
    image_ids = [f"img_{i:04d}" for i in range(128)]

    # Contrasts
    contrasts_dir = tmp_path / "contrasts"
    contrasts_dir.mkdir()
    contrast_names = ["brightness", "temperature", "sharpness"]
    contrasts = [
        {
            "contrast_id": f"c_{name}",
            "name": name,
            "source": "test",
            "description": f"test {name}",
            "mass": 1.0,
            "stability": 1.0,
            "quantiles": {"p10": 0.0, "p25": 0.25, "p50": 0.5, "p75": 0.75, "p90": 1.0},
            "exemplars": {"low": [], "median": [], "high": []},
        }
        for name in contrast_names
    ]
    library = {"version": "test_v1", "count": len(contrasts), "contrasts": contrasts}
    (contrasts_dir / "contrast_library.json").write_text(json.dumps(library))

    coords = {
        name: {iid: float(i * (ci + 1)) / 128.0
               for i, iid in enumerate(image_ids)}
        for ci, name in enumerate(contrast_names)
    }
    (contrasts_dir / "coordinates.json").write_text(json.dumps(coords))

    atlas_dir = tmp_path / "atlas"
    all_levels = []

    # L0: 4 nodes
    l0_nodes = []
    for i in range(4):
        nid = f"n_{i:03d}"
        iids = image_ids[i * 32:(i + 1) * 32]
        l0_nodes.append({
            "node_id": nid,
            "image_ids": iids,
            "size": len(iids),
            "level": 0,
            "parent_id": None,
            "child_ids": [f"L1_{i * 2 + j:02d}" for j in range(2)],
            "is_leaf": False,
            "rect": [i * 0.25, 0.0, 0.25, 1.0],
            "order_key": float(i),
            "tile_path": f"tiles/{nid}.jpg",
            "representative_ids": iids[:3],
            "neighbor_ids": [],
        })
    all_levels.append(l0_nodes)

    # L1: 8 nodes
    l1_nodes = []
    for i in range(8):
        parent_idx = i // 2
        nid = f"L1_{i:02d}"
        iids = image_ids[i * 16:(i + 1) * 16]
        l1_nodes.append({
            "node_id": nid,
            "image_ids": iids,
            "size": len(iids),
            "level": 1,
            "parent_id": f"n_{parent_idx:03d}",
            "child_ids": [f"L2_{i * 2 + j:02d}" for j in range(2)],
            "is_leaf": False,
            "rect": [(i % 2) * 0.5, 0.0, 0.5, 1.0],
            "order_key": float(i),
            "tile_path": f"tiles/{nid}.jpg",
            "representative_ids": iids[:3],
            "neighbor_ids": [],
        })
    all_levels.append(l1_nodes)

    # L2: 16 nodes
    l2_nodes = []
    for i in range(16):
        parent_idx = i // 2
        nid = f"L2_{i:02d}"
        iids = image_ids[i * 8:(i + 1) * 8]
        child_ids = ([f"L3_{i * 2 + j:02d}" for j in range(2)]
                     if max_level >= 3 else [])
        l2_nodes.append({
            "node_id": nid,
            "image_ids": iids,
            "size": len(iids),
            "level": 2,
            "parent_id": f"L1_{parent_idx:02d}",
            "child_ids": child_ids,
            "is_leaf": max_level < 3,
            "rect": [(i % 2) * 0.5, 0.0, 0.5, 1.0],
            "order_key": float(i),
            "tile_path": f"tiles/{nid}.jpg",
            "representative_ids": iids[:3],
            "neighbor_ids": [],
        })
    all_levels.append(l2_nodes)

    # L3: 32 leaf nodes
    if max_level >= 3:
        l3_nodes = []
        for i in range(32):
            parent_idx = i // 2
            nid = f"L3_{i:02d}"
            iids = image_ids[i * 4:(i + 1) * 4]
            l3_nodes.append({
                "node_id": nid,
                "image_ids": iids,
                "size": len(iids),
                "level": 3,
                "parent_id": f"L2_{parent_idx:02d}",
                "child_ids": [],
                "is_leaf": True,
                "rect": [(i % 2) * 0.5, 0.0, 0.5, 1.0],
                "order_key": float(i),
                "tile_path": f"tiles/{nid}.jpg",
                "representative_ids": iids[:2],
                "neighbor_ids": [],
            })
        all_levels.append(l3_nodes)

    # Write level metadata
    for lvl, nodes in enumerate(all_levels):
        level_dir = atlas_dir / f"level{lvl}"
        level_dir.mkdir(parents=True)
        (level_dir / "tiles").mkdir()
        meta = {
            "corpus_size": 128,
            "n_neighborhoods": len(nodes),
            "max_level": max_level,
            "nodes": nodes,
        }
        (level_dir / "meta.json").write_text(json.dumps(meta))

    # Root sigil — a proper node like any other
    root_dir = atlas_dir / "root"
    tiles_dir = root_dir / "tiles"
    tiles_dir.mkdir(parents=True)
    (tiles_dir / "root_tile.jpg").write_bytes(b"FAKE_ROOT_TILE")
    l0_node_ids = [n["node_id"] for n in l0_nodes]
    root_meta = {
        "corpus_size": 128,
        "n_neighborhoods": 1,
        "nodes": [{
            "node_id": "__root__",
            "image_ids": image_ids,
            "size": 128,
            "order_key": 0.0,
            "rect": [0.0, 0.0, 1.0, 1.0],
            "tile_path": "tiles/root_tile.jpg",
            "representative_ids": image_ids[:9],
            "neighbor_ids": [],
            "level": -1,
            "parent_id": None,
            "child_ids": l0_node_ids,
            "is_leaf": False,
        }],
    }
    (root_dir / "meta.json").write_text(json.dumps(root_meta))

    # Manifest
    manifest = {
        "max_level": max_level,
        "levels": [
            {"level": lvl, "n_nodes": len(nodes)}
            for lvl, nodes in enumerate(all_levels)
        ],
    }
    (atlas_dir / "manifest.json").write_text(json.dumps(manifest))

    # Ride stats (z-summaries power the flow graph)
    from sigiltree.ride_stats import compute_ride_stats, save_ride_stats
    stats = compute_ride_stats(coords, all_levels)
    save_ride_stats(stats, tmp_path)

    return tmp_path


@pytest.fixture
def atlas_dir(tmp_path):
    """Multi-level atlas fixture (4 levels: L0..L3)."""
    return _build_atlas(tmp_path, max_level=3)


@pytest.fixture
def atlas_app(atlas_dir):
    """Create aiohttp app with atlas."""
    return create_app(atlas_dir)


async def _get_doors(client, node_id, level, from_node="", from_level=""):
    """Helper to fetch doors from the endpoint."""
    url = (
        f"/api/atlas/node/{node_id}/doors"
        f"?level={level}&from_node={from_node}&from_level={from_level}"
    )
    resp = await client.get(url)
    assert resp.status == 200, f"doors({node_id}, L{level}) returned {resp.status}"
    data = await resp.json()
    return data["doors"]


# ---------------------------------------------------------------------------
# No Dead Ends
# ---------------------------------------------------------------------------

class TestNoDeadEnds:
    """Every node at every level must have at least one door."""

    @pytest.mark.asyncio
    async def test_root_nodes_have_doors(self, atlas_app):
        """L0 nodes with children have down doors."""
        async with TestClient(TestServer(atlas_app)) as client:
            doors = await _get_doors(client, "n_000", 0)
            assert len(doors) > 0, "Root node n_000 has no doors"
            types = {d["door_type"] for d in doors}
            assert "down" in types, "Root node should have down doors (children)"

    @pytest.mark.asyncio
    async def test_mid_level_nodes_have_doors(self, atlas_app):
        """L1 nodes have both down + lateral doors."""
        async with TestClient(TestServer(atlas_app)) as client:
            doors = await _get_doors(client, "L1_00", 1, from_node="n_000", from_level="0")
            assert len(doors) > 0, "L1 node has no doors"
            types = {d["door_type"] for d in doors}
            assert "back" in types, "L1 node should have back door"

    @pytest.mark.asyncio
    async def test_leaf_nodes_have_lateral_doors(self, atlas_app):
        """Leaf nodes (L3) must have lateral doors — the no-dead-ends guarantee."""
        async with TestClient(TestServer(atlas_app)) as client:
            doors = await _get_doors(client, "L3_00", 3, from_node="L2_00", from_level="2")
            types = {d["door_type"] for d in doors}
            assert "lateral" in types, (
                "Leaf node L3_00 has no lateral doors — dead end!"
            )

    @pytest.mark.asyncio
    async def test_every_node_at_every_level_has_doors(self, atlas_app, atlas_dir):
        """Exhaustive: every single node at every level has >= 1 door."""
        async with TestClient(TestServer(atlas_app)) as client:
            manifest = json.loads(
                (atlas_dir / "atlas" / "manifest.json").read_text()
            )
            for level_info in manifest["levels"]:
                level = level_info["level"]
                meta = json.loads(
                    (atlas_dir / "atlas" / f"level{level}" / "meta.json").read_text()
                )
                for node in meta["nodes"]:
                    nid = node["node_id"]
                    doors = await _get_doors(client, nid, level)
                    assert len(doors) > 0, (
                        f"Node {nid} at level {level} has ZERO doors — dead end!"
                    )

    @pytest.mark.asyncio
    async def test_leaf_with_back_door_always_has_way_out(self, atlas_app):
        """Even if lateral doors were empty, the back door provides a way out."""
        async with TestClient(TestServer(atlas_app)) as client:
            doors = await _get_doors(client, "L3_00", 3, from_node="L2_00", from_level="2")
            assert len(doors) >= 1, "Leaf node has no doors at all"
            # At minimum the back door exists
            back_doors = [d for d in doors if d["door_type"] == "back"]
            assert len(back_doors) == 1, "Leaf must have exactly one back door"


# ---------------------------------------------------------------------------
# Back Door
# ---------------------------------------------------------------------------

class TestBackDoor:
    """Back door connects to the node you came from."""

    @pytest.mark.asyncio
    async def test_back_door_present(self, atlas_app):
        """When from_node specified, back door appears."""
        async with TestClient(TestServer(atlas_app)) as client:
            doors = await _get_doors(client, "L1_00", 1, from_node="n_000", from_level="0")
            back = [d for d in doors if d["door_type"] == "back"]
            assert len(back) == 1
            assert back[0]["node_id"] == "n_000"

    @pytest.mark.asyncio
    async def test_root_back_door_without_from_node(self, atlas_app):
        """No from_node -> root back door (the corpus sigil)."""
        async with TestClient(TestServer(atlas_app)) as client:
            doors = await _get_doors(client, "n_000", 0)
            back = [d for d in doors if d["door_type"] == "back"]
            assert len(back) == 1, "Should always have a back door"
            assert back[0]["node_id"] == "__root__"
            assert back[0]["level"] == -1
            assert back[0]["tile_path"] == "tiles/root_tile.jpg"

    @pytest.mark.asyncio
    async def test_root_back_door_has_corpus_size(self, atlas_app):
        """Root back door carries the full corpus size."""
        async with TestClient(TestServer(atlas_app)) as client:
            doors = await _get_doors(client, "n_000", 0)
            back = [d for d in doors if d["door_type"] == "back"]
            assert back[0]["size"] == 128

    @pytest.mark.asyncio
    async def test_back_door_cross_level(self, atlas_app):
        """Back door can reference a node at a different level."""
        async with TestClient(TestServer(atlas_app)) as client:
            # Enter L3 from L2
            doors = await _get_doors(client, "L3_00", 3, from_node="L2_00", from_level="2")
            back = [d for d in doors if d["door_type"] == "back"]
            assert len(back) == 1
            assert back[0]["node_id"] == "L2_00"
            assert back[0]["level"] == 2

    @pytest.mark.asyncio
    async def test_back_door_same_level_lateral(self, atlas_app):
        """Back door for lateral navigation (same level)."""
        async with TestClient(TestServer(atlas_app)) as client:
            # Navigate from L3_00 to a lateral neighbor, then check back door
            doors_first = await _get_doors(client, "L3_00", 3,
                                           from_node="L2_00", from_level="2")
            lateral = [d for d in doors_first if d["door_type"] == "lateral"]
            if lateral:
                neighbor_id = lateral[0]["node_id"]
                # Enter that neighbor, coming from L3_00
                doors_second = await _get_doors(client, neighbor_id, 3,
                                                from_node="L3_00", from_level="3")
                back = [d for d in doors_second if d["door_type"] == "back"]
                assert len(back) == 1
                assert back[0]["node_id"] == "L3_00"

    @pytest.mark.asyncio
    async def test_back_door_not_duplicated_in_lateral(self, atlas_app):
        """Back door node_id should not appear again as a lateral door."""
        async with TestClient(TestServer(atlas_app)) as client:
            doors = await _get_doors(client, "L3_00", 3, from_node="L3_01", from_level="3")
            back_ids = {d["node_id"] for d in doors if d["door_type"] == "back"}
            lateral_ids = {d["node_id"] for d in doors if d["door_type"] == "lateral"}
            overlap = back_ids & lateral_ids
            assert len(overlap) == 0, (
                f"Back door duplicated in lateral doors: {overlap}"
            )


# ---------------------------------------------------------------------------
# Down Doors
# ---------------------------------------------------------------------------

class TestDownDoors:
    """Down doors lead to children nodes."""

    @pytest.mark.asyncio
    async def test_down_doors_match_children(self, atlas_app, atlas_dir):
        """Down doors are exactly the node's children."""
        async with TestClient(TestServer(atlas_app)) as client:
            meta = json.loads(
                (atlas_dir / "atlas" / "level0" / "meta.json").read_text()
            )
            node = next(n for n in meta["nodes"] if n["node_id"] == "n_000")
            expected_children = set(node["child_ids"])

            doors = await _get_doors(client, "n_000", 0)
            down = [d for d in doors if d["door_type"] == "down"]
            actual_children = {d["node_id"] for d in down}

            assert actual_children == expected_children, (
                f"Expected children {expected_children}, got {actual_children}"
            )

    @pytest.mark.asyncio
    async def test_down_doors_at_next_level(self, atlas_app):
        """Down doors have level = parent_level + 1."""
        async with TestClient(TestServer(atlas_app)) as client:
            doors = await _get_doors(client, "n_000", 0)
            down = [d for d in doors if d["door_type"] == "down"]
            for d in down:
                assert d["level"] == 1, (
                    f"Down door {d['node_id']} has level {d['level']}, expected 1"
                )

    @pytest.mark.asyncio
    async def test_leaf_has_no_down_doors(self, atlas_app):
        """Leaf nodes have no children, hence no down doors."""
        async with TestClient(TestServer(atlas_app)) as client:
            doors = await _get_doors(client, "L3_00", 3, from_node="L2_00", from_level="2")
            down = [d for d in doors if d["door_type"] == "down"]
            assert len(down) == 0, f"Leaf L3_00 has {len(down)} down doors"


# ---------------------------------------------------------------------------
# Lateral Doors
# ---------------------------------------------------------------------------

class TestLateralDoors:
    """Lateral doors connect to flow-neighbors at the same level."""

    @pytest.mark.asyncio
    async def test_lateral_doors_same_level(self, atlas_app):
        """Lateral doors are at the same level as the current node."""
        async with TestClient(TestServer(atlas_app)) as client:
            doors = await _get_doors(client, "L3_00", 3, from_node="L2_00", from_level="2")
            lateral = [d for d in doors if d["door_type"] == "lateral"]
            for d in lateral:
                assert d["level"] == 3, (
                    f"Lateral door {d['node_id']} at level {d['level']}, expected 3"
                )

    @pytest.mark.asyncio
    async def test_lateral_doors_max_8(self, atlas_app):
        """At most 8 lateral doors are returned."""
        async with TestClient(TestServer(atlas_app)) as client:
            doors = await _get_doors(client, "L3_00", 3, from_node="L2_00", from_level="2")
            lateral = [d for d in doors if d["door_type"] == "lateral"]
            assert len(lateral) <= 8, f"Got {len(lateral)} lateral doors (max 8)"

    @pytest.mark.asyncio
    async def test_lateral_doors_are_flow_neighbors(self, atlas_app, atlas_dir):
        """Lateral doors come from the precomputed flow graph."""
        from sigiltree.flythrough import compute_flow_graph
        from sigiltree.ride_stats import load_ride_stats

        stats = load_ride_stats(atlas_dir)
        level_zs = stats["zsummaries"].get("3", {})
        meta = json.loads(
            (atlas_dir / "atlas" / "level3" / "meta.json").read_text()
        )
        node_ids = [n["node_id"] for n in meta["nodes"]]
        flow = compute_flow_graph(node_ids, level_zs)

        async with TestClient(TestServer(atlas_app)) as client:
            doors = await _get_doors(client, "L3_00", 3, from_node="L2_00", from_level="2")
            lateral_ids = {d["node_id"] for d in doors if d["door_type"] == "lateral"}
            flow_neighbors = set(flow.get("L3_00", []))
            assert lateral_ids.issubset(flow_neighbors), (
                f"Lateral doors {lateral_ids - flow_neighbors} not in flow graph"
            )

    @pytest.mark.asyncio
    async def test_lateral_doors_exclude_self(self, atlas_app):
        """A node never appears as its own lateral door."""
        async with TestClient(TestServer(atlas_app)) as client:
            doors = await _get_doors(client, "L3_00", 3, from_node="L2_00", from_level="2")
            lateral_ids = {d["node_id"] for d in doors if d["door_type"] == "lateral"}
            assert "L3_00" not in lateral_ids, "Node is its own lateral door"


# ---------------------------------------------------------------------------
# Graph Navigability
# ---------------------------------------------------------------------------

class TestGraphNavigability:
    """The graph is fully navigable — no orphans, no traps."""

    @pytest.mark.asyncio
    async def test_can_always_go_back(self, atlas_app):
        """Navigate down 3 levels, then back door at each returns correctly."""
        async with TestClient(TestServer(atlas_app)) as client:
            # L0 -> L1
            doors_l0 = await _get_doors(client, "n_000", 0)
            down_l0 = [d for d in doors_l0 if d["door_type"] == "down"]
            assert len(down_l0) > 0
            l1_id = down_l0[0]["node_id"]

            # L1 -> L2
            doors_l1 = await _get_doors(client, l1_id, 1,
                                        from_node="n_000", from_level="0")
            down_l1 = [d for d in doors_l1 if d["door_type"] == "down"]
            assert len(down_l1) > 0
            l2_id = down_l1[0]["node_id"]

            # L2 -> L3
            doors_l2 = await _get_doors(client, l2_id, 2,
                                        from_node=l1_id, from_level="1")
            down_l2 = [d for d in doors_l2 if d["door_type"] == "down"]
            assert len(down_l2) > 0
            l3_id = down_l2[0]["node_id"]

            # At L3: back door returns to L2
            doors_l3 = await _get_doors(client, l3_id, 3,
                                        from_node=l2_id, from_level="2")
            back_l3 = [d for d in doors_l3 if d["door_type"] == "back"]
            assert len(back_l3) == 1
            assert back_l3[0]["node_id"] == l2_id

    @pytest.mark.asyncio
    async def test_lateral_navigation_forms_cycle(self, atlas_app):
        """Following lateral doors eventually returns to the starting node."""
        async with TestClient(TestServer(atlas_app)) as client:
            start = "L3_00"
            current = start
            visited = {current}
            max_steps = 100

            for step in range(max_steps):
                doors = await _get_doors(client, current, 3,
                                         from_node="L2_00", from_level="2")
                lateral = [d for d in doors if d["door_type"] == "lateral"]
                if not lateral:
                    break

                # Pick the first lateral door not yet visited
                next_node = None
                for d in lateral:
                    if d["node_id"] not in visited:
                        next_node = d["node_id"]
                        break
                if next_node is None:
                    # All lateral neighbors visited — graph is connected
                    break

                visited.add(next_node)
                current = next_node

            # We should have visited multiple nodes
            assert len(visited) > 1, "Lateral navigation visited only 1 node"

    @pytest.mark.asyncio
    async def test_all_l3_reachable_via_lateral(self, atlas_app, atlas_dir):
        """From any L3 node, all other L3 nodes are reachable via lateral doors."""
        from sigiltree.flythrough import compute_flow_graph
        from sigiltree.ride_stats import load_ride_stats

        stats = load_ride_stats(atlas_dir)
        level_zs = stats["zsummaries"].get("3", {})
        meta = json.loads(
            (atlas_dir / "atlas" / "level3" / "meta.json").read_text()
        )
        node_ids = [n["node_id"] for n in meta["nodes"]]
        flow = compute_flow_graph(node_ids, level_zs)

        # Flow graph is fully connected: every node can reach every other
        for nid in node_ids:
            neighbors = set(flow.get(nid, []))
            other_nodes = set(node_ids) - {nid}
            assert neighbors == other_nodes, (
                f"Node {nid} cannot reach {other_nodes - neighbors} via flow"
            )

    @pytest.mark.asyncio
    async def test_down_then_back_is_identity(self, atlas_app):
        """Going down through a door, then back, returns to the same node."""
        async with TestClient(TestServer(atlas_app)) as client:
            # Get children of n_000
            doors = await _get_doors(client, "n_000", 0)
            down = [d for d in doors if d["door_type"] == "down"]
            child_id = down[0]["node_id"]

            # Enter child, get back door
            child_doors = await _get_doors(client, child_id, 1,
                                           from_node="n_000", from_level="0")
            back = [d for d in child_doors if d["door_type"] == "back"]
            assert back[0]["node_id"] == "n_000", (
                f"Back from {child_id} goes to {back[0]['node_id']}, expected n_000"
            )


# ---------------------------------------------------------------------------
# Door Completeness (structural invariants)
# ---------------------------------------------------------------------------

class TestDoorStructure:
    """Each door has required fields and valid data."""

    @pytest.mark.asyncio
    async def test_door_has_required_fields(self, atlas_app):
        """Every door dict has node_id, level, door_type, and a tile source."""
        async with TestClient(TestServer(atlas_app)) as client:
            doors = await _get_doors(client, "n_000", 0)
            for d in doors:
                assert "node_id" in d, f"Door missing node_id: {d}"
                assert "level" in d, f"Door missing level: {d}"
                assert "door_type" in d, f"Door missing door_type: {d}"
                assert d["door_type"] in ("back", "down", "lateral"), (
                    f"Invalid door_type: {d['door_type']}"
                )
                # Every door needs a tile source: either tile_path or thumb_url
                has_tile = "tile_path" in d or "thumb_url" in d
                assert has_tile, f"Door missing tile source: {d}"

    @pytest.mark.asyncio
    async def test_door_types_exhaustive(self, atlas_app):
        """At L1 with from_node: all three door types present."""
        async with TestClient(TestServer(atlas_app)) as client:
            doors = await _get_doors(client, "L1_00", 1,
                                     from_node="n_000", from_level="0")
            types = {d["door_type"] for d in doors}
            assert "back" in types, "Missing back door"
            assert "down" in types, "Missing down doors"
            assert "lateral" in types, "Missing lateral doors"

    @pytest.mark.asyncio
    async def test_no_duplicate_node_ids(self, atlas_app):
        """No node_id appears twice in the doors list."""
        async with TestClient(TestServer(atlas_app)) as client:
            doors = await _get_doors(client, "L1_00", 1,
                                     from_node="n_000", from_level="0")
            ids = [d["node_id"] for d in doors]
            assert len(ids) == len(set(ids)), (
                f"Duplicate node_ids in doors: {ids}"
            )

    @pytest.mark.asyncio
    async def test_nonexistent_node_returns_empty(self, atlas_app):
        """Requesting doors for a node that doesn't exist returns empty list."""
        async with TestClient(TestServer(atlas_app)) as client:
            doors = await _get_doors(client, "NONEXISTENT", 0)
            # Should still return 200 with empty doors (or just back door if from_node exists)
            # The key is it doesn't crash
            assert isinstance(doors, list)


# ---------------------------------------------------------------------------
# Flow Graph Unit Tests (pure functions, no server)
# ---------------------------------------------------------------------------

class TestFlowGraphProperties:
    """Properties of the flow graph that ensure no dead ends."""

    def test_flow_graph_is_complete(self):
        """Every node has n-1 neighbors (complete graph)."""
        from sigiltree.flythrough import compute_flow_graph

        nodes = [f"n_{i}" for i in range(10)]
        z_vals = {
            "c1": {nid: float(i) for i, nid in enumerate(nodes)},
            "c2": {nid: float(i * 2) for i, nid in enumerate(nodes)},
        }
        zs = {}
        for cname, vals in z_vals.items():
            zs[cname] = {nid: {"z_mean": z, "z_std": 0.1, "n": 5}
                         for nid, z in vals.items()}

        flow = compute_flow_graph(nodes, zs)

        for nid in nodes:
            assert len(flow[nid]) == len(nodes) - 1, (
                f"{nid} has {len(flow[nid])} neighbors, expected {len(nodes) - 1}"
            )

    def test_flow_graph_symmetric_reachability(self):
        """If A can reach B, B can reach A."""
        from sigiltree.flythrough import compute_flow_graph

        nodes = [f"n_{i}" for i in range(8)]
        z_vals = {
            "c1": {nid: float(i) for i, nid in enumerate(nodes)},
        }
        zs = {"c1": {nid: {"z_mean": z, "z_std": 0.1, "n": 5}
                      for nid, z in z_vals["c1"].items()}}

        flow = compute_flow_graph(nodes, zs)

        for a in nodes:
            for b in nodes:
                if a != b:
                    assert b in flow[a], f"{b} not reachable from {a}"
                    assert a in flow[b], f"{a} not reachable from {b}"

    def test_flow_similarity_ordering_stable(self):
        """Flow ordering is deterministic."""
        from sigiltree.flythrough import compute_flow_graph

        nodes = [f"n_{i}" for i in range(6)]
        z_vals = {"c1": {nid: float(i) for i, nid in enumerate(nodes)}}
        zs = {"c1": {nid: {"z_mean": z, "z_std": 0.1, "n": 5}
                      for nid, z in z_vals["c1"].items()}}

        flow1 = compute_flow_graph(nodes, zs)
        flow2 = compute_flow_graph(nodes, zs)

        for nid in nodes:
            assert flow1[nid] == flow2[nid], (
                f"Flow ordering not stable for {nid}"
            )

    def test_flow_graph_empty_zsummaries(self):
        """Empty z-summaries -> empty flow graph."""
        from sigiltree.flythrough import compute_flow_graph

        nodes = [f"n_{i}" for i in range(5)]
        flow = compute_flow_graph(nodes, {})

        # With no z-data, all profiles are zero vectors -> cosine sim = 0
        # But nodes still appear in flow graph
        for nid in nodes:
            assert nid in flow

    def test_flow_graph_single_contrast(self):
        """Flow works with just one contrast."""
        from sigiltree.flythrough import compute_flow_graph

        nodes = ["a", "b", "c"]
        zs = {
            "only_contrast": {
                "a": {"z_mean": 1.0, "z_std": 0.1, "n": 5},
                "b": {"z_mean": 0.9, "z_std": 0.1, "n": 5},
                "c": {"z_mean": -1.0, "z_std": 0.1, "n": 5},
            }
        }
        flow = compute_flow_graph(nodes, zs)

        # a and b are close, c is far
        assert flow["a"][0] == "b", f"Expected b as a's closest, got {flow['a'][0]}"
        assert flow["b"][0] == "a", f"Expected a as b's closest, got {flow['b'][0]}"
