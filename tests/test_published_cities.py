import json
import zipfile

import geopandas as gpd
import numpy as np
import pytest

from georesilience import published_cities as published
from georesilience.crucitti import CITIES, _sha256


def archive_fixture(path, *, topology="1 2\n2 3\n", endpoints=None):
    # A bent 3-4 path. Its 7 m network distance differs from its 5 m chord.
    endpoints = endpoints or "1 1 0 0 2 3 0 3\n2 2 3 0 3 3 4 4\n"
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr("cities/README.txt", "Test fixture, not the published archive.")
        for city in CITIES:
            bundle.writestr(f"cities/{city.slug}.net", topology)
            bundle.writestr(f"cities/{city.slug}_edge_info.txt", endpoints)
    return path


def test_loader_preserves_metric_lengths_and_coordinates(tmp_path):
    path = archive_fixture(tmp_path / "fixture.zip")
    graph, audit = published.read_city(path, "cairo", expected_counts=(3, 2), expected_lengths=(3.5, .5))
    assert list(graph) == [1, 2, 3]
    assert graph.nodes[3] == {"x": 3., "y": 4.}
    assert graph[2][3][2]["length"] == 4
    assert audit["topology_matches_endpoint_table"]
    assert audit["connected_components"] == 1
    with pytest.raises(ValueError, match="N/K mismatch"):
        published.read_city(path, "cairo", expected_counts=(3, 3))
    with pytest.raises(ValueError, match="length statistics mismatch"):
        published.read_city(path, "cairo", expected_lengths=(4, .5))


@pytest.mark.parametrize("topology,endpoints,reason", [
    ("1 3\n2 3\n", None, "disagree"),
    ("1 2\n2 3\n", "1 1 0 0 2 3 0 3\n2 2 3.1 0 3 3 4 4\n", "inconsistent coordinates"),
    ("1 2\n2 3\n", "1 1 0 0 2 3 0 0\n2 2 3 0 3 3 4 4\n", "nonpositive"),
    ("1 2\n2 3\n", "1 1 nan 0 2 3 0 3\n2 2 3 0 3 3 4 4\n", "nonfinite"),
    ("1 2\n2 3\n", "1 1.1 0 0 2 3 0 3\n2 2 3 0 3 3 4 4\n", "integers"),
])
def test_loader_rejects_inconsistent_data(tmp_path, topology, endpoints, reason):
    path = archive_fixture(tmp_path / "fixture.zip", topology=topology, endpoints=endpoints)
    with pytest.raises(ValueError, match=reason):
        published.read_city(path, "cairo")


def test_published_validation_offline_and_no_cleaning(tmp_path, monkeypatch):
    path = archive_fixture(tmp_path / "fixture.zip")
    with pytest.raises(ValueError, match="checksum"):
        published.validate_published(path, tmp_path / "bad")
    monkeypatch.setattr(published, "ARCHIVE_SHA256", _sha256(path))
    monkeypatch.setattr(published, "PAPER_COUNTS", {city.slug: (3, 2) for city in CITIES})
    monkeypatch.setattr(published, "PAPER_LENGTHS", {city.slug: (3.5, .5) for city in CITIES})
    out = tmp_path / "result"
    summary = published.validate_published(path, out, n_jobs=1, max_memory_gb=.01)
    assert summary["comparisons"]["ap2_spatial"]["completed_cities"] == 4
    for city in CITIES:
        result = json.loads((out / city.slug / "summary.json").read_text())
        assert result["node_count"] == 3 and result["link_count"] == 2
        assert result["baseline_efficiency"]["inverse_distance_per_m"] == pytest.approx(61 / 252)
        assert result["baseline_efficiency"]["spatial_dimensionless"] == pytest.approx(19 / 21)
        assert result["cleaning"]["applied"] is False
        nodes = gpd.read_file(out / city.slug / "network.gpkg", layer="nodes")
        assert nodes.crs.is_engineering  # Never label local coordinates as GPS/UTM.
        edges = gpd.read_file(out / city.slug / "network.gpkg", layer="edges")
        assert not edges.oneway.any()
        np.testing.assert_allclose(nodes.information_spatial, [12 / 19, 1, 12 / 19])
        assert "OSM 2026" not in (out / city.slug / "report.txt").read_text()
    assert (out / "inputs" / "cities.zip").read_bytes() == path.read_bytes()
    before = (out / "comparison.json").read_bytes()
    with pytest.raises(ValueError, match="not empty"):
        published.validate_published(path, out)
    assert (out / "comparison.json").read_bytes() == before


def test_repeated_edge_labels_and_parallel_roads_are_preserved(tmp_path):
    path = archive_fixture(tmp_path / "fixture.zip", topology="1 2\n1 2\n",
        endpoints="1 1 0 0 2 3 0 3\n1 1 0 0 2 3 0 4\n")
    graph, audit = published.read_city(path, "cairo")
    assert graph.number_of_edges() == 2
    assert audit["repeated_edge_labels"] == 1
    assert audit["parallel_or_repeated_pairs"] == 1
    from georesilience.links import _link_rows
    from georesilience.centralities import build_analysis_graph
    links = _link_rows(graph)
    assert len(links) == 2
    analysis = build_analysis_graph(graph, links)
    assert analysis.csr[0, 1] == 3  # Shortest paths choose the shortest physical road.
