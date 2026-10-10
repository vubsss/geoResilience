import json
import math
import subprocess
import sys
import threading
import time

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
import psutil
import pytest
from scipy.sparse.csgraph import floyd_warshall

from georesilience.centralities import build_analysis_graph, compute_centralities
from georesilience.config import AnalysisConfig, RunConfig, load_config
from georesilience.figures import FIGURE_FILENAMES
from georesilience.links import _link_rows
from georesilience.pipeline import run
from georesilience.shortest_paths import (
    CentralityReducer, GIB, ShortestPathEngine, aggregate_efficiency, fits_in_memory, resolve_resources,
)


def road_graph(simple, coordinates):
    graph = nx.MultiDiGraph(crs="EPSG:32644", simplified=True)
    for node in simple:
        x, y = coordinates[node]
        graph.add_node(node, x=x, y=y)
    for way, (u, v, data) in enumerate(simple.edges(data=True)):
        length = data.get("length", math.dist(coordinates[u], coordinates[v]))
        for a, b in ((u, v), (v, u)):
            graph.add_edge(a, b, length=length, osmid=way + 1, highway="residential")
    return graph


def compute(graph, jobs=1, memory=0.1):
    links = _link_rows(graph)
    result = compute_centralities(graph, links, AnalysisConfig(n_jobs=jobs, max_memory_gb=memory))
    return links, result


def test_known_answers_path_star_grid_and_two_nodes():
    graph = road_graph(nx.path_graph(5), {i: (float(i), 0.0) for i in range(5)})
    _, (_, values, _, _, _) = compute(graph)
    np.testing.assert_allclose(values["straightness"], 1, rtol=0, atol=1e-15)

    coordinates = {0: (0, 0), 1: (1, 0), 2: (0, 1), 3: (-1, 0), 4: (0, -1)}
    star = road_graph(nx.star_graph(4), coordinates)
    _, (_, values, edges, _, _) = compute(star)
    np.testing.assert_allclose(values["betweenness"], [1, 0, 0, 0, 0], atol=1e-15)
    np.testing.assert_allclose(list(edges.values()), 0.4, atol=1e-15)

    grid = nx.grid_2d_graph(3, 3)
    _, (analysis, values, _, _, _) = compute(road_graph(grid, {node: node for node in grid}))
    centre = analysis.node_ids.index((1, 1))
    assert values["closeness"][centre] == pytest.approx(8 / 12)

    _, (_, values, edges, stats, _) = compute(road_graph(nx.path_graph(2), {0: (0, 0), 1: (7, 0)}))
    assert stats["global_efficiency"] == pytest.approx(1 / 7)
    np.testing.assert_array_equal(values["betweenness"], [0, 0])
    assert list(edges.values()) == [1]


def test_parallel_link_attribution_tie_and_self_loop():
    graph = road_graph(nx.path_graph(3), {i: (float(i), 0) for i in range(3)})
    for osmid, length in ((99, 2.0), (100, 1.0)):
        for u, v in ((0, 1), (1, 0)):
            graph.add_edge(u, v, osmid=osmid, length=length)
    graph.add_edge(1, 1, osmid=101, length=0)
    links, (analysis, _, scores, stats, _) = compute(graph)
    by_way = {row["osm_way_ids"]: scores[row["link_id"]] for row in links}
    assert by_way["1"] == pytest.approx(2 / 3)
    assert by_way["99"] == 0
    assert by_way["100"] == 0  # Equal-length tie: lowest link_id supplies the edge.
    assert np.isnan(by_way["101"])
    assert analysis.csr[0, 1] == 1
    assert stats["edge_betweenness"]["mean"] == pytest.approx(1 / 3)


@pytest.mark.parametrize("seed", range(5))
def test_random_spatial_graph_against_networkx_and_floyd_warshall(seed):
    rng = np.random.default_rng(seed)
    simple = nx.random_geometric_graph(200, 0.18, seed=seed)
    assert nx.is_connected(simple)
    coords = {node: tuple(1000 * np.asarray(data["pos"])) for node, data in simple.nodes(data=True)}
    for u, v in simple.edges:
        simple[u][v]["length"] = math.dist(coords[u], coords[v]) * rng.uniform(1, 1.3)
    graph = road_graph(simple, coords)
    links, (analysis, values, edges, stats, _) = compute(graph)
    expected_closeness = nx.closeness_centrality(simple, distance="length")
    expected_nodes = nx.betweenness_centrality(simple, normalized=True, weight="length")
    expected_edges = {frozenset(pair): value / (200 * 199 / 2) for pair, value in
                      nx.edge_betweenness_centrality(simple, normalized=False, weight="length").items()}
    np.testing.assert_allclose(values["closeness"], [expected_closeness[u] for u in analysis.node_ids],
                               rtol=0, atol=1e-9)
    np.testing.assert_allclose(values["betweenness"], [expected_nodes[u] for u in analysis.node_ids],
                               rtol=0, atol=1e-9)
    np.testing.assert_allclose([edges[row["link_id"]] for row in links],
                               [expected_edges[frozenset((row["_u"], row["_v"]))] for row in links],
                               rtol=0, atol=1e-9)
    distances = floyd_warshall(analysis.csr, directed=False)
    inverse = np.divide(1, distances, out=np.zeros_like(distances), where=distances > 0)
    assert stats["global_efficiency"] == pytest.approx(inverse.sum() / (200 * 199), abs=1e-9)
    # Independent, slow straightness reference as well.
    expected_straightness = []
    for i, u in enumerate(analysis.node_ids):
        expected_straightness.append(sum(math.dist(coords[u], coords[v]) / distances[i, j]
                                        for j, v in enumerate(analysis.node_ids) if i != j) / 199)
    np.testing.assert_allclose(values["straightness"], expected_straightness, rtol=0, atol=1e-12)


def test_jobs_and_memory_chunk_invariance():
    rng = np.random.default_rng(42)
    simple = nx.random_geometric_graph(200, 0.18, seed=42)
    coords = {u: tuple(np.asarray(data["pos"]) * 1000) for u, data in simple.nodes(data=True)}
    for u, v in simple.edges:
        simple[u][v]["length"] = math.dist(coords[u], coords[v]) * rng.uniform(1, 1.3)
    graph = road_graph(simple, coords)
    _, (_, baseline, baseline_edges, baseline_stats, _) = compute(graph)
    for jobs, memory in ((4, 0.1), (1, 0.00001), (4, 0.0001)):
        _, (_, values, edges, stats, computation) = compute(graph, jobs, memory)
        for name in baseline:
            np.testing.assert_allclose(values[name], baseline[name], rtol=0, atol=1e-12)
        np.testing.assert_allclose(list(edges.values()), list(baseline_edges.values()), rtol=0, atol=1e-12)
        assert stats["global_efficiency"] == pytest.approx(baseline_stats["global_efficiency"], abs=1e-12)
        if memory < 0.001:
            assert computation["shortest_path_chunks"] > 1


def test_engine_subset_direction_cutoff_and_budget():
    from scipy.sparse import csr_matrix
    csr = csr_matrix([[0, 2, 0], [0, 0, 3], [0, 0, 0]], dtype=float)
    engine = ShortestPathEngine(csr, n_jobs=1, budget_bytes=3 * 8 * 3)
    assert engine.chunk_rows == 1
    assert engine.fits_in_memory(dtype=np.float64)
    assert not fits_in_memory(4, np.float64, budget_bytes=72)
    reduced = list(engine.reduce([2, 0], lambda d, s: d[:, 0], directed=True))
    assert [sources.tolist() for sources, _ in reduced] == [[2], [0]]
    assert np.isinf(reduced[0][1][0])
    reduced = list(engine.reduce([0], lambda d, s: d[:, 2], directed=True, limit=4))
    assert np.isinf(reduced[0][1][0])
    reduced = list(engine.reduce([2], lambda d, s: d[:, 0], directed=False))
    assert reduced[0][1][0] == 5
    assert list(engine.reduce([], lambda d, s: d.sum(axis=1))) == []


def test_reducer_unreachable_and_optional_node_weights():
    reducer = CentralityReducer(np.array([[0, 0], [2, 0], [4, 0]]))
    result = reducer(np.array([[0., 2., np.inf]]), np.array([0]))
    np.testing.assert_allclose(result, [[0, 0.5, 0.5]])
    weighted = CentralityReducer(reducer.coordinates, np.array([1., 3., 0.]))
    result = weighted(np.array([[0., 2., np.inf]]), np.array([0]))
    np.testing.assert_allclose(result, [[0.5, 1, 1.5]])
    assert aggregate_efficiency([1.5, 0.5, 7], [1, 3, 0]) == 0.5
    assert aggregate_efficiency([0], [0]) == 0
    singleton = CentralityReducer(np.array([[0., 0.]]))
    np.testing.assert_array_equal(singleton(np.array([[0.]]), np.array([0])), [[0, 0, 0]])


def test_resources_and_invalid_config(monkeypatch):
    monkeypatch.setenv("SLURM_CPUS_PER_TASK", "4")
    assert resolve_resources("auto", 0.5) == (4, GIB // 2)
    monkeypatch.setenv("SLURM_CPUS_PER_TASK", "bad")
    with pytest.raises(ValueError, match="SLURM_CPUS_PER_TASK"):
        resolve_resources()
    for values in ({"n_jobs": 0}, {"n_jobs": -1}, {"max_memory_gb": 0}, {"max_memory_gb": float("nan")}):
        with pytest.raises(ValueError):
            AnalysisConfig(**values)


def test_directed_flag_rejected_without_modifying_output(tmp_path):
    output = tmp_path / "existing"
    output.mkdir()
    marker = output / "summary.json"
    marker.write_text("keep this")
    config = RunConfig(input={"path": "unused.graphml"}, analysis={"directed_centrality": True},
                       output={"dir": output})
    with pytest.raises(NotImplementedError, match="directed_centrality"):
        run(config, overwrite=True)
    assert marker.read_text() == "keep this"
    path = tmp_path / "directed.yaml"
    path.write_text("input:\n  path: unused.graphml\nanalysis:\n  directed_centrality: true\n")
    process = subprocess.run([sys.executable, "-m", "georesilience.cli", "run", "--config", str(path)],
                             capture_output=True, text=True)
    assert process.returncode == 2
    assert "analysis.directed_centrality" in process.stderr
    assert "Traceback" not in process.stderr


def test_outputs_and_overwrite_removes_old_figures(tmp_path):
    coords = {0: (500000, 1900000), 1: (500100, 1900000), 2: (500000, 1900100),
              3: (499900, 1900000), 4: (500000, 1899900)}
    graph = road_graph(nx.star_graph(4), coords)
    graph.add_edge(0, 0, length=0, osmid=99)
    source = tmp_path / "star.graphml"
    ox.save_graphml(graph, filepath=source)
    config = RunConfig(input={"path": source}, cleaning={"consolidate": False},
                       analysis={"n_jobs": 1, "max_memory_gb": 0.1}, output={"dir": tmp_path / "results"})
    summary = run(config)
    output = config.output.dir
    nodes = gpd.read_file(output / "network.gpkg", layer="nodes")
    edges = gpd.read_file(output / "network.gpkg", layer="edges")
    assert set(("closeness", "straightness", "betweenness")) <= set(nodes.columns)
    assert nodes.loc[nodes.node_id == "0", "betweenness"].item() == 1
    assert edges.loc[edges.is_self_loop, "edge_betweenness"].isna().all()
    np.testing.assert_allclose(edges.loc[~edges.is_self_loop, "edge_betweenness"], 0.4)
    for name in ("closeness", "straightness", "betweenness", "edge_betweenness"):
        assert set(summary["metrics"][name]) == {"mean", "median", "p90", "max"}
    assert summary["metrics"]["global_efficiency"] == pytest.approx(0.007)
    assert all(value >= 0 for value in summary["metrics"]["runtime_seconds"].values())
    text = (output / "report.txt").read_text()
    assert "Centralities" in text and "Top 20 links by edge betweenness" in text
    assert text.isascii() and max(map(len, text.splitlines())) <= 100
    for name in FIGURE_FILENAMES:
        assert (output / "figures" / name).stat().st_size > 1000
    resolved = load_config(output / "run_config.yaml")
    assert resolved.analysis.n_jobs == 1
    assert resolved.analysis.max_memory_gb == pytest.approx(0.1)
    resolved.output.figures = False
    run(resolved, overwrite=True)
    assert not (output / "figures").exists()


@pytest.mark.slow
def test_60k_perturbed_grid_benchmark(tmp_path):
    rng = np.random.default_rng(42)
    # Exactly 60,000 nodes. Jitter and continuous road-length multipliers remove ties.
    width, height = 250, 240
    simple = nx.grid_2d_graph(width, height)
    coords = {u: tuple(100 * (np.asarray(u) + rng.uniform(-0.1, 0.1, 2))) for u in simple}
    for u, v in simple.edges:
        simple[u][v]["length"] = math.dist(coords[u], coords[v]) * rng.uniform(1, 1.3)
    graph = road_graph(simple, coords)
    links = _link_rows(graph)
    del simple, coords
    process = psutil.Process()
    peak = [0]
    stop = threading.Event()
    def sample_memory():
        while not stop.is_set():
            total = process.memory_info().rss
            for child in process.children(recursive=True):
                try:
                    total += child.memory_info().rss
                except psutil.NoSuchProcess:
                    pass
            peak[0] = max(peak[0], total)
            stop.wait(0.05)
    thread = threading.Thread(target=sample_memory, daemon=True)
    thread.start()
    started = time.perf_counter()
    try:
        result = compute_centralities(graph, links, AnalysisConfig(n_jobs=8, max_memory_gb=2))
    finally:
        stop.set()
        thread.join()
    elapsed = time.perf_counter() - started
    record = {"nodes": 60000, "n_jobs": 8, "budget_gib": 2,
              "elapsed_seconds": elapsed, "peak_rss_gib": peak[0] / GIB,
              "runtime_seconds": result[3]["runtime_seconds"]}
    (tmp_path / "benchmark.json").write_text(json.dumps(record, indent=2))
    print(json.dumps(record, indent=2), flush=True)
    assert elapsed < 600
    assert peak[0] <= 3 * GIB


@pytest.mark.parametrize("length", [0, -1, np.nan, np.inf])
def test_invalid_road_lengths_are_rejected(length):
    graph = road_graph(nx.path_graph(2), {0: (0, 0), 1: (1, 0)})
    for _, _, data in graph.edges(data=True):
        data["length"] = length
    with pytest.raises(ValueError, match="length_m must be finite and positive"):
        build_analysis_graph(graph, _link_rows(graph))
