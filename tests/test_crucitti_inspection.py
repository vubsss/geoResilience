"""Scientific bookkeeping checks for the offline sensitivity inspection."""

import importlib.util
import json
from pathlib import Path

import networkx as nx
import geopandas as gpd
import osmnx as ox
import pytest
from pyproj import Transformer

from georesilience.crucitti import CITIES, frozen_input, square_sample, validate_crucitti
from georesilience.links import _link_rows

spec = importlib.util.spec_from_file_location(
    "ticket15_inspection", Path(__file__).resolve().parents[1] / "examples/inspect_ticket15_samples.py")
inspection = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inspection)


def test_physical_street_mix_does_not_double_count_reciprocal_or_mixed_roads():
    graph = nx.MultiDiGraph()
    for node in range(4):
        graph.add_node(node, x=node * 10, y=0)
    for u, v, length, highway in ((0, 1, 100, "residential"),
                                  (1, 2, 50, ["footway", "residential"]),
                                  (2, 3, 50, None)):
        graph.add_edge(u, v, osmid=u, length=length, highway=highway)
        graph.add_edge(v, u, osmid=u, length=length, highway=highway)
    roads = _link_rows(graph)
    rows = inspection.street_mix(roads, city="test", stage="raw")
    assert sum(row["physical_segments"] for row in rows) == 3
    assert sum(row["length_km"] for row in rows) == pytest.approx(.2)
    assert sum(row["length_pct"] for row in rows) == pytest.approx(100)
    lengths = {row["value"]: row["length_pct"] for row in rows}
    assert lengths == {"residential": 50, "footway;residential": 25, "(unspecified)": 25}
    assert inspection.category("footway;residential") == "mixed"
    assert inspection.category("footway;steps") == "path_or_cycle"
    assert inspection.category("service") == "service"
    assert inspection.category(None) == "missing"
    assert inspection.category(float("nan")) == "missing"
    assert inspection.street_mix([{"length_m": 1, "highway": float("nan")}],
                                 city="test", stage="raw")[0]["value"] == "(unspecified)"
    # Zero total length remains defined without division by zero.
    assert inspection.street_mix([{"length_m": 0}], city="test", stage="raw")[0]["length_pct"] == 0


@pytest.mark.parametrize("change", [None, "hash", "workers", "coverage", "tolerance", "missing_city"])
def test_sensitivity_requires_same_snapshots_and_other_settings(tmp_path, change):
    first, second = tmp_path / "15m", tmp_path / "0m"
    first.mkdir()
    second.mkdir()
    config = {"snapshots": {city.slug: city.slug + "-sha" for city in CITIES},
              "consolidation_tolerance_m": 15, "n_jobs": 2,
              "information_coverage": "all", "started_utc": "first", "inputs_dir": "source"}
    (first / "run_config.json").write_text(json.dumps(config))
    config.update(consolidation_tolerance_m=0, started_utc="second", inputs_dir="same-copy")
    if change == "hash":
        config["snapshots"]["cairo"] = "different-sha"
    elif change == "workers":
        config["n_jobs"] = 1
    elif change == "coverage":
        config["information_coverage"] = "candidates"
    elif change == "tolerance":
        config["consolidation_tolerance_m"] = 10
    elif change == "missing_city":
        del config["snapshots"]["cairo"]
    (second / "run_config.json").write_text(json.dumps(config))
    if change:
        with pytest.raises(ValueError):
            inspection.controlled_configs(first, second)
    else:
        inspection.controlled_configs(first, second)


def test_cluster_audit_measures_extent_instead_of_assuming_tolerance_is_a_cap():
    raw = nx.MultiDiGraph()
    for node, x in enumerate((0, 25, 50, 100)):
        raw.add_node(node, x=x, y=0)
    cleaned = nx.MultiDiGraph()
    cleaned.add_node(10, osmid_original=[0, 1, 2], x=25, y=0)
    cleaned.add_node(11, osmid_original=3, x=100, y=0)
    merged, singleton = inspection.cluster_audit(cleaned, raw)
    assert merged["merged_junctions"] == 3
    assert merged["max_displacement_m"] == 25
    assert merged["diameter_m"] == 50
    assert singleton["merged_junctions"] == 1
    assert singleton["max_displacement_m"] == singleton["diameter_m"] == 0


def test_offline_inspection_outputs_and_tampered_input_refusal(tmp_path, monkeypatch):
    inputs, baseline, comparison, audit = (tmp_path / name for name in ("inputs", "baseline", "comparison", "audit"))
    for city in CITIES:
        square, crs, _ = square_sample(city)
        x, y = square.centroid.coords[0]
        backward = Transformer.from_crs(crs, 4326, always_xy=True)
        graph = nx.MultiDiGraph(crs="EPSG:4326")
        for node, (dx, dy) in enumerate(((0, 0), (100, 0), (0, 100), (-100, 0))):
            lon, lat = backward.transform(x + dx, y + dy)
            graph.add_node(node, x=lon, y=lat)
        for node, highway in enumerate(("footway", "service", "residential"), 1):
            graph.add_edge(0, node, osmid=node, length=100.0, highway=highway, oneway=True)
        monkeypatch.setattr(ox, "graph_from_polygon", lambda *args, _graph=graph, **kwargs: _graph)
        frozen_input(city, inputs)
    def forbidden(*args, **kwargs):
        raise AssertionError("inspection must remain offline")
    monkeypatch.setattr(ox, "graph_from_polygon", forbidden)
    validate_crucitti(baseline, inputs_dir=inputs, offline=True, tolerance_m=15, figures=False)
    validate_crucitti(comparison, inputs_dir=inputs, offline=True, tolerance_m=0, figures=False)
    # The audit must leave all source files byte-for-byte unchanged.
    before = {path: path.read_bytes() for root in (inputs, baseline, comparison)
              for path in root.rglob("*") if path.is_file()}
    inspection.inspect(inputs, baseline, audit, comparison)
    assert all(path.read_bytes() == original for path, original in before.items())
    windows = json.loads((audit / "windows.json").read_text())
    assert len(windows) == 4 and windows[0]["raw_physical_segments"] == 3
    assert sum(windows[0]["raw_category_length_pct"].values()) == pytest.approx(100)
    assert "explicitly labels Richmond, CA" in windows[3]["location_warning"]
    layers = set(gpd.list_layers(audit / "cairo.gpkg")["name"])
    assert layers == {"raw_edges", "raw_nodes", "boundary", "clusters_15m",
                      "edges_15m", "nodes_15m", "edges_0m", "nodes_0m"}
    assert (audit / "raw_windows.png").stat().st_size > 1000
    assert (audit / "topology_comparison.png").stat().st_size > 1000
    with pytest.raises(ValueError, match="separate"):
        inspection.inspect(inputs, baseline, baseline / "cairo", comparison)
    assert all(path.read_bytes() == original for path, original in before.items())
    # Refuse an altered snapshot before creating a misleading audit directory.
    with (inputs / "cairo" / "raw.graphml").open("a") as stream:
        stream.write("\n")
    with pytest.raises(ValueError, match="checksum"):
        inspection.inspect(inputs, baseline, tmp_path / "invalid", comparison)
    assert not (tmp_path / "invalid").exists()
