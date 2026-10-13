"""Freeze public source samples, then audit offline. No accounts, scraping APIs or geocoding.

The district samples lack numeric coordinates. Their location/match criterion stays open;
OSM coordinates are never substituted as independent official reference coordinates.
"""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import re

import requests
import yaml

from georesilience.facility_config import FacilityConfig
from georesilience.facilities import run_facilities

BBOX = (78.465, 17.385, 78.480, 17.400)
URLS = {
    "schools.html": "https://hyderabad.telangana.gov.in/public-utility-category/government-schools/",
    "hospitals.html": "https://vvp.telangana.gov.in/content.php?U=2",
    "fire.html": "https://tgfireuat.cgg.gov.in/home/Home/knowurfstn",
    "osm.osm": "https://api.openstreetmap.org/api/0.6/map?bbox=" + ",".join(map(str, BBOX)),
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text(fragment):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def samples(raw, inputs):
    schools = re.findall(r'<h2 class="heading4">(.*?)</h2>', (raw / "schools.html").read_text(), re.S)
    school_rows = [{"id": f"district-page-{i:03}", "name": text(name), "lon": "", "lat": ""}
                   for i, name in enumerate(schools, 1)]
    hospital_rows, excluded = [], []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", (raw / "hospitals.html").read_text(), re.S | re.I):
        cells = [text(c) for c in re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.S | re.I)]
        if len(cells) == 4 and cells[1] == "Hyderabad" and cells[3].isdigit():
            entry = {"id": f"tvvp-page-{len(hospital_rows)+len(excluded)+1:03}", "name": cells[2],
                     "beds": cells[3], "directory_prefix": cells[2].split()[0].rstrip(","), "lon": "", "lat": ""}
            if entry["directory_prefix"] in {"DH", "AH", "MCH"}:
                hospital_rows.append(entry)
            else:
                excluded.append({**entry, "reason": "outside_DH_AH_MCH_hospital_definition"})
    if not school_rows or not hospital_rows:
        raise ValueError("official sample HTML layout changed; inspect the frozen sources")
    for name, rows in (("schools", school_rows), ("hospitals", hospital_rows)):
        with (inputs / f"{name}.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    if excluded:
        with (inputs / "excluded-directory-records.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(excluded[0]))
            writer.writeheader()
            writer.writerows(excluded)
    return {"school_sample_rows": len(school_rows), "hospital_sample_rows": len(hospital_rows),
            "hospital_directory_rows_excluded_by_type": len(excluded)}


def audit(out_dir, download=False, overwrite=False):
    inputs, raw = out_dir / "inputs", out_dir / "inputs" / "raw"
    manifest_path = inputs / "manifest.json"
    if download:
        raw.mkdir(parents=True, exist_ok=True)
        manifest = {"bbox": BBOX, "sources": {}}
        for name, url in URLS.items():
            print(f"Downloading {name}", flush=True)
            response = requests.get(url, timeout=90, headers={"User-Agent": "GeoResilience/0.1 facility-source-audit"})
            response.raise_for_status()
            path = raw / name
            path.write_bytes(response.content)
            manifest["sources"][name] = {"url": url, "sha256": sha(path),
                                            "retrieved_at": datetime.now(timezone.utc).isoformat()}
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    if not manifest_path.exists():
        raise ValueError("frozen source manifest missing; run once with --download")
    manifest = json.loads(manifest_path.read_text())
    for name, metadata in manifest["sources"].items():
        if sha(raw / name) != metadata["sha256"]:
            raise ValueError(f"source checksum mismatch: {name}")
    counts = samples(raw, inputs)
    sources = []
    for service, name in (("school", "schools"), ("hospital", "hospitals")):
        metadata = manifest["sources"][f"{name}.html"]
        source = {"name": f"official_{name}", "kind": "official", "format": "csv",
                  "path": str((inputs / f"{name}.csv").resolve()), "service": service,
                  "x": "lon", "y": "lat", "crs": "EPSG:4326",
                  "columns": {"source_id": "id", "name": "name"}, "default_status": "unknown",
                  "reference_year": "not stated", "url": metadata["url"], "retrieved_at": metadata["retrieved_at"],
                  "licence": "public webpage; bulk redistribution permission not verified"}
        if service == "hospital":
            source["columns"].update({"supply_value": "beds", "subtype": "directory_prefix"})
            source["capacity_unit"] = "beds"
        sources.append(source)
    metadata = manifest["sources"]["osm.osm"]
    sources.append({"name": "osm_hyderabad", "kind": "osm", "format": "osm_xml", "path": str((raw / "osm.osm").resolve()),
                    "bbox": BBOX, "reference_year": "OSM snapshot", "url": metadata["url"], "retrieved_at": metadata["retrieved_at"],
                    "licence": "OpenStreetMap contributors, ODbL 1.0; https://www.openstreetmap.org/copyright"})
    config = FacilityConfig.model_validate({"sources": sources,
        "supply": {s: {"mode": "equal", "unit": "facilities", "missing": "error"} for s in ("school", "hospital", "fire_station")},
        "metric_crs": "EPSG:32644", "offline": True, "include_osm_candidates": True,
        "include_unknown_status": True, "output_dir": str(out_dir / "registry")})
    summary = run_facilities(config, overwrite=overwrite)
    (out_dir / "audit_config.yaml").write_text(yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False))
    findings = {**counts, "osm_bbox": BBOX, "official_inventory_scope": "Hyderabad district webpage samples; not a bbox inventory",
                "real_data_acceptance": "OPEN: no independently geocoded official school/hospital sample; no UDISE+ export",
                "official_coordinates": "absent; no inferred or OSM-borrowed coordinates",
                "official_ids": "generated page row keys only; not UDISE/HFR identifiers",
                "hospital_filter": "only DH/AH/MCH name prefixes; CHC/UCHC/dispensaries excluded and exported",
                "hospital_identity_caution": "DH & MCH King Koti and MCH King Koti may overlap; no automatic merge or bed summation",
                "first_worked_service": "hospital, provisional equal-supply OSM worked example",
                "selection_reason": "OSM locations are usable and TVVP publishes bed fields for later verification; school export is gated",
                "capacity_model": "deferred until bed reference date, operational status and identity/location are verified",
                "school_supply": "enrolment, places, teachers and classrooms absent in this district sample",
                "fire_source": "names available in state webpage; coordinates, appliances and crews not established",
                "match_interpretation": "zero located official denominator: undefined coverage, not evidence of absent OSM facilities",
                "facilities": summary}
    (out_dir / "source_findings.json").write_text(json.dumps(findings, indent=2) + "\n")
    print(json.dumps({**counts, "registry_facilities": summary["facility_count"], "acceptance": findings["real_data_acceptance"]}, indent=2))
    return findings


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("results/ticket17-india"))
    parser.add_argument("--download", action="store_true", help="Explicitly fetch public snapshots; otherwise strictly offline")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if not args.download:
        def forbidden(*args, **kwargs):
            raise AssertionError("HTTP forbidden in offline audit")
        requests.sessions.Session.request = forbidden
    audit(args.out, args.download, args.overwrite)
