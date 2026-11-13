"""Known-answer checks for the first Tier 4 traffic assignment slice."""

import csv
from types import SimpleNamespace

import networkx as nx
import pytest

from georesilience.traffic import (assign_traffic, evaluate_closures, gravity_od, population_gravity_od, prepare_traffic,
                                  write_traffic_closures_csv, write_traffic_csv, write_traffic_od_csv)


def _graph(*roads):
    graph = nx.MultiDiGraph()
    for u, v, key in roads:
        graph.add_edge(u, v, key=key, length=1000)
    return graph


def _csv(path, fields, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_one_road_bpr_time_and_system_delay():
    graph = _graph((0, 1, 0))
    edge = (0, 1, 0)
    rows, summary = assign_traffic(graph, {edge: 60}, {edge: 100}, {(0, 1): 100})
    assert rows[edge]["assigned_volume_pcu_h"] == 100
    assert rows[edge]["congested_time_s"] == pytest.approx(69)
    assert rows[edge]["vc_ratio"] == 1
    assert summary["tstt_pcu_hours"] == pytest.approx(100 * 69 / 3600)
    assert summary["delay_pcu_hours"] == pytest.approx(100 * 9 / 3600)
    assert summary["status"] == "converged"


def test_parallel_roads_equilibrate_and_conserve_flow():
    graph = _graph((0, 1, 0), (0, 1, 1))
    fast, slow = (0, 1, 0), (0, 1, 1)
    rows, summary = assign_traffic(graph, {fast: 60, slow: 120},
                                   {fast: 100, slow: 100}, {(0, 1): 200})
    assert summary["status"] == "converged"
    assert sum(row["assigned_volume_pcu_h"] for row in rows.values()) == pytest.approx(200)
    assert rows[fast]["assigned_volume_pcu_h"] > rows[slow]["assigned_volume_pcu_h"] > 0
    assert rows[fast]["congested_time_s"] == pytest.approx(rows[slow]["congested_time_s"], rel=1e-4)


def test_directed_csv_input_and_assignment_export(tmp_path):
    graph = _graph((0, 1, 0), (1, 0, 0))
    od = tmp_path / "od.csv"
    _csv(od, ["origin", "destination", "demand_pcu_h"],
         [{"origin": 0, "destination": 1, "demand_pcu_h": 100}])
    config = SimpleNamespace(source="assignment", demand_source="od_csv", od_csv=od, capacity_csv=None,
                             capacity_pcu_h=100, vdf="bpr", alpha=.15, beta=4,
                             relative_gap=1e-4, max_iterations=200, period="demo", duration_h=1)
    result = prepare_traffic(graph, config, {(0, 1, 0): 60, (1, 0, 0): 60})
    assert result.summary["status"] == "converged"
    assert result.summary["mean_od_time_s"] == pytest.approx(69)
    assert result.edge_seconds[(0, 1, 0)] == pytest.approx(69)
    assert result.edge_seconds[(1, 0, 0)] == 60
    path = tmp_path / "traffic_arcs.csv"
    write_traffic_csv(result, path)
    with path.open(newline="") as stream:
        exported = list(csv.DictReader(stream))
    assert len(exported) == 2
    assert {row["assigned_volume_pcu_h"] for row in exported} == {"100.0", "0.0"}

    capacities = tmp_path / "capacities.csv"
    _csv(capacities, ["u", "v", "key", "capacity_pcu_h"],
         [{"u": 0, "v": 1, "key": 0, "capacity_pcu_h": 200},
          {"u": 1, "v": 0, "key": 0, "capacity_pcu_h": 100}])
    config.capacity_csv = capacities
    with_override = prepare_traffic(graph, config, {(0, 1, 0): 60, (1, 0, 0): 60})
    assert with_override.summary["capacity_source"] == "directed_csv"
    assert with_override.edge_seconds[(0, 1, 0)] == pytest.approx(60 * (1 + .15 * .5**4))

    supplied = tmp_path / "times.csv"
    _csv(supplied, ["u", "v", "key", "travel_time_s"],
         [{"u": 0, "v": 1, "key": 0, "travel_time_s": 95},
          {"u": 1, "v": 0, "key": 0, "travel_time_s": 80}])
    config.source, config.edge_times_csv = "edge_times_csv", supplied
    imported = prepare_traffic(graph, config)
    assert imported.edge_seconds == {(0, 1, 0): 95, (1, 0, 0): 80}
    assert all("assigned_volume_pcu_h" not in row for row in imported.rows)
    _csv(supplied, ["u", "v", "key", "travel_time_s"],
         [{"u": 0, "v": 1, "key": 0, "travel_time_s": 95}])
    with pytest.raises(ValueError, match="cover every"):
        prepare_traffic(graph, config)


def test_conical_profile_and_unreachable_od():
    graph = _graph((0, 1, 0))
    edge = (0, 1, 0)
    rows, summary = assign_traffic(graph, {edge: 60}, {edge: 100}, {(0, 1): 100},
                                   vdf="conical", alpha=1.58, beta=1.86)
    assert rows[edge]["congested_time_s"] > 60
    assert summary["status"] == "converged"
    with pytest.raises(ValueError, match="unreachable"):
        assign_traffic(graph, {edge: 60}, {edge: 100}, {(1, 0): 100})


def test_gravity_generates_balanced_synthetic_od(tmp_path):
    graph = _graph(*[(u, v, 0) for u in range(3) for v in range(3) if u != v])
    free = {(u, v, key): 60 for u, v, key in graph.edges(keys=True)}
    zones = tmp_path / "zones.csv"
    _csv(zones, ["node", "mass"], [{"node": node, "mass": 1} for node in range(3)])
    demand = gravity_od(graph, free, zones, 300, .1)
    assert len(demand) == 6
    assert all(value == pytest.approx(50) for value in demand.values())
    config = SimpleNamespace(source="assignment", demand_source="gravity", zone_mass_csv=zones,
                             total_demand_pcu_h=300, gravity_lambda_per_min=.1,
                             capacity_csv=None, capacity_pcu_h=100, vdf="bpr", alpha=.15,
                             beta=4, relative_gap=1e-4, max_iterations=200,
                             period="demo", duration_h=1)
    result = prepare_traffic(graph, config, free)
    assert result.summary["demand_source"] == "gravity"
    assert result.summary["demand_pcu_h"] == pytest.approx(300)
    assert result.summary["mean_od_time_s"] > 60
    output = tmp_path / "traffic_od.csv"
    write_traffic_od_csv(result, output)
    with output.open(newline="") as stream:
        assert len(list(csv.DictReader(stream))) == 6
    _csv(zones, ["node", "mass"], [{"node": 0, "mass": 1},
                                    {"node": 1, "mass": 2}, {"node": 2, "mass": 2}])
    unbalanced = gravity_od(graph, free, zones, 300, .1)
    assert [sum(value for (u, _), value in unbalanced.items() if u == node)
            for node in graph] == pytest.approx([60, 120, 120])
    assert [sum(value for (_, v), value in unbalanced.items() if v == node)
            for node in graph] == pytest.approx([60, 120, 120])


def test_population_demand_and_road_attribute_capacities():
    graph = nx.MultiDiGraph()
    for origin, destination in ((0, 1), (1, 0), (0, 2), (2, 0), (1, 2), (2, 1)):
        attrs = {"length": 1000, "lanes": "2", "width": "7 m"}
        graph.add_edge(origin, destination, key=0, **attrs)
    edges = list(graph.edges(keys=True))
    free = {edge: 60 for edge in edges}
    demand = population_gravity_od(graph, free, [10, 20, 0], .1, .08)
    assert sum(demand.values()) == pytest.approx(3)
    assert demand == pytest.approx({(0, 1): 1.5, (1, 0): 1.5})

    graph[0][1][0]["oneway"] = True
    del graph[1][2][0]["lanes"]
    del graph[0][2][0]["lanes"]
    del graph[0][2][0]["width"]
    config = SimpleNamespace(source="assignment", demand_source="population", od_csv=None,
        zone_mass_csv=None, total_demand_pcu_h=None, gravity_lambda_per_min=.08,
        population_trip_rate_per_person_h=.1, population_zone_limit=100,
        capacity_csv=None, capacity_pcu_h=None,
        road_capacity_pcu_h_per_lane=1000, default_lanes_per_direction=1,
        lane_width_m=3.5, vdf="bpr", alpha=.15, beta=4, relative_gap=1e-4,
        max_iterations=20, period="demo", duration_h=1, closure_top_n=0)
    result = prepare_traffic(graph, config, free, [10, 20, 0])
    assert result.summary["capacity_source"] == "road_attributes"
    assert result.summary["demand_pcu_h"] == pytest.approx(3)
    assert result.summary["capacity_tag_coverage"] == {
        "lanes_tagged": 4, "width_tagged": 1, "fallback": 1, "invalid_tag_arcs": 0}
    by_edge = {(row["u"], row["v"]): row for row in result.rows}
    assert by_edge[("0", "1")]["effective_lanes"] == 2
    assert by_edge[("1", "2")]["capacity_source"] == "width_inferred_lanes"
    assert by_edge[("0", "2")]["capacity_source"] == "default_lanes"


def test_physical_closure_reassignment_and_disconnection(tmp_path):
    graph = _graph((0, 1, 0), (0, 2, 0), (2, 1, 0))
    free = {edge: 60 for edge in graph.edges(keys=True)}
    od = tmp_path / "od.csv"
    _csv(od, ["origin", "destination", "demand_pcu_h"],
         [{"origin": 0, "destination": 1, "demand_pcu_h": 100}])
    config = SimpleNamespace(source="assignment", demand_source="od_csv", od_csv=od,
                             capacity_csv=None, capacity_pcu_h=100, vdf="bpr", alpha=.15,
                             beta=4, relative_gap=1e-4, max_iterations=200,
                             period="demo", duration_h=1, closure_top_n=1)
    result = prepare_traffic(graph, config, free)
    links = [{"link_id": i, "osm_way_ids": str(i), "is_self_loop": False,
              "_edges": (edge,)} for i, edge in enumerate(graph.edges(keys=True))]
    closures = evaluate_closures(graph, links, result, free, config)
    assert closures[0]["link_id"] == 0
    assert closures[0]["newly_unreachable_demand_pcu_h"] == 0
    assert closures[0]["delta_tstt_pcu_hours"] == pytest.approx(100 * 69 / 3600)
    output = tmp_path / "traffic_closures.csv"
    write_traffic_closures_csv(result, output)
    with output.open(newline="") as stream:
        assert len(list(csv.DictReader(stream))) == 1

    single = _graph((0, 1, 0))
    one = (0, 1, 0)
    isolated = prepare_traffic(single, config, {one: 60})
    closed = evaluate_closures(single, links[:1], isolated, {one: 60}, config)[0]
    assert closed["newly_unreachable_demand_pcu_h"] == 100
    assert closed["delta_tstt_pcu_hours"] is None


def test_pipeline_exports_traffic_and_uses_congested_times(tmp_path):
    import geopandas as gpd
    import json
    import osmnx as ox

    from georesilience.config import RunConfig
    from georesilience.pipeline import run
    from tests.helpers.small_inputs import raster_fixture

    graph = nx.MultiDiGraph(crs="EPSG:32644", simplified=True)
    for node, (x, y) in enumerate(((500000, 1900000), (501000, 1900000),
                                   (500500, 1900866))):
        graph.add_node(node, x=x, y=y)
    for way, (u, v) in enumerate(((0, 1), (1, 2), (2, 0)), 1):
        for a, b in ((u, v), (v, u)):
            graph.add_edge(a, b, osmid=way, highway="residential", length=1000,
                           maxspeed=60)
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    source = input_dir / "roads.graphml"
    ox.save_graphml(graph, source)
    population, _ = raster_fixture(input_dir)
    od = tmp_path / "traffic_od.csv"
    _csv(od, ["origin", "destination", "demand_pcu_h"],
         [{"origin": 0, "destination": 1, "demand_pcu_h": 100}])
    config = RunConfig(
        input={"source": "graphml", "path": source, "directory": input_dir}, cleaning={"consolidate": False},
        population={"worldpop": population, "snap_max_m": 500},
        analysis={"n_jobs": 1, "max_memory_gb": .1},
        robustness={"fraction": .5, "steps": 1},
        reliability={"samples": 32}, travel_time={"samples": 32},
        traffic={"enabled": True, "od_csv": od, "capacity_pcu_h": 100,
                 "closure_top_n": 1},
        output={"dir": tmp_path / "results", "figures": False})
    summary = run(config)
    assert summary["traffic"]["status"] == "converged"
    assert summary["traffic"]["arc_count"] == 6
    assert summary["traffic"]["mean_od_time_s"] == pytest.approx(69)
    assert len(list(csv.DictReader((config.output.dir / "traffic_arcs.csv").open()))) == 6
    assert len(list(csv.DictReader((config.output.dir / "traffic_closures.csv").open()))) == 1
    arcs = gpd.read_file(config.output.dir / "network.gpkg", layer="traffic_arcs")
    assert len(arcs) == 6
    assert arcs.congested_time_s.max() == pytest.approx(69)
    manifest = json.loads((config.output.dir / "run_manifest.json").read_text())
    assert manifest["resolved_config"]["traffic"]["enabled"]
