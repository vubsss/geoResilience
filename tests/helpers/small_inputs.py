"""Small offline road and population inputs shared by contract tests."""

import math
from xml.etree.ElementTree import Element, ElementTree, SubElement

import networkx as nx
import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin
from shapely.geometry import box
from shapely.ops import transform


def junction_graph():
    graph = nx.MultiDiGraph(crs="EPSG:32644", simplified=True)
    coords = [(499995, 1900005), (500005, 1900005), (500005, 1899995),
              (499995, 1899995), (499900, 1900005), (500005, 1900100),
              (500100, 1899995), (499995, 1899900)]
    for node, (x, y) in enumerate(coords):
        graph.add_node(node, x=x, y=y)
    for way, (u, v) in enumerate([(0, 1), (1, 2), (2, 3), (3, 0),
                                 (0, 4), (1, 5), (2, 6), (3, 7)]):
        length = math.dist(coords[u], coords[v])
        for a, b in [(u, v), (v, u)]:
            graph.add_edge(a, b, osmid=way, length=length, highway="residential")
    return graph


def xml_fixture(path):
    root = Element("osm", version="0.6", generator="georesilience-test")
    tags = [{"highway": "footway"}, {"highway": "service"},
            {"highway": "residential", "access": "private"},
            {"highway": "residential"}, {"highway": "residential", "area": "yes"},
            {"highway": "residential", "motor_vehicle": "no"},
            {"highway": "residential", "motorcar": "no"}]
    for i, attrs in enumerate(tags):
        for j in (0, 1):
            SubElement(root, "node", id=str(i * 2 + j + 1),
                       lon=str(78.47 + j * 0.001), lat=str(17.40 + i * 0.001))
        way = SubElement(root, "way", id=str(100 + i))
        for j in (0, 1):
            SubElement(way, "nd", ref=str(i * 2 + j + 1))
        for key, value in attrs.items():
            SubElement(way, "tag", k=key, v=value)
    ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return path


def raster_fixture(tmp_path, values=None, crs=32644):
    path = tmp_path / "counts.tif"
    values = np.arange(1, 10, dtype="float32").reshape(3, 3) if values is None else np.array(values, dtype="float32")
    affine = from_origin(500000, 1900300, 100, 100)
    if crs == 4326:
        affine = from_origin(78, 17.003, .001, .001)
    with rasterio.open(path, "w", driver="GTiff", height=3, width=3, count=1,
                       dtype="float32", crs=crs, transform=affine, nodata=-9999) as raster:
        raster.write(values, 1)
    return path, affine


def cell_graph(affine, crs=32644, cells=8):
    graph = nx.MultiDiGraph(crs="EPSG:32644", simplified=True)
    projection = Transformer.from_crs(crs, 32644, always_xy=True)
    for node in range(cells):
        xy = rasterio.transform.xy(affine, node // 3, node % 3)
        x, y = projection.transform(*xy)
        graph.add_node(node, x=x, y=y)
    for way, (u, v) in enumerate(zip(range(cells - 1), range(1, cells)), 1):
        distance = math.dist((graph.nodes[u]["x"], graph.nodes[u]["y"]),
                             (graph.nodes[v]["x"], graph.nodes[v]["y"]))
        for a, b in ((u, v), (v, u)):
            graph.add_edge(a, b, length=distance, osmid=way, highway="residential")
    return graph


def boundary_for(affine, crs=32644, cols=3):
    left, top = affine * (0, 0)
    right, bottom = affine * (cols, 3)
    return transform(Transformer.from_crs(crs, 4326, always_xy=True).transform,
                     box(left, bottom, right, top))
