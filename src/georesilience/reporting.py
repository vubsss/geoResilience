"""Final report assembly and geographic locators from finished analysis layers."""

import math
import re
import textwrap

import geopandas as gpd
import pandas as pd

from .accessibility import accessibility_report
from .centralities import centrality_report
from .classification import classification_report
from .connectivity import connectivity_report
from .criticality import criticality_report
from .failure_probabilities import failure_probabilities_report
from .network import cleaning_report
from .population import population_report
from .robustness import robustness_report
from .scorecard import scorecard_report
from .screening import redundancy_report
from .travel_time import travel_time_report
from .zones import _midpoint, _zone_key, zones_report


def _number(value):
    return float(value) if value is not None and not pd.isna(value) and math.isfinite(value) else None


def _text(value):
    return None if value is None or pd.isna(value) else str(value)


def _ways(value):
    return [int(part) for part in (_text(value) or "").split(",") if part.strip()]


def build_locator_tables(nodes, links, population_on):
    """Separate reporting ranks; leave the existing analysis ranks/layers untouched."""
    link_metric = "eff_drop_pop" if population_on else "eff_drop"
    pair_metric = "disc_pair_frac_pop" if population_on else "disc_pair_frac"
    node_metric = "vuln_pop" if population_on else "vuln"
    active = links.loc[~links.is_self_loop.astype(bool)]
    link_records = active.to_dict("records")
    selected = [row for row in link_records if _number(row.get(link_metric)) is not None]
    selected.sort(key=lambda row: (-row[link_metric], -(_number(row.get(pair_metric)) or 0), row["link_id"]))
    top_links = []
    if selected:
        points = gpd.GeoSeries([_midpoint(row["geometry"]) for row in selected[:20]], crs=links.crs).to_crs(4326)
        for rank, (row, point) in enumerate(zip(selected[:20], points), 1):
            ways = _ways(row.get("osm_way_ids"))
            top_links.append({"rank": rank, "link_id": int(row["link_id"]), "name": _text(row.get("name")),
                              "highway": _text(row.get("highway")), "first_osm_way_id": str(ways[0]) if ways else None,
                              "latitude": float(point.y), "longitude": float(point.x),
                              "eff_drop": _number(row.get("eff_drop")), "eff_drop_pop": _number(row.get("eff_drop_pop"))})
    incidents = {}
    for row in links.to_dict("records"):
        for node in {str(row["u"]), str(row["v"])}:
            incidents.setdefault(node, []).append(row)
    node_records = nodes.to_dict("records")
    selected = [row for row in node_records if _number(row.get(node_metric)) is not None]
    selected.sort(key=lambda row: (-row[node_metric], _zone_key(row["node_id"])))
    top_nodes = []
    if selected:
        points = gpd.GeoSeries([row["geometry"] for row in selected[:20]], crs=nodes.crs).to_crs(4326)
        for rank, (row, point) in enumerate(zip(selected[:20], points), 1):
            roads = incidents.get(str(row["node_id"]), [])
            ways = sorted({way for road in roads for way in _ways(road.get("osm_way_ids"))})
            names = sorted({_text(road.get("name")) for road in roads if _text(road.get("name"))})
            highways = sorted({_text(road.get("highway")) for road in roads if _text(road.get("highway"))})
            top_nodes.append({"rank": rank, "node_id": str(row["node_id"]), "name": "; ".join(names) or None,
                              "highway": "; ".join(highways) or None, "first_osm_way_id": str(ways[0]) if ways else None,
                              "latitude": float(point.y), "longitude": float(point.x),
                              "vuln": _number(row.get("vuln")), "vuln_pop": _number(row.get("vuln_pop"))})
    return {"link_metric": link_metric, "node_metric": node_metric,
            "ranking": "descending selected metric; link ties use disconnected pair fraction then link ID; node ties use canonical node ID",
            "coordinate_crs": "EPSG:4326", "link_location": "actual geometry half-length point",
            "node_osm_id": "smallest incident OSM way ID", "top20_critical_links": top_links,
            "top20_vulnerable_nodes": top_nodes}


def collect_coverage_warnings(summary):
    """Collect existing stage diagnostics without inventing new analysis results."""
    warnings = []

    def add(stage, message):
        item = {"stage": stage, "message": str(message)}
        if item not in warnings:
            warnings.append(item)

    cleaning = summary.get("cleaning", {})
    dropped = cleaning.get("dropped_components", {})
    if dropped:
        add("Cleaning", f"Dropped components: {dropped.get('count', 0)}; nodes: {dropped.get('nodes_dropped', 0)}; road length: {dropped.get('length_dropped_pct', 0):.6g}%.")
    reliability = summary.get("reliability", {})
    proxy = reliability.get("coverage", {}).get("proxy_length_pct")
    if proxy is not None:
        add("Failure probabilities", f"p_fail proxy share: {proxy:.6g}% of physical road length; mixed links may contain both user and proxy parts.")
    population = summary.get("population")
    if population is None:
        add("Population", "not computed: population disabled; population variants are unavailable.")
    else:
        add("Population", f"Unallocated population: {population['unallocated']:.9g} ({population['unallocated_pct']:.6g}%); excluded from weighted metrics.")
    metrics = summary.get("metrics", {})
    info = metrics.get("information", {})
    add("Information centrality", f"Information coverage: {info.get('coverage', 'not computed')}; candidate count: {info.get('candidate_count', 'unknown')}.")
    critical = metrics.get("criticality", {})
    if critical.get("unevaluated_link_count", 0):
        add("Critical links", f"Unevaluated physical roads: {critical['unevaluated_link_count']}; rankings cover evaluated closures only.")
    accessibility = metrics.get("accessibility", {})
    if accessibility:
        add("Accessibility", f"Vulnerability scope: {accessibility.get('vulnerability_scope')}; undefined nodes: {accessibility.get('undefined_vulnerability_count', 0)} structural, {accessibility.get('undefined_vulnerability_count_pop', 'population off')} population-destination.")
    detour = metrics.get("redundancy", {})
    if detour.get("detour_none_count", 0):
        add("Redundancy", f"No finite detour for {detour['detour_none_count']} roads; these roads are excluded from the median detour score.")
    if detour.get("detour_ratio", {}).get("median") is not None and detour["detour_ratio"]["median"] < 1:
        add("Redundancy", "Median detour is below 1; its inverse score exceeds 1 because an alternative is shorter than the removed road.")
    travel = summary.get("travel_time", {})
    if travel.get("status") != "computed":
        add("Travel-time reliability", f"not computed: {travel.get('status', 'stage unavailable')}.")
    if "zones" not in summary:
        add("Zones", "not computed: zone polygons not supplied.")
    else:
        zones = summary["zones"]
        add("Zones", f"Unassigned nodes: {zones['unassigned_nodes']}; roads: {zones['unassigned_links']}; allocated population: {zones['unassigned_population']}; full supplied polygon areas retained.")
    for row in summary.get("scorecard", {}).get("rows", []):
        if row["status"] == "not computed":
            add("Scorecard", f"{row['label']}: not computed ({row['reason']}).")
        interval = row.get("ci_95")
        if interval and interval[0] == interval[1]:
            add(row["dimension"], "Constant observed scores yield a zero-width normal interval; rare unseen failures remain possible.")

    def diagnostics(value, stage):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in ("warnings", "od_warnings"):
                    if isinstance(child, list):
                        for message in child:
                            add(stage, message)
                    elif isinstance(child, dict):
                        for message in child.get("shown", []):
                            add(stage, message)
                        if child.get("omitted_count", 0):
                            add(stage, f"{child['omitted_count']} additional warnings omitted; see full stage summary.")
                elif key == "status" and isinstance(child, str) and (child.startswith("skipped") or child == "disabled"):
                    add(stage, f"not computed: {child}.")
                else:
                    diagnostics(child, stage)
    for stage, data in (("Cleaning", cleaning), ("Failure/Connectivity", reliability),
                        ("Travel-time reliability", travel), ("Population", population), ("Metrics", metrics),
                        ("Network class", summary.get("classification", {}))):
        diagnostics(data, stage)
    return warnings


def locator_report(tables, kind):
    links = kind == "links"
    rows = tables["top20_critical_links" if links else "top20_vulnerable_nodes"]
    metric = tables["link_metric" if links else "node_metric"]
    lines = ["Top 20 critical link locators" if links else "Top 20 vulnerable node locators",
             f"Reporting order uses {metric}; coordinates are WGS84 latitude/longitude.", tables["ranking"],
             "rank | ID | metric | name | highway | first_osm_way_id | latitude | longitude"]
    for row in rows:
        identifier = row["link_id" if links else "node_id"]
        lines.append(f"{row['rank']} | {identifier} | {row[metric]:.9g} | {row['name'] or '-'} | "
                     f"{row['highway'] or '-'} | {row['first_osm_way_id'] or '-'} | {row['latitude']:.7f} | {row['longitude']:.7f}")
        if metric.endswith("_pop"):
            uniform = row[metric[:-4]]
            lines.append(f"  Structural value for {identifier}: {uniform:.9g}" if uniform is not None else "  Structural value: not computed")
    if not rows:
        lines.append(f"not computed: no finite evaluated {metric} values")
    return lines


METHOD_NOTES = [
    "Structural robustness (Albert 2000): normalized integral of largest SCC / original N over requested [0, f_max]. Actual integer removals are used, with final plateau to f_max. This project AUC is not the fraction remaining at 20% removal. Random-failure bands describe variation across runs, not a confidence interval for every headline.",
    "Centrality and class (Crucitti 2006): undirected metric centralities use mean(1/d) efficiency, distinct from the paper's spatial mean(d_E/d). Information may cover only candidates; then classification uses betweenness fallback. Relative likelihood/AIC evidence may be inconclusive; it is not a goodness-of-fit proof or a resilience score.",
    "Redundancy (Taylor 2006 vulnerability context; project definition): undirected bridge count fraction and directed finite endpoint detour median. Inverse median excludes roads with no alternative, so read it with bridge/no-alternative counts. It may exceed 1 for shorter alternatives. These normalisations are project choices, not published universal scores.",
    "Connectivity reliability (Taylor 2006 context; project SCC Monte Carlo): distinct pairs count as connected only within the same SCC; directed OD reachability is separate. Population pair weights are population products. Main-SCC population retention uses the largest SCC by node count and its deterministic ID tie break. Population-weighted pair fractions cannot be interpreted as fractions of persons.",
    "Accessibility (Taylor 2006 motivation; plan's exponential definition): A_i = sum W_j exp(-beta*d_ij), j != i, outbound d_ij <= R. This differs from AP3's inverse-cost accessibility expression. Vulnerability is each node's worst evaluated single-link relative loss; network means omit undefined origins and population weights destinations only. Candidate-only coverage can understate worst loss; optional top-three k=2 search is not globally exhaustive.",
    "Travel-time reliability (Taylor 2006 context; project definition): probability of finite directed journeys meeting the configured relative-time threshold, conditional on fixed selected origins and the specified additive time model. Free-flow estimates omit congestion and speed uncertainty; no usable speed data means the stage is skipped.",
    "Data limits: clipped boundaries create artificial dead-ends; routes outside the retained graph are unavailable. The largest-component filter discards other components. Failure p is per event/scenario, not annual risk; independent physical-road closures and length proxies do not model correlated hazards. Monte Carlo intervals condition on these assumptions; constant samples can miss rare failures.",
    "Population and zones: WorldPop is a modelled estimate, not a census. Nearest-node allocation omits unallocated cells. Ward aggregates summarize finished network results only; whole road lengths follow geometry midpoints and full zone areas are used, so partial study coverage affects density. Origin-population-weighted zone vulnerability differs from destination-weighted vuln_pop.",
    "Composite: a weighted mean is calculated only for explicitly supplied valid weights and available scores; weights are normalized and disclosed. Choosing metrics/weights can change rankings. There is no default composite, paper-defined weighting scheme, or propagated composite confidence interval.",
]


def build_report(summary, config, links, run_name):
    metrics = summary["metrics"]
    lines = [f"GeoResilience {summary['meta']['package_version']}", f"Run: {run_name}",
             f"Input: {summary['meta']['input']}", f"UTC: {summary['meta']['timestamp_utc']}",
             f"Nodes: {summary['meta']['node_count']}; physical links: {summary['meta']['link_count']}; directed edges: {summary['meta']['directed_edge_count']}",
             f"Graph CRS: EPSG:{summary['meta']['crs_epsg']}; requested network type: {config.network.type}; applied: {summary['meta']['network_type_applied']}",
             "", *scorecard_report(summary["scorecard"]), "", "Data and coverage warnings"]
    lines.extend(f"{item['stage']}: {item['message']}" for item in summary["coverage_warnings"])
    histogram = metrics["degree"]["histogram"]
    sections = [cleaning_report(summary["cleaning"]) + ["", "Degree", "degree: count"] + [f"{key}: {value}" for key, value in histogram.items()],
                centrality_report(metrics, links), classification_report(summary["classification"]),
                redundancy_report(metrics["redundancy"], links),
                criticality_report(metrics["criticality"], metrics["information"]) + [""] + locator_report(summary["critical_tables"], "links"),
                robustness_report(metrics["robustness"]), failure_probabilities_report(summary["reliability"]),
                connectivity_report(summary["reliability"]), travel_time_report(summary["travel_time"]),
                accessibility_report(metrics["accessibility"]) + [""] + locator_report(summary["critical_tables"], "nodes"),
                population_report(summary["population"]) if "population" in summary else ["Population", "not computed: population disabled"],
                zones_report(summary["zones"]) if "zones" in summary else ["Zones", "not computed: zone polygons not supplied"],
                ["Method notes", *METHOD_NOTES]]
    for section in sections:
        lines.extend(["", *section])
    # Escaping keeps identifiers/names visible on ASCII terminals; normalize
    # embedded newlines/control characters before wrapping so rows cannot inject headings.
    clean = [re.sub(r"[\x00-\x1f\x7f]", " ", line) for line in lines]
    escaped = [line.encode("ascii", "backslashreplace").decode() for line in clean]
    return "\n".join(textwrap.fill(line, width=100) if len(line) > 100 else line for line in escaped) + "\n"
