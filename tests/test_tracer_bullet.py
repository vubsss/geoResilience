import json
import subprocess
import sys

import networkx as nx
import osmnx as ox
from georesilience.pipeline import _link_rows


def test_link_model_handles_two_way_one_way_parallel_and_loop():
    graph = nx.MultiDiGraph(crs="EPSG:4326", simplified=True)
    graph.add_node("a", x=0, y=0)
    graph.add_node("b", x=0.001, y=0)
    attrs = {"length": 100, "osmid": 10}
    graph.add_edge("a", "b", **attrs)
    graph.add_edge("b", "a", **attrs)
    graph.add_edge("a", "b", length=100, osmid=11)
    graph.add_edge("a", "a", length=0, osmid=12)
    rows = _link_rows(graph)
    assert len(rows) == 3
    assert sum(not row["oneway"] and not row["is_self_loop"] for row in rows) == 1
    assert sum(row["oneway"] and not row["is_self_loop"] for row in rows) == 1
    assert sum(row["is_self_loop"] for row in rows) == 1


def test_cli_writes_all_artifacts(tmp_path):
    graph = nx.MultiDiGraph(crs="EPSG:4326", simplified=True)
    for y in range(3):
        for x in range(3):
            graph.add_node(str(y * 3 + x), x=-122.0 + x * 0.001, y=37.0 + y * 0.001)
    for y in range(3):
        for x in range(3):
            u = str(y * 3 + x)
            for dx, dy in ((1, 0), (0, 1)):
                if x + dx < 3 and y + dy < 3:
                    v = str((y + dy) * 3 + x + dx)
                    graph.add_edge(u, v, length=100, osmid=1000 + int(u) * 10 + int(v))
                    graph.add_edge(v, u, length=100, osmid=1000 + int(u) * 10 + int(v))
    graph.add_edge("0", "1", length=100, osmid=9001)
    graph.add_edge("0", "0", length=0, osmid=9002)
    source = tmp_path / "grid.graphml"
    ox.save_graphml(graph, filepath=source)
    output = tmp_path / "results"
    config = tmp_path / "run.yaml"
    config.write_text(f"input:\n  source: graphml\n  path: {source}\noutput:\n  dir: {output}\n")
    subprocess.run([sys.executable, "-m", "georesilience.cli", "run", "--config", str(config)], check=True)
    for name in ("network.gpkg", "summary.json", "report.txt", "run_config.yaml", "figures/degree_hist.png"):
        assert (output / name).is_file()
    summary = json.loads((output / "summary.json").read_text())
    assert summary["meta"]["node_count"] == 9
    assert summary["meta"]["link_count"] == 14
    assert summary["meta"]["directed_edge_count"] == 26
    # Degree is from the 3x3 grid; the self-loop and parallel one-way link add no neighbours.
    assert summary["metrics"]["degree"]["histogram"] == {"2": 4, "3": 4, "4": 1}


def test_unknown_config_key_names_key(tmp_path):
    config = tmp_path / "bad.yaml"
    config.write_text("input:\n  source: graphml\n  path: graph.graphml\n  typo: true\n")
    result = subprocess.run([sys.executable, "-m", "georesilience.cli", "run", "--config", str(config)],
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert "input.typo" in result.stderr
