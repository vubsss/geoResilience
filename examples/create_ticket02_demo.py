"""Create small, offline inputs for manually reviewing ticket 02."""
from pathlib import Path
import math
from xml.etree.ElementTree import Element, SubElement, ElementTree

import geopandas as gpd
import networkx as nx
import osmnx as ox
from shapely.geometry import box


def main():
    folder = Path("data/ticket02-demo")
    folder.mkdir(parents=True, exist_ok=True)
    graph = nx.MultiDiGraph(crs="EPSG:32644", simplified=True)
    coords = [(499995, 1900005), (500005, 1900005), (500005, 1899995),
              (499995, 1899995), (499900, 1900005), (500005, 1900100),
              (500100, 1899995), (499995, 1899900)]
    for node, (x, y) in enumerate(coords):
        graph.add_node(node, x=x, y=y)
    for way, (u, v) in enumerate([(0, 1), (1, 2), (2, 3), (3, 0),
                                 (0, 4), (1, 5), (2, 6), (3, 7)]):
        for a, b in ((u, v), (v, u)):
            graph.add_edge(a, b, length=math.dist(coords[u], coords[v]),
                           osmid=100 + way, highway="residential")
    ox.save_graphml(graph, filepath=folder / "junction.graphml")
    root = Element("osm", version="0.6", generator="georesilience-demo")
    for i, tags in enumerate([{"highway": "footway"}, {"highway": "service"},
                              {"highway": "residential", "access": "private"},
                              {"highway": "residential"}]):
        for j in (0, 1):
            SubElement(root, "node", id=str(i * 2 + j + 1),
                       lon=str(78.47 + j * 0.001), lat=str(17.40 + i * 0.001))
        way = SubElement(root, "way", id=str(100 + i))
        for j in (0, 1):
            SubElement(way, "nd", ref=str(i * 2 + j + 1))
        for key, value in tags.items():
            SubElement(way, "tag", k=key, v=value)
    ElementTree(root).write(folder / "roads.osm", encoding="utf-8", xml_declaration=True)
    gpd.GeoDataFrame(geometry=[box(78.469, 17.399, 78.479, 17.409)], crs=4326).to_file(
        folder / "boundary.geojson", driver="GeoJSON")
    print(f"Created {folder}/junction.graphml, roads.osm, and boundary.geojson")


if __name__ == "__main__":
    main()
