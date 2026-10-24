"""Strict physical-link event probabilities and length-proxy coverage."""

import csv
import io
import math
from dataclasses import dataclass
from pathlib import Path

from .links import _link_rows

TEMPLATE_COLUMNS = ("link_uid", "osm_way_ids", "u", "v", "length_m", "name", "highway", "p_fail")
FINGERPRINT_PREFIX = "# georesilience_fingerprint="


def _probability(value, name="p_fail"):
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be finite and in [0,1]") from exc
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"{name} must be finite and in [0,1]")
    return value


def export_edge_template(graph, path=None):
    fingerprint = graph.graph.get("input_cleaning_fingerprint")
    if fingerprint is None:
        raise ValueError("failure template requires a cleaned input with a fingerprint")
    stream = io.StringIO(newline="")
    stream.write("# p_fail is the probability of closure during one event/scenario, not an annual rate.\n")
    stream.write(FINGERPRINT_PREFIX + fingerprint + "\n")
    writer = csv.DictWriter(stream, fieldnames=TEMPLATE_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for link in _link_rows(graph):
        if not link["is_self_loop"]:
            writer.writerow({**{key: link[key] for key in TEMPLATE_COLUMNS if key != "p_fail"}, "p_fail": ""})
    content = stream.getvalue()
    if path is not None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return content


def read_failure_csv(path, links, fingerprint, require_complete=False):
    known = {row["link_uid"] for row in links if not row["is_self_loop"]}
    values, seen, blanks = {}, set(), 0
    if path is not None:
        lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
        fingerprints = [line[len(FINGERPRINT_PREFIX):].strip() for line in lines if line.startswith(FINGERPRINT_PREFIX)]
        if fingerprints != [fingerprint]:
            raise ValueError("failure CSV input/cleaning fingerprint mismatch or missing; regenerate failures-template")
        reader = csv.DictReader(line for line in lines if line.strip() and not line.lstrip().startswith("#"))
        if reader.fieldnames is None or not {"link_uid", "p_fail"} <= set(reader.fieldnames):
            raise ValueError("failure CSV requires link_uid,p_fail columns")
        if len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError("failure CSV has duplicate column names")
        for number, row in enumerate(reader, 1):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"failure CSV data row {number}: invalid column count")
            uid = row["link_uid"].strip()
            if uid in seen:
                raise ValueError(f"failure CSV data row {number}: duplicate link_uid {uid}")
            if uid not in known:
                raise ValueError(f"failure CSV data row {number}: unknown link_uid {uid}")
            seen.add(uid)
            if row["p_fail"].strip():
                values[uid] = _probability(row["p_fail"], f"failure CSV data row {number} p_fail")
            else:
                blanks += 1
    missing = known - values.keys()
    if require_complete and missing:
        raise ValueError(f"complete failure probabilities required: {len(missing)} uncovered or blank physical links")
    return values, {"blank_values": blanks, "uncovered_links": len(missing)}


def probabilities_at_p0(links, user_probabilities, p0):
    p0 = _probability(p0, "p0")
    result = {}
    for row in links:
        if row["is_self_loop"]:
            continue
        length = row["length_m"] / 1000
        if not math.isfinite(length) or length <= 0:
            raise ValueError("physical-link length must be finite and positive")
        result[row["link_id"]] = (_probability(user_probabilities[row["link_uid"]])
            if row["link_uid"] in user_probabilities else
            1.0 if p0 == 1 else -math.expm1(length * math.log1p(-p0)))
    return result


@dataclass
class FailureProbabilities:
    link_metrics: dict
    summary: dict
    user_probabilities: dict


def compute_failure_probabilities(graph, links, config):
    user, validation = read_failure_csv(config.p_fail_csv, links,
        graph.graph.get("input_cleaning_fingerprint"), config.require_complete_failures)
    probabilities = probabilities_at_p0(links, user, config.p0)
    by_source = {source: {"links": 0, "length_m": 0.0} for source in ("user", "proxy")}
    metrics = {}
    for row in links:
        if row["is_self_loop"]:
            metrics[row["link_id"]] = {"p_fail": None, "p_fail_source": None}
        else:
            source = "user" if row["link_uid"] in user else "proxy"
            by_source[source]["links"] += 1
            by_source[source]["length_m"] += row["length_m"]
            metrics[row["link_id"]] = {"p_fail": probabilities[row["link_id"]], "p_fail_source": source}
        for edge in row["_edges"]:
            graph.edges[edge].update(metrics[row["link_id"]])
    count = sum(row["links"] for row in by_source.values())
    length = sum(row["length_m"] for row in by_source.values())
    for row in by_source.values():
        row.update(links_pct=100 * row["links"] / count if count else None,
                   length_pct=100 * row["length_m"] / length if length else None)
    return FailureProbabilities(metrics, {"coverage": {"non_self_loop_links": count,
        "total_length_m": length, "by_source": by_source}, "validation": validation,
        "model": "independent physical-link closures per event/scenario",
        "proxy": "1 - (1 - p0) ** (length_m / 1000)", "p0": config.p0}, user)


def failure_probabilities_report(summary):
    return ["Failure probabilities: independent physical-link closures during one event/scenario.",
            "Not annual probabilities. Missing values use 1 - (1 - p0) ** length_km.",
            "Coverage: " + str(summary["coverage"])]
