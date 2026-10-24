"""A concise report of retained metrics, coverage and assumptions."""


def build_report(summary):
    lines = ["GeoResilience", ""]
    for group in ("unweighted", "population_weighted"):
        lines.append(group.replace("_", " ").title())
        for name, metric in summary[group].items():
            value = metric["value"]
            text = f"{value:.8g}" if value is not None else "unavailable: " + metric["reason"]
            if metric.get("ci_low") is not None:
                text += f" (95% CI {metric['ci_low']:.6g} to {metric['ci_high']:.6g}; {metric['samples']} scenarios)"
            lines.append(f"  {name}: {text}")
            lines.append("    " + metric["definition"])
        lines.append("")
    lines.append("Removal coverage")
    for kind, coverage in summary["coverage"].items():
        lines.append(f"  {kind}: {coverage['mode']}; {coverage['evaluated']} / {coverage['total']} evaluated")
        lines.append("    " + coverage["method"])
    population = summary["population"]
    lines.extend(["", "Population counts", f"  Crop total: {population['total']:.9g}; allocated: {population['allocated']:.9g}; "
                  f"unallocated: {population['unallocated']:.9g} ({population['unallocated_pct']:.4g}%)",
                  "  WorldPop counts are modelled estimates; unallocated cells are excluded from weighted measures.",
                  "", "Failure coverage"])
    for source, row in summary["probabilities"]["coverage"]["by_source"].items():
        lines.append(f"  {source}: {row['links']} links; {row['length_m']:.9g} metres; "
                     f"{row['links_pct']}% of links; {row['length_pct']}% of length")
    lines.extend(["", "Definitions and assumptions", *["  " + value for value in summary["definitions"].values()],
                  "  Failure probabilities apply to one event/scenario, not annual rates. Physical-link failures are independent.",
                  "  Reliability intervals are conservative 95% Hoeffding bounds over independent scenario fractions.",
                  "  Travel times use supplied static speeds or edge costs; congestion and observed trips are not modelled.",
                  "  Speed/time source: " + str(summary["time_model"]),
                  "  Attack AUC: " + summary["attack"]["auc_convention"],
                  f"  Attack horizon: {summary['attack']['horizon']:.6g} of physical links; "
                  f"order: {summary['attack']['order']}.",
                  "  All input hashes, resolved settings, versions and evaluated IDs are in run_manifest.json."])
    if summary.get("reliability_scenarios"):
        lines.append("  Additional p0 scenarios: " + ", ".join(summary["reliability_scenarios"]))
    return "\n".join(lines) + "\n"
