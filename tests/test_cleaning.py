"""Offline local-road loading, filtering, cleaning and provenance contracts."""

import networkx as nx
import osmnx as ox
import pytest

from georesilience.config import RunConfig
from georesilience.links import _link_rows
from georesilience.network import EXTRA_WAY_TAGS, load_and_clean
from tests.helpers.small_inputs import junction_graph, xml_fixture


def graph_config(tmp_path, graph, **options):
    path = tmp_path / "roads.graphml"
    ox.save_graphml(graph, filepath=path)
    return RunConfig(input={"source": "graphml", "path": path},
        output={"dir": tmp_path / "results", "figures": False}, **options)


def test_xml_drive_filter_is_applied_before_simplification_and_recorded(tmp_path):
    path = xml_fixture(tmp_path / "roads.osm")
    config = RunConfig(input={"source": "osm_xml", "path": path}, cleaning={"consolidate": False})
    graph, meta, stats = load_and_clean(config)
    assert [row["osm_way_ids"] for row in _link_rows(graph)] == ["103"]
    assert stats["raw"]["link_count"] == 7
    assert stats["filtered"]["link_count"] == 1
    assert meta["network_type_applied"] == "drive"
    assert meta["osm_download_utc"] is None
    assert meta["study_boundary_wkt"] is None
    assert meta["input"]["path"] == str(path.resolve())
    assert set(EXTRA_WAY_TAGS) <= set(ox.settings.useful_tags_way)
    assert graph.graph["input_cleaning_fingerprint"]


def test_xml_all_retains_road_classes_without_drive_filter(tmp_path):
    path = xml_fixture(tmp_path / "roads.osm")
    _, meta, stats = load_and_clean(RunConfig(input={"source": "osm_xml", "path": path},
        network={"type": "all"}, cleaning={"consolidate": False}))
    # Every disjoint XML segment reaches simplification. Component retention
    # subsequently selects one, independently of the road-class filter.
    assert stats["simplified"]["link_count"] == 7
    assert stats["raw"]["link_count"] == stats["filtered"]["link_count"]
    assert meta["network_type_applied"] == "as-provided"


@pytest.mark.parametrize("network_type", ["drive", "all"])
def test_graphml_filter_provenance_is_as_provided(tmp_path, network_type):
    graph = junction_graph()
    nx.set_edge_attributes(graph, "footway", "highway")
    nx.set_edge_attributes(graph, "private", "access")
    cleaned, meta, stats = load_and_clean(graph_config(tmp_path, graph,
        network={"type": network_type}, cleaning={"consolidate": False}))
    assert len(cleaned) == 8
    assert len(_link_rows(cleaned)) == 8
    assert all(data["highway"] == "footway" for _, _, data in cleaned.edges(data=True))
    assert meta["network_type_applied"] == "as-provided"
    assert meta["osm_download_utc"] is None
    assert "filtered" not in stats


@pytest.mark.parametrize("consolidate, expected_nodes", [(True, 5), (False, 8)])
def test_junction_consolidation_preserves_dead_ends(tmp_path, consolidate, expected_nodes):
    graph, meta, stats = load_and_clean(graph_config(tmp_path, junction_graph(),
        cleaning={"consolidate": consolidate}))
    assert len(graph) == expected_nodes
    if consolidate:
        assert sorted(dict(nx.Graph(graph).degree()).values()) == [1, 1, 1, 1, 4]
    assert stats["consolidation_enabled"] is consolidate
    assert stats["dead_ends"] == {"before": 4, "after": 4}
    assert stats["final"]["node_count"] == len(graph)
    assert stats["final"]["link_count"] == len(_link_rows(graph))
    assert meta["network_type_applied"] == "as-provided"


def test_real_consolidation_rejects_lost_cul_de_sac(tmp_path):
    graph = junction_graph()
    graph.add_node(8, x=499990, y=1900010)
    for u, v in ((0, 8), (8, 0)):
        graph.add_edge(u, v, length=7.1, osmid=99)
    with pytest.raises(ValueError, match="degree-1 node count changed"):
        load_and_clean(graph_config(tmp_path, graph))


def test_strong_component_drop_counts_match_retained_physical_links(tmp_path):
    graph = junction_graph()
    graph.add_node(100, x=501000, y=1900000)
    graph.add_node(101, x=501100, y=1900000)
    for u, v in ((100, 101), (101, 100)):
        graph.add_edge(u, v, length=100, osmid=100)
    graph.add_node(102, x=502000, y=1900000)
    graph.add_edge(4, 102, length=1000, osmid=101)
    cleaned, _, stats = load_and_clean(graph_config(tmp_path, graph, cleaning={"consolidate": False}))
    dropped = stats["dropped_components"]
    assert dropped["count"] == 2
    assert dropped["nodes_dropped"] == 3
    assert dropped["length_dropped_km"] == pytest.approx(1.1)
    assert set(cleaned) == set(range(8))
    assert nx.is_strongly_connected(cleaned)
    links = _link_rows(cleaned)
    assert stats["final"]["node_count"] == len(cleaned)
    assert stats["final"]["link_count"] == len(links)
    assert stats["final"]["total_length_km"] == pytest.approx(sum(row["length_m"] for row in links) / 1000)
    assert dropped["length_dropped_pct"] == pytest.approx(
        100 * dropped["length_dropped_km"] / stats["consolidated"]["total_length_km"])


def test_raw_simplification_counts_preserve_physical_length(tmp_path):
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    for node in range(3):
        graph.add_node(node, x=78.47 + node * .001, y=17.40)
    for u, v in ((0, 1), (1, 2)):
        graph.add_edge(u, v, length=100, osmid=1)
        graph.add_edge(v, u, length=100, osmid=1)
    cleaned, _, stats = load_and_clean(graph_config(tmp_path, graph, cleaning={"consolidate": False}))
    assert stats["raw"] == {"node_count": 3, "link_count": 2, "total_length_km": .2}
    assert stats["simplified"] == {"node_count": 2, "link_count": 1, "total_length_km": .2}
    assert len(_link_rows(cleaned)) == 1
    assert _link_rows(cleaned)[0]["length_m"] == 200


@pytest.mark.parametrize("source", ["graphml", "osm_xml"])
def test_missing_local_input_fails_before_outputs(tmp_path, source):
    output = tmp_path / "results"
    config = RunConfig(input={"source": source, "path": tmp_path / "missing"}, output={"dir": output})
    with pytest.raises(ValueError, match="input.path does not exist"):
        load_and_clean(config)
    assert not output.exists()


def test_empty_local_graph_is_rejected(tmp_path):
    graph = nx.MultiDiGraph(crs=32644, simplified=True)
    graph.add_node(0, x=500000, y=1900000)
    with pytest.raises(ValueError, match="network has no road edges"):
        load_and_clean(graph_config(tmp_path, graph, cleaning={"consolidate": False}))


def test_graphml_non_numeric_ids_are_preserved_as_supplied(tmp_path):
    graph = nx.relabel_nodes(junction_graph(), lambda node: f"junction-{node}")
    cleaned, meta, _ = load_and_clean(graph_config(tmp_path, graph, cleaning={"consolidate": False}))
    assert set(cleaned) == set(graph)
    assert meta["network_type_applied"] == "as-provided"


@pytest.mark.parametrize("length", [0, -1, float("nan"), float("inf")])
def test_invalid_lengths_fail_during_input_validation(tmp_path, length):
    graph = junction_graph()
    graph[0][1][0]["length"] = length
    with pytest.raises(ValueError, match="length"):
        load_and_clean(graph_config(tmp_path, graph, cleaning={"consolidate": False}))


def test_default_consolidation_keeps_tiny_fixture_bidirectional_links():
    from pathlib import Path
    from georesilience.metrics import compute_link_consequences
    source = Path(__file__).parent / "fixtures/tiny/roads.graphml"
    graph, _, _ = load_and_clean(RunConfig(input={"source": "graphml", "path": source}))
    links = _link_rows(graph)
    assert len(links) == 8
    assert all(len(row["_edges"]) == 2 and not row["oneway"] for row in links)
    result = compute_link_consequences(graph, [1] * len(graph), coverage="all")
    assert all(row["is_bridge"] for row in result.links)
    assert result.redundancy["bridge_redundancy"]["value"] == 0
