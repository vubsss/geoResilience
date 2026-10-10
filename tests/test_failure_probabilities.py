import csv
import importlib.util
import json
import math

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
import pytest
import yaml

from georesilience.cli import main
from georesilience.config import ReliabilityConfig, RunConfig, load_config
from georesilience.failure_probabilities import (
    compute_failure_probabilities, export_edge_template, failure_probabilities_report,
    link_failure_probability, probabilities_at_p0, read_failure_csv,
)
from georesilience.links import _link_rows
from georesilience.pipeline import run


def demo_module():
    spec = importlib.util.spec_from_file_location("ticket08_demo", "examples/create_ticket08_demo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def coverage_graph():
    graph = nx.MultiDiGraph(crs="EPSG:32644", simplified=True)
    for node in range(3):
        graph.add_node(node, x=500000 + 100 * node, y=1900000)
    for u, v, length, ways in [(0, 1, 1000, 10), (1, 2, 2000, [20, 21]), (2, 0, 3000, 30)]:
        for a, b in [(u, v), (v, u)]:
            graph.add_edge(a, b, length=length, osmid=ways, name="Road, with punctuation")
    graph.add_edge(0, 0, length=0, osmid=999)
    return graph


def write_probabilities(path, text):
    path.write_text("# per event\nosm_way_id,p_fail,ignored\n" + text)
    return path


@pytest.mark.parametrize("length,ways,user,p0,expected", [
    (2000, [1], {}, .01, .0199),
    (1000, [1, 2], {1: .1, 2: .1}, .01, .19),
    (1000, [1, 2], {1: .1, 2: .3}, .01, .37),
    (3000, [1, 2], {1: .1}, .01, 1 - .9 * .99**1.5),
    (2000, [], {}, .01, .0199),
    (1000, [1, 1, 1], {1: .1}, .01, .1),
    (1000, [1, 2], {1: 0, 2: 0}, 1, 0),
    (1000, [1, 2], {1: 1}, 0, 1),
    (1000, [1, 2], {1: 0}, 1, 1),
    (1000, [1], {}, 0, 0),
])
def test_known_answers_and_boundaries(length, ways, user, p0, expected):
    assert link_failure_probability(length, ways, user, p0) == pytest.approx(expected)


def test_tiny_probabilities_do_not_round_to_zero():
    p = link_failure_probability(.001, [1], {}, 1e-12)
    assert p == pytest.approx(1e-18, rel=1e-10, abs=0)
    assert link_failure_probability(1000, [1], {1: 1e-18}, .01) == pytest.approx(1e-18, abs=0)


@pytest.mark.parametrize("length,p0", [(0, .01), (-1, .01), (math.nan, .01), (math.inf, .01),
                                       (1000, -.01), (1000, 1.01), (1000, math.nan)])
def test_invalid_library_inputs(length, p0):
    with pytest.raises(ValueError):
        link_failure_probability(length, [1], {}, p0)


@pytest.mark.parametrize("settings", [{"p0": -.1}, {"p0": 1.1}, {"p0": math.nan},
                                      {"p0_sweep": [.01, math.inf]}, {"p0_sweep": [-.1]}])
def test_config_validation(settings):
    with pytest.raises(ValueError, match="p0"):
        ReliabilityConfig(**settings)


def test_primary_sweep_inclusion_and_deduplication():
    assert ReliabilityConfig(p0=.02, p0_sweep=[.05, .001, .05]).p0_sweep == [.001, .02, .05]
    assert ReliabilityConfig(p0=.02, p0_sweep=[]).p0_sweep == [.02]
    assert ReliabilityConfig().p0_sweep == [.001, .01, .05]


def test_template_roundtrip_multiple_ways_parallel_and_loop(tmp_path):
    graph = demo_module().exact_graph()
    graph.add_edge(0, 0, length=0, osmid=999)
    content = export_edge_template(graph, tmp_path / "template.csv")
    assert content.startswith("# p_fail = probability")
    assert "not an annual rate" in content and "equally" in content
    rows = list(csv.DictReader(line for line in content.splitlines() if not line.startswith("#")))
    assert [int(row["osm_way_id"]) for row in rows] == [101, 201, 202, 301, 401, 402, 501, 502]
    assert all(row["p_fail"] == "" for row in rows)
    assert sum(float(row["length_m"]) for row in rows) == 10000
    assert float(next(row for row in rows if row["osm_way_id"] == "201")["length_m"]) == 1500
    for row in rows:
        row["p_fail"] = .1
    with (tmp_path / "filled.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    links = _link_rows(graph)
    result = compute_failure_probabilities(graph, links, ReliabilityConfig(p_fail_csv=tmp_path / "filled.csv"))
    for link in links:
        metrics = result.link_metrics[link["link_id"]]
        if link["is_self_loop"]:
            assert metrics == {"p_fail": None, "p_fail_source": None}
        else:
            assert metrics["p_fail_source"] == "user"
            expected = 1 - .9**len(link["osm_way_ids"].split(","))
            assert metrics["p_fail"] == pytest.approx(expected)
            for u, v, key in link["_edges"]:
                assert graph.edges[u, v, key]["p_fail"] == metrics["p_fail"]
    two_way_one_way = [link for link in links if link["oneway"] and link["osm_way_ids"] == "401,402"]
    assert len(two_way_one_way) == 1
    assert result.link_metrics[two_way_one_way[0]["link_id"]]["p_fail"] == pytest.approx(.19)


def test_template_shared_way_counts_and_equal_share():
    graph = coverage_graph()
    graph.edges[0, 2, 0]["osmid"] = graph.edges[2, 0, 0]["osmid"] = [10, 30, 30]
    rows = list(csv.DictReader(line for line in export_edge_template(graph).splitlines()
                               if not line.startswith("#")))
    record = next(row for row in rows if row["osm_way_id"] == "10")
    assert record["n_links"] == "2"
    assert float(record["length_m"]) == 2500  # 1 km plus half of the 3 km physical link
    assert len(rows) == 4 and all("999" != row["osm_way_id"] for row in rows)
    assert record["name"] == "Road, with punctuation"


@pytest.mark.parametrize("text,expected", [
    ("10,-0.1,x\n", "data row 1"), ("10,1.1,x\n", "data row 1"),
    ("10,banana,x\n", "data row 1"), ("10,NaN,x\n", "data row 1"),
    ("10,inf,x\n", "data row 1"), ("10,.1,x\n010,.2,x\n", "duplicate"),
    ("1e3,.1,x\n", "integer"), (",.1,x\n", "integer"),
    ("9999,garbage,x\n", "data row 1"),
])
def test_csv_validation_names_offending_data_rows(tmp_path, text, expected):
    path = write_probabilities(tmp_path / "bad.csv", text)
    with pytest.raises(ValueError, match=expected):
        read_failure_csv(path, {10})


def test_csv_reports_all_bad_rows_and_required_columns(tmp_path):
    path = write_probabilities(tmp_path / "bad.csv", "10,-.1,x\n20,2,x\n30,no,x\n")
    with pytest.raises(ValueError) as exc:
        read_failure_csv(path, {10, 20, 30})
    assert all(f"data row {number}" in str(exc.value) for number in (1, 2, 3))
    path.write_text("osm_way_id,something_else\n10,.1\n")
    with pytest.raises(ValueError, match="missing columns: p_fail"):
        read_failure_csv(path, {10})
    path.write_text("# no data\n")
    with pytest.raises(ValueError, match="invalid CSV"):
        read_failure_csv(path, {10})


def test_extra_csv_cells_cannot_shift_way_ids(tmp_path):
    path = tmp_path / "shifted.csv"
    path.write_text("osm_way_id,p_fail\n123,456,.2\n")
    with pytest.raises(ValueError, match="invalid CSV"):
        read_failure_csv(path, {123, 456})


def test_csv_blank_unknown_comment_large_id_and_warning_cap(tmp_path):
    big = 9007199254740993
    text = f"{big},0,ignored\n# midway comment\n10, ,ignored\n"
    text += "".join(f"{way},.2,ignored\n" for way in range(100, 125))
    values, warnings = read_failure_csv(write_probabilities(tmp_path / "warnings.csv", text), {10, big})
    assert values == {big: 0}
    assert warnings["blank_values"] == 1 and warnings["user_ids_unmatched"] == 25
    assert warnings["total_count"] == 26 and len(warnings["shown"]) == 20
    assert warnings["omitted_count"] == 6
    # A neighboring large ID remains distinct, with no conversion through float.
    path = write_probabilities(tmp_path / "large.csv", f"{big},.1,x\n{big-1},.2,x\n")
    values, _ = read_failure_csv(path, {big, big-1})
    assert values == {big: .1, big-1: .2}


def test_coverage_and_warning_use_uncovered_mixed_length(tmp_path):
    graph = coverage_graph()
    path = write_probabilities(tmp_path / "partial.csv", "10,0,x\n20,.1,x\n21,,x\n999,.2,x\n")
    result = compute_failure_probabilities(graph, _link_rows(graph), ReliabilityConfig(p_fail_csv=path))
    coverage = result.summary["coverage"]
    assert coverage["non_self_loop_links"] == 3 and coverage["total_length_km"] == 6
    assert coverage["user_length_km"] == 2 and coverage["proxy_length_km"] == 4
    assert coverage["user_length_pct"] == pytest.approx(100 / 3)
    assert coverage["proxy_length_pct"] == pytest.approx(200 / 3)
    for source, length in [("user", 1), ("mixed", 2), ("proxy", 3)]:
        row = coverage["by_source"][source]
        assert row["links"] == 1 and row["links_pct"] == pytest.approx(100 / 3)
        assert row["length_km"] == length and row["length_pct"] == pytest.approx(100 * length / 6)
    report = "\n".join(failure_probabilities_report(result.summary))
    assert "WARNING: 66.7% of network length uses the length proxy" in report
    assert "CSV warnings: 2 total; 2 shown; 0 omitted" in report
    assert coverage["user_ids_unmatched"] == 1  # self-loop-only ID is unmatched
    json.dumps(result.summary, allow_nan=False)


@pytest.mark.parametrize("length,user,warn", [(1000, {}, False), (1000, {10: 0}, True),
                                              (1000, {20: .1}, True), (2000, {10: .1}, False),
                                              (1000, {10: .1, 20: .1}, False),
                                              (1999.9, {10: .1}, True), (2000.1, {10: .1}, False)])
def test_proxy_warning_boundary(tmp_path, length, user, warn):
    graph = coverage_graph()
    # Remove third road and self-loop; vary supplied coverage across the 50% boundary.
    graph.remove_edges_from([(2, 0, 0), (0, 2, 0), (0, 0, 0)])
    graph.edges[0, 1, 0]["length"] = graph.edges[1, 0, 0]["length"] = length
    path = write_probabilities(tmp_path / "user.csv", "".join(f"{way},{p},x\n" for way, p in user.items()))
    result = compute_failure_probabilities(graph, _link_rows(graph), ReliabilityConfig(p_fail_csv=path))
    report = "\n".join(failure_probabilities_report(result.summary))
    assert ("% of network length uses the length proxy" in report) is warn


def test_missing_way_ids_empty_and_self_loop_only_graphs():
    graph = coverage_graph()
    for _, _, _, data in graph.edges(keys=True, data=True):
        data.pop("osmid", None)
    result = compute_failure_probabilities(graph, _link_rows(graph), ReliabilityConfig())
    assert result.summary["coverage"]["by_source"]["proxy"]["links"] == 3
    assert "osm_way_id" in export_edge_template(graph)
    assert len(export_edge_template(graph).splitlines()) == 3  # comments + header only
    graph.remove_edges_from(list(graph.edges(keys=True)))
    graph.add_edge(0, 0, length=0, osmid=10)
    result = compute_failure_probabilities(graph, _link_rows(graph), ReliabilityConfig())
    assert result.summary["coverage"]["total_length_km"] == 0
    assert result.summary["coverage"]["user_length_pct"] == 0
    graph.remove_edges_from(list(graph.edges(keys=True)))
    assert probabilities_at_p0(_link_rows(graph), {}, .01) == {}


@pytest.mark.parametrize("seed", [7, 42, 84])
def test_200_node_spatial_reference_monotonicity_and_reproducibility(seed):
    module = demo_module()
    graph, manifest = module.spatial_graph(200, seed)
    again, repeat_manifest = module.spatial_graph(200, seed)
    assert manifest == repeat_manifest
    links = _link_rows(graph)
    assert [(row["osm_way_ids"], row["length_m"]) for row in links] == [
        (row["osm_way_ids"], row["length_m"]) for row in _link_rows(again)]
    rng = np.random.default_rng(seed)
    ids = sorted({int(way) for link in links for way in link["osm_way_ids"].split(",")})
    user = {way: float(rng.uniform(0, 1)) for way in ids[::3]}
    results = [probabilities_at_p0(links, user, p0) for p0 in [0, .001, .01, .05, 1]]
    for link in links:
        ways = set(map(int, link["osm_way_ids"].split(",")))
        covered = ways & user.keys()
        for p0, calculated in zip([0, .001, .01, .05, 1], results):
            expected = 1 - math.prod(1-user[way] for way in covered) * (
                (1-p0)**(link["length_m"] / 1000 * (1-len(covered)/len(ways))))
            assert calculated[link["link_id"]] == pytest.approx(expected, abs=1e-14)
        values = [result[link["link_id"]] for result in results]
        assert all(0 <= p <= 1 for p in values) and values == sorted(values)
        if covered == ways:
            assert len(set(values)) == 1
        u, v = link["_u"], link["_v"]
        distance = math.dist([graph.nodes[u]["x"], graph.nodes[u]["y"]],
                             [graph.nodes[v]["x"], graph.nodes[v]["y"]])
        assert distance <= link["length_m"] <= distance * 1.3
    assert link_failure_probability(2000, [1], {}, .01) > link_failure_probability(1000, [1], {}, .01)


def test_template_cli_runs_only_cleaning_and_refuses_overwrite(tmp_path, monkeypatch, capsys):
    graph = nx.MultiDiGraph(crs="EPSG:32644")
    for node in range(3):
        graph.add_node(node, x=500000 + 100 * node, y=1900000)
    for u, v, length, way in [(0, 1, 500, 10), (1, 2, 1500, 20)]:
        for a, b in [(u, v), (v, u)]:
            graph.add_edge(a, b, length=length, osmid=way)
    source = tmp_path / "raw.graphml"
    ox.save_graphml(graph, filepath=source)
    config = tmp_path / "run.yaml"
    config.write_text(yaml.safe_dump({"input": {"path": str(source)}, "cleaning": {"consolidate": False},
                                     "output": {"dir": str(tmp_path / "analysis")},
                                     "reliability": {"p_fail_csv": "does-not-exist.csv"}}))
    def forbidden(*args, **kwargs):
        raise AssertionError("template must not run analysis")
    monkeypatch.setattr("georesilience.cli.run", forbidden)
    target = tmp_path / "templates" / "roads.csv"
    argv = ["template", "--config", str(config), "--out", str(target)]
    assert main(argv) == 0
    assert not (tmp_path / "analysis").exists()
    rows = list(csv.DictReader(line for line in target.read_text().splitlines() if not line.startswith("#")))
    assert len(rows) == 2
    assert all(float(row["length_m"]) == 1000 and row["n_links"] == "1" for row in rows)
    original = target.read_bytes()
    assert main(argv) == 2 and "use --overwrite" in capsys.readouterr().err
    assert target.read_bytes() == original
    assert main([*argv, "--overwrite"]) == 0


def test_four_demo_scenarios_pipeline_outputs_and_resolved_config(tmp_path):
    module = demo_module()
    folder = tmp_path / "demo"
    manifest = module.create_examples(folder, n=20, seed=42)
    for name in manifest["scenarios"]:
        config = load_config(folder / f"{name}.yaml")
        config.analysis.n_jobs = 1
        out = tmp_path / name
        summary = run(config, out)
        coverage = summary["reliability"]["coverage"]
        assert coverage["p0_sweep"] == [.001, .01, .05]
        edges = gpd.read_file(out / "network.gpkg", layer="edges")
        with (folder / f"{name}-expected.csv").open() as stream:
            expected = {row["name"]: row for row in csv.DictReader(stream)}
        for row in edges.itertuples():
            assert row.p_fail == pytest.approx(float(expected[row.name]["expected_p_fail"]))
            assert row.p_fail_source == expected[row.name]["expected_source"]
        assert json.loads(json.dumps(summary, allow_nan=False)) == json.loads((out / "summary.json").read_text())
        report = (out / "report.txt").read_text()
        assert "Failure probabilities" in report and "ONE event/scenario" in report
        assert report.isascii() and max(map(len, report.splitlines())) <= 100
        resolved = load_config(out / "run_config.yaml")
        assert resolved.reliability == config.reliability
        if name == "spatial-proxy":
            assert coverage["by_source"]["proxy"]["links_pct"] == 100
        elif name == "spatial-user":
            assert coverage["by_source"]["user"]["links_pct"] == 100
        elif name == "spatial-mixed":
            assert all(row["links"] > 0 for row in coverage["by_source"].values())
            assert coverage["user_ids_unmatched"] == 1


def test_bad_csv_stops_before_expensive_analysis(tmp_path, monkeypatch):
    graph = coverage_graph()
    source = tmp_path / "graph.graphml"
    ox.save_graphml(graph, filepath=source)
    path = write_probabilities(tmp_path / "bad.csv", "10,wrong,x\n")
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid CSV must fail before centrality work")
    monkeypatch.setattr("georesilience.pipeline.compute_centralities", forbidden)
    config = RunConfig(input={"path": source}, cleaning={"consolidate": False},
                       reliability={"p_fail_csv": path}, output={"dir": tmp_path / "results"})
    with pytest.raises(ValueError, match="data row 1"):
        run(config)
