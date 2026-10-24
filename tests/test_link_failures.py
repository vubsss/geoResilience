"""Cleaned physical-link failure probabilities and bound CSV templates."""

import csv
import json

import osmnx as ox
import pytest

from georesilience.config import ReliabilityConfig, RunConfig
from georesilience.failure_probabilities import (
    compute_failure_probabilities, export_edge_template, probabilities_at_p0, read_failure_csv,
)
from georesilience.links import _link_rows, identify_links
from georesilience.network import load_and_clean
from tests.helpers.small_inputs import junction_graph, xml_fixture
from tests.test_link_identity import parallel_graph


TEMPLATE_COLUMNS = ["link_uid", "osm_way_ids", "u", "v", "length_m", "name", "highway", "p_fail"]


def write_failure_csv(path, fingerprint, rows, fields=None):
    with path.open("w", newline="", encoding="utf-8") as stream:
        stream.write(f"# georesilience_fingerprint={fingerprint}\n")
        writer = csv.DictWriter(stream, fieldnames=fields or ["link_uid", "p_fail"])
        writer.writeheader()
        writer.writerows(rows)
    return path


def bound_parallel_graph():
    graph = parallel_graph()
    return graph, identify_links(graph, "test-input-cleaning-fingerprint")


@pytest.mark.parametrize("source", ["graphml", "osm_xml"])
def test_clean_local_network_export_edit_and_probability_roundtrip(tmp_path, source):
    if source == "graphml":
        road_path = tmp_path / "roads.graphml"
        ox.save_graphml(junction_graph(), filepath=road_path)
    else:
        road_path = xml_fixture(tmp_path / "roads.osm")
    graph, _, _ = load_and_clean(RunConfig(
        input={"source": source, "path": road_path}, cleaning={"consolidate": False}))
    fingerprint = graph.graph["input_cleaning_fingerprint"]
    links = _link_rows(graph)
    target = tmp_path / "edge_failures.csv"
    content = export_edge_template(graph, target)
    assert target.read_text() == content
    assert f"# georesilience_fingerprint={fingerprint}" in content.splitlines()
    records = csv.DictReader(line for line in content.splitlines() if not line.startswith("#"))
    assert records.fieldnames == TEMPLATE_COLUMNS
    rows = list(records)
    assert {row["link_uid"] for row in rows} == {link["link_uid"] for link in links}
    assert all(row["p_fail"] == "" for row in rows)
    for index, row in enumerate(rows, 1):
        row["p_fail"] = str(index / (len(rows) + 1))
    write_failure_csv(target, fingerprint, rows, fields=TEMPLATE_COLUMNS)
    values, metadata = read_failure_csv(target, links, fingerprint, require_complete=True)
    assert values == {row["link_uid"]: float(row["p_fail"]) for row in rows}
    assert metadata["blank_values"] == 0
    result = compute_failure_probabilities(graph, links, ReliabilityConfig(
        p_fail_csv=target, require_complete_failures=True))
    assert result.user_probabilities == values
    for link in links:
        metrics = result.link_metrics[link["link_id"]]
        assert metrics == {"p_fail": values[link["link_uid"]], "p_fail_source": "user"}
        for u, v, key in link["_edges"]:
            assert graph.edges[u, v, key]["p_fail"] == metrics["p_fail"]
    coverage = result.summary["coverage"]
    assert coverage["by_source"]["user"]["links"] == len(links)
    assert coverage["by_source"]["proxy"]["links"] == 0
    assert coverage["by_source"]["user"]["length_pct"] == 100
    json.dumps(result.summary, allow_nan=False)


def test_template_rejects_reuse_after_changed_cleaning_settings(tmp_path):
    road_path = tmp_path / "roads.graphml"
    ox.save_graphml(junction_graph(), filepath=road_path)
    config = RunConfig(input={"source": "graphml", "path": road_path},
                       cleaning={"consolidate": False})
    graph, _, _ = load_and_clean(config)
    target = tmp_path / "edge_failures.csv"
    export_edge_template(graph, target)
    changed = config.model_copy(update={"cleaning": config.cleaning.model_copy(
        update={"tolerance_m": config.cleaning.tolerance_m + 1})})
    other, _, _ = load_and_clean(changed)
    assert graph.graph["input_cleaning_fingerprint"] != other.graph["input_cleaning_fingerprint"]
    with pytest.raises(ValueError, match="(?i)fingerprint|cleaning|mismatch"):
        read_failure_csv(target, _link_rows(other), other.graph["input_cleaning_fingerprint"])


def test_parallel_roads_with_shared_way_ids_keep_independent_user_probabilities(tmp_path):
    graph, links = bound_parallel_graph()
    target = write_failure_csv(tmp_path / "parallel.csv", graph.graph["input_cleaning_fingerprint"], [
        {"link_uid": links[0]["link_uid"], "p_fail": 0},
        {"link_uid": links[1]["link_uid"], "p_fail": 1},
    ])
    result = compute_failure_probabilities(graph, links, ReliabilityConfig(p_fail_csv=target))
    assert [result.link_metrics[link["link_id"]]["p_fail"] for link in links] == [0, 1]
    assert result.summary["coverage"]["by_source"]["user"]["links"] == 2


def test_multiway_link_user_probability_is_one_physical_link_probability():
    graph = parallel_graph()
    for _, _, _, data in graph.edges(keys=True, data=True):
        data["osmid"] = [100, 200]
    links = identify_links(graph, "multiway-fingerprint")
    values = {link["link_uid"]: .25 for link in links}
    assert probabilities_at_p0(links, values, .99) == {link["link_id"]: .25 for link in links}


@pytest.mark.parametrize("invalid_probability", ["-0.1", "1.1", "nan", "inf", "-inf", "banana"])
def test_invalid_probability_names_data_row(tmp_path, invalid_probability):
    graph, links = bound_parallel_graph()
    target = write_failure_csv(tmp_path / "invalid.csv", graph.graph["input_cleaning_fingerprint"], [
        {"link_uid": links[0]["link_uid"], "p_fail": invalid_probability},
    ])
    with pytest.raises(ValueError, match="(?i)row 1|p_fail"):
        read_failure_csv(target, links, graph.graph["input_cleaning_fingerprint"])


@pytest.mark.parametrize("invalid_uid", ["", "unknown-uid", "123", "1e3"])
def test_unknown_or_blank_link_ids_are_errors(tmp_path, invalid_uid):
    graph, links = bound_parallel_graph()
    target = write_failure_csv(tmp_path / "unknown.csv", graph.graph["input_cleaning_fingerprint"], [
        {"link_uid": invalid_uid, "p_fail": .1},
    ])
    with pytest.raises(ValueError, match="(?i)link_uid|unknown|network|empty"):
        read_failure_csv(target, links, graph.graph["input_cleaning_fingerprint"])


def test_duplicate_link_ids_are_errors_even_when_one_value_is_blank(tmp_path):
    graph, links = bound_parallel_graph()
    target = write_failure_csv(tmp_path / "duplicate.csv", graph.graph["input_cleaning_fingerprint"], [
        {"link_uid": links[0]["link_uid"], "p_fail": ""},
        {"link_uid": links[0]["link_uid"], "p_fail": .2},
    ])
    with pytest.raises(ValueError, match="(?i)duplicate"):
        read_failure_csv(target, links, graph.graph["input_cleaning_fingerprint"])


@pytest.mark.parametrize("fingerprint", [None, "other-input-or-cleaning"])
def test_csv_must_match_the_cleaned_input_fingerprint(tmp_path, fingerprint):
    graph, links = bound_parallel_graph()
    target = tmp_path / "unbound.csv"
    comment = "" if fingerprint is None else f"# georesilience_fingerprint={fingerprint}\n"
    target.write_text(comment + f"link_uid,p_fail\n{links[0]['link_uid']},.1\n")
    with pytest.raises(ValueError, match="(?i)fingerprint"):
        read_failure_csv(target, links, graph.graph["input_cleaning_fingerprint"])


def test_blank_probability_falls_back_and_zero_stays_user_covered(tmp_path):
    graph, links = bound_parallel_graph()
    target = write_failure_csv(tmp_path / "partial.csv", graph.graph["input_cleaning_fingerprint"], [
        {"link_uid": links[0]["link_uid"], "p_fail": "0"},
        {"link_uid": links[1]["link_uid"], "p_fail": " "},
    ])
    user, metadata = read_failure_csv(target, links, graph.graph["input_cleaning_fingerprint"])
    assert user == {links[0]["link_uid"]: 0}
    assert metadata["blank_values"] == 1
    result = compute_failure_probabilities(graph, links, ReliabilityConfig(p_fail_csv=target, p0=.01))
    assert result.link_metrics[links[0]["link_id"]] == {"p_fail": 0, "p_fail_source": "user"}
    assert result.link_metrics[links[1]["link_id"]] == {
        "p_fail": pytest.approx(1 - .99**.1), "p_fail_source": "proxy"}
    coverage = result.summary["coverage"]
    for source in ("user", "proxy"):
        assert coverage["by_source"][source]["links"] == 1
        assert coverage["by_source"][source]["length_m"] == pytest.approx(100)
        assert coverage["by_source"][source]["length_pct"] == 50
    assert coverage["by_source"]["user"]["length_pct"] == coverage["by_source"]["proxy"]["length_pct"] == 50


@pytest.mark.parametrize("missing_kind", ["blank", "omitted"])
def test_require_complete_rejects_blank_and_omitted_links(tmp_path, missing_kind):
    graph, links = bound_parallel_graph()
    rows = [{"link_uid": links[0]["link_uid"], "p_fail": .1}]
    if missing_kind == "blank":
        rows.append({"link_uid": links[1]["link_uid"], "p_fail": ""})
    target = write_failure_csv(tmp_path / "partial.csv", graph.graph["input_cleaning_fingerprint"], rows)
    with pytest.raises(ValueError, match="(?i)complete|missing|blank|coverage"):
        read_failure_csv(target, links, graph.graph["input_cleaning_fingerprint"], require_complete=True)
    with pytest.raises(ValueError, match="(?i)complete|missing|blank|coverage"):
        compute_failure_probabilities(graph, links, ReliabilityConfig(
            p_fail_csv=target, require_complete_failures=True))


def test_no_csv_uses_length_proxy_for_all_links_and_complete_mode_rejects_it():
    graph, links = bound_parallel_graph()
    result = compute_failure_probabilities(graph, links, ReliabilityConfig(p0=.01))
    assert result.user_probabilities == {}
    assert result.summary["coverage"]["by_source"]["proxy"]["links"] == 2
    assert all(row["p_fail"] == pytest.approx(1 - .99**.1) for row in result.link_metrics.values())
    with pytest.raises(ValueError, match="(?i)complete|missing|CSV|coverage"):
        compute_failure_probabilities(graph, links, ReliabilityConfig(require_complete_failures=True))
