"""Local inventories and checksum-verified, explicitly online OSM acquisition."""
import hashlib
import json
import math
import shutil
from xml.etree import ElementTree as ET
from pathlib import Path

import geopandas as gpd
import osmnx as ox
import pandas as pd
import requests
from pyproj import CRS, Transformer
from shapely.geometry import Point, box
from shapely import get_coordinates, transform

from .facility_config import FacilitySource

TAGS = {"amenity": ["school", "hospital", "fire_station"], "healthcare": "hospital"}
INACTIVE = {"closed", "inactive", "disused", "abandoned", "demolished", "proposed", "construction"}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def freeze(path, out_dir):
    checksum = digest(path)
    target = out_dir / "raw" / f"{checksum}{Path(path).suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.resolve() != Path(path).resolve():
        shutil.copyfile(path, target)
    return {"sha256": checksum, "raw_path": str(target.resolve()), "input_path": str(Path(path).resolve())}


def osm_input(source: FacilitySource, offline: bool):
    if source.format == "osm_xml":
        return source.path
    w, s, e, n = source.bbox
    query = (f'[out:xml][timeout:90];(nwr["amenity"~"^(school|hospital|fire_station)$"]({s},{w},{n},{e});'
             f'nwr["healthcare"="hospital"]({s},{w},{n},{e}););(._;>>;);out body;')
    key = hashlib.sha256((source.endpoint + query).encode()).hexdigest()
    folder = source.cache_dir.expanduser()
    path, meta_path = folder / f"{key}.osm", folder / f"{key}.json"
    if path.exists() or meta_path.exists():
        if not path.exists() or not meta_path.exists():
            raise ValueError(f"incomplete OSM cache: {path}")
        metadata = json.loads(meta_path.read_text())
        if metadata.get("sha256") != digest(path) or metadata.get("query") != query:
            raise ValueError(f"OSM cache checksum/query mismatch: {path}")
        return path
    if offline:
        raise ValueError(f"offline OSM cache missing: {path}; acquire once with offline: false")
    response = requests.get(source.endpoint, params={"data": query}, timeout=120)
    response.raise_for_status()
    # Reject Overpass error payloads before freezing them as a successful cache.
    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as exc:
        raise ValueError("OSM endpoint returned invalid XML") from exc
    if root.tag != "osm" or root.find("remark") is not None:
        raise ValueError("OSM endpoint returned an error or non-OSM XML")
    folder.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_bytes(response.content)
    temp.replace(path)
    from datetime import datetime, timezone
    meta_path.write_text(json.dumps({"query": query, "endpoint": source.endpoint,
                                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                                    "sha256": digest(path)}, indent=2) + "\n")
    return path


def clean(value):
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return ""
    return str(value).strip()


def osm_service(row):
    categories = set()
    if clean(row.get("amenity")) in {"school", "hospital", "fire_station"}:
        categories.add(clean(row.get("amenity")))
    for lifecycle in INACTIVE:
        if clean(row.get(f"{lifecycle}:amenity")) in {"school", "hospital", "fire_station"}:
            categories.add(clean(row.get(f"{lifecycle}:amenity")))
    if clean(row.get("healthcare")) == "hospital":
        categories.add("hospital")
    return next(iter(categories)) if len(categories) == 1 else None


def osm_status(row):
    if any(clean(row.get(f"{k}:amenity")) in {"school", "hospital", "fire_station"} for k in INACTIVE):
        return "inactive"
    if any(clean(row.get(k)).lower() in {"yes", "true", "1"} for k in INACTIVE):
        return "inactive"
    if clean(row.get("operational_status")).lower() in INACTIVE:
        return "inactive"
    return "unknown"  # an amenity tag does not prove current operation


def import_source(source, config, out_dir):
    path = osm_input(source, config.offline) if source.format in {"osm_xml", "osm_bbox"} else source.path
    if source.sha256 and digest(path) != source.sha256:
        raise ValueError(f"{source.name}: frozen source checksum mismatch")
    metadata = {**source.model_dump(mode="json"), **freeze(path, out_dir)}
    if source.format == "osm_bbox":
        acquisition = json.loads(path.with_suffix(".json").read_text())
        metadata["acquisition"] = acquisition
        metadata["retrieved_at"] = acquisition["retrieved_at"]
    if source.format in {"osm_xml", "osm_bbox"}:
        try:
            frame = ox.features_from_xml(path, tags=None, polygon=box(*source.bbox) if source.bbox else None)
        except ET.ParseError as exc:
            raise ValueError(f"{source.name}: invalid OSM XML") from exc
        except ox._errors.InsufficientResponseError:
            frame = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
        frame = frame.reset_index()
    elif source.format == "csv":
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    else:
        frame = gpd.read_file(path, layer=source.layer, engine="pyogrio")
        if source.crs and frame.crs and CRS.from_user_input(source.crs) != frame.crs:
            raise ValueError(f"{source.name}: declared CRS disagrees with GeoPackage CRS")
        if frame.crs is None:
            if not source.crs:
                raise ValueError(f"{source.name}: GeoPackage requires CRS or explicit crs mapping")
            frame = frame.set_crs(source.crs)
        # Numeric identifiers have already lost any leading zeros: require text storage.
        id_col = source.columns["source_id"]
        for id_col in [source.columns[k] for k in ("source_id", "official_id") if k in source.columns]:
            if id_col in frame and any(not isinstance(v, str) for v in frame[id_col].dropna()):
                raise ValueError(f"{source.name}: GeoPackage identifiers must be stored as text")
    required = set(source.columns.values())
    if source.format == "csv":
        required.update([source.x, source.y])
    if required - set(frame.columns):
        raise ValueError(f"{source.name}: missing columns {sorted(required - set(frame.columns))}")
    source_crs = source.crs if source.format == "csv" else str(frame.crs)
    to_wgs = Transformer.from_crs(source_crs, "EPSG:4326", always_xy=True)
    to_metric = Transformer.from_crs(source_crs, config.metric_crs, always_xy=True)
    records, rejects, seen = [], [], set()
    for index, raw in frame.iterrows():
        osm = source.format in {"osm_xml", "osm_bbox"}
        service = osm_service(raw) if osm else source.service
        if osm and (service is None or (source.service and service != source.service)):
            continue
        values = {key: clean(raw.get(column)) for key, column in source.columns.items()}
        source_id = f"{clean(raw.get('element')) or clean(raw.get('element_type'))}/{clean(raw.get('id')) or clean(raw.get('osmid'))}" if osm else values.pop("source_id")
        key = f"{source.name}:{source_id}"
        if not source_id or key in seen:
            rejects.append({"record_key": key, "reason": "missing_or_duplicate_source_id", "row": int(index)})
            continue
        seen.add(key)
        if osm:
            values.update({"name": clean(raw.get("name")), "address": clean(raw.get("addr:full")),
                           "status": osm_status(raw), "management": clean(raw.get("operator")),
                           "service_level": clean(raw.get("isced:level")),
                           "subtype": clean(raw.get("healthcare:speciality")),
                           "official_id": clean(raw.get("ref:udise")) if service == "school" else clean(raw.get("ref:hfr")),
                           "supply_value": clean(raw.get("capacity:beds")) if service == "hospital" else "",
                           "supply_unit": "beds" if service == "hospital" and clean(raw.get("capacity:beds")) else ""})
        status_raw = values.get("status", "")
        status = status_raw if osm else source.status_map.get(status_raw, source.default_status)
        if not osm and status_raw in {"active", "inactive", "unknown"}:
            status = source.status_map.get(status_raw, status_raw)
        if status_raw and status_raw not in source.status_map and status_raw not in {"active", "inactive", "unknown"} and not osm:
            status = "unknown"
            rejects.append({"record_key": key, "reason": "unmapped_status", "row": int(index), "value": status_raw})
        geometry, point, original = None, None, None
        try:
            original = Point(float(raw[source.x]), float(raw[source.y])) if source.format == "csv" else raw.geometry
            if original is None or original.is_empty or not original.is_valid or original.geom_type not in {"Point", "Polygon", "MultiPolygon"}:
                raise ValueError("missing/invalid point or site")
            # Check all vertices, not just the representative point.
            for x, y in get_coordinates(original):
                lon, lat = to_wgs.transform(x, y, errcheck=True)
                if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90):
                    raise ValueError("coordinates out of range")
                if CRS.from_user_input(source_crs).is_geographic and not (-180 <= x <= 180 and -90 <= y <= 90):
                    raise ValueError("source lon/lat out of range")
            geometry = transform(original, to_metric.transform, interleaved=False)
            if not all(math.isfinite(v) for v in geometry.bounds):
                raise ValueError("nonfinite projected geometry")
            point = geometry if geometry.geom_type == "Point" else geometry.representative_point()
        except (ValueError, TypeError, OverflowError, RuntimeError):
            rejects.append({"record_key": key, "reason": "invalid_coordinates", "row": int(index)})
            geometry, point = None, None
        raw_supply = values.get("supply_value", "")
        supply = None
        if raw_supply:
            try:
                supply = float(raw_supply)
                if not math.isfinite(supply) or supply < 0:
                    raise ValueError("invalid supply")
            except ValueError:
                supply = None
                rejects.append({"record_key": key, "reason": "invalid_supply", "row": int(index), "value": raw_supply})
        records.append({"record_key": key, "source": source.name, "source_id": source_id,
                        "kind": source.kind, "service": service, **values, "status": status,
                        "official_id": values.get("official_id", ""), "id_namespace": (("udise" if service == "school" else "hfr" if service == "hospital" else "") if osm else source.id_namespace or ""),
                        "reference_year": values.get("reference_year") or source.reference_year or "",
                        "retrieved_at": metadata["retrieved_at"], "source_sha256": metadata["sha256"],
                        "supply_value": supply, "supply_unit": values.get("supply_unit") or source.capacity_unit or "",
                        "original_crs": source_crs, "original_wkt": original.wkt if original is not None else "",
                        "geometry": geometry, "point": point})
    metadata.update({"raw_rows": len(frame), "imported_records": len(records), "reject_events": len(rejects)})
    return records, rejects, metadata
