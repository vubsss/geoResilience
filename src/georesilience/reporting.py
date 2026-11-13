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
    if summary.get("traffic"):
        traffic = summary["traffic"]
        lines.extend(["", "Traffic assignment",
            f"  Status: {traffic['status']}; source: {traffic['source']}; period: {traffic['period']}",
            f"  Directed arcs: {traffic['arc_count']}"])
        if traffic["source"] == "assignment":
            lines.extend([f"  Demand: {traffic['demand_pcu_h']:.6g} PCU/h",
                f"  Demand source: {traffic['demand_source']}; capacity source: {traffic['capacity_source']}",
                f"  VDF: {traffic['vdf']} (alpha={traffic['alpha']}, beta={traffic['beta']})",
                f"  Relative gap: {traffic['relative_gap']:.6g} after {traffic['iterations']} iterations",
                f"  Total system travel time: {traffic['tstt_pcu_hours']:.6g} PCU-hours",
                f"  Mean OD time/delay: {traffic['mean_od_time_s']:.6g} / {traffic['mean_od_delay_s']:.6g} seconds",
                "  Traffic inputs are simulated/supplied scenario assumptions, not observed counts."])
            if traffic["demand_source"] == "population":
                lines.append(f"  Effective rate: {traffic['population_trip_rate_per_person_h']:.6g} PCU/person/hour")
                lines.append(f"  Population zones: {traffic['population_zone_count']} of "
                    f"{traffic['populated_node_count']} populated nodes")
            if traffic["capacity_source"] == "road_attributes":
                coverage = traffic["capacity_tag_coverage"]
                lines.append(f"  Capacity tags (directed arcs): lanes={coverage['lanes_tagged']}, "
                    f"width-only={coverage['width_tagged']}, defaults={coverage['fallback']}, "
                    f"invalid tags={coverage['invalid_tag_arcs']}")
    return "\n".join(lines) + "\n"
