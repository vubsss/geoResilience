"""Time topology tests with an independent directed NetworkX oracle."""

import networkx as nx
import numpy as np
import pytest

from georesilience.config import TravelTimeConfig
from georesilience.links import _link_rows
from georesilience.removal import ActiveEdgeGraph
from georesilience.time_models import PreparedTimeModel
from georesilience.time_routing import TimeTopology, prepare_static_time


def time_fixture():
    graph = nx.MultiDiGraph(crs='EPSG:3857')
    graph.add_nodes_from((i, {"x": i*100., "y": 0.}) for i in range(5))
    for u, v, length, seconds in [(0, 1, 10, 90), (0, 1, 100, 10),
            (1, 2, 10, 20), (2, 1, 10, 20), (2, 3, 10, 30), (3, 3, 1, 0)]:
        graph.add_edge(u, v, length=length, travel_time_s=seconds, osmid=100 + min(u, v)*100 + max(u, v)*10 + length)
    links = _link_rows(graph)
    routing = prepare_static_time(graph, links, TravelTimeConfig(time_model='edge_attribute'))
    return graph, links, routing


class TimeStats:
    def __call__(self, distances, sources):
        return np.column_stack((np.isfinite(distances).sum(axis=1),
            np.where(np.isfinite(distances), distances, 0).sum(axis=1)))


def query(topology, sources, **kwargs):
    result = np.empty((len(sources), 2))
    index = {source: i for i, source in enumerate(sources)}
    for block, reduced in topology.reduce(sources, TimeStats(), **kwargs):
        for source, row in zip(block, reduced):
            result[index[source]] = row
    return result


def test_direction_parallel_minima_and_inclusive_seconds_boundary():
    graph, links, routing = time_fixture()
    top = routing.topology
    assert top.csr()[0, 1] == 10
    assert ActiveEdgeGraph(graph, links).csr()[0, 1] == 10  # shortest arc takes 90s
    inbound = query(top, [3], transpose=True, cutoff_seconds=60)
    outbound = query(top, [3], cutoff_seconds=60)
    np.testing.assert_array_equal(inbound[0], [4, 140])  # 60 + 50 + 30 + 0
    np.testing.assert_array_equal(outbound[0], [1, 0])
    np.testing.assert_array_equal(query(top, [3], transpose=True, cutoff_seconds=59.999)[0], [3, 80])
    assert top.csr().shape == (5, 5)  # isolated original node retained
    assert top.csr()[3, 3] == 0  # loop irrelevant to positive-cost routing


@pytest.mark.parametrize('transpose', [False, True])
@pytest.mark.parametrize('closure', ['none', 'link', 'node'])
def test_closures_match_networkx_and_parallel_small_blocks(transpose, closure):
    graph, links, routing = time_fixture()
    removed = [next(row['link_id'] for row in links if any(u == 1 and v == 2 for u, v, k in row['_edges']))] if closure == 'link' else []
    isolated = [1] if closure == 'node' else []
    oracle = graph.copy()
    oracle.remove_edges_from([arc for row in links if row['link_id'] in removed for arc in row['_edges']])
    oracle.remove_edges_from([(u, v, k) for u, v, k in list(oracle.edges(keys=True)) if u in isolated or v in isolated])
    if transpose:
        oracle = oracle.reverse()
    expected = []
    for origin in oracle:
        distances = nx.single_source_dijkstra_path_length(oracle, origin, cutoff=60, weight='travel_time_s')
        expected.append([len(distances), sum(distances.values())])
    options = dict(removed_links=removed, isolated_nodes=isolated, transpose=transpose, cutoff_seconds=60)
    serial = query(routing.topology, list(graph), n_jobs=1, budget_bytes=5*64, **options)
    parallel = query(routing.topology, list(graph), n_jobs=2, budget_bytes=5*64*2, **options)
    np.testing.assert_allclose(serial, expected)
    np.testing.assert_array_equal(serial, parallel)


def test_budget_missing_times_dynamic_and_static_custom_costs():
    graph, links, routing = time_fixture()
    with pytest.raises(ValueError, match='memory budget too small'):
        query(routing.topology, [0], budget_bytes=1)
    assert prepare_static_time(graph, links, TravelTimeConfig()).reason == 'skipped: no speed data'
    costs = {(u, v, k): 2 for u, v, k in graph.edges(keys=True) if u != v}
    prepared = PreparedTimeModel(costs, {'status': 'computed', 'time_model': 'custom', 'time_units': 'seconds'})
    static = prepare_static_time(graph, links, TravelTimeConfig(), prepared=prepared)
    assert static.topology.csr()[0, 1] == 2
    dynamic = PreparedTimeModel(costs, prepared.summary, lambda context: costs)
    with pytest.raises(ValueError, match='static seconds.*dynamic'):
        prepare_static_time(graph, links, TravelTimeConfig(), prepared=dynamic)


@pytest.mark.parametrize('invalid', [0, -1, float('nan'), float('inf'), 'bad', None])
def test_invalid_static_edge_seconds(invalid):
    graph, links, _ = time_fixture()
    costs = {(u, v, k): 2 for u, v, k in graph.edges(keys=True) if u != v}
    costs[next(iter(costs))] = invalid
    with pytest.raises(ValueError, match='seconds'):
        TimeTopology(graph, links, PreparedTimeModel(costs, {'status': 'computed'}))
