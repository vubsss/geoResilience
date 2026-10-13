"""Auditable facility identity and supply; no road attachment or accessibility yet."""
import itertools
import json
import re
import textwrap
from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

import geopandas as gpd
import pandas as pd
import yaml

from .facility_config import FacilityConfig
from .facility_sources import clean, digest, freeze, import_source


@dataclass
class FacilityRegistry:
    facilities: gpd.GeoDataFrame
    records: gpd.GeoDataFrame
    matches: pd.DataFrame
    rejects: pd.DataFrame
    summary: dict
    provenance: dict


def normal(value):
    return " ".join(re.findall(r"\w+", clean(value).casefold()))


def identity_conflict(a, b):
    return bool(a["service"] != b["service"] or
                (a["official_id"] and b["official_id"] and a["id_namespace"] and
                 a["id_namespace"] == b["id_namespace"] and a["official_id"] != b["official_id"]) or
                (a.get("service_level") and b.get("service_level") and
                 normal(a["service_level"]) != normal(b["service_level"])))


def same_id(a, b):
    return bool(a["official_id"] and a["id_namespace"] and
                (a["official_id"], a["id_namespace"]) == (b["official_id"], b["id_namespace"]))


def same_site(a, b):
    ga, gb = a["geometry"], b["geometry"]
    if ga is None or gb is None or normal(a.get("name")) != normal(b.get("name")) or not normal(a.get("name")):
        return False
    if ga.geom_type == gb.geom_type == "Point":
        return ga.distance(gb) <= 0.5
    # A point inside a named polygon is a duplicate representation candidate.
    return ((ga.geom_type == "Point" and gb.covers(ga)) or
            (gb.geom_type == "Point" and ga.covers(gb)) or ga.equals(gb))


def reconcile(records, config):
    by_key = {r["record_key"]: r for r in records}
    keys = sorted(by_key)
    parent = {key: key for key in keys}
    def root(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key
    def union(a, b):
        ra, rb = root(a), root(b)
        parent[max(ra, rb)] = min(ra, rb)
    decisions, manual, separate = [], {}, set()
    if config.overrides:
        overrides = pd.read_csv(config.overrides, dtype=str, keep_default_na=False)
        if not {"left", "right", "action"} <= set(overrides):
            raise ValueError("match overrides require left,right,action columns")
        for row in overrides.to_dict("records"):
            a, b = row["left"], row["right"]
            if a not in by_key or b not in by_key or a == b or row["action"] not in {"merge", "separate"}:
                raise ValueError(f"invalid match override: {row}")
            pair = tuple(sorted((a, b)))
            if pair in manual:
                raise ValueError(f"duplicate match override: {pair}")
            manual[pair] = row["action"]
            if row["action"] == "separate":
                separate.add(pair)
            elif by_key[a]["service"] != by_key[b]["service"]:
                raise ValueError("manual merges cannot cross services")
            else:
                union(a, b)
            decisions.append({"left": pair[0], "right": pair[1], "decision": row["action"],
                              "reason": "manual_override", "distance_m": None})
    if any(root(a) == root(b) for a, b in separate):
        raise ValueError("transitive manual merges violate a separate override")
    # ID matches need no coordinates. Spatial candidates use a metric index.
    pairs = set()
    ids = defaultdict(list)
    for r in records:
        if r["official_id"] and r["id_namespace"]:
            ids[(r["service"], r["id_namespace"], r["official_id"])].append(r["record_key"])
    for group in ids.values():
        pairs.update(itertools.combinations(sorted(group), 2))
    located = [by_key[k] for k in keys if by_key[k]["geometry"] is not None]
    spatial = gpd.GeoSeries([r["geometry"] for r in located], crs=config.metric_crs)
    if len(spatial):
        index = spatial.sindex
        for i, r in enumerate(located):
            for j in index.query(r["geometry"].buffer(config.match_max_m)):
                if int(j) > i:
                    pairs.add(tuple(sorted((r["record_key"], located[int(j)]["record_key"]))))
    candidates = []
    for left, right in sorted(pairs):
        if (left, right) in manual:
            continue
        a, b = by_key[left], by_key[right]
        if a["service"] != b["service"]:
            continue
        distance = a["point"].distance(b["point"]) if a["point"] is not None and b["point"] is not None else None
        exact = same_id(a, b)
        name_a, name_b = normal(a.get("name")), normal(b.get("name"))
        site = "osm" in {a["kind"], b["kind"]} and same_site(a, b)
        conflict = identity_conflict(a, b)
        contextual = (distance is not None and distance <= config.match_max_m and
                      bool(name_a and name_b and name_a == name_b) and
                      (not a.get("address") or not b.get("address") or normal(a["address"]) == normal(b["address"])))
        plausible = (distance is not None and distance <= config.match_max_m and
                     (not name_a or not name_b or SequenceMatcher(None, name_a, name_b).ratio() >= 0.8))
        if exact or site or (a["source"] != b["source"] and contextual):
            reason = "official_id" if exact else "named_site" if site else "name_location_context"
            if exact and distance is not None and distance > config.match_max_m and not site:
                decisions.append({"left": left, "right": right, "decision": "review",
                                  "reason": "id_location_conflict", "distance_m": distance})
            elif conflict:
                decisions.append({"left": left, "right": right, "decision": "review",
                                  "reason": "identity_conflict", "distance_m": distance})
            else:
                candidates.append((left, right, reason, distance))
        elif plausible and not conflict and a["source"] != b["source"]:
            decisions.append({"left": left, "right": right, "decision": "review",
                              "reason": "insufficient_context", "distance_m": distance})
    # Build whole candidate components before deciding: iteration order cannot choose a winner.
    adjacency = {k: set() for k in keys}
    for a, b, _, _ in candidates:
        adjacency[root(a)].add(root(b))
        adjacency[root(b)].add(root(a))
    manual_groups, component_edges = defaultdict(list), defaultdict(list)
    for key in keys:
        manual_groups[root(key)].append(by_key[key])
    for edge in candidates:
        component_edges[root(edge[0])].append(edge)
    review_pairs = {tuple(sorted((d["left"], d["right"]))) for d in decisions if d["decision"] == "review"}
    visited = set()
    for start in keys:
        if start in visited or root(start) != start:
            continue
        todo, component = [start], set()
        while todo:
            key = todo.pop()
            if key in component:
                continue
            component.add(key)
            todo.extend(adjacency[key] - component)
        visited.update(component)
        members = [record for key in sorted(component) for record in manual_groups[key]]
        ambiguous = False
        for a, b in itertools.combinations(members, 2):
            pair = tuple(sorted((a["record_key"], b["record_key"])))
            # Explicit human merges may resolve otherwise contradictory identifiers/levels.
            if root(a["record_key"]) == root(b["record_key"]):
                continue
            if pair in separate or pair in review_pairs or identity_conflict(a, b) or (
                a["source"] == b["source"] and not same_id(a, b) and
                not (a["kind"] == b["kind"] == "osm" and same_site(a, b))
            ):
                ambiguous = True
        edges = sorted(edge for key in component for edge in component_edges[key])
        # Capture edges before union changes roots.
        for a, b, reason, distance in edges:
            decisions.append({"left": a, "right": b, "decision": "review" if ambiguous else "merge",
                              "reason": "ambiguous_component" if ambiguous else reason, "distance_m": distance})
        if not ambiguous:
            for a, b, _, _ in edges:
                union(a, b)
    if any(root(a) == root(b) for a, b in separate):
        raise ValueError("matching violated a separate override")
    groups = defaultdict(list)
    for k in keys:
        groups[root(k)].append(by_key[k])
    return list(groups.values()), decisions


def build_registry(config: FacilityConfig, out_dir: Path):
    records, rejects, manifests = [], [], []
    for source in config.sources:
        imported, rejected, metadata = import_source(source, config, out_dir)
        records.extend(imported)
        rejects.extend(rejected)
        manifests.append(metadata)
    if config.overrides:
        if config.override_sha256 and digest(config.overrides) != config.override_sha256:
            raise ValueError("frozen override checksum mismatch")
        override_manifest = freeze(config.overrides, out_dir)
    else:
        override_manifest = None
    groups, decisions = reconcile(records, config)
    review_keys = {row[key] for row in decisions if row["decision"] == "review" for key in ("left", "right")}
    facilities, lineage = [], {}
    fields = ("name", "address", "status", "service_level", "management", "subtype", "reference_year",
              "enrolment", "teachers", "classrooms")
    for group in groups:
        group.sort(key=lambda r: (r["kind"] != "official", r["source"], r["source_id"]))
        service = group[0]["service"]
        if service not in config.supply:
            raise ValueError(f"declare supply for imported service: {service}")
        convention = config.supply[service]
        # Identity anchored to a stable source key; membership changes are recorded in lineage.
        facility_id = group[0]["record_key"]
        selected, provenance, conflicts = {}, {}, {}
        for field in fields:
            available = [r for r in group if clean(r.get(field))]
            selected[field] = available[0].get(field) if available else ""
            provenance[field] = [{"record_key": r["record_key"], "value": r.get(field)} for r in available]
            if len({clean(r.get(field)) for r in available}) > 1:
                conflicts[field] = provenance[field]
        located = [r for r in group if r["point"] is not None]
        geom_record = located[0] if located else None
        provenance["geometry"] = [{"record_key": r["record_key"], "method": "point" if r["geometry"].geom_type == "Point" else "representative_point"} for r in located]
        kind = {r["kind"] for r in group}
        source_status = "matched" if len(kind) == 2 else "official_only" if "official" in kind else "osm_only"
        status_conflict = len({r["status"] for r in group} - {"unknown"}) > 1
        eligible = bool(geom_record and not any(r["record_key"] in review_keys for r in group) and selected["status"] != "inactive" and not status_conflict and
                        (selected["status"] == "active" or config.include_unknown_status) and
                        ("official" in kind or config.include_osm_candidates))
        capacity_records = [r for r in group if r["supply_value"] is not None]
        if convention.mode == "capacity" and any(r["supply_unit"] != convention.unit for r in capacity_records):
            raise ValueError(f"{facility_id}: capacity units differ from declared {convention.unit}")
        capacity = capacity_records[0]["supply_value"] if capacity_records else None
        provenance["capacity"] = [{"record_key": r["record_key"], "value": r["supply_value"], "unit": r["supply_unit"]} for r in capacity_records]
        if len({(r["supply_value"], r["supply_unit"]) for r in capacity_records}) > 1:
            conflicts["capacity"] = provenance["capacity"]
        if convention.mode == "equal":
            supply_value = 1.0 if eligible else None
        else:
            supply_value = capacity if eligible else None
            if eligible and capacity is None:
                rejects.append({"record_key": facility_id, "reason": "missing_supply", "row": None})
                if convention.missing == "error":
                    raise ValueError(f"{facility_id}: missing capacity ({convention.unit})")
                if convention.missing == "exclude":
                    eligible = False
        row = {"facility_id": facility_id, "service": service, **selected,
               "source_status": source_status, "supplementary_candidate": source_status == "osm_only",
               "eligible": eligible, "supply_ready": eligible and supply_value is not None,
               "review_required": any(r["record_key"] in review_keys for r in group) or bool(conflicts),
               "supply_value": supply_value, "supply_unit": convention.unit, "supply_mode": convention.mode,
               "capacity_value": capacity, "capacity_unit": capacity_records[0]["supply_unit"] if capacity_records else "",
               "source_keys": json.dumps([r["record_key"] for r in group]),
               "source_ids": json.dumps([{k: r[k] for k in ("source", "source_id", "official_id", "id_namespace")} for r in group]),
               "geometry_source": geom_record["record_key"] if geom_record else "",
               "location_method": ("point" if geom_record["geometry"].geom_type == "Point" else "representative_point") if geom_record else "missing",
               "attribute_provenance": json.dumps(provenance, ensure_ascii=False, sort_keys=True),
               "conflicts": json.dumps(conflicts, ensure_ascii=False, sort_keys=True),
               "geometry": geom_record["point"] if geom_record else None}
        facilities.append(row)
        for r in group:
            lineage[r["record_key"]] = facility_id
    facility_columns = ["facility_id", "service", "eligible", "supply_ready", "source_status", "geometry"]
    frame = gpd.GeoDataFrame(facilities if facilities else {k: [] for k in facility_columns}, geometry="geometry", crs=config.metric_crs)
    record_frame = gpd.GeoDataFrame([{**{k: v for k, v in r.items() if k != "point"},
                                     "facility_id": lineage[r["record_key"]]} for r in records] or
                                   {"record_key": [], "service": [], "kind": [], "status": [], "geometry": []},
                                   geometry="geometry", crs=config.metric_crs)
    summary = {"crs": config.metric_crs, "facility_count": len(frame), "record_count": len(records),
               "reject_event_count": len(rejects), "review_pair_count": sum(d["decision"] == "review" for d in decisions),
               "services": {}}
    for service, convention in sorted(config.supply.items()):
        entries = [r for r in facilities if r["service"] == service]
        official = [r for r in records if r["service"] == service and r["kind"] == "official"]
        eligible_official = [r for r in official if r["status"] != "inactive" and
                             (r["status"] == "active" or config.include_unknown_status)]
        valid_official = [r for r in eligible_official if r["geometry"] is not None]
        matched_ids = {r["facility_id"] for r in entries if r["source_status"] == "matched"}
        matched = [r for r in valid_official if lineage[r["record_key"]] in matched_ids]
        summary["services"][service] = {
            "source_status_counts": dict(Counter(r["source_status"] for r in entries)),
            "status_counts": dict(Counter(r["status"] for r in entries)),
            "official_records": len(official), "eligible_official_records": len(eligible_official),
            "valid_coordinate_official_records": len(valid_official), "osm_matched_official_records": len(matched),
            "osm_match_fraction_valid_official": len(matched) / len(valid_official) if valid_official else None,
            "eligible_facilities": sum(r["eligible"] for r in entries),
            "supply_ready_facilities": sum(r["supply_ready"] for r in entries),
            "capacity_complete_facilities": sum(r["capacity_value"] is not None for r in entries),
            "eligible_official_capacity_records": sum(r["supply_value"] is not None for r in eligible_official),
            "missing_location_facilities": sum(r["geometry"] is None for r in entries),
            "supply": convention.model_dump(),
            "reference_years": sorted({r["reference_year"] for r in records if r["service"] == service}),
            "retrieval_dates": sorted({r["retrieved_at"] for r in records if r["service"] == service}),
            "coverage_interpretation": "OSM matches relative to this reference sample; not inventory completeness"}
    provenance = {"sources": manifests, "overrides": override_manifest,
                  "matching": "IDs, then exact normalized name plus spatial/address context; ambiguous components stay separate",
                  "identity_version": 1}
    return FacilityRegistry(frame, record_frame,
                            pd.DataFrame(decisions, columns=["left", "right", "decision", "reason", "distance_m"]),
                            pd.DataFrame(rejects, columns=["record_key", "reason", "row", "value"]), summary, provenance)


def facility_report(summary):
    lines = ["Facilities (Ticket 17; attachment and 2SFCA not computed)",
             f"Registry: {summary['facility_count']} facilities from {summary['record_count']} records",
             f"Reject events: {summary['reject_event_count']}; review pairs: {summary['review_pair_count']}"]
    for service, audit in summary["services"].items():
        lines.extend([f"{service}: {audit['eligible_facilities']} eligible; {audit['supply_ready_facilities']} supply-ready",
                      f"Supply: {audit['supply']['mode']} ({audit['supply']['unit']}); missing: {audit['supply']['missing']}",
                      f"Official sample: {audit['eligible_official_records']} eligible, {audit['valid_coordinate_official_records']} valid locations, {audit['osm_matched_official_records']} OSM matches",
                      audit["coverage_interpretation"]])
    return lines


def export_registry(result, config, out_dir, *, gpkg=None):
    out_dir.mkdir(parents=True, exist_ok=True)
    path = gpkg or out_dir / "registry.gpkg"
    result.facilities.to_file(path, layer="facilities", driver="GPKG", engine="pyogrio")
    result.records.to_file(path, layer="facility_source_records", driver="GPKG", engine="pyogrio")
    result.matches.to_csv(out_dir / "facility_matches.csv", index=False)
    result.rejects.to_csv(out_dir / "facility_rejects.csv", index=False)
    (out_dir / "facility_audit.json").write_text(json.dumps(result.summary, indent=2, allow_nan=False) + "\n")
    (out_dir / "facility_provenance.json").write_text(json.dumps(result.provenance, indent=2) + "\n")
    # Resolve to frozen raw inputs and override, so a copied config remains rerunnable offline.
    resolved = config.model_dump(mode="json")
    for source, metadata in zip(resolved["sources"], result.provenance["sources"]):
        if source["format"] in {"osm_bbox", "osm_xml"}:
            source["format"] = "osm_xml"
        source["path"] = metadata["raw_path"]
        source["retrieved_at"] = metadata["retrieved_at"]
        source["sha256"] = metadata["sha256"]
    resolved["offline"] = True
    resolved["output_dir"] = str(out_dir.resolve())
    if result.provenance["overrides"]:
        resolved["overrides"] = result.provenance["overrides"]["raw_path"]
        resolved["override_sha256"] = result.provenance["overrides"]["sha256"]
    (out_dir / "facility_config.yaml").write_text(yaml.safe_dump(resolved, sort_keys=False))
    if not config.figures:
        (out_dir / "facility_comparison.png").unlink(missing_ok=True)
    if config.figures:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        services = sorted(config.supply)
        fig, axes = plt.subplots(1, len(services), figsize=(6 * len(services), 5), squeeze=False)
        located = result.facilities[result.facilities.geometry.notna()]
        bounds = located.total_bounds if len(located) else None
        for ax, service in zip(axes[0], services):
            for status, color, marker in (("matched", "tab:green", "o"), ("official_only", "tab:blue", "x"), ("osm_only", "tab:orange", "+")):
                subset = result.facilities.loc[(result.facilities.service == service) & (result.facilities.source_status == status)]
                subset = subset[subset.geometry.notna()]
                if len(subset):
                    subset.plot(ax=ax, color=color, marker=marker, label=status, markersize=40)
            ax.set_title(service)
            ax.set_xlabel("Easting (m)")
            ax.set_ylabel("Northing (m)")
            if bounds is not None:
                xmin, ymin, xmax, ymax = bounds
                margin = max(xmax - xmin, ymax - ymin, 100) * 0.1
                ax.set_xlim(xmin - margin, xmax + margin)
                ax.set_ylim(ymin - margin, ymax + margin)
            if not len(located[located.service == service]):
                ax.text(0.5, 0.5, "No located facilities", transform=ax.transAxes, ha="center")
            from matplotlib.ticker import MaxNLocator
            ax.xaxis.set_major_locator(MaxNLocator(3))
            ax.yaxis.set_major_locator(MaxNLocator(4))
            ax.ticklabel_format(style="plain", useOffset=False)
            ax.tick_params(axis="both", labelsize=8)
            ax.set_aspect("equal")
            if ax.get_legend_handles_labels()[0]:
                ax.legend()
        fig.suptitle("Facility source comparison (missing locations omitted)")
        fig.text(0.5, 0.005, "OSM data: OpenStreetMap contributors (ODbL); official source details in facility_provenance.json",
                 ha="center", fontsize=7)
        fig.tight_layout(rect=(0, 0.025, 1, 1))
        fig.savefig(out_dir / "facility_comparison.png", dpi=160)
        plt.close(fig)


def run_facilities(config, out_override=None, overwrite=False):
    out_dir = out_override or config.output_dir
    if out_dir.exists() and any(out_dir.iterdir()) and not overwrite:
        raise ValueError(f"facility output exists: {out_dir} (use --overwrite)")
    # Never delete raw files; resolved offline configs may point into this directory.
    result = build_registry(config, out_dir)
    export_registry(result, config, out_dir)
    (out_dir / "summary.json").write_text(json.dumps({"facilities": result.summary}, indent=2) + "\n")
    (out_dir / "run_config.yaml").write_text((out_dir / "facility_config.yaml").read_text())
    (out_dir / "report.txt").write_text("\n".join(textwrap.fill(line, width=100) for line in facility_report(result.summary)) + "\n")
    return result.summary
