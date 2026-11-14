"""Validated local inputs, paired metrics and staged output publication."""

import json
import platform
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from tempfile import TemporaryDirectory

import geopandas as gpd
from shapely.geometry import LineString, Point

from . import __version__
from .config import RunConfig
from .failure_probabilities import compute_failure_probabilities
from .figures import FIGURE_FILENAMES, SERVICE_FIGURE_FILENAMES, write_figures
from .links import _link_rows
from .metrics import compute_local_metrics, score, POPULATION_REASON
from .network import load_and_clean
from .od import load_od_pairs
from .population import prepare_population, sha256_file, study_boundary
from .reliability import compute_reliability, write_od_reliability
from .reporting import build_report
from .robustness import compute_targeted_attack, write_curve
from .shortest_paths import resolve_resources, GIB
from .time_models import FreeFlowTimeModel, PreparedTimeModel
from .traffic import (canonical_traffic_graph, evaluate_closures, prepare_traffic, write_traffic_closures_csv,
                      write_traffic_csv, write_traffic_od_csv)
from .services import prepare_services, service_node_weights, service_node_fields, combined_node_importance
from .service_inputs import load_facility_records
from .service_metrics import ServiceUniverse, evaluate_service_matrix
from .service_criticality import compute_service_criticality
from .sfca import compute_sfca, METHOD_VERSION
from .time_models import prepare_time_model
from .composite import calculate_composites, write_composites
from .traffic_failures import ReassignedTrafficTimeModel
from .time_routing import prepare_static_time

CORE_FILES = ("network.gpkg", "summary.json", "attack_curve.csv", "report.txt", "run_manifest.json",
    "od_reliability.csv", "traffic_arcs.csv", "traffic_od.csv", "traffic_closures.csv", "composite.csv", "traffic_failure_states.csv")
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
    for package in ("osmnx", "networkx", "networkit", "scipy", "numpy", "geopandas", "pyogrio", "rasterio", "shapely", "pyproj", "pydantic", "joblib", "matplotlib"):
        try:
            result[package] = version(package)
        except PackageNotFoundError:
            result[package] = "not installed"
    return result


def _consumed(config):
    files = [("roads", config.input.path), ("population", config.population.worldpop), ("saved_population", config.population.node_counts),
        ("boundary", config.input.boundary), ("failure_probabilities", config.reliability.p_fail_csv),
        ("od_pairs", config.reliability.od_pairs_csv),
        ("traffic_od", config.traffic.od_csv if config.traffic.enabled else None),
        ("traffic_zone_masses", config.traffic.zone_mass_csv if config.traffic.enabled else None),
        ("traffic_edge_times", config.traffic.edge_times_csv if config.traffic.enabled else None),
        ("traffic_capacities", config.traffic.capacity_csv if config.traffic.enabled else None)]
    if config.services is not None:
        files.append(("facilities", config.services.facilities_csv))
    if config.population.worldpop is None and config.population.node_counts is None and config.services is None:
        raise ValueError("one local WorldPop count GeoTIFF is required")
    # GDAL may consult local georeferencing sidecars; include them in replay checks.
    raster = Path(config.population.worldpop).expanduser() if config.population.worldpop is not None else None
    for sidecar in ((Path(str(raster) + ".aux.xml"), raster.with_suffix(".tfw")) if raster is not None else ()):
        if sidecar.is_file():
            files.append(("raster_sidecar", sidecar))
    return [{"role": role, "path": str(Path(path).expanduser().resolve()),
             "sha256": sha256_file(Path(path).expanduser()), "size_bytes": Path(path).expanduser().stat().st_size}
            for role, path in files if path is not None]


def _known_paths(output):
    return [*(output / name for name in (*CORE_FILES, *LEGACY_FILES)),
            *(output / "figures" / name for name in (*FIGURE_FILENAMES, *SERVICE_FIGURE_FILENAMES, *LEGACY_FIGURES))]


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


class _TrafficTimeModel:
    def __init__(self, traffic):
        self.traffic = traffic

    def prepare(self, graph, config):
        return PreparedTimeModel(self.traffic.edge_seconds, {
            "status": "computed" if self.traffic.summary["status"] in {"computed", "converged"} else "non_converged",
            "time_model": "traffic_" + self.traffic.summary["source"], "time_units": "seconds",
            "time_function": "directed traffic scenario travel time",
            "assumptions": f"{self.traffic.summary['provenance']} traffic; fixed edge times during event simulations",
            "maxspeed_coverage": None})


def run(config: RunConfig, out_override=None, overwrite=False, *, time_model=None):
    output = Path(out_override or config.output.dir).expanduser().resolve()
    input_dir = (config.input.directory or config.input.path.parent).expanduser().resolve()
    _validate_output(output, input_dir, overwrite)
    jobs, budget = resolve_resources(config.analysis.n_jobs, config.analysis.max_memory_gb)
    try:
        import networkit as nk
        nk.setNumberOfThreads(jobs)
    except ImportError:
        pass
    consumed = _consumed(config)
    inputs = {Path(item["path"]) for item in consumed}
    if any(path.resolve() in inputs for path in _known_paths(output)):
        raise ValueError("generated output cannot replace a consumed input file")
    if config.services is not None:
        load_facility_records(config.services)
    graph, input_meta, cleaning = load_and_clean(config)
    boundary, boundary_meta = study_boundary(graph, config.input.boundary, config.population.snap_max_m)
    population = prepare_population(graph, boundary, config.population, uniform_if_missing=config.services is not None)
    links = _link_rows(graph)
    failures = compute_failure_probabilities(graph, links, config.reliability)
    od = load_od_pairs(graph, config.reliability.od_pairs_csv)
    traffic = None
    reliability_time_model = time_model
    if config.traffic.enabled:
        if time_model is not None or config.travel_time.time_model != "free_flow":
            raise ValueError("traffic supplies travel-time costs; remove the custom or edge-attribute travel-time model")
        assignment_graph, tag_changes = canonical_traffic_graph(graph, config.travel_time.highway_speeds_kph)
        free_flow = None
        if config.traffic.source == "assignment":
            free_flow = FreeFlowTimeModel().prepare(assignment_graph, config.travel_time)
            if free_flow.summary["status"] != "computed":
                raise ValueError("traffic assignment requires resolvable edge speeds; use --speed or supply maxspeed tags")
        traffic = prepare_traffic(assignment_graph, config.traffic,
            free_flow.edge_seconds if free_flow is not None else None, population.weights)
        traffic.summary["resolved_mixed_tag_fields"] = tag_changes
        if config.traffic.source == "assignment" and config.traffic.closure_top_n:
            evaluate_closures(graph, links, traffic, free_flow.edge_seconds, config.traffic)
            traffic.summary["closures"] = traffic.closure_rows
        reliability_time_model = _TrafficTimeModel(traffic)
    facilities = prepare_services(graph, config.services) if config.services is not None else None
    weights = service_node_weights(facilities, config.services) if facilities is not None else None
    importance = combined_node_importance(population.weights, weights, config.services.population_importance) if facilities is not None else None
    service_nodes = [node for node, weight in zip(graph, weights) if weight > 0] if weights is not None else []
    prepared_time = prepare_time_model(graph, config.travel_time, reliability_time_model) if facilities is not None else None
    routing = (prepare_static_time(graph, links, config.travel_time, prepared=prepared_time)
        if facilities is not None and config.services.mode == 'sfca' else None)
    demand_basis = 'population' if config.population.worldpop is not None or config.population.node_counts is not None else 'uniform_node_demand'
    cost_mode = config.accessibility.cost
    if cost_mode == 'auto':
        cost_mode = 'time' if traffic is not None else 'distance'
    local_costs = None
    if cost_mode == 'time':
        cost_prepared = prepare_time_model(graph, config.travel_time, reliability_time_model)
        if cost_prepared.summary['status'] != 'computed':
            raise ValueError('time-based graph metrics require complete positive edge times')
        local_costs = cost_prepared.edge_seconds
    half_cost = config.accessibility.half_time_minutes * 60 if local_costs is not None else config.accessibility.half_distance_km * 1000
    settings = {"half_distance_km": half_cost / 1000,
                "cutoff_factor": config.accessibility.cutoff_factor, "n_jobs": jobs, "budget_bytes": budget}
    local = compute_local_metrics(graph, population.weights, coverage=config.criticality.coverage,
        link_candidate_limit=config.criticality.link_candidates, node_candidate_limit=config.criticality.node_candidates, service_nodes=service_nodes, edge_costs=local_costs, **settings)
    for row in local.links:
        row.update(failures.link_metrics[row["link_id"]])
    service_baseline = sfca = criticality = None
    if facilities is not None:
        service_baseline = evaluate_service_matrix(local.baseline.topology.csr(),
            ServiceUniverse(population.weights, weights), **settings)
        sfca = compute_sfca(facilities, population.weights, config.services, routing,
            n_jobs=jobs, budget_bytes=budget, demand_basis=demand_basis)
        criticality = compute_service_criticality(local, facilities, population.weights, config.services,
            routing, baseline=sfca, n_jobs=jobs, budget_bytes=budget)
        fields = service_node_fields(facilities, weights)
        for i, node in enumerate(graph):
            local.nodes[node].update(fields[node], node_importance=float(importance[0][i]),
                importance_population_component=float(importance[1][i]), importance_service_component=float(importance[2][i]))
            for category, result in sfca.categories.items():
                value = float(result.node_access[i]) if result.node_access is not None else None
                local.nodes[node][f'{category}_sfca'] = value
                local.nodes[node][f'{category}_sfca_per_1000'] = value * 1000 if value is not None else None
                if value is None:
                    local.nodes[node]['service_null_reasons'].update({f'{category}_sfca': result.reason,
                        f'{category}_sfca_per_1000': result.reason})
    attack = compute_targeted_attack(graph, local.links, population.weights,
        fraction=config.robustness.fraction, steps=config.robustness.steps, order=config.robustness.order, seed=config.analysis.seed,
        service_weights=weights, node_importance=importance[0] if importance is not None else None, edge_costs=local_costs)
    reassignment = None
    if traffic is not None and config.traffic.source == 'assignment' and config.traffic.reassign_failures:
        def facility_state(times, closed):
            if facilities is None or config.services.mode != 'sfca':
                return {}
            snapshot_routing = prepare_static_time(graph, links, config.travel_time,
                prepared=PreparedTimeModel(times, {'status': 'computed', 'time_units': 'seconds'}))
            result = compute_sfca(facilities, population.weights, config.services, snapshot_routing,
                removed_links=closed, n_jobs=1, budget_bytes=budget, demand_basis=demand_basis)
            return {f'{category}_{key}': value.summary[key] for category, value in result.categories.items()
                    for key in ('population_mean_per_1000', 'zero_access_population_share')}
        reassignment = ReassignedTrafficTimeModel(graph, links, traffic, free_flow.edge_seconds,
            config.traffic, on_state=facility_state)
        reliability_time_model = reassignment
        # Baseline 2SFCA uses a static snapshot; reliability explicitly prepares dynamic event costs.
    reliability = compute_reliability(graph, local.links, population.weights, failures.user_probabilities,
        p0=config.reliability.p0, p0_sweep=config.reliability.p0_sweep,
        connectivity_samples=config.reliability.samples, travel_time_samples=config.travel_time.samples,
        time_threshold=config.travel_time.tau, seed=config.analysis.seed, n_jobs=jobs, budget_bytes=budget,
        time_config=config.travel_time, time_model=reliability_time_model, od_inputs=od,
        service_weights=weights, prepared_time=None if reassignment is not None else prepared_time)
    if reassignment is not None:
        traffic.summary['failure_reassignment'] = reassignment.summary()
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
        "attack": attack.summary, "definitions": definitions, "od_warnings": od.warnings,
        **({"traffic": traffic.summary} if traffic is not None else {})}
    if facilities is not None:
        summary['schema_version'] = 2
        summary['services'] = {'schema_version': 1, 'input': facilities.summary,
            'weights': {'school': config.services.school.importance, 'hospital': config.services.hospital.importance,
                'total_service_weight': float(weights.sum()), 'definition': 'sum of category importance times attached facility count; capacity independent'},
            'node_importance': {'definition': 'population_importance * P_i/sum(P) + service_weight_i/sum(service_weight)',
                'population_importance': config.services.population_importance, 'total': float(importance[0].sum()),
                'population_component_basis': demand_basis, 'zero_component_rule': 'a zero total contributes zero; supplied zero population is not replaced'},
            'demand': {'basis': demand_basis, 'total': float(population.weights.sum()),
                'description': ('allocated total population; schools use an all-resident proxy' if demand_basis == 'population'
                    else 'population absent: one uniform demand unit per retained node; not estimated resident counts')},
            'service_weighted': {**service_baseline.summary, **reliability.summary['service_weighted'],
                'targeted_attack_robustness': attack.summary['service_weighted']},
            'node_importance_weighted': {'targeted_attack_robustness': attack.summary['node_importance_weighted']},
            'sfca': sfca.summary, 'criticality': criticality.summary,
            'limitations': 'study boundary does not correct missing neighbouring demand/supply; reliability views do not recompute 2SFCA'}
        if local_costs is not None:
            summary['services']['service_weighted']['hansen_accessibility']['definition'] = (
                'original population-to-service normalized seconds-decay Hansen, including co-location')
        if reassignment is not None and config.services.mode == 'sfca':
            summary['services']['failure_sfca'] = reassignment.summary()
            summary['services']['limitations'] = (
                'per-event static 2SFCA catchments recomputed after traffic reassignment; original demand retained; '
                'facility operations assumed unaffected except road access; missing neighbouring supply/demand not corrected')
        if demand_basis != 'population':
            definitions['population'] = 'Population absent: weighted views use one uniform demand unit per retained node, not resident counts.'
            definitions['service_demand'] = summary['services']['demand']['description']
            summary['services']['criticality']['raw_changes'] = 'signed damaged-minus-baseline means per uniform node demand unit'
    summary['default_view'] = config.analysis.default_view
    summary['metric_cost'] = {'kind': cost_mode, 'unit': 'seconds' if local_costs is not None else 'metres', 'half_cost': half_cost}
    if local_costs is not None:
        definitions['routing'] = 'Graph and removal routing use fixed intact directed seconds; physical road membership and lengths remain unchanged. Failure reliability reassigns traffic when requested.'
        definitions['hansen'] = f'Normalized time Hansen; half-life {half_cost:g} seconds; original population/pair denominators.'
        definitions['detour'] = 'Worst directional alternative-time / original directional road time; no alternative is null.'
        definitions['betweenness'] = 'Undirected minimum physical-road mean directional time; canonical road tie break.'
    summary['composite'] = calculate_composites(summary, config.composite)
    summary['headline'] = summary['composite'][summary['default_view']]
    if config.reliability.p0_sweep:
        summary["reliability_scenarios"] = {key: value for key, value in reliability.summary["scenarios"].items() if key != "primary"}
    resolved = config.model_dump(mode="json")
    resolved["output"]["dir"] = str(output)
    resolved["input"]["path"] = str(config.input.path.expanduser().resolve())
    resolved["input"]["directory"] = str(input_dir)
    if config.population.worldpop is not None:
        resolved["population"]["worldpop"] = str(Path(config.population.worldpop).expanduser().resolve())
    if config.population.node_counts is not None:
        resolved['population']['node_counts'] = str(config.population.node_counts.resolve())
    if config.services is None:
        resolved.pop('services', None)
    else:
        resolved['services']['facilities_csv'] = str(config.services.facilities_csv.expanduser().resolve())
    for section, field in (("input", "boundary"), ("reliability", "p_fail_csv"), ("reliability", "od_pairs_csv")):
        if resolved[section][field] is not None:
            resolved[section][field] = str(Path(resolved[section][field]).expanduser().resolve())
    for field in ("od_csv", "zone_mass_csv", "edge_times_csv", "capacity_csv"):
        value = resolved["traffic"].get(field)
        if value is not None:
            resolved["traffic"][field] = str(Path(value).expanduser().resolve())
    resolved["analysis"].update(n_jobs=jobs, max_memory_gb=budget / GIB)
    if time_model is not None:
        resolved["travel_time"]["time_model"] = "custom"
    manifest = {"schema_version": 1, "created_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": consumed, "resolved_config": resolved, "versions": _versions(), "seed": config.analysis.seed,
        "input_cleaning_fingerprint": graph.graph["input_cleaning_fingerprint"], "cleaning": cleaning,
        "boundary": boundary_meta, "coverage": local.coverage, "population": population.provenance,
        "probabilities": failures.summary, "time_model": reliability.summary["time_model"],
        **({"traffic": traffic.summary} if traffic is not None else {}),
        "sampling": reliability.computation, "attack_removal_order": attack.removal_order,
        "pair_universe": {"nodes": baseline.universe.n, "ordered_node_pairs": baseline.universe.denominator,
            "normalized_population_pair_mass": baseline.universe.denominator_pop,
            "definition": "distinct ordered original pairs; population masses normalized by original population total before products"},
        "units": {"distance": "metres", "time": "seconds", "population": "people", "probability": "one event/scenario"},
        "memory_scope": "shortest-path/simulation workspace; graph, geometry and output storage are additional",
        "custom_time_provider": (type(time_model).__module__ + "." + type(time_model).__qualname__) if time_model is not None else None}
    if facilities is not None:
        manifest['schema_version'] = 2
        manifest['services'] = {'method_version': METHOD_VERSION, 'input': facilities.summary,
            'weights': summary['services']['weights'], 'node_importance': summary['services']['node_importance'],
            'demand': summary['services']['demand'], 'sfca': sfca.summary,
            'facility_mappings': [row for result in sfca.categories.values() for row in result.facilities],
            'candidate_scope': local.coverage, 'time_model': prepared_time.summary}
        if demand_basis != 'population':
            manifest['units']['population'] = 'uniform node demand units; no population data supplied'
    node_records = []
    for index, (node, data) in enumerate(graph.nodes(data=True)):
        metrics = dict(local.nodes[node])
        metrics["null_reasons"] = json.dumps(metrics["null_reasons"], sort_keys=True)
        if "service_null_reasons" in metrics:
            metrics["service_null_reasons"] = json.dumps(metrics["service_null_reasons"], sort_keys=True)
        node_records.append({"node_id": str(node), "population": float(population.weights[index]), **metrics,
                            "geometry": Point(data["x"], data["y"])})
    nodes = gpd.GeoDataFrame(node_records, crs=graph.graph["crs"])
    edge_records = []
    for row in local.links:
        record = {key: value for key, value in row.items() if not key.startswith("_")}
        record["null_reasons"] = json.dumps(record["null_reasons"], sort_keys=True)
        if "service_null_reasons" in record:
            record["service_null_reasons"] = json.dumps(record["service_null_reasons"], sort_keys=True)
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
        if traffic is not None:
            write_traffic_csv(traffic, stage / "traffic_arcs.csv")
            if traffic.od_rows:
                write_traffic_od_csv(traffic, stage / "traffic_od.csv")
            if traffic.closure_rows is not None:
                write_traffic_closures_csv(traffic, stage / "traffic_closures.csv")
            edge_by_label = {(str(u), str(v), str(key)): (u, v, key)
                for u, v, key in traffic.edge_seconds}
            link_by_edge = {edge: row["link_uid"] for row in links for edge in row["_edges"]}
            arc_records = []
            for row in traffic.rows:
                edge = edge_by_label[(row["u"], row["v"], row["key"])]
                u, v, key = edge
                geometry = graph[u][v][key].get("geometry")
                if geometry is None:
                    geometry = LineString([(graph.nodes[u]["x"], graph.nodes[u]["y"]),
                                           (graph.nodes[v]["x"], graph.nodes[v]["y"])])
                arc_records.append({**row, "link_uid": link_by_edge[edge], "geometry": geometry})
            gpd.GeoDataFrame(arc_records, geometry="geometry", crs=graph.graph["crs"]).to_file(
                stage / "network.gpkg", layer="traffic_arcs", driver="GPKG", engine="pyogrio", mode="a")
        if facilities is not None:
            rows = [row for result in sfca.categories.values() for row in result.facilities]
            if rows:
                points = gpd.GeoDataFrame(rows, geometry=[Point(row['longitude'], row['latitude']) for row in rows], crs=4326)
            else:
                points = gpd.GeoDataFrame({'facility_id': [], 'service_type': []}, geometry=[], crs=4326)
            points.to_file(stage / 'network.gpkg', layer='facilities', driver='GPKG', engine='pyogrio')
        write_composites(summary['composite'], stage / 'composite.csv')
        if reassignment is not None:
            reassignment.write(stage / 'traffic_failure_states.csv')
        _write_json(stage / "summary.json", summary)
        _write_json(stage / "run_manifest.json", manifest)
        (stage / "report.txt").write_text(build_report(summary), encoding="utf-8")
        write_curve(attack, stage / "attack_curve.csv")
        if config.reliability.od_pairs_csv is not None:
            write_od_reliability(reliability, stage / "od_reliability.csv")
        if config.output.figures:
            write_figures(nodes, edges, attack, summary, stage / "figures")
        for item in consumed:
            if sha256_file(item["path"]) != item["sha256"]:
                raise ValueError(f"input changed during analysis: {item['path']}")
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
