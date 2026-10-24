"""Validated local inputs, paired metrics and staged output publication."""

import json
import platform
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from tempfile import TemporaryDirectory

import geopandas as gpd
from shapely.geometry import Point

from . import __version__
from .config import RunConfig
from .failure_probabilities import compute_failure_probabilities
from .figures import FIGURE_FILENAMES, write_figures
from .links import _link_rows
from .metrics import compute_local_metrics, score, POPULATION_REASON
from .network import load_and_clean
from .od import load_od_pairs
from .population import prepare_population, sha256_file, study_boundary
from .reliability import compute_reliability, write_od_reliability
from .reporting import build_report
from .robustness import compute_targeted_attack, write_curve
from .shortest_paths import resolve_resources, GIB

CORE_FILES = ("network.gpkg", "summary.json", "attack_curve.csv", "report.txt", "run_manifest.json", "od_reliability.csv")
# Recognised outputs of prior releases, used only for safe overwrite migration.
LEGACY_FILES = ("run_config.yaml", "robustness_curves.csv", "zones.gpkg")
LEGACY_FIGURES = ("degree_hist.png", "closeness_ccdf.png", "straightness_ccdf.png", "betweenness_ccdf.png",
    "edge_betweenness_map.png", "redundancy_map.png", "critical_links_map.png", "robustness_scc.png",
    "robustness_efficiency.png", "connectivity_nodes_map.png", "hansen_a_map.png", "vuln_map.png",
    "access_drop_map.png", "scorecard.png", "population_map.png", "zones_vulnerability_map.png",
    *(f"classification_{name}_{scale}.png" for name in ("degree", "closeness", "straightness", "betweenness", "information")
      for scale in ("loglog", "logy")))


def _versions():
    result = {"python": platform.python_version(), "georesilience": __version__}
    for package in ("osmnx", "networkx", "scipy", "numpy", "geopandas", "pyogrio", "rasterio", "shapely", "pyproj", "pydantic", "joblib", "matplotlib"):
        try:
            result[package] = version(package)
        except PackageNotFoundError:
            result[package] = "not installed"
    return result


def _consumed(config):
    files = [("roads", config.input.path), ("population", config.population.worldpop),
        ("boundary", config.input.boundary), ("failure_probabilities", config.reliability.p_fail_csv),
        ("od_pairs", config.reliability.od_pairs_csv)]
    if config.population.worldpop is None:
        raise ValueError("one local WorldPop count GeoTIFF is required")
    # GDAL may consult local georeferencing sidecars; include them in replay checks.
    raster = Path(config.population.worldpop).expanduser()
    for sidecar in (Path(str(raster) + ".aux.xml"), raster.with_suffix(".tfw")):
        if sidecar.is_file():
            files.append(("raster_sidecar", sidecar))
    return [{"role": role, "path": str(Path(path).expanduser().resolve()),
             "sha256": sha256_file(Path(path).expanduser()), "size_bytes": Path(path).expanduser().stat().st_size}
            for role, path in files if path is not None]


def _known_paths(output):
    return [*(output / name for name in (*CORE_FILES, *LEGACY_FILES)),
            *(output / "figures" / name for name in (*FIGURE_FILENAMES, *LEGACY_FIGURES))]


def _validate_output(output, input_dir, overwrite):
    if output == input_dir or input_dir in output.parents:
        raise ValueError("output must be outside the input directory")
    if output.exists() and not output.is_dir():
        raise ValueError("output must be a directory")
    if output.exists() and any(output.iterdir()) and not overwrite:
        raise ValueError(f"output exists and is not empty: {output} (use --overwrite)")
    if (output / "figures").is_symlink():
        raise ValueError("output figures directory cannot be a symlink")
    for path in _known_paths(output):
        if path.exists() and path.is_dir():
            raise ValueError(f"generated output path is occupied by a directory: {path}")


def _write_json(path, values):
    path.write_text(json.dumps(values, indent=2, allow_nan=False, sort_keys=True) + "\n", encoding="utf-8")


def run(config: RunConfig, out_override=None, overwrite=False, *, time_model=None):
    output = Path(out_override or config.output.dir).expanduser().resolve()
    input_dir = (config.input.directory or config.input.path.parent).expanduser().resolve()
    _validate_output(output, input_dir, overwrite)
    jobs, budget = resolve_resources(config.analysis.n_jobs, config.analysis.max_memory_gb)
    consumed = _consumed(config)
    inputs = {Path(item["path"]) for item in consumed}
    if any(path.resolve() in inputs for path in _known_paths(output)):
        raise ValueError("generated output cannot replace a consumed input file")
    graph, input_meta, cleaning = load_and_clean(config)
    boundary, boundary_meta = study_boundary(graph, config.input.boundary, config.population.snap_max_m)
    population = prepare_population(graph, boundary, config.population)
    links = _link_rows(graph)
    failures = compute_failure_probabilities(graph, links, config.reliability)
    od = load_od_pairs(graph, config.reliability.od_pairs_csv)
    settings = {"half_distance_km": config.accessibility.half_distance_km,
                "cutoff_factor": config.accessibility.cutoff_factor, "n_jobs": jobs, "budget_bytes": budget}
    local = compute_local_metrics(graph, population.weights, coverage=config.criticality.coverage,
        link_candidate_limit=config.criticality.link_candidates, node_candidate_limit=config.criticality.node_candidates, **settings)
    for row in local.links:
        row.update(failures.link_metrics[row["link_id"]])
    attack = compute_targeted_attack(graph, local.links, population.weights,
        fraction=config.robustness.fraction, steps=config.robustness.steps, order=config.robustness.order, seed=config.analysis.seed)
    reliability = compute_reliability(graph, local.links, population.weights, failures.user_probabilities,
        p0=config.reliability.p0, p0_sweep=config.reliability.p0_sweep,
        connectivity_samples=config.reliability.samples, travel_time_samples=config.travel_time.samples,
        time_threshold=config.travel_time.tau, seed=config.analysis.seed, n_jobs=jobs, budget_bytes=budget,
        time_config=config.travel_time, time_model=time_model, od_inputs=od)
    baseline = local.baseline
    definitions = {
        "routing": "Betweenness: length-weighted undirected minimum-link graph; routing/removals: directed retained network.",
        "information": "Information centrality is relative directed network efficiency loss on isolating a node; original ordered-pair denominator retained.",
        "hansen": f"Hansen: mean exp(-ln(2)*distance/half_distance) over other nodes; half-distance {config.accessibility.half_distance_km:g} km, inclusive cutoff {config.accessibility.cutoff_factor:g} times half-distance. Unreachable pairs contribute zero.",
        "population": "Population pairs use P_i*P_j, a resident-to-resident demand proxy, not observed trips. Population Hansen normalizes destination masses per origin and averages origins using P_i.",
        "removal": "Removal accessibility loss compares network Hansen indices with original origin/destination populations and denominators. Isolated-node pairs count as lost.",
        "detour": "Detour is the worst alternative distance ratio over a physical link's original directions; no alternative has a null ratio and detour_none=true.",
        "betweenness": "Parallel roads use the shortest undirected physical link; equal-length ties use deterministic physical-link order.",
        "nulls": "Undefined and unevaluated local values are null; each row's null_reasons explains them. evaluated refers to single-removal consequences."}
    summary = {"schema_version": 1, "unweighted": {**local.redundancy,
        "targeted_attack_robustness": attack.summary["unweighted"],
        "hansen_accessibility": score(baseline.accessibility, "equal-origin mean of normalized structural node Hansen", "no distinct nodes"),
        **reliability.summary["unweighted"]},
        "population_weighted": {"targeted_attack_robustness": attack.summary["population_weighted"],
        "hansen_accessibility": score(baseline.accessibility_pop, "population-origin mean of destination-normalized node Hansen", POPULATION_REASON),
        **reliability.summary["population_weighted"]},
        "network": {**cleaning["final"], "network_type_applied": input_meta["network_type_applied"]},
        "population": population.summary, "boundary": boundary_meta, "coverage": local.coverage,
        "probabilities": failures.summary, "time_model": reliability.summary["time_model"],
        "attack": attack.summary, "definitions": definitions, "od_warnings": od.warnings}
    if config.reliability.p0_sweep:
        summary["reliability_scenarios"] = {key: value for key, value in reliability.summary["scenarios"].items() if key != "primary"}
    resolved = config.model_dump(mode="json")
    resolved["output"]["dir"] = str(output)
    resolved["input"]["path"] = str(config.input.path.expanduser().resolve())
    resolved["input"]["directory"] = str(input_dir)
    resolved["population"]["worldpop"] = str(Path(config.population.worldpop).expanduser().resolve())
    for section, field in (("input", "boundary"), ("reliability", "p_fail_csv"), ("reliability", "od_pairs_csv")):
        if resolved[section][field] is not None:
            resolved[section][field] = str(Path(resolved[section][field]).expanduser().resolve())
    resolved["analysis"].update(n_jobs=jobs, max_memory_gb=budget / GIB)
    if time_model is not None:
        resolved["travel_time"]["time_model"] = "custom"
    manifest = {"schema_version": 1, "created_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": consumed, "resolved_config": resolved, "versions": _versions(), "seed": config.analysis.seed,
        "input_cleaning_fingerprint": graph.graph["input_cleaning_fingerprint"], "cleaning": cleaning,
        "boundary": boundary_meta, "coverage": local.coverage, "population": population.provenance,
        "probabilities": failures.summary, "time_model": reliability.summary["time_model"],
        "sampling": reliability.computation, "attack_removal_order": attack.removal_order,
        "pair_universe": {"nodes": baseline.universe.n, "ordered_node_pairs": baseline.universe.denominator,
            "normalized_population_pair_mass": baseline.universe.denominator_pop,
            "definition": "distinct ordered original pairs; population masses normalized by original population total before products"},
        "units": {"distance": "metres", "time": "seconds", "population": "people", "probability": "one event/scenario"},
        "memory_scope": "shortest-path/simulation workspace; graph, geometry and output storage are additional",
        "custom_time_provider": (type(time_model).__module__ + "." + type(time_model).__qualname__) if time_model is not None else None}
    node_records = []
    for index, (node, data) in enumerate(graph.nodes(data=True)):
        metrics = dict(local.nodes[node])
        metrics["null_reasons"] = json.dumps(metrics["null_reasons"], sort_keys=True)
        node_records.append({"node_id": str(node), "population": float(population.weights[index]), **metrics,
                            "geometry": Point(data["x"], data["y"])})
    nodes = gpd.GeoDataFrame(node_records, crs=graph.graph["crs"])
    edge_records = []
    for row in local.links:
        record = {key: value for key, value in row.items() if not key.startswith("_")}
        record["null_reasons"] = json.dumps(record["null_reasons"], sort_keys=True)
        edge_records.append(record)
    edges = gpd.GeoDataFrame(edge_records, crs=graph.graph["crs"])
    # Validate serializability before touching an existing output.
    json.dumps(summary, allow_nan=False)
    json.dumps(manifest, allow_nan=False)
    for item in consumed:
        if sha256_file(item["path"]) != item["sha256"]:
            raise ValueError(f"input changed during analysis: {item['path']}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".georesilience-", dir=output.parent) as directory:
        stage = Path(directory)
        nodes.to_file(stage / "network.gpkg", layer="nodes", driver="GPKG", engine="pyogrio")
        edges.to_file(stage / "network.gpkg", layer="edges", driver="GPKG", engine="pyogrio")
        _write_json(stage / "summary.json", summary)
        _write_json(stage / "run_manifest.json", manifest)
        (stage / "report.txt").write_text(build_report(summary), encoding="utf-8")
        write_curve(attack, stage / "attack_curve.csv")
        if config.reliability.od_pairs_csv is not None:
            write_od_reliability(reliability, stage / "od_reliability.csv")
        if config.output.figures:
            write_figures(nodes, edges, attack, summary, stage / "figures")
        output.mkdir(parents=True, exist_ok=True)
        for path in _known_paths(output):
            path.unlink(missing_ok=True)
        for path in sorted(stage.rglob("*")):
            if path.is_file():
                destination = output / path.relative_to(stage)
                destination.parent.mkdir(parents=True, exist_ok=True)
                path.replace(destination)
        try:
            (output / "figures").rmdir()
        except OSError:
            pass
    return summary


def replay_manifest(path, out, overwrite=False, *, time_model=None):
    manifest = json.loads(Path(path).read_text())
    for item in manifest["inputs"]:
        if sha256_file(item["path"]) != item["sha256"]:
            raise ValueError(f"input checksum mismatch: {item['path']}")
    if manifest.get("custom_time_provider") and time_model is None:
        raise ValueError("manifest requires its custom Python time provider")
    return run(RunConfig.model_validate(manifest["resolved_config"]), out_override=out,
               overwrite=overwrite, time_model=time_model)
