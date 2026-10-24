import networkx as nx
import osmnx as ox
from shapely.geometry import LineString

from georesilience.config import CleaningConfig, NetworkConfig
from georesilience.links import _link_rows, cleaning_fingerprint, identify_links


def parallel_graph():
    graph = nx.MultiDiGraph(crs=32644, simplified=True)
    graph.add_node(0, x=500000, y=1900000)
    graph.add_node(1, x=500100, y=1900000)
    for _ in range(2):
        for u, v in [(0, 1), (1, 0)]:
            graph.add_edge(u, v, length=100, osmid=1)
    return graph


def test_identical_parallel_roads_remain_distinct_and_repeatable():
    graph = parallel_graph()
    links = identify_links(graph, "same-input")
    assert len(links) == 2 and all(len(row["_edges"]) == 2 for row in links)
    assert len({row["link_uid"] for row in links}) == 2
    assert [r["link_uid"] for r in links] == [r["link_uid"] for r in _link_rows(graph.copy())]
    reverse_insertion = nx.MultiDiGraph(**graph.graph)
    reverse_insertion.add_nodes_from(graph.nodes(data=True))
    reverse_insertion.add_edges_from(reversed(list(graph.edges(keys=True, data=True))))
    assert [r["link_uid"] for r in links] == [r["link_uid"] for r in _link_rows(reverse_insertion)]


def test_fingerprint_binds_input_bytes_and_cleaning_options(tmp_path):
    path = tmp_path / "roads.graphml"
    ox.save_graphml(parallel_graph(), filepath=path)
    network = NetworkConfig()
    baseline = cleaning_fingerprint(path, network, CleaningConfig())
    assert baseline == cleaning_fingerprint(path, network, CleaningConfig())
    assert baseline != cleaning_fingerprint(path, network, CleaningConfig(consolidate=False))
    assert baseline != cleaning_fingerprint(path, network, CleaningConfig(tolerance_m=20))
    before = identify_links(parallel_graph(), baseline)[0]["link_uid"]
    assert before != identify_links(parallel_graph(), "different")[0]["link_uid"]
    path.write_text(path.read_text() + "\n")
    assert baseline != cleaning_fingerprint(path, network, CleaningConfig())


def test_missing_reverse_geometry_still_pairs_one_physical_link():
    graph = parallel_graph()
    graph.remove_edges_from([(0, 1, 1), (1, 0, 1)])
    graph[0][1][0]["geometry"] = LineString([(500000, 1900000), (500050, 1900010), (500100, 1900000)])
    links = _link_rows(graph)
    assert len(links) == 1 and len(links[0]["_edges"]) == 2


def test_numpy_integer_endpoint_aliases_are_the_same_physical_nodes():
    import numpy as np
    graph = nx.MultiDiGraph(crs=32644, simplified=True)
    graph.add_node(0, x=0, y=0)
    graph.add_node(1, x=100, y=0)
    graph.add_edge(0, np.int64(1), length=100, osmid=1)
    graph.add_edge(1, np.int64(0), length=100, osmid=1)
    links = _link_rows(graph)
    assert len(links) == 1
    assert len(links[0]["_edges"]) == 2
