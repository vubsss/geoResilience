"""Frozen modern-city comparison with Crucitti, Latora & Porta (AP2).

This is a qualitative comparison, not a reconstruction of the historical maps.
The production classifier and inverse-distance convention remain unchanged.
"""

import copy
import csv
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import geopandas as gpd
import numpy as np
import osmnx as ox
from pyproj import CRS, Transformer
from scipy.spatial.distance import cdist
from scipy.stats import expon, rayleigh
from shapely import transform
from shapely.geometry import Point, box, mapping

from .centralities import compute_centralities
from .classification import agreement, classify_network, fit_distribution, network_decision
from .config import AnalysisConfig, RunConfig
from .links import _link_rows
from .network import _log, cleaning_report, load_and_clean
from .pipeline import _versions
from .progress import StageProgress
from .removal import ActiveEdgeGraph, removal_engine

SIDE_M = 1609.0
CONVENTIONS = ("framework_inverse_distance", "ap2_spatial")
CAVEAT = ("OSM 2026 ≠ 1990s street maps used in the paper; sample locations approximate; "
          "agreement is qualitative.")


@dataclass(frozen=True)
class City:
    slug: str
    name: str
    latitude: float
    longitude: float
    pattern: str
    information: str
    betweenness: str
    paper_gamma: float | None = None


CITIES = (
    City("ahmedabad", "Ahmedabad", 23.0225, 72.5880, "self-organised", "power_law", "exponential", 2.74),
    City("cairo", "Cairo", 30.0478, 31.2625, "self-organised", "power_law", "exponential", 2.63),
    City("los-angeles", "Los Angeles", 34.0480, -118.2520, "planned", "exponential", "gaussian"),
    City("richmond", "Richmond, CA", 37.9358, -122.3478, "planned", "exponential", "gaussian"),
)


def square_sample(city, side_m=SIDE_M):
    """Return a metric UTM square, its CRS and its WGS84 download polygon."""
    if not math.isfinite(side_m) or side_m <= 0:
        raise ValueError("sample side must be finite and positive")
    zone = min(60, max(1, int((city.longitude + 180) // 6) + 1))
    crs = CRS.from_epsg((32600 if city.latitude >= 0 else 32700) + zone)
    forward = Transformer.from_crs(4326, crs, always_xy=True)
    backward = Transformer.from_crs(crs, 4326, always_xy=True)
    x, y = forward.transform(city.longitude, city.latitude)
    half = side_m / 2
    square = box(x - half, y - half, x + half, y + half)
    boundary = transform(square, lambda xy: np.column_stack(backward.transform(xy[:, 0], xy[:, 1])))
    return square, crs, boundary


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path, value):
    # Atomic writes leave either the previous complete record or the new one.
    temporary = Path(str(path) + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def frozen_input(city, inputs_dir, *, offline=False):
    folder = Path(inputs_dir) / city.slug
    graph_path, manifest_path = folder / "raw.graphml", folder / "manifest.json"
    boundary_path = folder / "boundary.geojson"
    sample = {"city": asdict(city), "side_m": SIDE_M, "network_type": "all",
              "simplify": False, "retain_all": True, "truncate_by_edge": False}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("sample") != sample:
            raise ValueError(f"{manifest_path}: frozen sample settings differ; use a new inputs directory")
        for name, path in (("raw_graph_sha256", graph_path), ("boundary_sha256", boundary_path)):
            if not path.is_file() or _sha256(path) != manifest.get(name):
                raise ValueError(f"{path}: frozen input missing or checksum mismatch")
        if not (folder / "input.gpkg").exists():
            _input_preview(ox.load_graphml(filepath=graph_path), square_sample(city)[2], folder / "input.gpkg")
        _log(f"{city.name}: reusing frozen input from {manifest['download_utc']}")
        return graph_path, manifest
    if offline:
        raise ValueError(f"{city.name}: no frozen manifest in {folder}; download inputs first")
    if graph_path.exists():
        raise ValueError(f"{graph_path}: graph has no provenance manifest; use a new inputs directory")
    folder.mkdir(parents=True, exist_ok=True)
    square, crs, boundary = square_sample(city)
    _json(boundary_path, {"type": "FeatureCollection", "features": [{"type": "Feature",
          "properties": {"city": city.name, "side_m": SIDE_M, "projected_crs": crs.to_string()},
          "geometry": mapping(boundary)}]})
    _log(f"{city.name}: downloading {SIDE_M:g} m square, network.type=all")
    graph = ox.graph_from_polygon(boundary, network_type="all", simplify=False,
                                  retain_all=True, truncate_by_edge=False)
    if not len(graph) or not graph.number_of_edges():
        raise ValueError(f"{city.name}: downloaded network is empty")
    temporary = folder / "raw.tmp.graphml"
    ox.save_graphml(graph, filepath=temporary)
    temporary.replace(graph_path)
    manifest = {"sample": sample, "download_utc": datetime.now(timezone.utc).isoformat(),
                "raw_graph_sha256": _sha256(graph_path), "boundary_sha256": _sha256(boundary_path),
                "projected_crs": crs.to_string(), "projected_bounds": list(square.bounds),
                "raw_nodes": len(graph), "raw_directed_edges": graph.number_of_edges(),
                "versions": _versions(), "overpass_url": ox.settings.overpass_url,
                "overpass_settings": ox.settings.overpass_settings,
                "location_note": "Fixed Ticket 15 coordinates; not the original georeferenced AP2 windows."}
    _json(manifest_path, manifest)
    _input_preview(graph, boundary, folder / "input.gpkg")
    return graph_path, manifest


def _input_preview(graph, boundary, path):
    """QGIS copy of the raw input, before simplification/consolidation."""
    projected = ox.project_graph(graph)
    path.unlink(missing_ok=True)
    nodes = [{"node_id": str(node), "geometry": Point(data["x"], data["y"])}
             for node, data in projected.nodes(data=True)]
    edges = [{key: row[key] for key in ("link_id", "u", "v", "length_m", "geometry")}
             for row in _link_rows(projected)]
    for layer, records in (("nodes", nodes), ("edges", edges)):
        gpd.GeoDataFrame(records, geometry="geometry", crs=projected.graph["crs"]).to_file(
            path, layer=layer, driver="GPKG", engine="pyogrio", mode="w" if layer == "nodes" else "a")
    gpd.GeoDataFrame(geometry=[boundary], crs=4326).to_crs(projected.graph["crs"]).to_file(
        path, layer="boundary", driver="GPKG", engine="pyogrio", mode="a")


@dataclass
class DualEfficiencyReducer:
    coordinates: np.ndarray

    def __call__(self, distances, sources):
        inverse = np.divide(1.0, distances, out=np.zeros_like(distances),
                            where=np.isfinite(distances) & (distances > 0))
        spatial = cdist(self.coordinates[sources], self.coordinates)
        spatial *= inverse
        return np.column_stack((inverse.sum(axis=1), spatial.sum(axis=1)))


def information_pair(graph, links, analysis, *, n_jobs, budget_bytes):
    """Both exact conventions from the same Dijkstra blocks for every node.

    Disconnected pairs contribute zero; original N and coordinates are retained.
    There is no candidate fallback and no dense matrix per removed node retained.
    """
    active = ActiveEdgeGraph(graph, links, directed=False)
    n = len(active.node_ids)
    if active.node_ids != analysis.node_ids or n < 2:
        raise ValueError("information comparison requires matching node order and at least two nodes")
    reducer = DualEfficiencyReducer(analysis.coordinates)

    def efficiencies(csr):
        engine = removal_engine(csr, n_jobs, budget_bytes)
        engine.chunk_rows = min(engine.chunk_rows, max(1, math.ceil(n / n_jobs)))
        sums = np.zeros(2)
        for _, values in engine.reduce(np.arange(n), reducer, directed=False):
            sums += values.sum(axis=0)
        return sums / (n * (n - 1))

    started = perf_counter()
    baseline = efficiencies(active.csr())
    scores = np.full((n, 2), np.nan)
    with StageProgress("Exact information nodes (both efficiency conventions)", n) as progress:
        for index in range(n):
            changed = efficiencies(active.csr(isolated_nodes=[index]))
            scores[index] = np.divide(baseline - changed, baseline,
                                      out=np.full(2, np.nan), where=baseline > 0).clip(0, 1)
            progress.advance()
    return scores, baseline, perf_counter() - started


def ap2_betweenness_fit(values):
    """Compare exponential and AP2's Gaussian-shaped CCDF via body MLE/AIC.

    exp(-x²/(2σ²)) is the survival function of a Rayleigh distribution, whereas
    Ticket 07 fits a half-normal density. Keep this diagnostic separate.
    """
    raw = np.asarray(values, dtype=float)
    x = raw[np.isfinite(raw) & (raw > 0)]
    result = {"verdict": "inconclusive", "positive_count": len(x),
              "zeros_dropped": int(np.count_nonzero(raw == 0)),
              "nonfinite_dropped": int(np.count_nonzero(~np.isfinite(raw))),
              "negative_dropped": int(np.count_nonzero(np.isfinite(raw) & (raw < 0))),
              "delta_aic": None, "exponential_scale": None, "rayleigh_scale": None,
              "aic_exponential": None, "aic_rayleigh": None,
              "method": "positive-body MLE: exponential vs Rayleigh (AP2 Fig.3 Gaussian-shaped CCDF)",
              "threshold": 10, "reason": "too few or fewer than three distinct positive values"}
    if len(x) < 50 or len(np.unique(x)) < 3:
        return result
    unit = float(np.median(x))
    scaled = x / unit
    exp_scale = float(scaled.mean())
    ray_scale = float(np.sqrt(np.mean(scaled ** 2) / 2))
    exp_ll = float(expon.logpdf(scaled, scale=exp_scale).sum())
    ray_ll = float(rayleigh.logpdf(scaled, scale=ray_scale).sum())
    delta = 2 * (ray_ll - exp_ll)
    if not all(math.isfinite(value) for value in (exp_ll, ray_ll, delta)):
        result["reason"] = "nonfinite model comparison"
        return result
    offset = 2 * len(x) * math.log(unit)
    result.update(delta_aic=delta, exponential_scale=exp_scale * unit, rayleigh_scale=ray_scale * unit,
                  aic_exponential=2 - 2 * exp_ll + offset, aic_rayleigh=2 - 2 * ray_ll + offset,
                  verdict="gaussian" if delta > 10 else "exponential" if delta < -10 else "inconclusive",
                  reason="relative body evidence using project AIC threshold; not AP2's original fitting procedure")
    return result


def match_counts(rows):
    """Never turn a partial, duplicated or unknown-city study into a pass."""
    expected = {city.slug: city for city in CITIES}
    slugs = [row["city"] for row in rows]
    if len(slugs) != len(set(slugs)) or any(slug not in expected for slug in slugs):
        raise ValueError("comparison rows must contain unique known cities")
    info = sum(row["information"] == expected[row["city"]].information for row in rows)
    between = sum(row["betweenness"] == expected[row["city"]].betweenness for row in rows)
    complete = set(slugs) == set(expected)
    inconclusive = {name: sum(row[name] == "inconclusive" for row in rows)
                    for name in ("information", "betweenness")}
    return {"status": "INCOMPLETE" if not complete else "PASS" if info >= 3 and between >= 3 else "MISMATCH",
            "information_matches": info, "betweenness_matches": between,
            "expected_cities": 4, "completed_cities": len(rows), "inconclusive": inconclusive,
            "criterion": "at least 3/4 information matches AND at least 3/4 betweenness matches"}


def _write_layers(graph, links, node_metrics, degree, scores, path):
    nodes = [{"node_id": str(node), "degree": int(degree[i]),
              **{key: float(value[i]) for key, value in node_metrics.items()},
              "information_inverse": float(scores[i, 0]), "information_spatial": float(scores[i, 1]),
              "geometry": Point(graph.nodes[node]["x"], graph.nodes[node]["y"])}
             for i, node in enumerate(graph)]
    frame = gpd.GeoDataFrame(nodes, geometry="geometry", crs=graph.graph["crs"])
    frame.to_file(path, layer="nodes", driver="GPKG", engine="pyogrio")
    frame.drop(columns="geometry").to_csv(path.parent / "centralities.csv", index=False)
    edges = [{key: value for key, value in row.items() if not key.startswith("_")} for row in links]
    if not graph.is_directed():
        for row in edges:
            row["oneway"] = False
    gpd.GeoDataFrame(edges, geometry="geometry", crs=graph.graph["crs"]).to_file(
        path, layer="edges", driver="GPKG", engine="pyogrio", mode="a")


def analyse_city(city, source, manifest, folder, *, n_jobs, max_memory_gb, tolerance_m):
    started = perf_counter()
    config = RunConfig(input={"source": "graphml", "path": source}, network={"type": "all"},
                       analysis=AnalysisConfig(n_jobs=n_jobs, max_memory_gb=max_memory_gb),
                       cleaning={"consolidate": tolerance_m > 0, "tolerance_m": tolerance_m or 15})
    # Fixed 15 m default is retained even when it changes dead ends by >=5%;
    # preserve and expose the warning instead of silently retuning the experiment.
    graph, _, cleaning = load_and_clean(config, undirected=True, enforce_dead_end_guard=False)
    return analyse_graph(city, graph, manifest, folder, analysis_config=config.analysis,
                         cleaning=cleaning, started=started)


def analyse_graph(city, graph, manifest, folder, *, analysis_config, cleaning, started=None,
                  source_note=CAVEAT, cleaning_lines=None):
    """Compare conventions on an already prepared graph without changing its topology."""
    started = perf_counter() if started is None else started
    links = _link_rows(graph)
    analysis, metrics, edge_scores, statistics, computation = compute_centralities(graph, links, analysis_config)
    for row in links:
        row["edge_betweenness"] = edge_scores[row["link_id"]]
    n = len(analysis.node_ids)
    degree = np.diff(analysis.csr.indptr)
    scores, baseline, info_seconds = information_pair(
        graph, links, analysis, n_jobs=computation["n_jobs"], budget_bytes=computation["memory_budget_bytes"])
    values = {"degree": degree, **metrics, "information": scores[:, 0]}
    production = classify_network(values, {"coverage": "all", "efficiency_convention": "inverse_distance"}, {})
    reference = copy.deepcopy(production.summary)
    reference["distributions"]["information"] = fit_distribution(scores[:, 1])
    reference["distributions"]["betweenness"] = ap2_betweenness_fit(metrics["betweenness"])
    reference.update(network_decision(reference["distributions"], "all"),
                     efficiency_convention="spatial_d_E_over_d", rule="ticket15-ap2-reference-v1",
                     limitations="AP2 efficiency and cumulative betweenness family; modern project fitting rules, "
                                 "not a reconstruction of AP2's fitting procedure. No bootstrap goodness-of-fit test.")
    # The independent degree diagnostic must describe the reference label too.
    reference["degree_agreement"] = agreement(reference["network_label"], reference["degree_evidence"]["verdict"])
    comparisons = dict(zip(CONVENTIONS, (production.summary, reference)))
    result = {"city": city.slug, "name": city.name, "expected": asdict(city),
              "node_count": n, "link_count": len(links), "cleaning": cleaning,
              "input_manifest": manifest, "information_coverage": "all", "information_nodes": n,
              "baseline_efficiency": {"inverse_distance_per_m": float(baseline[0]),
                                      "spatial_dimensionless": float(baseline[1])},
              "comparisons": comparisons, "centrality_statistics": statistics, "computation": computation,
              "information_seconds": info_seconds, "total_seconds": perf_counter() - started}
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "network.gpkg"
    path.unlink(missing_ok=True)
    _write_layers(graph, links, metrics, degree, scores, path)
    lines = [f"{city.name} — Ticket 15", source_note, f"Nodes: {n}; physical links: {len(links)}",
             f"Information coverage: all ({n}/{n}); isolated node retained for every removal.",
             f"Inverse-distance efficiency (1/m): {baseline[0]:.9g}",
             f"AP2 spatial efficiency (dimensionless): {baseline[1]:.9g}", "",
             *(cleaning_report(cleaning) if cleaning_lines is None else cleaning_lines)]
    for convention, summary in comparisons.items():
        lines.extend(["", convention, f"Network label: {summary['network_label']}",
                      f"Betweenness consistency: {summary['consistency']}"])
        for name, fitted in summary["distributions"].items():
            lines.append(f"  {name}: {fitted['verdict']} — {fitted['reason']}")
            if name == "information":
                lines.append(f"    alpha (density)={fitted['alpha']}; xmin={fitted['xmin']}; tail={fitted['n_tail']}")
    lines.append(f"\nInformation calculation: {info_seconds:.3f} seconds")
    (folder / "report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    result["total_seconds"] = perf_counter() - started
    _json(folder / "summary.json", result)
    return result, {"information": scores, "betweenness": metrics["betweenness"]}


def comparison_summary(results):
    comparisons = {}
    for convention in CONVENTIONS:
        rows = []
        for result in results:
            fits = result["comparisons"][convention]
            info = fits["distributions"]["information"]
            alpha = info["alpha"] if info["verdict"] == "power_law" else None
            rows.append({"city": result["city"], "name": result["name"], "node_count": result["node_count"],
                         "link_count": result["link_count"], "information": info["verdict"],
                         "betweenness": fits["distributions"]["betweenness"]["verdict"],
                         "alpha_density": alpha, "gamma_ccdf": alpha - 1 if alpha is not None else None,
                         "network_label": fits["network_label"], "expected": result["expected"],
                         "information_reason": info["reason"],
                         "betweenness_reason": fits["distributions"]["betweenness"]["reason"]})
        comparisons[convention] = {**match_counts(rows), "rows": rows}
    return {"status": comparisons[CONVENTIONS[0]]["status"], "comparisons": comparisons,
            "caveat": CAVEAT, "versions": _versions(),
            "fitting_note": "Framework: Ticket 07 unchanged. AP2 reference: spatial efficiency and "
                            "exponential vs Rayleigh body AIC for betweenness; same modern power-law "
                            "tail rules for information. Inconclusive is an abstention, not an error.",
            "exponent_note": "AP2 gamma describes the CCDF; continuous ideal gamma = density alpha - 1. "
                             "Historical values are context, not numerical pass targets.",
            "criterion_note": "3/4 in each centrality is a project benchmark, not a criterion supplied by AP2."}


def comparison_report(summary):
    lines = [f"{summary['status']} — Ticket 15 framework comparison", summary["caveat"],
             summary["fitting_note"], summary["exponent_note"], summary["criterion_note"],
             "No thresholds, centres or consolidation settings are retuned to obtain agreement."]
    for convention, comparison in summary["comparisons"].items():
        lines.extend(["", f"{convention}: {comparison['status']}",
                      f"Information matches: {comparison['information_matches']}/4; "
                      f"betweenness matches: {comparison['betweenness_matches']}/4",
                      f"Inconclusive: {comparison['inconclusive']}",
                      "City | N | links | expected info / obtained | expected betweenness / obtained | label | alpha / gamma"])
        for row in comparison["rows"]:
            expected = row["expected"]
            exponent = (f"{row['alpha_density']:.4g} / {row['gamma_ccdf']:.4g}"
                        if row["alpha_density"] is not None else "n/a")
            lines.append(f"{row['name']} | {row['node_count']} | {row['link_count']} | "
                         f"{expected['information']} / {row['information']} | "
                         f"{expected['betweenness']} / {row['betweenness']} | {row['network_label']} | {exponent}")
            if row["information"] == "inconclusive" or row["betweenness"] == "inconclusive":
                lines.append(f"  Information: {row['information_reason']}; betweenness: {row['betweenness_reason']}")
    lines.extend(["", "Read each city's report.txt for cleaning warnings and fit reasons. "
                  "Read its summary.json for complete evidence and input provenance.",
                  "PASS means qualitative agreement under this benchmark only; MISMATCH is a research finding."])
    return "\n".join(lines) + "\n"


def write_comparison_csv(summary, path):
    fields = ("convention", "city", "node_count", "link_count", "expected_information", "information",
              "information_match", "expected_betweenness", "betweenness", "betweenness_match",
              "network_label", "alpha_density", "gamma_ccdf")
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for convention, comparison in summary["comparisons"].items():
            for row in comparison["rows"]:
                writer.writerow({"convention": convention,
                    **{name: row[name] for name in ("city", "node_count", "link_count", "information",
                                                    "betweenness", "network_label", "alpha_density", "gamma_ccdf")},
                    **{f"expected_{name}": row["expected"][name] for name in ("information", "betweenness")},
                    **{f"{name}_match": row[name] == row["expected"][name] for name in ("information", "betweenness")}})


def write_comparison_figures(values, folder, summary, *, information_title=None):
    import matplotlib.pyplot as plt
    folder.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for column, convention in enumerate(CONVENTIONS):
        for city in CITIES:
            x = np.sort(values[city.slug]["information"][:, column])
            x = x[np.isfinite(x) & (x > 0)]
            if len(x):
                axes[column].step(x, (len(x) - np.arange(len(x))) / len(x), where="pre", label=city.name)
        axes[column].set(xscale="log", yscale="log", xlabel="Information centrality",
                         ylabel="Fraction of positive scores ≥ x", title=convention)
        axes[column].grid(alpha=.2)
        axes[column].legend(fontsize="small")
    fig.suptitle(information_title or "Modern city samples: information CCDF (AP2 Fig. 3 comparison)")
    fig.tight_layout()
    fig.savefig(folder / "information_ccdf.png", dpi=150)
    plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    reference_rows = {row["city"]: row for row in summary["comparisons"][CONVENTIONS[1]]["rows"]}
    for city in CITIES:
        x = np.sort(values[city.slug]["betweenness"])
        x = x[np.isfinite(x) & (x > 0)]
        if not len(x):
            continue
        survival = (len(x) - np.arange(len(x))) / len(x)
        fitted = ap2_betweenness_fit(x)
        for axis, squared in zip(axes, (False, True)):
            plotted = x ** 2 if squared else x
            line, = axis.step(plotted, survival, where="pre", label=city.name)
            scale = fitted["rayleigh_scale"] if reference_rows[city.slug]["betweenness"] == "gaussian" else fitted["exponential_scale"]
            if scale is not None and reference_rows[city.slug]["betweenness"] != "inconclusive":
                sf = rayleigh.sf(x, scale=scale) if reference_rows[city.slug]["betweenness"] == "gaussian" else expon.sf(x, scale=scale)
                axis.plot(plotted, np.maximum(sf, 1e-12), "--", color=line.get_color(), alpha=.6)
    for axis, label in zip(axes, ("Betweenness", "Betweenness²")):
        axis.set(yscale="log", xlabel=label, ylabel="Fraction of positive scores ≥ x", ylim=(1e-4, 1.05))
        axis.grid(alpha=.2)
        axis.legend(fontsize="small")
    fig.suptitle("Betweenness CCDF: exponential / AP2 Gaussian-shaped reference overlays")
    fig.tight_layout()
    fig.savefig(folder / "betweenness_ccdf.png", dpi=150)
    plt.close(fig)


def validate_crucitti(out_dir, *, inputs_dir=None, offline=False, download_only=False,
                      overwrite=False, n_jobs=1, max_memory_gb=1.0, tolerance_m=15.0, figures=True):
    out_dir = Path(out_dir)
    inputs_dir = Path(inputs_dir) if inputs_dir is not None else out_dir / "inputs"
    # Validate numeric options even for download-only invocations.
    AnalysisConfig(n_jobs=n_jobs, max_memory_gb=max_memory_gb)
    if not math.isfinite(tolerance_m) or tolerance_m < 0:
        raise ValueError("consolidation tolerance must be finite and nonnegative (0 disables consolidation)")
    existing = [out_dir / name for name in ("crucitti_report.txt", "comparison.json", "comparison.csv", "run_config.json")]
    existing += [out_dir / city.slug for city in CITIES]
    if not download_only and not overwrite and any(path.exists() for path in existing):
        raise ValueError("validation outputs already exist; use --overwrite (frozen inputs will be reused)")
    out_dir.mkdir(parents=True, exist_ok=True)
    snapshots = []
    for city in CITIES:
        source, manifest = frozen_input(city, inputs_dir, offline=offline)
        snapshots.append((source, manifest))
    if download_only:
        _log(f"All four frozen inputs ready in {inputs_dir}; no analyses run")
        return {"status": "INPUTS_READY", "inputs_dir": str(inputs_dir)}
    # Remove stale aggregate outputs before any analysis, so an interrupted rerun
    # cannot leave an old PASS beside newly written city results.
    for path in (out_dir / "crucitti_report.txt", out_dir / "comparison.json", out_dir / "comparison.csv"):
        path.unlink(missing_ok=True)
    for name in ("information_ccdf.png", "betweenness_ccdf.png"):
        (out_dir / "figures" / name).unlink(missing_ok=True)
    _json(out_dir / "run_config.json", {"inputs_dir": str(inputs_dir.resolve()), "n_jobs": n_jobs,
          "max_memory_gb": max_memory_gb, "consolidation_tolerance_m": tolerance_m,
          "dead_end_guard": "warning only; fixed experiment settings", "information_coverage": "all",
          "component": "largest undirected connected", "versions": _versions(),
          "started_utc": datetime.now(timezone.utc).isoformat(),
          "snapshots": {city.slug: manifest["raw_graph_sha256"] for city, (_, manifest) in zip(CITIES, snapshots)}})
    results, values = [], {}
    for city, (source, manifest) in zip(CITIES, snapshots):
        _log(f"Validating {city.name}")
        result, city_values = analyse_city(city, source, manifest, out_dir / city.slug,
            n_jobs=n_jobs, max_memory_gb=max_memory_gb, tolerance_m=tolerance_m)
        results.append(result)
        values[city.slug] = city_values
    summary = comparison_summary(results)
    if figures:
        write_comparison_figures(values, out_dir / "figures", summary)
    _json(out_dir / "comparison.json", summary)
    write_comparison_csv(summary, out_dir / "comparison.csv")
    (out_dir / "crucitti_report.txt").write_text(comparison_report(summary), encoding="utf-8")
    _log(f"{summary['status']}: {out_dir / 'crucitti_report.txt'}")
    return summary
