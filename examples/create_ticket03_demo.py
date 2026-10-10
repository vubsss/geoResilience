"""Generate metre-based known-answer graphs and QGIS copies for ticket 03."""

import math
from pathlib import Path

import networkx as nx
import osmnx as ox


def export_graph(folder, name, simple, coordinates):
    graph = nx.MultiDiGraph(crs="EPSG:32644", simplified=True)
    for node, (x, y) in coordinates.items():
        graph.add_node(node, x=500000 + x, y=1900000 + y)
    for way, (u, v) in enumerate(simple.edges, start=1):
        for a, b in ((u, v), (v, u)):
            graph.add_edge(a, b, length=math.dist(coordinates[u], coordinates[v]),
                           osmid=way, name=f"Demo road {way}", highway="residential")
    ox.save_graphml(graph, filepath=folder / f"{name}.graphml")
    nodes, edges = ox.graph_to_gdfs(graph)
    target = folder / f"{name}-input.gpkg"
    nodes.to_file(target, layer="nodes", driver="GPKG", engine="pyogrio")
    edges.to_file(target, layer="edges", driver="GPKG", engine="pyogrio")
    print(f"Created {folder}/{name}.graphml and {name}-input.gpkg")


def main():
    folder = Path("data/ticket03-demo")
    folder.mkdir(parents=True, exist_ok=True)
    export_graph(folder, "star", nx.star_graph(4),
                 {0: (0, 0), 1: (100, 0), 2: (0, 100), 3: (-100, 0), 4: (0, -100)})
    export_graph(folder, "path", nx.path_graph(5), {i: (100 * i, 0) for i in range(5)})
    grid = nx.convert_node_labels_to_integers(nx.grid_2d_graph(3, 3), label_attribute="grid_position")
    export_graph(folder, "grid", grid,
                 {i: tuple(100 * value for value in data["grid_position"]) for i, data in grid.nodes(data=True)})


if __name__ == "__main__":
    main()
