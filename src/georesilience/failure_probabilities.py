"""Per-event physical-link probabilities, independent of failure simulation."""

import csv
import io
import math
import re
import warnings
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .links import _link_rows, _way_ids

TEMPLATE_COMMENT = (
    "# p_fail = probability the road is closed during ONE event/scenario (not an annual rate), "
    "in [0,1]; leave blank to use the length proxy.\n"
    "# length_m splits each physical link equally among its distinct OSM ways; "
    "simplification does not retain per-way lengths.\n"
)
TEMPLATE_COLUMNS = ("osm_way_id", "name", "highway", "length_m", "n_links", "p_fail")
WARNING_LIMIT = 20


def _ways(link):
    return _way_ids([int(value) for value in link["osm_way_ids"].split(",") if value])


def _length(length_m):
    value = float(length_m)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("non-self-loop link length_m must be finite and positive")
    return value


def _probability(value, name):
    value = float(value)
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"{name} must be finite and in [0,1]")
    return value


def export_edge_template(graph, path=None):
    """Return commented CSV text for the cleaned graph, optionally writing it to path."""
    records = {}
    for link in _link_rows(graph):
        if link["is_self_loop"]:
            continue
        ways = _ways(link)
        length = _length(link["length_m"])
        for way in ways:
            row = records.setdefault(way, {"lengths": [], "names": set(), "highways": set()})
            row["lengths"].append(length / len(ways))
            if link["name"]:
                row["names"].add(link["name"])
            if link["highway"]:
                row["highways"].add(link["highway"])
    stream = io.StringIO(newline="")
    stream.write(TEMPLATE_COMMENT)
    writer = csv.DictWriter(stream, fieldnames=TEMPLATE_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for way, row in sorted(records.items()):
        writer.writerow({"osm_way_id": way, "name": ";".join(sorted(row["names"])),
                         "highway": ";".join(sorted(row["highways"])),
                         "length_m": math.fsum(row["lengths"]), "n_links": len(row["lengths"]),
                         "p_fail": ""})
    content = stream.getvalue()
    if path is not None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(content, encoding="utf-8")
    return content


def read_failure_csv(path, network_way_ids):
    """Validate every CSV row, retaining at most 20 warning messages.

    Row numbers are one-based data-record numbers after the header; comments and
    empty lines do not count. IDs stay strings until integer parsing (no floats).
    """
    values, seen, errors, shown = {}, {}, [], []
    warning_count = unmatched = blanks = 0

    def warn(message):
        nonlocal warning_count
        warning_count += 1
        if len(shown) < WARNING_LIMIT:
            shown.append(message)

    if path is not None:
        try:
            # Reject extra cells instead of letting pandas infer an index and
            # silently shift a probability onto a different way ID.
            with warnings.catch_warnings():
                warnings.simplefilter("error", pd.errors.ParserWarning)
                frame = pd.read_csv(path, comment="#", dtype=str, keep_default_na=False,
                                    index_col=False)
        except (pd.errors.ParserError, pd.errors.EmptyDataError, pd.errors.ParserWarning) as exc:
            raise ValueError(f"p_fail_csv: invalid CSV: {exc}") from exc
        missing = {"osm_way_id", "p_fail"} - set(frame.columns)
        if missing:
            raise ValueError(f"p_fail_csv: missing columns: {', '.join(sorted(missing))}")
        for number, (raw_id, raw_p) in enumerate(
                frame[["osm_way_id", "p_fail"]].itertuples(index=False, name=None), start=1):
            raw_id, raw_p = str(raw_id).strip(), str(raw_p).strip()
            label = f"CSV data row {number} (osm_way_id={raw_id!r})"
            if re.fullmatch(r"[+-]?\d+", raw_id) is None:
                errors.append(f"{label}: osm_way_id must be an integer")
                continue
            way = int(raw_id)
            if way in seen:
                errors.append(f"{label}: duplicate osm_way_id; first appears at data row {seen[way]}")
            seen[way] = number
            if way not in network_way_ids:
                unmatched += 1
                warn(f"{label}: ID not present in the network")
            if not raw_p:
                blanks += 1
                warn(f"{label}: blank p_fail; treated as missing")
                continue
            try:
                probability = _probability(raw_p, "p_fail")
            except (ValueError, TypeError):
                errors.append(f"{label}: p_fail must be numeric, finite and in [0,1]; got {raw_p!r}")
                continue
            if way in network_way_ids:
                values[way] = probability
        if errors:
            raise ValueError("p_fail_csv validation failed:\n" + "\n".join(errors))
    return values, {"total_count": warning_count, "shown": shown,
                    "omitted_count": warning_count - len(shown),
                    "user_ids_unmatched": unmatched, "blank_values": blanks}


def link_failure_probability(length_m, way_ids, user_probabilities, p0):
    """Any-part-fails probability at p0; way IDs form a set, not a sequence.

    Empty way sets use a full length proxy. A CSV value of zero is still covered.
    log1p/expm1 preserve tiny probabilities; exact-one cases avoid log(0).
    """
    length = _length(length_m) / 1000
    p0 = _probability(p0, "p0")
    ways = _way_ids(way_ids)
    covered = [_probability(user_probabilities[way], "p_fail")
               for way in ways if way in user_probabilities]
    share = (len(ways) - len(covered)) / len(ways) if ways else 1.0
    if any(p == 1 for p in covered) or (share > 0 and p0 == 1):
        return 1.0
    log_survival = math.fsum(math.log1p(-p) for p in covered)
    if share > 0:
        log_survival += length * share * math.log1p(-p0)
    return -math.expm1(log_survival)


def probabilities_at_p0(links, user_probabilities, p0):
    """Return non-self-loop {link_id: probability}, reusable by Tickets 09/10."""
    _probability(p0, "p0")
    return {link["link_id"]: link_failure_probability(
        link["length_m"], _ways(link), user_probabilities, p0)
        for link in links if not link["is_self_loop"]}


@dataclass
class FailureProbabilities:
    link_metrics: dict
    summary: dict
    user_probabilities: dict


def compute_failure_probabilities(graph, links, config):
    active = [link for link in links if not link["is_self_loop"]]
    network_ids = {way for link in active for way in _ways(link)}
    user, warnings = read_failure_csv(config.p_fail_csv, network_ids)
    probabilities = probabilities_at_p0(links, user, config.p0)
    categories = {source: {"links": 0, "lengths": []} for source in ("user", "mixed", "proxy")}
    metrics, covered_lengths = {}, []
    for link in links:
        if link["is_self_loop"]:
            metrics[link["link_id"]] = {"p_fail": None, "p_fail_source": None}
        else:
            ways = _ways(link)
            covered = sum(way in user for way in ways)
            source = "proxy" if not covered else "user" if covered == len(ways) else "mixed"
            length = _length(link["length_m"]) / 1000
            categories[source]["links"] += 1
            categories[source]["lengths"].append(length)
            covered_lengths.append(length * covered / len(ways) if ways else 0.0)
            metrics[link["link_id"]] = {"p_fail": probabilities[link["link_id"]],
                                       "p_fail_source": source}
        # One physical link supplies the value for every constituent directed edge.
        for u, v, key in link["_edges"]:
            graph.edges[u, v, key].update(metrics[link["link_id"]])
    total_length = math.fsum(_length(link["length_m"]) / 1000 for link in active)
    by_source = {}
    for source, counts in categories.items():
        length = math.fsum(counts["lengths"])
        by_source[source] = {"links": counts["links"], "length_km": length,
                             "links_pct": 100 * counts["links"] / len(active) if active else 0.0,
                             "length_pct": 100 * length / total_length if total_length else 0.0}
    user_length = math.fsum(covered_lengths)
    proxy_length = max(0.0, total_length - user_length)
    coverage = {"non_self_loop_links": len(active), "total_length_km": total_length,
                "by_source": by_source, "user_length_km": user_length, "proxy_length_km": proxy_length,
                "user_length_pct": 100 * user_length / total_length if total_length else 0.0,
                "proxy_length_pct": 100 * proxy_length / total_length if total_length else 0.0,
                "user_ids_unmatched": warnings["user_ids_unmatched"],
                "p0": config.p0, "p0_sweep": config.p0_sweep}
    return FailureProbabilities(metrics, {"coverage": coverage, "warnings": warnings,
                               "p_fail_csv": str(config.p_fail_csv) if config.p_fail_csv else None}, user)


def failure_probabilities_report(summary):
    coverage, warnings = summary["coverage"], summary["warnings"]
    lines = ["Failure probabilities", "p_fail: closure probability during ONE event/scenario; not an annual rate.",
             f"Primary p0: {coverage['p0']:g} per km per event; sweep: {coverage['p0_sweep']}",
             "Source       Links    Links (%)    Length (km)    Length (%)"]
    for source, row in coverage["by_source"].items():
        lines.append(f"{source:<10} {row['links']:>7} {row['links_pct']:>12.2f} "
                     f"{row['length_km']:>14.3f} {row['length_pct']:>13.2f}")
    lines.extend([
        "Coverage excludes self-loops; reciprocal directed edges count as one physical link.",
        "Mixed links split length equally among distinct ways (per-way lengths are unavailable).",
        f"Effective user length: {coverage['user_length_pct']:.2f}%; "
        f"length proxy: {coverage['proxy_length_pct']:.2f}% (including uncovered shares of mixed links).",
        f"Unmatched user IDs: {coverage['user_ids_unmatched']}; blank values: {warnings['blank_values']}"])
    if 0 < coverage["user_length_pct"] < 50:
        lines.append(f"WARNING: {coverage['proxy_length_pct']:.1f}% of network length uses the length proxy")
    lines.append(f"CSV warnings: {warnings['total_count']} total; {len(warnings['shown'])} shown; "
                 f"{warnings['omitted_count']} omitted")
    lines.extend(f"WARNING: {message}" for message in warnings["shown"])
    lines.append("No road-class failure table is shipped; hazard presets are future work.")
    return lines
