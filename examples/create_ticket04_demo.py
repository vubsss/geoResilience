"""Generate known-answer redundancy fixtures, including input layers for QGIS."""

import math
from pathlib import Path

import networkx as nx
import osmnx as ox


def road_graph(simple, coordinates):
    graph = nx.MultiDiGraph(crs="EPSG:32644", simplified=True)
    for node, (x, y) in coordinates.items():
        graph.add_node(node, x=500000 + x, y=1900000 + y)
    for way, (u, v) in enumerate(simple.edges, start=1):
        for a, b in ((u, v), (v, u)):
            graph.add_edge(a, b, length=100.0, osmid=way, name=f"Demo road {way}", highway="residential")
    return graph


def export_graph(folder, name, graph):
    ox.save_graphml(graph, filepath=folder / f"{name}.graphml")
    nodes, edges = ox.graph_to_gdfs(graph)
    target = folder / f"{name}-input.gpkg"
    nodes.to_file(target, layer="nodes", driver="GPKG", engine="pyogrio")
    edges.to_file(target, layer="edges", driver="GPKG", engine="pyogrio")
    print(f"Created {folder}/{name}.graphml and {name}-input.gpkg")


def main():
    folder = Path("data/ticket04-demo")
    folder.mkdir(parents=True, exist_ok=True)
    ring = road_graph(nx.cycle_graph(6),
                      {i: (100 * math.cos(i * math.pi / 3), 100 * math.sin(i * math.pi / 3))
                       for i in range(6)})
    export_graph(folder, "ring", ring)
    directed = ring.copy()
    directed.remove_edge(1, 0)
    export_graph(folder, "directed-ring", directed)
    export_graph(folder, "path", road_graph(nx.path_graph(6), {i: (i * 100, 0) for i in range(6)}))
    parallel = road_graph(nx.path_graph(2), {0: (0, 0), 1: (100, 0)})
    # Curved backup road: the two physical roads are visible separately in QGIS.
    from shapely.geometry import LineString
    geometry = LineString([(500000, 1900000), (500050, 1900050), (500100, 1900000)])
    for u, v in ((0, 1), (1, 0)):
        parallel.add_edge(u, v, length=150.0, osmid=99, name="Backup road", highway="residential",
                          geometry=geometry if u == 0 else LineString(list(geometry.coords)[::-1]))
    export_graph(folder, "parallel", parallel)


if __name__ == "__main__":
    main()
