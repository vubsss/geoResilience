import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
import yaml
from shapely.geometry import Point

from georesilience.cli import main
from georesilience.facility_config import FacilityConfig, FacilitySource, FacilitySupply, load_facility_config
from georesilience.facilities import build_registry, reconcile, run_facilities
from georesilience.facility_sources import osm_input

FIXTURE = Path(__file__).parent / "fixtures" / "facilities"


def demo(**updates):
    config = load_facility_config(Path("examples/ticket17-facilities.yaml"))
    return config.model_copy(update={"figures": False, **updates})


def record(key, *, kind="official", name="School", x=0, level="primary", official_id="", source=None):
    return {"record_key": key, "source": source or key.split(":")[0], "source_id": key.split(":")[-1],
            "kind": kind, "service": "school", "name": name, "address": "", "service_level": level,
            "official_id": official_id, "id_namespace": "udise", "geometry": Point(x, 0), "point": Point(x, 0)}


def test_offline_import_identity_and_supply(tmp_path):
    result = build_registry(demo(), tmp_path)
    assert len(result.records) == 11
    assert len(result.facilities) == 9
    school = result.facilities.set_index("facility_id").loc["official_demo:001"]
    assert school.source_status == "matched"
    assert json.loads(school.source_keys) == ["official_demo:001", "osm_demo:node/1", "osm_demo:way/100"]
    assert school.supply_value == 1 and school.supply_unit == "facilities"
    assert school.enrolment == "120" and school.capacity_value != 120
    assert "official_demo:002" in set(result.facilities.facility_id)  # same campus, different school
    invalid = result.facilities.set_index("facility_id").loc["official_demo:004"]
    assert invalid.geometry is None and not invalid.eligible
    assert "invalid_coordinates" in set(result.rejects.reason)
    closed = result.facilities[result.facilities.status == "inactive"]
    assert len(closed) == 2 and not closed.eligible.any()
    assert result.summary["services"]["school"]["eligible_official_records"] == 4
    assert result.summary["services"]["school"]["valid_coordinate_official_records"] == 3
    assert result.summary["services"]["school"]["osm_matched_official_records"] == 1
    assert set(result.facilities.source_status) == {"matched", "osm_only", "official_only"}
    hospital = result.facilities[result.facilities.service == "hospital"].iloc[0]
    assert hospital.supply_value == 20 and hospital.supply_unit == "beds"
    assert len(list((tmp_path / "raw").iterdir())) == 2


def test_ambiguity_and_order_independence(tmp_path):
    records = [record("official:01", x=0, official_id="01"), record("official:02", x=20, official_id="02"),
               record("osm:node/1", kind="osm", x=10)]
    groups, decisions = reconcile(records, demo())
    assert len(groups) == 3
    assert all(row["decision"] == "review" for row in decisions)
    assert reconcile(records[::-1], demo())[1] == decisions
    overrides = tmp_path / "review.csv"
    overrides.write_text("left,right,action\nofficial:01,osm:node/1,merge\nofficial:02,osm:node/1,separate\n")
    groups, decisions = reconcile(records, demo(overrides=overrides))
    assert sorted(map(len, groups)) == [1, 2]
    assert any(d["reason"] == "manual_override" for d in decisions)


def test_id_namespace_and_service_level():
    a, b = record("a:001", official_id="001"), record("b:002", kind="osm", official_id="002")
    assert len(reconcile([a, b], demo())[0]) == 2
    b["official_id"] = "001"
    b["service_level"] = "secondary"
    groups, decisions = reconcile([a, b], demo())
    assert len(groups) == 2 and decisions[0]["reason"] == "identity_conflict"
    b["service_level"] = "primary"
    b["point"] = b["geometry"] = None
    assert len(reconcile([a, b], demo())[0]) == 1


def test_nearby_different_institutions_do_not_merge():
    a, b = record("a:1", name="Primary Academy"), record("b:1", kind="osm", name="Girls School", x=1)
    assert len(reconcile([a, b], demo())[0]) == 2


@pytest.mark.parametrize("policy", ["error", "exclude", "keep_missing"])
def test_capacity_missing_and_units(tmp_path, policy):
    config = demo(supply={"school": FacilitySupply(mode="capacity", unit="student_places", missing=policy),
                          "hospital": FacilitySupply(mode="capacity", unit="beds"),
                          "fire_station": FacilitySupply()})
    if policy == "error":
        with pytest.raises(ValueError, match="missing capacity"):
            build_registry(config, tmp_path)
    else:
        result = build_registry(config, tmp_path)
        schools = result.facilities[result.facilities.service == "school"]
        assert schools.supply_value.isna().all()
        assert not schools.supply_ready.any()
        assert "missing_supply" in set(result.rejects.reason)
        if policy == "exclude":
            assert not schools.eligible.any()
        else:
            assert schools.eligible.any()
    mismatch = demo(supply={**demo().supply, "hospital": FacilitySupply(mode="capacity", unit="physicians")})
    with pytest.raises(ValueError, match="capacity units differ"):
        build_registry(mismatch, tmp_path)


def test_offline_exports_and_rerun(tmp_path):
    config = demo()
    first = tmp_path / "first"
    expected = run_facilities(config, first)
    assert (first / "registry.gpkg").exists()
    assert gpd.read_file(first / "registry.gpkg", layer="facility_source_records").source_id.str.contains("001").any()
    frozen = load_facility_config(first / "facility_config.yaml")
    second = tmp_path / "second"
    assert run_facilities(frozen, second) == expected
    pd.testing.assert_frame_equal(pd.read_csv(first / "facility_matches.csv"), pd.read_csv(second / "facility_matches.csv"))
    assert json.loads((first / "facility_provenance.json").read_text())["sources"][0]["sha256"]
    assert main(["facilities", "--config", str(first / "facility_config.yaml"), "--out", str(tmp_path / "cli")]) == 0
    assert main(["facilities", "--config", str(first / "facility_config.yaml"), "--out", str(first)]) == 2


def test_gpkg_mapping_and_text_id(tmp_path):
    path = tmp_path / "inventory.gpkg"
    frame = gpd.GeoDataFrame({"code": ["0003"], "label": ["School"]}, geometry=[Point(78.47, 17.4)], crs=4326)
    frame.to_file(path, layer="inventory", driver="GPKG")
    source = FacilitySource(name="gpkg", kind="official", format="gpkg", path=path, layer="inventory",
                            service="school", columns={"source_id": "code", "name": "label"},
                            retrieved_at="2026-10-13", url="fixture", licence="fixture")
    result = build_registry(demo(sources=[source], supply={"school": FacilitySupply()}), tmp_path / "out")
    assert result.records.source_id.tolist() == ["0003"]
    with pytest.raises(ValueError, match="CRS disagrees"):
        build_registry(demo(sources=[source.model_copy(update={"crs": "EPSG:3857"})]), tmp_path / "bad")


def test_config_rejects_implicit_units_resources_and_degrees():
    for values in ({"mode": "equal", "unit": "beds"}, {"mode": "capacity", "unit": "enrolment"}):
        with pytest.raises(ValueError):
            FacilitySupply(**values)
    with pytest.raises(ValueError, match="projected in metres"):
        FacilityConfig.model_validate({**demo().model_dump(), "metric_crs": "EPSG:4326"})
    source = demo().sources[0].model_dump()
    source["columns"] = {**source["columns"], "supply_value": "enrolment"}
    with pytest.raises(ValueError, match="cannot also be supply_value"):
        FacilitySource.model_validate(source)


def test_osm_cache_no_http_and_checksum(tmp_path):
    source = FacilitySource(name="osm", kind="osm", format="osm_bbox", bbox=(78.46, 17.39, 78.48, 17.41),
                            cache_dir=tmp_path / "cache", retrieved_at="2026-10-13", url="osm", licence="ODbL")
    with pytest.raises(ValueError, match="offline OSM cache missing"):
        osm_input(source, True)
    import hashlib
    w, s, e, n = source.bbox
    query = (f'[out:xml][timeout:90];(nwr["amenity"~"^(school|hospital|fire_station)$"]({s},{w},{n},{e});'
             f'nwr["healthcare"="hospital"]({s},{w},{n},{e}););(._;>>;);out body;')
    key = hashlib.sha256((source.endpoint + query).encode()).hexdigest()
    source.cache_dir.mkdir()
    raw = source.cache_dir / f"{key}.osm"
    raw.write_bytes((FIXTURE / "facilities.osm").read_bytes())
    meta = raw.with_suffix(".json")
    meta.write_text(json.dumps({"query": query, "retrieved_at": "2026-10-13", "sha256": hashlib.sha256(raw.read_bytes()).hexdigest()}))
    assert osm_input(source, True) == raw
    raw.write_text("corrupt")
    with pytest.raises(ValueError, match="checksum/query mismatch"):
        osm_input(source, True)


def test_transitive_separation_rejected(tmp_path):
    path = tmp_path / "overrides.csv"
    path.write_text("left,right,action\na:1,b:1,merge\nb:1,c:1,merge\na:1,c:1,separate\n")
    with pytest.raises(ValueError, match="transitive manual merges"):
        reconcile([record(k) for k in ("a:1", "b:1", "c:1")], demo(overrides=path))


def test_official_rows_without_crosswalk_ids_stay_separate():
    records = [record("official:001"), record("official:002")]
    assert len(reconcile(records, demo())[0]) == 2


def test_frozen_input_tampering_is_detected(tmp_path):
    run_facilities(demo(), tmp_path / "first")
    config = load_facility_config(tmp_path / "first" / "facility_config.yaml")
    config.sources[0].path.write_text("corrupt")
    with pytest.raises(ValueError, match="frozen source checksum mismatch"):
        build_registry(config, tmp_path / "second")


def test_osm_acquisition_is_cached(monkeypatch, tmp_path):
    source = FacilitySource(name="osm", kind="osm", format="osm_bbox", bbox=(78.46, 17.39, 78.48, 17.41),
                            cache_dir=tmp_path / "cache", retrieved_at="2026-10-13", url="osm", licence="ODbL")
    class Response:
        content = (FIXTURE / "facilities.osm").read_bytes()
        def raise_for_status(self):
            pass
    calls = []
    def request(*args, **kwargs):
        calls.append(kwargs["params"]["data"])
        return Response()
    import requests
    monkeypatch.setattr(requests, "get", request)
    path = osm_input(source, False)
    assert "nwr" in calls[0]  # includes relations as well as nodes/ways
    assert osm_input(source, True) == path
    assert len(calls) == 1


def test_ambiguous_records_are_not_supply_ready(tmp_path):
    path = tmp_path / "official.csv"
    path.write_text("code,name,longitude,latitude\n01,OSM Only School,78.472,17.402\n02,OSM Only School,78.4721,17.402\n")
    config = demo()
    official = config.sources[0].model_copy(update={"path": path, "columns": {"source_id": "code", "official_id": "code", "name": "name"}})
    result = build_registry(config.model_copy(update={"sources": [official, config.sources[1]]}), tmp_path / "out")
    ambiguous = result.facilities[result.facilities.name == "OSM Only School"]
    assert len(ambiguous) == 3
    assert ambiguous.review_required.all() and not ambiguous.supply_ready.any()


def test_facilities_integrate_with_road_pipeline(tmp_path):
    import networkx as nx
    import osmnx as ox
    from georesilience.config import RunConfig
    from georesilience.pipeline import run
    graph = nx.MultiDiGraph(crs="EPSG:4326", simplified=True)
    graph.add_node(1, x=78.47, y=17.4)
    graph.add_node(2, x=78.471, y=17.4)
    for a, b in ((1, 2), (2, 1)):
        graph.add_edge(a, b, length=100, osmid=1, highway="residential")
    path = tmp_path / "roads.graphml"
    ox.save_graphml(graph, path)
    config = RunConfig.model_validate({"input": {"source": "graphml", "path": path},
        "facilities": demo().model_dump(), "cleaning": {"consolidate": False},
        "analysis": {"n_jobs": 1, "max_memory_gb": 0.1}, "output": {"figures": False},
        "travel_time": {"enabled": False}, "reliability": {"samples": 2},
        "robustness": {"steps": 1, "failure_runs": 1}})
    output = tmp_path / "run"
    result = run(config, output)
    assert result["facilities"]["facility_count"] == 9
    layers = set(gpd.list_layers(output / "network.gpkg").name)
    assert {"nodes", "edges", "facilities", "facility_source_records"} <= layers
    resolved = yaml.safe_load((output / "run_config.yaml").read_text())
    assert resolved["facilities"]["offline"]
    assert resolved["facilities"]["metric_crs"] == result["facilities"]["crs"]
    assert "Facilities (Ticket 17" in (output / "report.txt").read_text()
    run(config.model_copy(update={"facilities": None}), output, overwrite=True)
    assert not (output / "facility_matches.csv").exists()
    assert "facilities" not in set(gpd.list_layers(output / "network.gpkg").name)


def test_matching_id_with_distant_coordinates_needs_review():
    groups, decisions = reconcile([record("official:001", official_id="001"),
                                   record("osm:1", kind="osm", official_id="001", x=5000)], demo())
    assert len(groups) == 2
    assert decisions[0]["decision"] == "review" and decisions[0]["reason"] == "id_location_conflict"


def test_empty_osm_result_can_be_exported(tmp_path):
    path = tmp_path / "empty.osm"
    path.write_text('<osm version="0.6" generator="fixture"></osm>')
    source = demo().sources[1].model_copy(update={"path": path})
    config = demo(sources=[source])
    summary = run_facilities(config, tmp_path / "out")
    assert summary["facility_count"] == 0
    assert summary["services"]["school"]["osm_match_fraction_valid_official"] is None


def test_distant_id_review_cannot_be_bypassed_by_a_transitive_match():
    records = [record("a:1", official_id="001", x=0), record("b:1", official_id="001", x=70),
               record("c:1", official_id="001", x=140)]
    groups, decisions = reconcile(records, demo())
    assert len(groups) == 3
    assert all(d["decision"] == "review" for d in decisions)
