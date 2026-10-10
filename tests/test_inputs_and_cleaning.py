import json
import math
from xml.etree.ElementTree import Element, SubElement, ElementTree

import geopandas as gpd
import networkx as nx
import osmnx as ox
import pytest
from shapely import from_wkt
from shapely.geometry import box

from georesilience.config import RunConfig, load_config
from georesilience.network import EXTRA_WAY_TAGS, load_and_clean
from georesilience.pipeline import run


def junction_graph():
    graph = nx.MultiDiGraph(crs="EPSG:32644", simplified=True)
    coords = [(499995, 1900005), (500005, 1900005), (500005, 1899995),
              (499995, 1899995), (499900, 1900005), (500005, 1900100),
              (500100, 1899995), (499995, 1899900)]
    for node, (x, y) in enumerate(coords):
        graph.add_node(node, x=x, y=y)
    for way, (u, v) in enumerate([(0, 1), (1, 2), (2, 3), (3, 0),
                                 (0, 4), (1, 5), (2, 6), (3, 7)]):
        length = math.dist(coords[u], coords[v])
        for a, b in [(u, v), (v, u)]:
            graph.add_edge(a, b, osmid=way, length=length, highway="residential")
    return graph


def graph_config(tmp_path, graph, **kwargs):
    path = tmp_path / "network.graphml"
    ox.save_graphml(graph, filepath=path)
    return RunConfig(input={"source": "graphml", "path": path},
                     output={"dir": tmp_path / "results", "figures": False}, **kwargs)


def xml_fixture(path):
    root = Element("osm", version="0.6", generator="georesilience-test")
    # Each way has a separate pair of nodes so filtering can be checked exactly.
    tags = [{"highway": "footway"}, {"highway": "service"},
            {"highway": "residential", "access": "private"},
            {"highway": "residential"}, {"highway": "residential", "area": "yes"},
            {"highway": "residential", "motor_vehicle": "no"},
            {"highway": "residential", "motorcar": "no"}]
    for i, attrs in enumerate(tags):
        for j in (0, 1):
            SubElement(root, "node", id=str(i * 2 + j + 1),
                       lon=str(78.47 + j * 0.001), lat=str(17.40 + i * 0.001))
        way = SubElement(root, "way", id=str(100 + i))
        for j in (0, 1):
            SubElement(way, "nd", ref=str(i * 2 + j + 1))
        for key, value in attrs.items():
            SubElement(way, "tag", k=key, v=value)
    ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return path


def test_xml_drive_filter_and_metadata(tmp_path):
    path = xml_fixture(tmp_path / "roads.osm")
    config = RunConfig(input={"source": "osm_xml", "path": path},
                       cleaning={"consolidate": False},
                       output={"dir": tmp_path / "results", "figures": False})
    summary = run(config)
    edges = gpd.read_file(tmp_path / "results/network.gpkg", layer="edges")
    assert edges.osm_way_ids.tolist() == ["103"]
    assert summary["cleaning"]["raw"]["link_count"] == 7
    assert summary["cleaning"]["filtered"]["link_count"] == 1
    assert summary["meta"]["network_type_applied"] == "drive"
    assert summary["meta"]["osm_download_utc"] is None
    assert summary["meta"]["study_boundary_wkt"] is None
    assert set(EXTRA_WAY_TAGS) <= set(ox.settings.useful_tags_way)


def test_other_xml_type_is_as_provided(tmp_path, capsys):
    path = xml_fixture(tmp_path / "roads.osm")
    _, meta, stats = load_and_clean(RunConfig(
        input={"source": "osm_xml", "path": path}, network={"type": "walk"},
        cleaning={"consolidate": False}))
    assert meta["network_type_applied"] == "as-provided"
    assert stats["simplified"]["link_count"] == 7
    assert "keeping as-provided" in capsys.readouterr().err


@pytest.mark.parametrize("consolidate, node_count", [(True, 5), (False, 8)])
def test_dual_carriageway_consolidation(tmp_path, consolidate, node_count):
    config = graph_config(tmp_path, junction_graph(), cleaning={"consolidate": consolidate})
    graph, meta, stats = load_and_clean(config)
    assert len(graph) == node_count
    if consolidate:
        degrees = dict(nx.Graph(graph).degree())
        assert sorted(degrees.values()) == [1, 1, 1, 1, 4]
    assert stats["dead_ends"] == {"before": 4, "after": 4}
    assert meta["network_type_applied"] == "as-provided"


def test_dead_end_guard_is_wired_into_real_consolidation(tmp_path):
    graph = junction_graph()
    # This cul-de-sac ends inside the junction's tolerance cluster. Even with
    # dead_ends=True, rebuilding contracts its edge and removes its degree-1 node.
    graph.add_node(8, x=499990, y=1900010)
    for u, v in ((0, 8), (8, 0)):
        graph.add_edge(u, v, length=7.1, osmid=99)
    config = graph_config(tmp_path, graph)
    with pytest.raises(ValueError, match="degree-1 node count changed"):
        load_and_clean(config)


def test_scc_report_and_gpkg_agree(tmp_path):
    graph = junction_graph()
    graph.add_node(100, x=501000, y=1900000)
    graph.add_node(101, x=501100, y=1900000)
    for u, v in ((100, 101), (101, 100)):
        graph.add_edge(u, v, length=100, osmid=100)
    # A one-way tail belongs to the same weak component but must be dropped.
    graph.add_node(102, x=502000, y=1900000)
    graph.add_edge(4, 102, length=1000, osmid=101)
    config = graph_config(tmp_path, graph, cleaning={"consolidate": False})
    summary = run(config)
    stats = summary["cleaning"]
    assert stats["dropped_components"]["count"] == 2
    assert stats["dropped_components"]["nodes_dropped"] == 3
    assert stats["dropped_components"]["length_dropped_km"] == pytest.approx(1.1)
    nodes = gpd.read_file(config.output.dir / "network.gpkg", layer="nodes")
    edges = gpd.read_file(config.output.dir / "network.gpkg", layer="edges")
    assert stats["final"]["node_count"] == len(nodes) == summary["meta"]["node_count"]
    assert stats["final"]["link_count"] == len(edges) == summary["meta"]["link_count"]
    assert stats["final"]["total_length_km"] == pytest.approx(edges.length_m.sum() / 1000)
    report = (config.output.dir / "report.txt").read_text()
    for name in ("Cleaning", "raw", "simplified", "consolidated", "final",
                 "check boundary clipping / one-way slivers", "buffered download is planned"):
        assert name in report
    assert report.isascii()
    assert max(map(len, report.splitlines())) <= 100
    assert json.loads((config.output.dir / "summary.json").read_text()) == json.loads(json.dumps(summary))
    # The resolved config contains output-only versions; it must be reusable.
    resolved = load_config(config.output.dir / "run_config.yaml")
    repeat = run(resolved, out_override=tmp_path / "repeat")
    summary["meta"].pop("timestamp_utc")
    repeat["meta"].pop("timestamp_utc")
    # Runtime measurements vary between runs; metric values must reproduce.
    summary["metrics"].pop("runtime_seconds")
    repeat["metrics"].pop("runtime_seconds")
    assert summary == repeat


def test_simplification_reports_real_raw_counts(tmp_path):
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    for node in range(3):
        graph.add_node(node, x=78.47 + node * 0.001, y=17.40)
    for u, v in ((0, 1), (1, 2)):
        graph.add_edge(u, v, length=100, osmid=1)
        graph.add_edge(v, u, length=100, osmid=1)
    _, _, stats = load_and_clean(graph_config(tmp_path, graph, cleaning={"consolidate": False}))
    assert stats["raw"] == {"node_count": 3, "link_count": 2, "total_length_km": 0.2}
    assert stats["simplified"] == {"node_count": 2, "link_count": 1, "total_length_km": 0.2}


@pytest.mark.parametrize("data, message", [
    ({"source": "place"}, "input.place"),
    ({"source": "polygon"}, "input.path"),
    ({"source": "bbox", "bbox": [78.47, 17.40, 78.48, 100]}, "WGS84"),
    ({"source": "bbox", "bbox": [78.5, 17.4, 78.4, 17.5]}, "WGS84"),
])
def test_source_validation(data, message):
    with pytest.raises(ValueError, match=message):
        RunConfig(input=data)


@pytest.mark.parametrize("source", ["place", "polygon", "bbox"])
def test_download_dispatch_and_boundary(tmp_path, monkeypatch, source):
    boundary = box(78.47, 17.40, 78.48, 17.41)
    frame = gpd.GeoDataFrame(
        geometry=[box(78.47, 17.40, 78.475, 17.41), box(78.475, 17.40, 78.48, 17.41)],
        crs=4326,
    )
    path = tmp_path / "boundary.geojson"
    frame.to_crs(32644).to_file(path, driver="GeoJSON")
    data = {"source": source}
    data.update({"place": "test area"} if source == "place" else
                {"path": path} if source == "polygon" else {"bbox": list(boundary.bounds)})
    seen = {}
    def loader(*args, **kwargs):
        assert set(EXTRA_WAY_TAGS) <= set(ox.settings.useful_tags_way)
        seen.update(kwargs)
        return junction_graph()
    monkeypatch.setattr(ox, f"graph_from_{source}", loader)
    monkeypatch.setattr(ox, "geocode_to_gdf", lambda _: frame)
    _, meta, _ = load_and_clean(RunConfig(input=data, network={"custom_filter": '["highway"]'}))
    assert from_wkt(meta["study_boundary_wkt"]).hausdorff_distance(boundary) < 1e-8
    assert meta["osm_download_utc"]
    assert meta["network_type_applied"] == "custom_filter"
    assert seen["network_type"] == "drive"
    assert seen["custom_filter"] == '["highway"]'
    assert seen["retain_all"] is True
    if source == "bbox":
        assert seen["bbox"] == tuple(boundary.bounds)


def test_road_line_input_is_rejected_before_download(tmp_path):
    from shapely.geometry import LineString
    path = tmp_path / "roads.geojson"
    gpd.GeoDataFrame(geometry=[LineString([(78.47, 17.40), (78.48, 17.41)])], crs=4326).to_file(
        path, driver="GeoJSON")
    with pytest.raises(ValueError, match="expected boundary polygons"):
        load_and_clean(RunConfig(input={"source": "polygon", "path": path}))


@pytest.mark.network
@pytest.mark.parametrize("source", ["place", "polygon", "bbox"])
def test_live_small_area_sources(tmp_path, source):
    boundary = box(78.469, 17.399, 78.479, 17.409)
    data = {"source": source}
    if source == "place":
        data["place"] = "Piedmont, California, USA"
    elif source == "bbox":
        data["bbox"] = list(boundary.bounds)
    else:
        path = tmp_path / "boundary.gpkg"
        gpd.GeoDataFrame(geometry=[boundary], crs=4326).to_file(path, driver="GPKG")
        data["path"] = path
    summary = run(RunConfig(input=data, cleaning={"consolidate": False},
                            output={"dir": tmp_path / "results", "figures": False}))
    assert summary["meta"]["node_count"] > 1
    assert summary["meta"]["network_type_applied"] == "drive"
    assert summary["meta"]["study_boundary_wkt"]


def test_point_only_place_has_actionable_error(monkeypatch):
    def point_only(_):
        raise TypeError("Nominatim did not geocode query to a polygon")
    monkeypatch.setattr(ox, "geocode_to_gdf", point_only)
    with pytest.raises(ValueError, match="input.place.*boundary polygon.*bbox/polygon"):
        load_and_clean(RunConfig(input={"source": "place", "place": "point neighbourhood"}))
