"""Figures for retained local measures and the shared targeted attack curve."""

from pathlib import Path

import numpy as np

FIGURE_FILENAMES = ("node_betweenness.png", "edge_betweenness.png", "hansen_accessibility.png",
                    "information_centrality.png", "attack_curve.png", "reliability.png")

SERVICE_FIGURE_FILENAMES = ("service_weight.png", "node_importance.png", "school_sfca.png", "hospital_sfca.png",
    "school_criticality.png", "hospital_criticality.png")


def write_figures(nodes, edges, attack, summary, folder):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for frame, column, name in ((nodes, "betweenness", "node_betweenness.png"),
            (edges, "edge_betweenness", "edge_betweenness.png"),
            (nodes, "hansen_accessibility", "hansen_accessibility.png"),
            (nodes, "information_centrality", "information_centrality.png")):
        fig, ax = plt.subplots(figsize=(7, 6))
        values = frame[column].astype(float)
        if np.isfinite(values).any():
            frame.assign(**{column: values}).plot(column=column, ax=ax, legend=True,
                cmap="viridis", missing_kwds={"color": "lightgrey"})
        else:
            frame.plot(ax=ax, color="lightgrey")
            ax.text(.5, .05, "No defined/evaluated values", transform=ax.transAxes, ha="center")
        ax.set_title(column.replace("_", " ").title())
        ax.set_axis_off()
        fig.tight_layout()
        fig.savefig(folder / name, dpi=140)
        plt.close(fig)
    fig, ax = plt.subplots(figsize=(7, 4))
    x = [row["fraction_removed"] for row in attack.curve]
    ax.plot(x, [row["node_share"] for row in attack.curve], label="Node share")
    if attack.curve[0]["population_share"] is not None:
        ax.plot(x, [row["population_share"] for row in attack.curve], label="Population in same component")
    for field, label in (('service_share', 'Service points in same component'),
                         ('node_importance_share', 'Combined node importance in same component')):
        if field in attack.curve[0] and attack.curve[0][field] is not None:
            ax.plot(x, [row[field] for row in attack.curve], label=label)
    ax.set(xlabel="Fraction of physical links removed", ylabel="Largest SCC share", ylim=(0, 1.05))
    ax.legend()
    fig.tight_layout()
    fig.savefig(folder / "attack_curve.png", dpi=140)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(7, 4))
    for offset, group in enumerate(("unweighted", "population_weighted")):
        for index, name in enumerate(("connectivity_reliability", "travel_time_reliability")):
            metric = summary[group][name]
            if metric["value"] is not None:
                value = metric["value"]
                ax.bar(index + offset * .3, value, width=.28, label=group if index == 0 else None)
                ax.errorbar(index + offset * .3, value, yerr=[[value - metric["ci_low"]],
                    [metric["ci_high"] - value]], color="black", capsize=3)
    ax.set(xticks=[.15, 1.15], xticklabels=["Mutual connectivity", "Travel time"], ylim=(0, 1.05), ylabel="Reliability")
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend()
    fig.tight_layout()
    fig.savefig(folder / "reliability.png", dpi=140)
    plt.close(fig)

    if summary.get('services'):
        _write_service_figures(nodes, summary['services'], folder)


def _write_service_figures(nodes, services, folder):
    import textwrap
    import matplotlib.pyplot as plt
    maps = [('service_weight', 'service_weight.png', 'Service points (category-weighted counts)'),
        ('node_importance', 'node_importance.png', 'Node importance (population + service shares)')]
    for category in ('school', 'hospital'):
        unit = services['sfca'][category]['display_unit'] or 'unavailable supply unit'
        maps.extend([(f'{category}_sfca_per_1000', f'{category}_sfca.png', f'{category.title()} 2SFCA ({unit})'),
            (f'{category}_access_shortfall', f'{category}_criticality.png', f'{category.title()} access shortfall (fraction)')])
    for column, filename, title in maps:
        fig, ax = plt.subplots(figsize=(7,6))
        values = nodes[column].astype(float)
        if np.isfinite(values).any():
            # Explicit bounds keep constant fields consistent with the colourbar.
            maximum = 1. if column.endswith('_access_shortfall') else max(float(values.max()), 1e-12)
            nodes.assign(**{column: values}).plot(column=column, ax=ax, legend=True, cmap='viridis',
                vmin=0, vmax=maximum, missing_kwds={'color': 'lightgrey'})
        else:
            nodes.plot(ax=ax, color='lightgrey')
            ax.text(.5, .05, 'Unavailable or not evaluated', transform=ax.transAxes, ha='center')
        ax.set_title(textwrap.fill(title, width=62))
        ax.set_axis_off()
        fig.tight_layout()
        fig.savefig(folder / filename, dpi=140)
        plt.close(fig)
