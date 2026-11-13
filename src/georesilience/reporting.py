"""A concise report of retained metrics, coverage and assumptions."""


def build_report(summary):
    lines = ["GeoResilience", ""]
    for group in ("unweighted", "population_weighted"):
        title = group.replace("_", " ").title()
        if group == "population_weighted" and summary["population"].get("basis") == "uniform_node_demand":
            title = "Uniform node demand weighted (population absent)"
        lines.append(title)
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
    if population.get('basis') == 'uniform_node_demand':
        lines = [('Uniform node demand units' if line == 'Population counts' else line)
            for line in lines if 'WorldPop counts are modelled estimates' not in line]
        lines.extend(['', 'Population fallback: one demand unit per retained node; these are not resident counts.'])
    if summary.get('services'):
        services = summary['services']
        lines.extend(['', 'Critical services and node importance',
            '  Demand: ' + services['demand']['description'],
            '  Node importance: ' + services['node_importance']['definition'],
            f"  Population importance coefficient: {services['node_importance']['population_importance']:g}",
            '  Service points: ' + services['weights']['definition'],
            '  Known zero-capacity institutions retain service points but contribute no 2SFCA supply.'])
        for category, coverage in services['input']['categories'].items():
            lines.extend([f"  {category}: {coverage['facility_count']} facilities; capacity unit: {coverage['capacity_unit']}; "
                f"known capacity: {coverage['known_capacity_total']:g}; unknown capacities: {coverage['unknown_capacity_count']}",
                '    Capacity sources: ' + (', '.join(coverage['capacity_sources']) or 'not supplied')])
        lines.extend(['', 'Service-weighted measures (original resident-demand × service-point mass)'])
        for name, metric in services['service_weighted'].items():
            text = f"{metric['value']:.8g}" if metric['value'] is not None else 'unavailable: ' + metric['reason']
            lines.append(f'  {name}: {text}')
            lines.append('    ' + metric['definition'])
        metric = services['node_importance_weighted']['targeted_attack_robustness']
        lines.append('  Combined node importance attack AUC: ' + (f"{metric['value']:.8g}" if metric['value'] is not None else 'unavailable: ' + metric['reason']))
        lines.extend(['', 'Standard 2SFCA by category (binary inclusive resident-to-facility time catchments)'])
        for category, result in services['sfca'].items():
            lines.append(f"  {category}: {result['status']}")
            if result['reason']:
                lines.append('    Unavailable: ' + result['reason'])
            else:
                lines.extend([f"    Catchment: {result['catchment_minutes']:g} minutes; unit: {result['raw_unit']}",
                    f"    Equal-node mean: {result['equal_node_mean']:.8g}; population/demand mean: {result['population_mean']:.8g}",
                    f"    Per 1,000 demand: equal-node {result['equal_node_mean_per_1000']:.8g}; population/demand {result['population_mean_per_1000']:.8g}",
                    f"    Zero-access demand share: {result['zero_access_population_share']:.8g}; zero-demand supply: {result['zero_demand_capacity']:.8g}"])
        lines.extend(['', 'Critical service closures: population access shortfall',
            '  ' + services['criticality']['primary_measure'],
            '  Positive losses do not cancel against competition-induced gains.',
            '  ' + services['criticality']['raw_changes'],
            '  ' + services['criticality']['screening_limitation']])
        for scope, groups in services['criticality']['rankings'].items():
            for category, ranking in groups.items():
                lines.append(f'  {category} {scope}:')
                if not ranking:
                    lines.append('    No defined evaluated loss baseline; inspect per-category availability and GIS service_null_reasons.')
                for row in ranking[:10]:
                    lines.append(f"    {row['id']}: access shortfall {row['access_shortfall']:.8g}")
        lines.extend(['', '  ' + services['limitations']])
    if summary.get("reliability_scenarios"):
        lines.append("  Additional p0 scenarios: " + ", ".join(summary["reliability_scenarios"]))
    return "\n".join(lines) + "\n"
