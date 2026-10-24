"""Figures for retained local measures and the shared targeted attack curve."""

from pathlib import Path

import numpy as np

FIGURE_FILENAMES = ("node_betweenness.png", "edge_betweenness.png", "hansen_accessibility.png",
                    "information_centrality.png", "attack_curve.png", "reliability.png")


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
