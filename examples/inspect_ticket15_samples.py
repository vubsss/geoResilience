"""Inspect frozen Ticket 15 windows and compare two consolidation runs offline.

Run from the repository root; see --help. No downloads, refitting, or edits to
the inputs/analysis results. With --comparison, require a completed controlled
15 m versus 0 m experiment before producing the comparison table.
"""

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
import textwrap

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter, LogLocator, NullFormatter
import numpy as np
import osmnx as ox
from shapely.geometry import Point
from scipy.spatial.distance import pdist

from georesilience.config import RunConfig
from georesilience.crucitti import CITIES, CONVENTIONS, _sha256, square_sample
from georesilience.links import _link_rows, _text
from georesilience.network import load_and_clean

PATH_TYPES = {"footway", "pedestrian", "path", "steps", "cycleway", "corridor"}
COLORS = {"other_highway": "#3379a8", "path_or_cycle": "#e69f00",
          "service": "#cc5364", "mixed": "#9966aa", "missing": "#888888"}
PAPER_COUNTS = {"ahmedabad": (2870, 4387), "cairo": (1496, 2255),
                "los-angeles": (240, 340), "richmond": (697, 1086)}
RICHMOND_NOTE = (
    "Location review: the companion paper by Porta, Crucitti and Latora (2006), "
    "The Network Analysis of Urban Streets: A Primal Approach, section 3.1/Figure 1, "
    "explicitly labels Richmond, CA. An initial concern from Jacobs' Virginia index "
    "does not establish a wrong-city error. Retain California; exact historical window is unverified."
)
RICHMOND_SOURCE = "https://www.udsu-strath.com/wp-content/uploads/2010/06/PA2006_09.pdf"


def category(highway):
    """Disjoint descriptive groups, not an access/transport-mode classifier."""
    if highway is None or (isinstance(highway, (float, np.floating)) and np.isnan(highway)) or not str(highway).strip():
        return "missing"
    types = set(str(highway).split(";"))
    groups = {"path_or_cycle" if value in PATH_TYPES else
              "service" if value == "service" else "other_highway" for value in types}
    return next(iter(groups)) if len(groups) == 1 else "mixed"


def street_mix(records, *, city, stage, tag="highway"):
    """Each physical segment contributes exactly once, including unknown tags.

    Counts on raw inputs refer to unsimplified OSM segments, not junction-to-
    junction streets. Length fractions are more useful for cross-stage review.
    Multi-valued tags are one explicitly combined category, never double counted.
    """
    totals = defaultdict(lambda: [0, 0.0])
    for record in records:
        raw_value = record.get(tag)
        missing = raw_value is None or (isinstance(raw_value, (float, np.floating)) and np.isnan(raw_value))
        value = "(unspecified)" if missing else _text(raw_value) or "(unspecified)"
        totals[value][0] += 1
        totals[value][1] += float(record["length_m"])
    length = sum(value[1] for value in totals.values())
    count = sum(value[0] for value in totals.values())
    return [{"city": city, "stage": stage, "tag": tag, "value": value,
             "physical_segments": n, "count_pct": 100 * n / count,
             "length_km": metres / 1000,
             "length_pct": 100 * metres / length if length else 0}
            for value, (n, metres) in sorted(totals.items(), key=lambda item: -item[1][1])]


def controlled_configs(baseline, comparison):
    """Fail closed if an apparent sensitivity study changed other settings."""
    configs = [json.loads((Path(folder) / "run_config.json").read_text())
               for folder in (baseline, comparison)]
    if [config["consolidation_tolerance_m"] for config in configs] != [15, 0]:
        raise ValueError("expected a 15 m baseline and a 0 m comparison")
    ignored = {"consolidation_tolerance_m", "started_utc", "inputs_dir"}
    stable = [{key: value for key, value in config.items() if key not in ignored} for config in configs]
    if stable[0] != stable[1]:
        raise ValueError("comparison changed settings or frozen hashes besides consolidation")
    if set(configs[0]["snapshots"]) != {city.slug for city in CITIES}:
        raise ValueError("expected all four frozen city snapshots")
    return configs


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def cluster_audit(cleaned, raw):
    """Measure original simplified junctions merged into each retained centroid."""
    records = []
    for node, data in cleaned.nodes(data=True):
        originals = data.get("osmid_original", node)
        originals = originals if isinstance(originals, list) else [originals]
        xy = np.array([[raw.nodes[n]["x"], raw.nodes[n]["y"]] for n in originals])
        centre = np.array([data["x"], data["y"]])
        records.append({"node_id": str(node), "merged_junctions": len(originals),
                        "max_displacement_m": float(np.linalg.norm(xy - centre, axis=1).max()),
                        "diameter_m": float(pdist(xy).max()) if len(xy) > 1 else 0.0,
                        "original_osm_node_ids": ",".join(map(str, originals)),
                        "geometry": Point(*centre)})
    return records


def plot_window(axis, edges, square, title, nodes=None):
    for group, color in COLORS.items():
        selected = edges[edges["category"] == group]
        if len(selected):
            selected.plot(ax=axis, color=color, linewidth=.65)
    if nodes is not None:
        nodes.plot(ax=axis, color="#222222", markersize=1.5, alpha=.7)
    x0, y0, x1, y1 = square.bounds
    axis.plot(*square.exterior.xy, color="black", linewidth=.8)
    axis.plot([x0 + 70, x0 + 570], [y0 + 65] * 2, color="black", linewidth=2)
    axis.text(x0 + 320, y0 + 95, "500 m", ha="center", fontsize=8)
    axis.set(xlim=(x0 - 15, x1 + 15), ylim=(y0 - 15, y1 + 15), title=title, aspect="equal")
    axis.set_axis_off()


def save_map(fig, path, title):
    handles = [Line2D([], [], color=color, label=name.replace("_", " ")) for name, color in COLORS.items()]
    fig.legend(handles=handles, loc="lower center", ncol=len(handles), fontsize=8)
    fig.suptitle(textwrap.fill(title, width=int(fig.get_figwidth() * 11)), fontsize=12)
    fig.tight_layout(rect=(0, .035, 1, .97))
    fig.savefig(path, dpi=180)
    plt.close(fig)


def inspect(inputs, baseline, output, comparison=None):
    inputs, baseline, output = map(Path, (inputs, baseline, output))
    comparison = Path(comparison) if comparison is not None else None
    sources = [inputs.resolve(), baseline.resolve()]
    if comparison is not None:
        sources.append(comparison.resolve())
    if any(output.resolve().is_relative_to(source) for source in sources):
        raise ValueError("inspection output must be separate from inputs and analysis directories")
    # Validate before writing anything, including partially completed comparisons.
    roots = [("15m", baseline)]
    if comparison is not None:
        configs = controlled_configs(baseline, comparison)
        roots.append(("0m", comparison))
    else:
        configs = [json.loads((baseline / "run_config.json").read_text())]
    summaries = {(stage, city.slug): json.loads((root / city.slug / "summary.json").read_text())
                 for stage, root in roots for city in CITIES}
    aggregates = {stage: json.loads((root / "comparison.json").read_text()) for stage, root in roots}
    manifests = {}
    for city in CITIES:
        folder = inputs / city.slug
        manifest = json.loads((folder / "manifest.json").read_text())
        for name, filename in (("raw_graph_sha256", "raw.graphml"), ("boundary_sha256", "boundary.geojson")):
            if _sha256(folder / filename) != manifest[name]:
                raise ValueError(f"{city.slug}: frozen {filename} checksum mismatch")
        if configs[0]["snapshots"][city.slug] != manifest["raw_graph_sha256"]:
            raise ValueError(f"{city.slug}: analysis used a different frozen input")
        if manifest["sample"]["city"] != vars(city) or manifest["sample"]["side_m"] != 1609:
            raise ValueError(f"{city.slug}: sample settings differ")
        for stage, _ in roots:
            if summaries[stage, city.slug]["input_manifest"] != manifest:
                raise ValueError(f"{city.slug}: summary provenance differs")
        if comparison is not None:
            for convention in CONVENTIONS:
                first, second = [summaries[stage, city.slug]["comparisons"][convention]
                                 for stage, _ in roots]
                for key in ("rule", "thresholds", "efficiency_convention"):
                    if first[key] != second[key]:
                        raise ValueError(f"{city.slug}/{convention}: classifier {key} differs")
        manifests[city.slug] = manifest
    output.mkdir(parents=True, exist_ok=True)
    # An interrupted audit must not leave an old completed report beside new layers.
    for filename in ("report.txt", "audit_manifest.json"):
        (output / filename).unlink(missing_ok=True)
    raw_fig, raw_axes = plt.subplots(2, 2, figsize=(11, 11))
    clean_fig, clean_axes = plt.subplots(4, len(roots), figsize=(5.5 * len(roots), 21), squeeze=False)
    score_fig, score_axes = plt.subplots(4, 3, figsize=(15, 15))
    mix, access, service, windows, comparisons, clusters = [], [], [], [], [], []
    lines = ["Ticket 15: fixed-window street audit and consolidation sensitivity",
             "Frozen inputs verified; no centres, filters, fitting rules or thresholds retuned.",
             "Raw counts = physical unsimplified segments; length = stored metric weights.",
             "Opposite arcs grouped by endpoint pair, OSM IDs and rounded length, as in analysis.",
             "Multi-valued highway tags form a combined class; each physical segment counted once.",
             "Path/cycle group: " + ", ".join(sorted(PATH_TYPES)) + ". Service reported separately.",
             "These groups do not establish legal access or motor-vehicle eligibility.",
             "Unspecified access/service tags mean unknown, not unrestricted/no service.",
             "Current OSMnx all-filter: " + ox._overpass._get_network_filter("all"),
             "The all-filter does not exclude private access. Inputs are frozen OSMnx 2.1.1 downloads.",
             "Frozen graphs do not retain footway/sidewalk subtype tags; parallel sidewalk coverage cannot be fully separated from other paths.",
             "AP2 Table 1 counts below are historical context, not numerical pass targets.", ""]
    lines.extend([RICHMOND_NOTE, "  Evidence: " + RICHMOND_SOURCE, ""])
    for index, city in enumerate(CITIES):
        manifest = manifests[city.slug]
        graph = ox.project_graph(ox.load_graphml(inputs / city.slug / "raw.graphml"),
                                 to_crs=manifest["projected_crs"])
        raw = _link_rows(graph)
        for row in raw:
            data = graph.edges[row["_edges"][0]]
            row.update(access=_text(data.get("access")), service=_text(data.get("service")),
                       category=category(row["highway"]))
        mix.extend(street_mix(raw, city=city.slug, stage="raw"))
        access.extend(street_mix(raw, city=city.slug, stage="raw", tag="access"))
        service.extend(street_mix(raw, city=city.slug, stage="raw", tag="service"))
        raw_edges = gpd.GeoDataFrame([{key: value for key, value in row.items() if not key.startswith("_")}
                                     for row in raw], crs=graph.graph["crs"])
        raw_nodes = gpd.GeoDataFrame([{"node_id": str(n), "geometry": Point(d["x"], d["y"])}
                                     for n, d in graph.nodes(data=True)], crs=graph.graph["crs"])
        square, crs, boundary = square_sample(city)
        total = sum(row["length_m"] for row in raw)
        fractions = {group: 100 * sum(row["length_m"] for row in raw if row["category"] == group) / total
                     for group in COLORS}
        unknown_access = sum(row["length_m"] for row in raw if row["access"] is None) / total * 100
        private = sum(row["length_m"] for row in raw if row["access"] == "private") / total * 100
        audit_path = output / f"{city.slug}.gpkg"
        audit_path.unlink(missing_ok=True)
        raw_edges.to_file(audit_path, layer="raw_edges", driver="GPKG", engine="pyogrio")
        raw_nodes.to_file(audit_path, layer="raw_nodes", driver="GPKG", engine="pyogrio", mode="a")
        gpd.GeoDataFrame(geometry=[square], crs=crs).to_file(
            audit_path, layer="boundary", driver="GPKG", engine="pyogrio", mode="a")
        config = RunConfig(input={"source": "graphml", "path": inputs / city.slug / "raw.graphml"},
                           cleaning={"consolidate": True, "tolerance_m": 15})
        cleaned, _, _ = load_and_clean(config, undirected=True, enforce_dead_end_guard=False)
        cluster_records = cluster_audit(cleaned, graph)
        cluster_frame = gpd.GeoDataFrame(cluster_records, crs=crs)
        saved_nodes = gpd.read_file(baseline / city.slug / "network.gpkg", layer="nodes").set_index("node_id")
        # Rebuilding must reproduce the stored baseline before interpreting clusters.
        for row in cluster_records:
            if row["geometry"].distance(saved_nodes.loc[row["node_id"], "geometry"]) > 1e-6:
                raise ValueError(f"{city.slug}: rebuilt consolidation differs from stored baseline")
        if len(saved_nodes) != len(cluster_frame):
            raise ValueError(f"{city.slug}: rebuilt consolidation node count differs")
        cluster_frame.to_file(audit_path, layer="clusters_15m", driver="GPKG", engine="pyogrio", mode="a")
        clusters.extend({"city": city.slug, **{k: v for k, v in row.items() if k != "geometry"}}
                        for row in cluster_records)
        largest = max(cluster_records, key=lambda row: row["merged_junctions"])
        max_shift = max(row["max_displacement_m"] for row in cluster_records)
        plot_window(raw_axes.flat[index], raw_edges, square,
                    f"{city.name}: {len(raw):,} raw segments\n"
                    f"centre {city.latitude:.4f}, {city.longitude:.4f}; north ↑")
        windows.append({"city": city.slug, "latitude": city.latitude, "longitude": city.longitude,
                        "side_m": 1609, "projected_crs": crs.to_string(),
                        "projected_bounds": list(square.bounds), "wgs84_bounds": list(boundary.bounds),
                        "raw_sha256": manifest["raw_graph_sha256"],
                        "raw_physical_segments": len(raw), "raw_length_km": total / 1000,
                        "raw_category_length_pct": fractions,
                        "private_access_length_pct": private, "unknown_access_length_pct": unknown_access,
                        "largest_retained_cluster_junctions": largest["merged_junctions"],
                        "largest_cluster_diameter_m": largest["diameter_m"],
                        "max_junction_displacement_m": max_shift,
                        "raw_nodes_outside_square": int((~raw_nodes.geometry.within(square.buffer(.01))).sum()),
                        "paper_nodes": PAPER_COUNTS[city.slug][0], "paper_edges": PAPER_COUNTS[city.slug][1],
                        "historical_window_verified": False})
        if city.slug == "richmond":
            windows[-1]["location_warning"] = RICHMOND_NOTE
            windows[-1]["location_evidence_url"] = RICHMOND_SOURCE
        lines.extend([city.name,
                      f"  Centre: {city.latitude}, {city.longitude}; 1609 m square; {crs.to_string()}",
                      f"  Raw: {len(graph)} nodes, {len(raw)} physical segments, {total / 1000:.3f} km",
                      f"  Path/cycle length: {fractions['path_or_cycle']:.2f}%; service: {fractions['service']:.2f}%",
                      f"  Explicit private-access length: {private:.2f}%; unspecified access: {unknown_access:.2f}%",
                      f"  Largest retained 15 m cluster: {largest['merged_junctions']} original junctions; "
                      f"diameter {largest['diameter_m']:.1f} m; maximum displacement across all clusters {max_shift:.1f} m",
                      f"  AP2 Table 1: N={PAPER_COUNTS[city.slug][0]}, K={PAPER_COUNTS[city.slug][1]}"])
        for column, (stage, root) in enumerate(roots):
            result = summaries[stage, city.slug]
            nodes = gpd.read_file(root / city.slug / "network.gpkg", layer="nodes").to_crs(crs)
            edges = gpd.read_file(root / city.slug / "network.gpkg", layer="edges").to_crs(crs)
            if len(nodes) != result["node_count"] or len(edges) != result["link_count"]:
                raise ValueError(f"{city.slug}/{stage}: layer and summary counts differ")
            if result["information_coverage"] != "all" or result["information_nodes"] != len(nodes):
                raise ValueError(f"{city.slug}/{stage}: information coverage is incomplete")
            for name in ("information_inverse", "information_spatial"):
                if not np.isfinite(nodes[name]).all() or not nodes[name].between(0, 1).all():
                    raise ValueError(f"{city.slug}/{stage}: invalid {name}")
            edges["category"] = edges["highway"].map(category)
            mix.extend(street_mix(edges.to_dict("records"), city=city.slug, stage=stage))
            for layer, frame in ((f"edges_{stage}", edges), (f"nodes_{stage}", nodes)):
                frame.to_file(audit_path, layer=layer, driver="GPKG", engine="pyogrio", mode="a")
            plot_window(clean_axes[index, column], edges, square,
                        f"{city.name}, {stage}: {len(nodes):,} nodes / {len(edges):,} links", nodes)
            boundary_leaves = int(((nodes["degree"] == 1) & (nodes.distance(square.boundary) <= 20)).sum())
            fits = result["comparisons"]
            for score_column, (field, convention, metric) in enumerate((
                    ("information_inverse", CONVENTIONS[0], "information"),
                    ("information_spatial", CONVENTIONS[1], "information"),
                    ("betweenness", CONVENTIONS[1], "betweenness"))):
                values = nodes[field].to_numpy(dtype=float)
                values = np.sort(values[np.isfinite(values) & (values > 0)])
                axis = score_axes[index, score_column]
                if len(values):
                    survival = (len(values) - np.arange(len(values))) / len(values)
                    verdict = fits[convention]["distributions"][metric]["verdict"]
                    axis.step(values, survival, where="pre", label=f"{stage}: {verdict}",
                              color=("#c74d4d", "#3379a8")[column], linestyle=("-", "--")[column])
                axis.set(yscale="log", xlabel=field.replace("_", " "),
                         ylabel="Fraction of positive scores ≥ x", title=city.name)
                if metric == "information":
                    axis.set_xscale("log")
                    axis.xaxis.set_major_locator(LogLocator(base=10, subs=(1, 2, 5), numticks=7))
                    axis.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:.3g}"))
                    axis.xaxis.set_minor_formatter(NullFormatter())
                axis.tick_params(labelsize=8)
                axis.grid(alpha=.2)
                axis.legend(fontsize="small")
            for convention in CONVENTIONS:
                fit = fits[convention]["distributions"]
                comparisons.append({"city": city.slug, "consolidation_m": int(stage[:-1]),
                                    "convention": convention, "nodes": len(nodes), "links": len(edges),
                                    "length_km": float(edges["length_m"].sum() / 1000),
                                    "degree_1_nodes": int((nodes["degree"] == 1).sum()),
                                    "max_degree": int(nodes["degree"].max()),
                                    "self_loop_links": int(edges["is_self_loop"].sum()),
                                    "median_link_length_m": float(edges["length_m"].median()),
                                    "degree_1_within_20m_of_boundary": boundary_leaves,
                                    "component_nodes_dropped": result["cleaning"]["dropped_components"]["nodes_dropped"],
                                    "baseline_efficiency": result["baseline_efficiency"][
                                        "inverse_distance_per_m" if convention == CONVENTIONS[0] else "spatial_dimensionless"],
                                    "information": fit["information"]["verdict"],
                                    "information_tail_nodes": fit["information"]["n_tail"],
                                    "betweenness": fit["betweenness"]["verdict"],
                                    "network_label": fits[convention]["network_label"],
                                    "information_seconds": result["information_seconds"]})
            lines.append(f"  {stage}: {len(nodes)} nodes / {len(edges)} links; "
                         f"degree-1 nodes {(nodes['degree'] == 1).sum()} ({boundary_leaves} within 20 m of boundary); "
                         f"maximum degree {nodes['degree'].max()}")
            for convention in CONVENTIONS:
                fit = fits[convention]["distributions"]
                lines.append(f"    {convention}: information={fit['information']['verdict']}, "
                             f"betweenness={fit['betweenness']['verdict']}")
        lines.append("")
    for stage, aggregate in aggregates.items():
        for convention in CONVENTIONS:
            row = aggregate["comparisons"][convention]
            lines.append(f"{stage} {convention}: {row['status']}; information {row['information_matches']}/4; "
                         f"betweenness {row['betweenness_matches']}/4")
    lines.extend(["", "Windows are fixed modern coordinate samples; their identity with AP2/Jacobs maps is unverified.",
                  "Review raw_windows.png and topology_comparison.png; QGIS layers retain highway/access/service tags.",
                  "Changing consolidation also changes connected-component membership and shortest-path weights.",
                  "OSMnx buffers nodes by tolerance and merges connected overlaps transitively: 15 m is not a maximum cluster diameter/displacement.",
                  "Node scores between runs are distributions over different junction populations; do not pair by node ID.",
                  "Street-type inspection alone does not quantify a filter effect: no alternative filter was run.",
                  "MISMATCH is empirical disagreement, not a numerical test failure. Do not pick settings to force PASS."])
    write_csv(output / "street_types.csv", mix)
    write_csv(output / "raw_access.csv", access)
    write_csv(output / "raw_service.csv", service)
    write_csv(output / "consolidation_comparison.csv", comparisons)
    write_csv(output / "consolidation_clusters.csv", clusters)
    provenance = {"run_configs": configs,
                  "summary_sha256": {stage: {city.slug: _sha256(root / city.slug / "summary.json")
                                             for city in CITIES} for stage, root in roots},
                  "inspection_script_sha256": _sha256(Path(__file__)),
                  "snapshot_boundary_sha256": {slug: manifest["boundary_sha256"]
                                               for slug, manifest in manifests.items()}}
    (output / "audit_manifest.json").write_text(json.dumps(provenance, indent=2, allow_nan=False) + "\n")
    (output / "windows.json").write_text(json.dumps(windows, indent=2, allow_nan=False) + "\n")
    (output / "report.txt").write_text("\n".join(lines) + "\n")
    save_map(raw_fig, output / "raw_windows.png", "Frozen Ticket 15 inputs: street types, same 1609 m extent; north up")
    save_map(clean_fig, output / "topology_comparison.png", "Fixed windows: consolidation changes topology and node population")
    score_fig.suptitle("Consolidation sensitivity: positive-score CCDFs (betweenness labels use AP2 reference)")
    score_fig.tight_layout(rect=(0, 0, 1, .97))
    score_fig.savefig(output / "centrality_comparison.png", dpi=150)
    plt.close(score_fig)
    print(f"Offline sample inspection written to {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, default=Path("results/ticket15-crucitti/inputs"))
    parser.add_argument("--baseline", type=Path, default=Path("results/ticket15-crucitti"))
    parser.add_argument("--comparison", type=Path, help="completed 0 m run; omit for baseline-only inspection")
    parser.add_argument("--out", type=Path, default=Path("results/ticket15-inspection"))
    args = parser.parse_args()
    inspect(args.inputs, args.baseline, args.out, args.comparison)
