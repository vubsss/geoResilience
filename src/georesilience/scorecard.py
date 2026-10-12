"""Describe existing results; normalisations/composites are project reporting choices."""

import math

from .config import COMPOSITE_KEYS


SOURCES = {
    "Albert 2000": {"citation": "Albert, Jeong and Barabasi (2000), Error and attack tolerance of complex networks",
                    "paper": "papers/AP1-error_and_attack_tolerance_of_complex_networks.pdf"},
    "Crucitti 2006": {"citation": "Crucitti, Latora and Porta (2006), Centrality measures in urban networks",
                      "paper": "papers/AP2-centrality_measures_in_urban_networks.pdf"},
    "Taylor 2006": {"citation": "Taylor, Sekhar and D'Este (2006), Application of Accessibility Based Methods for Vulnerability Analysis of Strategic Road Networks",
                    "paper": "papers/AP3-vulnerability_analysis.pdf"},
}
COMPOSITE_LABEL = "user-weighted composite -- weights chosen by the user, not part of the method"


def _finite(value):
    return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else None


def _interval(data, low="ci_low", high="ci_high"):
    values = [_finite(data.get(low)), _finite(data.get(high))]
    return values if all(value is not None for value in values) else None


def build_scorecard(summary, config):
    metrics = summary.get("metrics", {})
    robustness = metrics.get("robustness", {})
    links = robustness.get("links", {})
    redundancy = metrics.get("redundancy", {})
    reliability = summary.get("reliability", {})
    access = metrics.get("accessibility", {})
    population_on = "population" in summary
    rows = []

    def add(key, label, dimension, value, meaning, citation, ticket, *, normalise=None,
            reason="source metric unavailable", pop_value=None, pop_reason=None, has_variant=False,
            interval=None, pop_interval=None, extra=None):
        value, pop_value = _finite(value), _finite(pop_value)
        weighted = population_on and has_variant
        selected = pop_value if weighted else value
        row = {"key": key, "label": label, "dimension": dimension, "value": selected,
               "uniform_value": value, "population_value": pop_value if has_variant else None,
               "population_reason": (pop_reason or "population-weighted metric unavailable") if population_on
                                    else "population disabled",
               "basis": "population" if weighted else "structural",
               "status": "computed" if selected is not None else "not computed",
               "reason": None if selected is not None else (pop_reason if weighted else reason),
               "uniform_reason": None if value is not None else reason,
               "meaning": meaning, "citation": citation, "source_key": ticket,
               "unit": "ratio" if key == "redundancy_detour" else "fraction",
               "normalised_score": _finite(normalise(selected)) if selected is not None and normalise else None,
               "uniform_normalised_score": _finite(normalise(value)) if value is not None and normalise else None,
               "ci_95": pop_interval if weighted else interval, "uniform_ci_95": interval,
               "population_ci_95": pop_interval}
        if not has_variant:
            row["population_reason"] = "no population variant defined for this metric"
        if extra:
            row.update(extra)
        rows.append(row)

    f_max = robustness.get("parameters", {}).get("f_max")
    interval_text = f"0 to {100*f_max:g}% requested road removal" if _finite(f_max) is not None else "the configured removal range"
    for key, field, label, mode in (("robustness_attack", "auc_attack_S", "Link attack AUC (S)", "targeted attack"),
                                   ("robustness_failure", "auc_failure_S", "Link failure AUC (S)", "random failure")):
        add(key, label, "Structural robustness", links.get(field),
            f"Average largest strongly connected component / original node count over {interval_text}, under {mode}; this is not the final-step fraction.",
            "Albert 2000", "06", normalise=lambda x: x,
            reason="link removal experiment not configured" if not links else "link connectivity AUC undefined")
    bridge = redundancy.get("bridge_frac") if redundancy.get("non_self_loop_link_count", 0) > 0 else None
    add("redundancy_bridges", "Physical links that are bridges", "Redundancy", bridge,
        "Fraction of non-loop physical roads whose removal disconnects the undirected graph; score = 1 - fraction.",
        "Taylor 2006", "04", normalise=lambda x: 1-x, reason="no non-loop physical links or screening unavailable")
    detour = _finite(redundancy.get("detour_ratio", {}).get("median"))
    detour = detour if detour is not None and detour > 0 else None
    add("redundancy_detour", "Median finite detour ratio", "Redundancy", detour,
        "Median alternative u-to-v road distance / removed road length, among finite alternatives only; roads without alternatives are excluded; score = 1 / median.",
        "Taylor 2006", "04", normalise=lambda x: 1/x, reason="no positive finite detour ratios or screening unavailable",
        extra={"finite_detour_count": redundancy.get("finite_detour_count"), "no_alternative_count": redundancy.get("detour_none_count")})
    add("reliability", "Mutually connected pair fraction", "Connectivity reliability", reliability.get("conn_reliability"),
        "Expected fraction of distinct node pairs in the same SCC under independent physical-road failures; population variant weights pairs by population products, not persons retained.",
        "Taylor 2006", "09", normalise=lambda x: x, reason=reliability.get("pair_universe_status", "connectivity stage unavailable"),
        has_variant=True, pop_value=reliability.get("conn_reliability_pop"),
        pop_reason=(reliability.get("population_pair_universe_status") if reliability.get("population_pair_universe_status") not in (None, "defined")
                    else "population-weighted pair metric unavailable"),
        interval=_interval(reliability), pop_interval=_interval(reliability, "conn_reliability_pop_ci_low", "conn_reliability_pop_ci_high"))
    add("accessibility", "Mean single-link accessibility loss", "Accessibility vulnerability", access.get("vuln", {}).get("mean"),
        "Mean over defined node-specific worst evaluated single-road losses in truncated exponential Hansen accessibility; population variant weights destinations, with origins still averaged uniformly; score = 1 - mean loss.",
        "Taylor 2006", "11", normalise=lambda x: 1-x, reason="no defined node vulnerability scores or accessibility unavailable",
        has_variant=True, pop_value=access.get("vuln_pop", {}).get("mean"), pop_reason="no defined population-destination vulnerability scores",
        extra={"p90": _finite(access.get("vuln_pop" if population_on else "vuln", {}).get("p90")),
               "uniform_p90": _finite(access.get("vuln", {}).get("p90")),
               "population_p90": _finite(access.get("vuln_pop", {}).get("p90")),
               "scope": access.get("vulnerability_scope"),
               "undefined_nodes": access.get("undefined_vulnerability_count_pop" if population_on else "undefined_vulnerability_count")})
    allocated = _finite(summary.get("population", {}).get("allocated"))
    cut_off = _finite(reliability.get("expected_pop_cut_off"))
    retained = 1-cut_off/allocated if allocated is not None and allocated > 0 and cut_off is not None else None
    cutoff_ci = _interval(reliability, "expected_pop_cut_off_ci_low", "expected_pop_cut_off_ci_high")
    retention_ci = [1-cutoff_ci[1]/allocated, 1-cutoff_ci[0]/allocated] if retained is not None and cutoff_ci else None
    add("population_connected", "Allocated population retained", "Connectivity reliability", None,
        "Expected share of allocated population in the largest node-count SCC; distinct from population-weighted pair connectivity and from census population.",
        "Taylor 2006", "09/12", has_variant=True, pop_value=retained, pop_interval=retention_ci,
        reason="population disabled", pop_reason="zero allocated population or expected population cut off unavailable",
        extra={"uniform_reason": "population-only metric; no structural counterpart"})
    travel = summary.get("travel_time", {})
    add("travel_time", "Travel-time threshold reliability", "Travel-time reliability", travel.get("tt_reliability"),
        "Expected fraction of directed journeys from fixed selected origins within (1 + tau) of baseline time; reported separately from mutual connectivity.",
        "Taylor 2006", "10", reason=travel.get("status", "travel-time stage unavailable") if travel.get("status") != "computed"
        else "no distinct directed journeys", interval=_interval(travel))
    classification = summary.get("classification", {})
    rows.append({"key": "network_class", "label": "Network class", "dimension": "Network class",
                 "value": classification.get("network_label"), "basis": classification.get("label_basis"),
                 "status": "computed" if classification.get("network_label") else "not computed",
                 "reason": None if classification.get("network_label") else "classification unavailable",
                 "normalised_score": None, "unit": "label", "citation": "Crucitti 2006", "source_key": "07",
                 "meaning": "Relative centrality-distribution fit label; inconclusive is an allowed result and is not assigned a resilience score.",
                 "limitations": classification.get("limitations"),
                 "basis_reason": classification.get("distributions", {}).get(classification.get("label_basis"), {}).get("reason")})
    result = {"population_present": population_on, "rows": rows,
              "normalised_scores": {row["key"]: row["normalised_score"] for row in rows if row["key"] in COMPOSITE_KEYS},
              "sources": SOURCES, "normalisation_note": "Project reporting normalisations, not paper-defined universal resilience scores; inverse detour may exceed 1 if the alternative is shorter."}
    weights = config.weights
    if weights is not None:
        missing = [key for key in weights if result["normalised_scores"][key] is None]
        if missing:
            reasons = {row["key"]: row["reason"] or "normalised score is unavailable or nonfinite" for row in rows}
            raise ValueError("composite.weights: metric not computed: " + "; ".join(f"{key} ({reasons[key]})" for key in missing))
        # Scale first to avoid overflowing a sum of valid large user weights.
        maximum = max(weights.values())
        scaled = {key: weights[key]/maximum for key in COMPOSITE_KEYS if key in weights}
        total = math.fsum(scaled.values())
        normalised = {key: value/total for key, value in scaled.items()}
        value = math.fsum(weight*result["normalised_scores"][key] for key, weight in normalised.items())
        result["composite"] = {"value": value, "weights": normalised, "supplied_weights": dict(weights),
                               "scores": {key: result["normalised_scores"][key] for key in normalised},
                               "label": COMPOSITE_LABEL, "basis": "population variants where defined" if population_on else "structural variants"}
    return result


def scorecard_report(scorecard):
    def number(value):
        return "not computed" if value is None else f"{value:.9g}"

    lines = ["Scorecard", "Normalised scores follow the project definitions; 1 = resilient under each metric."]
    for row in scorecard["rows"]:
        value = row["value"]
        display = value if isinstance(value, str) else f"{value:.9g}" if value is not None else "not computed"
        lines.append(f"{row['dimension']} | {row['label']}: {display}; unit: {row['unit']}; basis: {row['basis']}")
        if value is None:
            lines.append(f"Reason: {row['reason']}")
        if "uniform_value" in row and row["key"] != "population_connected":
            uniform = row["uniform_value"]
            lines.append(f"Structural: {uniform:.9g}" if uniform is not None else f"Structural: not computed ({row['uniform_reason']})")
            if row["key"] in ("reliability", "accessibility"):
                pop = row["population_value"]
                lines.append(f"Population: {pop:.9g}" if pop is not None else f"Population: not computed ({row['population_reason']})")
        if row.get("ci_95"):
            lines.append(f"95% CI: [{row['ci_95'][0]:.9g}, {row['ci_95'][1]:.9g}]")
        if row.get("basis") == "population" and row.get("uniform_ci_95"):
            low, high = row["uniform_ci_95"]
            lines.append(f"Structural 95% CI: [{low:.9g}, {high:.9g}]")
        if "p90" in row:
            lines.append(f"p90 loss: {number(row['p90'])}; structural p90: {number(row['uniform_p90'])}; population p90: {number(row['population_p90'])}")
        if row["normalised_score"] is not None:
            lines.append(f"Normalised score ({row['key']}): {row['normalised_score']:.9g}")
        lines.extend([row["meaning"], f"Source: {row['citation']} (ticket {row['source_key']}); {SOURCES[row['citation']]['paper']}"])
        if row.get("basis_reason"):
            lines.append(f"Classification basis: {row['basis_reason']}")
    if "composite" in scorecard:
        composite = scorecard["composite"]
        lines.extend(["", composite["label"], f"composite_user_weighted: {composite['value']:.9g}",
                      "Normalised user weights: " + ", ".join(f"{key}={value:.9g}" for key, value in composite["weights"].items())])
    lines.append(scorecard["normalisation_note"])
    return lines
