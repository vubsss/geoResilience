"""Offline OD CSV validation and deterministic snapping."""

import math

import networkx as nx
import pytest
from pyproj import Transformer

from georesilience.od import load_od_pairs, node_id_key


def graph():
    result = nx.MultiDiGraph(crs=32644)
    result.add_node(10, x=500000, y=1900000)
    result.add_node(2, x=500100, y=1900000)
    return result


def write_od(path, x=500000, y=1900000, labels=("route",)):
    lon, lat = Transformer.from_crs(32644, 4326, always_xy=True).transform(x, y)
    path.write_text("label,origin_lon,origin_lat,dest_lon,dest_lat\n" +
                    "".join(f"{label},{lon},{lat},{lon},{lat}\n" for label in labels))
    return path


def test_snapped_indices_coordinates_and_numeric_id_tie_are_stable(tmp_path):
    source = graph()
    source.nodes[2].update(source.nodes[10])
    result = load_od_pairs(source, write_od(tmp_path / "od.csv"))
    row = result.pairs[0]
    assert row["origin_node_id"] == row["dest_node_id"] == "2"
    assert row["_origin"] == row["_dest"] == 1
    assert row["origin_snap_m"] == pytest.approx(0, abs=1e-7)
    assert sorted([10, 2, "x"], key=node_id_key) == [2, 10, "x"]


def test_midpoint_ties_and_insertion_order_do_not_change_selected_id(tmp_path):
    path = write_od(tmp_path / "midpoint.csv", x=500050)
    source = graph()
    reverse = nx.MultiDiGraph(crs=32644)
    reverse.add_nodes_from(reversed(list(source.nodes(data=True))))
    for candidate in (source, reverse):
        row = load_od_pairs(candidate, path).pairs[0]
        assert row["origin_node_id"] == "2"
        assert row["origin_snap_m"] == pytest.approx(50, abs=1e-7)


@pytest.mark.parametrize("row", ["x,181,0,0,0", "x,0,91,0,0", "x,nan,0,0,0",
    "x,word,0,0,0", ",0,0,0,0", "x,0,0,0,0\nx,0,0,0,0"])
def test_invalid_labels_or_coordinates_report_data_rows(tmp_path, row):
    path = tmp_path / "bad.csv"
    path.write_text("label,origin_lon,origin_lat,dest_lon,dest_lat\n" + row + "\n")
    with pytest.raises(ValueError, match="OD data row"):
        load_od_pairs(graph(), path)


@pytest.mark.parametrize("content", ["label,origin_lon\nx,0\n", "# empty\n",
    "label,origin_lon,origin_lat,dest_lon,dest_lat\nx,1,2,3,4,5\n"])
def test_missing_columns_empty_input_and_extra_cells_are_rejected(tmp_path, content):
    path = tmp_path / "bad.csv"
    path.write_text(content)
    with pytest.raises(ValueError, match="CSV|columns"):
        load_od_pairs(graph(), path)


def test_absent_and_header_only_od_files_are_valid_empty_inputs(tmp_path):
    assert load_od_pairs(graph()).pairs == []
    path = tmp_path / "empty.csv"
    path.write_text("label,origin_lon,origin_lat,dest_lon,dest_lat\n")
    assert load_od_pairs(graph(), path).pairs == []


def test_far_snap_warnings_are_counted_and_bounded(tmp_path):
    path = write_od(tmp_path / "far.csv", x=510000, y=1910000, labels=tuple(f"route-{i}" for i in range(12)))
    result = load_od_pairs(graph(), path)
    assert result.warnings["total_count"] == 24
    assert len(result.warnings["shown"]) == 20
    assert result.warnings["omitted_count"] == 4


@pytest.mark.parametrize("invalid", ["empty", "geographic", "nonfinite"])
def test_snapping_requires_nonempty_finite_metric_graph(tmp_path, invalid):
    source = graph()
    if invalid == "empty":
        source.clear()
        source.graph["crs"] = 32644
    elif invalid == "geographic":
        source.graph["crs"] = 4326
    else:
        source.nodes[10]["x"] = math.nan
    with pytest.raises(ValueError, match="OD snapping"):
        load_od_pairs(source, write_od(tmp_path / "valid.csv"))
