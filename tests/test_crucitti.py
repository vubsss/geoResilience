import json
import math
import csv

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
import pytest
from pyproj import Transformer
from shapely.geometry import LineString, Point

from georesilience.centralities import build_analysis_graph
from georesilience.cli import main
from georesilience.config import RunConfig
from georesilience.crucitti import (CITIES, CONVENTIONS, SIDE_M, ap2_betweenness_fit,
    frozen_input, information_pair, match_counts, square_sample, validate_crucitti)
from georesilience.links import _link_rows
from georesilience.network import load_and_clean


def path_graph():
    graph = nx.MultiDiGraph(crs="EPSG:32644", simplified=True)
    for node, (x, y) in enumerate(((0, 0), (3, 0), (3, 4))):
        graph.add_node(node, x=float(x), y=float(y))
    for u, v, length in ((0, 1, 3), (1, 2, 4)):
        graph.add_edge(u, v, osmid=u + 10, length=length)
        graph.add_edge(v, u, osmid=u + 10, length=length)
    return graph


@pytest.mark.parametrize("city", CITIES)
def test_metric_square_centred_correctly(city):
    square, crs, boundary = square_sample(city)
    x0, y0, x1, y1 = square.bounds
    assert x1 - x0 == pytest.approx(SIDE_M)
    assert y1 - y0 == pytest.approx(SIDE_M)
    assert square.area == pytest.approx(SIDE_M ** 2)
    lon, lat = Transformer.from_crs(crs, 4326, always_xy=True).transform(*square.centroid.coords[0])
    assert lon == pytest.approx(city.longitude, abs=1e-10)
    assert lat == pytest.approx(city.latitude, abs=1e-10)
    assert boundary.contains(Point(lon, lat))
    assert crs.axis_info[0].unit_name == "metre"


def test_exact_hand_computed_information_conventions():
    graph = path_graph()
    links = _link_rows(graph)
    analysis = build_analysis_graph(graph, links)
    scores, baseline, _ = information_pair(graph, links, analysis, n_jobs=1, budget_bytes=4096)
    assert baseline == pytest.approx([61 / 252, 19 / 21])
    assert scores[:, 0] == pytest.approx([40 / 61, 1, 33 / 61])
    assert scores[:, 1] == pytest.approx([12 / 19, 1, 12 / 19])
    # Uniform distance-unit changes cancel in relative drops but not inverse E.
    for _, data in graph.nodes(data=True):
        data["x"] *= 1000
        data["y"] *= 1000
    for _, _, data in graph.edges(data=True):
        data["length"] *= 1000
    scaled, efficiency, _ = information_pair(graph, _link_rows(graph),
        build_analysis_graph(graph, _link_rows(graph)), n_jobs=1, budget_bytes=4096)
    assert scaled == pytest.approx(scores)
    assert efficiency == pytest.approx([baseline[0] / 1000, baseline[1]])


def test_undefined_spatial_efficiency_and_disconnected_pairs():
    graph = path_graph()
    # Coincident coordinates have zero spatial efficiency, with a defined inverse E.
    for _, data in graph.nodes(data=True):
        data.update(x=0, y=0)
    links = _link_rows(graph)
    scores, baseline, _ = information_pair(graph, links, build_analysis_graph(graph, links),
        n_jobs=1, budget_bytes=4096)
    assert baseline[1] == 0 and np.isnan(scores[:, 1]).all()
    assert np.isfinite(scores[:, 0]).all()
    # Original isolated nodes remain in the pair denominator.
    graph = path_graph()
    graph.add_node(3, x=100, y=100)
    links = _link_rows(graph)
    scores, baseline, _ = information_pair(graph, links, build_analysis_graph(graph, links),
        n_jobs=1, budget_bytes=4096)
    assert baseline == pytest.approx([61 / 504, 19 / 42])
    assert scores[3] == pytest.approx([0, 0])


@pytest.mark.parametrize("jobs,budget", [(1, 256), (2, 8192)])
def test_random_information_matches_independent_networkx(jobs, budget):
    rng = np.random.default_rng(71)
    xy = rng.uniform(0, 1000, (9, 2))
    graph = nx.MultiDiGraph(crs="EPSG:32644", simplified=True)
    reference = nx.Graph()
    for i, (x, y) in enumerate(xy):
        graph.add_node(i, x=x, y=y)
        reference.add_node(i)
    for i in range(9):
        for j in range(i + 1, 9):
            if j == i + 1 or rng.random() < .3:
                length = float(np.linalg.norm(xy[i] - xy[j]) * rng.uniform(1, 1.4))
                graph.add_edge(i, j, osmid=10 * i + j, length=length)
                reference.add_edge(i, j, weight=length)
    def naive_efficiency(g):
        total = np.zeros(2)
        for i, distances in nx.all_pairs_dijkstra_path_length(g, weight="weight"):
            for j, length in distances.items():
                if i != j:
                    total += [1 / length, math.dist(xy[i], xy[j]) / length]
        return total / (9 * 8)
    expected_baseline = naive_efficiency(reference)
    expected = []
    for node in reference:
        changed = reference.copy()
        changed.remove_edges_from(list(changed.edges(node)))
        assert len(changed) == 9
        expected.append(1 - naive_efficiency(changed) / expected_baseline)
    links = _link_rows(graph)
    actual, baseline, _ = information_pair(graph, links, build_analysis_graph(graph, links),
        n_jobs=jobs, budget_bytes=budget)
    assert baseline == pytest.approx(expected_baseline, rel=1e-12)
    assert actual == pytest.approx(np.asarray(expected), abs=1e-12)


@pytest.mark.parametrize("model,expected", [("exponential", "exponential"), ("rayleigh", "gaussian")])
def test_ap2_cumulative_family_fits_and_units(model, expected):
    rng = np.random.default_rng(13)
    x = getattr(rng, model)(size=3000)
    fitted = ap2_betweenness_fit(x)
    assert fitted["verdict"] == expected
    assert fitted["exponential_scale"] == pytest.approx(x.mean())
    assert fitted["rayleigh_scale"] == pytest.approx(np.sqrt(np.mean(x*x) / 2))
    # Independent Rayleigh log likelihood: log(x) - 2log(sigma) - x²/(2sigma²).
    sigma = fitted["rayleigh_scale"]
    ray_ll = np.sum(np.log(x) - 2 * np.log(sigma) - x*x / (2 * sigma*sigma))
    exp_ll = -len(x) * np.log(x.mean()) - x.sum() / x.mean()
    assert fitted["delta_aic"] == pytest.approx(2 * (ray_ll - exp_ll))
    assert ap2_betweenness_fit(x * 1e-7)["delta_aic"] == pytest.approx(fitted["delta_aic"])
    assert ap2_betweenness_fit([0, np.nan, -1] + list(range(1, 31)))["verdict"] == "inconclusive"
    assert ap2_betweenness_fit(np.ones(60))["verdict"] == "inconclusive"


@pytest.mark.parametrize("info_count,between_count,status", [(4, 4, "PASS"), (3, 3, "PASS"),
    (2, 4, "MISMATCH"), (4, 2, "MISMATCH"), (0, 0, "MISMATCH")])
def test_separate_match_conditions(info_count, between_count, status):
    rows = [{"city": city.slug, "information": city.information if i < info_count else "inconclusive",
             "betweenness": city.betweenness if i < between_count else "inconclusive"}
            for i, city in enumerate(CITIES)]
    counts = match_counts(rows)
    assert counts["status"] == status
    assert counts["information_matches"] == info_count
    assert counts["betweenness_matches"] == between_count
    assert counts["inconclusive"]["information"] == 4 - info_count
    assert match_counts(rows[:3])["status"] == "INCOMPLETE"
    with pytest.raises(ValueError, match="unique"):
        match_counts(rows + rows[:1])


def download_graph(city):
    # One-way chain has four nodes in the undirected component, and singleton SCCs.
    graph = nx.MultiDiGraph(crs="EPSG:4326", simplified=True)
    for i in range(4):
        graph.add_node(i, x=city.longitude + i * .001, y=city.latitude)
    for i in range(3):
        graph.add_edge(i, i + 1, osmid=10 + i, length=120.0, oneway=True, highway="residential")
    return graph


def test_frozen_download_provenance_and_tamper_checks(tmp_path, monkeypatch):
    calls = []
    def download(boundary, **kwargs):
        calls.append(kwargs)
        return download_graph(CITIES[0])
    monkeypatch.setattr(ox, "graph_from_polygon", download)
    path, manifest = frozen_input(CITIES[0], tmp_path)
    assert calls == [{"network_type": "all", "simplify": False, "retain_all": True, "truncate_by_edge": False}]
    assert manifest["raw_nodes"] == 4
    assert manifest["download_utc"]
    assert gpd.read_file(path.parent / "boundary.geojson").crs.to_epsg() == 4326
    assert len(gpd.read_file(path.parent / "input.gpkg", layer="nodes")) == 4
    assert len(gpd.read_file(path.parent / "input.gpkg", layer="boundary")) == 1
    assert frozen_input(CITIES[0], tmp_path, offline=True) == (path, manifest)
    assert len(calls) == 1
    record = path.parent / "manifest.json"
    altered = json.loads(record.read_text())
    altered["sample"]["side_m"] = 999
    record.write_text(json.dumps(altered))
    with pytest.raises(ValueError, match="settings differ"):
        frozen_input(CITIES[0], tmp_path, offline=True)
    record.write_text(json.dumps(manifest))
    path.write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        frozen_input(CITIES[0], tmp_path)
    with pytest.raises(ValueError, match="no frozen"):
        frozen_input(CITIES[1], tmp_path, offline=True)


def test_undirected_cleaning_keeps_one_way_streets(tmp_path, monkeypatch):
    path = tmp_path / "chain.graphml"
    ox.save_graphml(download_graph(CITIES[0]), filepath=path)
    config = RunConfig(input={"source": "graphml", "path": path}, cleaning={"consolidate": False})
    graph, _, cleaning = load_and_clean(config, undirected=True)
    assert len(graph) == 4
    assert graph.number_of_edges() == 6
    assert cleaning["dropped_components"]["nodes_dropped"] == 0
    # Relaxing the experimental guard is explicit and leaves a warning.
    monkeypatch.setattr("georesilience.network._guard_dead_ends",
        lambda *args: (_ for _ in ()).throw(ValueError("dead-end test warning")))
    config.cleaning.consolidate = True
    graph, _, cleaning = load_and_clean(config, undirected=True, enforce_dead_end_guard=False)
    assert "dead-end test warning" in cleaning["warnings"]
    with pytest.raises(ValueError, match="dead-end test warning"):
        load_and_clean(config, undirected=True)


@pytest.mark.parametrize("simplified", [False, True])
def test_undirected_consolidation_preserves_arc_orientation_and_road_lengths(tmp_path, simplified):
    graph = nx.MultiDiGraph(crs="EPSG:32644", simplified=simplified)
    positions = {0: (0, 0), 1: (5, 0), 2: (-100, 0), 3: (0, 50),
                 4: (105, 0), 5: (5, 50)}
    for node, (x, y) in positions.items():
        graph.add_node(node, x=500000.0 + x, y=3000000.0 + y)
    for osmid, (u, v) in enumerate(((0, 1), (0, 2), (0, 3), (1, 4), (1, 5)), 100):
        coords = [(graph.nodes[node]["x"], graph.nodes[node]["y"]) for node in (u, v)]
        geometry = LineString(coords)
        # Actual one-way arcs: validation must create well-oriented reverse arcs.
        graph.add_edge(u, v, osmid=osmid, length=geometry.length, geometry=geometry, oneway=True)
    path = tmp_path / "nearby-junctions.graphml"
    ox.save_graphml(graph, filepath=path)
    config = RunConfig(input={"source": "graphml", "path": path},
                       cleaning={"consolidate": True, "tolerance_m": 3})
    cleaned, _, _ = load_and_clean(config, undirected=True)
    links = _link_rows(cleaned)
    assert len(cleaned) == 5  # Only junctions at x=0 and x=5 merge.
    assert len(links) == 4 and all(not row["oneway"] for row in links)
    # New centroid x=2.5 adds a 2.5 m connector to each of four surviving streets.
    assert sum(row["length_m"] for row in links) == pytest.approx(310.0, abs=1e-6)
    for u, v, data in cleaned.edges(data=True):
        coords = list(data["geometry"].coords)
        assert coords[0][:2] == pytest.approx((cleaned.nodes[u]["x"], cleaned.nodes[u]["y"]), abs=1e-6)
        assert coords[-1][:2] == pytest.approx((cleaned.nodes[v]["x"], cleaned.nodes[v]["y"]), abs=1e-6)


def test_four_city_cli_offline_outputs_and_reuse(tmp_path, monkeypatch):
    calls = []
    def download(boundary, **kwargs):
        city = CITIES[len(calls)]
        calls.append(city.slug)
        return download_graph(city)
    monkeypatch.setattr(ox, "graph_from_polygon", download)
    out = tmp_path / "study"
    assert main(["validate", "crucitti", "--out", str(out), "--download-only"]) == 0
    assert len(calls) == 4
    assert not (out / "crucitti_report.txt").exists()
    def forbidden(*args, **kwargs):
        raise AssertionError("Focused validation must skip the production pipeline and Monte Carlo")
    monkeypatch.setattr("georesilience.cli.run", forbidden)
    monkeypatch.setattr("georesilience.pipeline.compute_connectivity", forbidden)
    monkeypatch.setattr(ox, "graph_from_polygon", forbidden)
    args = ["validate", "crucitti", "--out", str(out), "--offline", "--consolidation-m", "0"]
    assert main(args) == 0  # Four inconclusive cities are findings, not command failures.
    summary = json.loads((out / "comparison.json").read_text())
    assert summary["status"] == "MISMATCH"
    assert (out / "crucitti_report.txt").read_text().startswith("MISMATCH")
    with (out / "comparison.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 8
    assert {row["convention"] for row in rows} == set(CONVENTIONS)
    assert (out / "figures" / "information_ccdf.png").stat().st_size > 1000
    assert (out / "figures" / "betweenness_ccdf.png").stat().st_size > 1000
    for convention in CONVENTIONS:
        assert summary["comparisons"][convention]["inconclusive"]["information"] == 4
    for city in CITIES:
        city_folder = out / city.slug
        result = json.loads((city_folder / "summary.json").read_text())
        assert result["node_count"] == result["information_nodes"] == 4
        assert result["information_coverage"] == "all"
        assert result["comparisons"][CONVENTIONS[1]]["efficiency_convention"] == "spatial_d_E_over_d"
        nodes = gpd.read_file(city_folder / "network.gpkg", layer="nodes")
        assert len(nodes) == 4 and np.isfinite(nodes["information_spatial"]).all()
        assert len(gpd.read_file(city_folder / "network.gpkg", layer="edges")) == 3
        assert (city_folder / "centralities.csv").exists()
        assert "AP2 spatial efficiency (dimensionless)" in (city_folder / "report.txt").read_text()
    assert main(args) == 2
    assert main(args + ["--overwrite", "--no-figures"]) == 0
    assert not (out / "figures" / "information_ccdf.png").exists()
    assert len(calls) == 4
    monkeypatch.setattr("georesilience.crucitti.analyse_city", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("interrupted")))
    assert main(args + ["--overwrite"]) == 2
    assert not (out / "comparison.json").exists()
    assert not (out / "crucitti_report.txt").exists()
    assert not (out / "comparison.csv").exists()


def test_invalid_options_and_missing_offline_inputs(tmp_path):
    assert main(["validate", "crucitti", "--out", str(tmp_path), "--offline"]) == 2
    for kwargs in ({"n_jobs": 0}, {"max_memory_gb": 0}, {"tolerance_m": -1}, {"tolerance_m": math.nan}):
        with pytest.raises(ValueError):
            validate_crucitti(tmp_path, offline=True, **kwargs)
