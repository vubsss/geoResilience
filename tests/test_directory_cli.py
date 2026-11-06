"""Offline directory CLI, public outputs, replay and safe replacement."""

import csv
import hashlib
import io
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import osmnx as ox
import pytest
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin

from tests.helpers.small_inputs import cell_graph, raster_fixture

CORE_FILES = {"network.gpkg", "summary.json", "attack_curve.csv", "report.txt", "run_manifest.json"}
STRUCTURAL_METRICS = {"bridge_redundancy", "detour_redundancy", "detour_no_alternative_share",
    "targeted_attack_robustness", "hansen_accessibility", "connectivity_reliability", "travel_time_reliability"}
WEIGHTED_METRICS = {"targeted_attack_robustness", "hansen_accessibility",
    "connectivity_reliability", "travel_time_reliability"}
NODE_METRICS = {"betweenness", "information_centrality", "information_centrality_pop",
    "hansen_accessibility", "hansen_accessibility_pop", "is_articulation", "accessibility_drop",
    "accessibility_drop_pop", "disconnected_pair_fraction", "disconnected_pair_fraction_pop",
    "evaluated", "null_reasons"}
EDGE_METRICS = {"edge_betweenness", "is_bridge", "detour_ratio", "detour_none", "efficiency_drop",
    "efficiency_drop_pop", "accessibility_drop", "accessibility_drop_pop", "disconnected_pair_fraction",
    "disconnected_pair_fraction_pop", "evaluated", "null_reasons"}
REMOVED_FIELDS = {"closeness", "straightness", "degree_centrality", "classification", "scorecard",
    "zones", "composite", "vuln", "vuln_k2", "rel_importance", "p_in_main", "p_tt_ok", "crit_rank"}


def invoke(arguments):
    from georesilience.cli import main
    try:
        return main(list(map(str, arguments)))
    except SystemExit as exc:
        return exc.code


def make_input(tmp_path, source="graphml", *, zero_population=False, speeds=True):
    directory = tmp_path / "input"
    directory.mkdir()
    values = np.zeros((3, 3), dtype="float32") if zero_population else None
    raster_path, affine = raster_fixture(directory, values=values)
    if source == "graphml":
        graph = cell_graph(affine)
        if speeds:
            for _, _, data in graph.edges(data=True):
                data["maxspeed"] = "40"
        road_path = directory / "arbitrary-road-name.graphml"
        ox.save_graphml(graph, filepath=road_path)
    else:
        road_path = directory / "arbitrary-road-name.osm.xml"
        speed_tag = '<tag k="maxspeed" v="40"/>' if speeds else ""
        road_path.write_text(f'''<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="georesilience-test">
  <node id="1" lat="17.4" lon="78.47"/>
  <node id="2" lat="17.4" lon="78.471"/>
  <way id="100"><nd ref="1"/><nd ref="2"/><tag k="highway" v="residential"/>{speed_tag}</way>
</osm>
''')
        affine = from_origin(78.469, 17.401, .001, .001)
        with rasterio.open(raster_path, "w", driver="GTiff", height=3, width=3, count=1,
                dtype="float32", crs=4326, transform=affine) as raster:
            raster.write(np.ones((3, 3), dtype="float32"), 1)
        graph = None
    return directory, road_path, raster_path, graph


def run_args(directory, output, *extra):
    return ["run", directory, "--out", output, "--no-consolidation", "--connectivity-samples", 8,
        "--travel-time-samples", 8, "--attack-fraction", 1, "--attack-steps", 3, "--jobs", 1,
        "--max-memory-gb", .1, "--no-figures", *extra]


def read_summary(output):
    return json.loads((output / "summary.json").read_text())


def assert_public_summary(summary):
    for group, expected in [("unweighted", STRUCTURAL_METRICS), ("population_weighted", WEIGHTED_METRICS)]:
        assert set(summary[group]) == expected
        for metric in summary[group].values():
            assert {"value", "definition", "reason"} <= metric.keys()
            assert metric["definition"]
            if metric["value"] is None:
                assert metric["reason"]
    assert not REMOVED_FIELDS & summary.keys()
    json.dumps(summary, allow_nan=False)


def snapshot_files(directory):
    return {str(path.relative_to(directory)): path.read_bytes()
            for path in directory.rglob("*") if path.is_file()}


@pytest.mark.parametrize("source", ["graphml", "osm_xml"])
def test_offline_cli_exact_files_public_schema_and_input_manifest(tmp_path, source):
    directory, road, raster, _ = make_input(tmp_path, source)
    output = tmp_path / "result"
    assert invoke(run_args(directory, output)) == 0
    assert {path.name for path in output.iterdir()} == CORE_FILES
    summary = read_summary(output)
    assert_public_summary(summary)
    nodes = gpd.read_file(output / "network.gpkg", layer="nodes")
    edges = gpd.read_file(output / "network.gpkg", layer="edges")
    assert NODE_METRICS | {"node_id", "population", "geometry"} <= set(nodes)
    assert EDGE_METRICS | {"link_uid", "p_fail", "p_fail_source", "geometry"} <= set(edges)
    assert not REMOVED_FIELDS & (set(nodes) | set(edges))
    assert "efficiency_drop" not in nodes and "efficiency_drop_pop" not in nodes
    assert edges.link_uid.is_unique
    assert nodes.population.sum() > 0
    manifest = json.loads((output / "run_manifest.json").read_text())
    assert {"inputs", "resolved_config", "boundary", "coverage", "cleaning", "versions", "seed",
            "probabilities", "time_model", "attack_removal_order"} <= manifest.keys()
    consumed = {Path(record["path"]).resolve() for record in manifest["inputs"]}
    assert consumed == {road.resolve(), raster.resolve()}
    for record in manifest["inputs"]:
        content = Path(record["path"]).read_bytes()
        assert record["role"]
        assert record["sha256"] == hashlib.sha256(content).hexdigest()
        assert record["size_bytes"] == len(content)
    assert manifest["seed"] == 42
    assert manifest["versions"]
    assert manifest["resolved_config"]["input"]["directory"] == str(directory.resolve())
    assert manifest["boundary"]["method"] == "retained_graph_extent_plus_snap"
    assert summary["unweighted"]["travel_time_reliability"]["value"] is not None


@pytest.mark.parametrize("source", ["graphml", "osm_xml"])
def test_cli_failure_template_edit_and_complete_roundtrip(tmp_path, source):
    directory, _, _, _ = make_input(tmp_path, source)
    template = tmp_path / "failures.csv"
    assert invoke(["failures-template", directory, "--out", template, "--no-consolidation"]) == 0
    lines = template.read_text().splitlines()
    comments = [line for line in lines if line.startswith("#")]
    reader = csv.DictReader(line for line in lines if not line.startswith("#"))
    fields, rows = reader.fieldnames, list(reader)
    assert fields == ["link_uid", "osm_way_ids", "u", "v", "length_m", "name", "highway", "p_fail"]
    assert rows and all(row["p_fail"] == "" for row in rows)
    stream = io.StringIO()
    stream.write("\n".join(comments) + "\n")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows({**row, "p_fail": "0"} for row in rows)
    template.write_text(stream.getvalue())
    output = tmp_path / "result"
    assert invoke(run_args(directory, output, "--failure-probs", template, "--require-complete-failures")) == 0
    edges = gpd.read_file(output / "network.gpkg", layer="edges")
    assert set(edges.p_fail_source) == {"user"}
    assert edges.p_fail.eq(0).all()
    assert read_summary(output)["unweighted"]["connectivity_reliability"]["value"] == 1
    manifest = json.loads((output / "run_manifest.json").read_text())
    assert template.resolve() in {Path(record["path"]).resolve() for record in manifest["inputs"]}


def test_optional_od_table_preserves_network_denominators(tmp_path):
    directory, _, _, graph = make_input(tmp_path)
    baseline, with_od = tmp_path / "baseline", tmp_path / "with-od"
    assert invoke(run_args(directory, baseline, "--p0", .5)) == 0
    projection = Transformer.from_crs(graph.graph["crs"], 4326, always_xy=True)
    origin = projection.transform(graph.nodes[0]["x"], graph.nodes[0]["y"])
    dest = projection.transform(graph.nodes[7]["x"], graph.nodes[7]["y"])
    od = tmp_path / "pairs.csv"
    with od.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["label", "origin_lon", "origin_lat", "dest_lon", "dest_lat"])
        writer.writerow(["home-to-work", *origin, *dest])
    assert invoke(run_args(directory, with_od, "--p0", .5, "--od-pairs", od)) == 0
    assert {path.name for path in with_od.iterdir()} == CORE_FILES | {"od_reliability.csv"}
    with (with_od / "od_reliability.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1 and rows[0]["label"] == "home-to-work"
    for weighting in ("unweighted", "population_weighted"):
        for metric in ("connectivity_reliability", "travel_time_reliability"):
            assert read_summary(baseline)[weighting][metric] == read_summary(with_od)[weighting][metric]


def test_named_p0_sweep_repeats_retained_reliability_measures(tmp_path):
    directory, _, _, _ = make_input(tmp_path)
    output = tmp_path / "result"
    assert invoke(run_args(directory, output, "--p0-sweep", "safe=0", "--p0-sweep", "closed=1")) == 0
    scenarios = read_summary(output)["reliability_scenarios"]
    assert {"safe", "closed"} <= scenarios.keys()
    for weighting in ("unweighted", "population_weighted"):
        for metric in ("connectivity_reliability", "travel_time_reliability"):
            assert scenarios["safe"][weighting][metric]["value"] == pytest.approx(1)
            assert scenarios["closed"][weighting][metric]["value"] == pytest.approx(0)


def test_allzero_population_retains_structural_results_and_weighted_reasons(tmp_path):
    directory, _, _, _ = make_input(tmp_path, zero_population=True)
    output = tmp_path / "result"
    assert invoke(run_args(directory, output)) == 0
    summary = read_summary(output)
    assert_public_summary(summary)
    for metric in summary["population_weighted"].values():
        assert metric["value"] is None and metric["reason"]
    assert summary["unweighted"]["connectivity_reliability"]["value"] is not None


def test_missing_speeds_has_explicit_travel_time_reason(tmp_path):
    directory, _, _, _ = make_input(tmp_path, speeds=False)
    output = tmp_path / "result"
    assert invoke(run_args(directory, output)) == 0
    for weighting in ("unweighted", "population_weighted"):
        metric = read_summary(output)[weighting]["travel_time_reliability"]
        assert metric["value"] is None and metric["reason"]


def test_output_inside_input_and_nonempty_without_overwrite_are_rejected(tmp_path):
    directory, _, _, _ = make_input(tmp_path)
    nested = directory / "results"
    assert invoke(run_args(directory, nested)) == 2
    assert not nested.exists()
    output = tmp_path / "result"
    output.mkdir()
    (output / "notes.txt").write_text("my analysis notes")
    before = snapshot_files(output)
    assert invoke(run_args(directory, output)) == 2
    assert snapshot_files(output) == before


def test_overwrite_preserves_unknown_files_and_removes_stale_generated_figures(tmp_path):
    from georesilience.figures import FIGURE_FILENAMES
    directory, _, _, _ = make_input(tmp_path)
    output = tmp_path / "result"
    assert invoke(run_args(directory, output)) == 0
    (output / "notes.txt").write_bytes(b"user notes\x00\xff")
    figures = output / "figures"
    figures.mkdir()
    (figures / "custom.txt").write_text("user figure notes")
    for name in FIGURE_FILENAMES:
        (figures / name).write_text("stale generated figure")
    assert invoke(run_args(directory, output, "--overwrite")) == 0
    assert (output / "notes.txt").read_bytes() == b"user notes\x00\xff"
    assert (figures / "custom.txt").read_text() == "user figure notes"
    assert {path.name for path in figures.iterdir()} == {"custom.txt"}


def test_invalid_probability_file_preserves_every_existing_result_byte(tmp_path):
    directory, _, _, _ = make_input(tmp_path)
    output = tmp_path / "result"
    assert invoke(run_args(directory, output)) == 0
    (output / "notes.txt").write_text("keep me")
    before = snapshot_files(output)
    bad = tmp_path / "wrong-fingerprint.csv"
    bad.write_text("# georesilience_fingerprint=wrong\nlink_uid,p_fail\nunknown,.5\n")
    assert invoke(run_args(directory, output, "--overwrite", "--failure-probs", bad)) == 2
    assert snapshot_files(output) == before


@pytest.mark.parametrize("bad_raster", ["missing_crs", "no_overlap"])
def test_population_validation_failure_leaves_new_output_absent(tmp_path, bad_raster):
    directory, _, path, _ = make_input(tmp_path)
    with rasterio.open(path) as raster:
        profile, values = raster.profile.copy(), raster.read(1)
    if bad_raster == "missing_crs":
        profile["crs"] = None
    else:
        profile["transform"] = from_origin(100000, 100000, 100, 100)
    with rasterio.open(path, "w", **profile) as raster:
        raster.write(values, 1)
    output = tmp_path / "result"
    assert invoke(run_args(directory, output)) == 2
    assert not output.exists()


def test_implicit_failure_csv_is_ignored(tmp_path):
    directory, _, _, _ = make_input(tmp_path)
    stale = directory / "link_failures.csv"
    stale.write_text("link_uid,p_fail\nstale,not-a-probability\n")
    output = tmp_path / "result"
    assert invoke(run_args(directory, output)) == 0
    assert set(gpd.read_file(output / "network.gpkg", layer="edges").p_fail_source) == {"proxy"}
    manifest = json.loads((output / "run_manifest.json").read_text())
    assert stale.resolve() not in {Path(record["path"]).resolve() for record in manifest["inputs"]}


@pytest.mark.parametrize("invalid", [["--jobs", "0"], ["--max-memory-gb", "nan"],
    ["--speed", "residential=-5"], ["--p0", "1.01"]])
def test_invalid_resources_speeds_and_probabilities_fail_before_output(tmp_path, invalid):
    directory, _, _, _ = make_input(tmp_path)
    output = tmp_path / "result"
    assert invoke(run_args(directory, output, *invalid)) == 2
    assert not output.exists()


def test_manifest_replay_reproduces_metrics_and_rejects_changed_consumed_file(tmp_path):
    from georesilience.pipeline import replay_manifest
    directory, _, raster, _ = make_input(tmp_path)
    output = tmp_path / "result"
    assert invoke(run_args(directory, output)) == 0
    manifest = output / "run_manifest.json"
    replayed = tmp_path / "replayed"
    replay_manifest(manifest, replayed)
    for weighting in ("unweighted", "population_weighted"):
        assert read_summary(output)[weighting] == read_summary(replayed)[weighting]
    assert (output / "attack_curve.csv").read_bytes() == (replayed / "attack_curve.csv").read_bytes()
    with rasterio.open(raster, "r+") as image:
        values = image.read(1)
        values[0, 0] += 1
        image.write(values, 1)
    failed = tmp_path / "changed-input"
    with pytest.raises(ValueError, match="(?i)hash|checksum|changed|fingerprint"):
        replay_manifest(manifest, failed)
    assert not failed.exists()


@pytest.mark.parametrize('options,match', [
    (['--service-mode', '2sfca'], 'require --facilities'),
    (['--service-importance', 'school=1'], 'require --facilities'),
    (['--facilities', 'missing.csv'], 'No such file'),
    (['--service-importance', 'clinic=1'], 'category'),
    (['--service-importance', 'school=nan'], 'finite'),
    (['--service-importance', 'school=0', '--service-importance', 'hospital=0'], 'positive category'),
    (['--service-importance', 'school=1', '--service-importance', 'school=2'], 'unique'),
    (['--service-catchment-minutes', 'school=0'], 'greater than 0'),
    (['--facility-snap-max-m', '-1'], 'greater than or equal'),
    (['--service-unit', 'school='], 'requires unique'),
    (['--service-mode', '2sfca'], 'catchment_minutes'),
])
def test_service_cli_contract_errors_before_output(tmp_path, capsys, options, match):
    from tests.test_service_inputs import facility_csv
    directory, _, _, _ = make_input(tmp_path)
    path = facility_csv(tmp_path)
    # Explicit no-file cases remain no-file; the rest exercise a valid local CSV.
    prefix = [] if match in ('require --facilities', 'No such file') else ['--facilities', path]
    output = tmp_path / 'result'
    assert invoke(run_args(directory, output, *prefix, *options)) == 2
    assert match in capsys.readouterr().err
    assert not output.exists()


def test_service_cli_settings_reach_run_and_default_remains_disabled(tmp_path, monkeypatch):
    from tests.test_service_inputs import facility_csv
    from georesilience import pipeline
    directory, _, _, _ = make_input(tmp_path)
    path = facility_csv(tmp_path)
    captured = []
    monkeypatch.setattr(pipeline, 'run', lambda config, **kwargs: captured.append(config))
    assert invoke(run_args(directory, tmp_path / 'none')) == 0
    assert captured[-1].services is None
    assert invoke(run_args(directory, tmp_path / 'with', '--facilities', path, '--service-mode', '2sfca',
        '--service-importance', 'school=2', '--service-catchment-minutes', 'school=12',
        '--service-unit', 'school=student_seats', '--facility-snap-max-m', '0')) == 0
    settings = captured[-1].services
    assert settings.school.importance == 2
    assert settings.school.catchment_seconds == 720
    assert settings.snap_max_m == 0
    assert settings.mode == 'sfca'
