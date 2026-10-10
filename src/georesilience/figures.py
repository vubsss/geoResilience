"""Exported figures for degree, exact centralities, and redundancy."""

import numpy as np

NODE_MEASURES = ("closeness", "straightness", "betweenness")
FIGURE_FILENAMES = ("degree_hist.png", *(f"{name}_ccdf.png" for name in NODE_MEASURES),
                    "edge_betweenness_map.png", "redundancy_map.png")


def write_figures(nodes, links, folder):
    import matplotlib.pyplot as plt

    folder.mkdir(exist_ok=True)
    fig, ax = plt.subplots()
    degree = nodes.degree.to_numpy()
    ax.hist(degree, bins=range(int(degree.max(initial=0)) + 2), align="left")
    ax.set(xlabel="Degree", ylabel="Node count")
    fig.savefig(folder / "degree_hist.png", bbox_inches="tight", dpi=180)
    plt.close(fig)

    for name in NODE_MEASURES:
        values = nodes[name].to_numpy()
        values = values[np.isfinite(values)]
        fig, ax = plt.subplots()
        if values.size:
            x, counts = np.unique(values, return_counts=True)
            ccdf = (values.size - np.r_[0, np.cumsum(counts[:-1])]) / values.size
            ax.step(x, ccdf, where="pre", marker="o", markersize=3)
            ax.set_yscale("log")
            ax.set_ylim(0.5 / values.size, 1.05)
        units = " (1/metres)" if name == "closeness" else ""
        ax.set(xlabel=name.replace("_", " ").capitalize() + units,
               ylabel="Fraction of nodes with value >= x", title=f"{name.capitalize()} distribution")
        fig.savefig(folder / f"{name}_ccdf.png", bbox_inches="tight", dpi=180)
        plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 8))
    links.plot(ax=ax, color="lightgrey", linewidth=0.6)
    active = links[np.isfinite(links.edge_betweenness)].copy()
    if not active.empty:
        values = active.edge_betweenness.to_numpy()
        widths = 0.7 + 0.6 * np.searchsorted(np.quantile(values, [.25, .5, .75, .9]), values, side="right")
        active.plot(ax=ax, column="edge_betweenness", cmap="viridis", linewidth=widths,
                    vmin=0, vmax=float(values.max()) if values.max() > 0 else 1,
                    legend=True, legend_kwds={"label": "Edge betweenness", "shrink": 0.65})
    ax.set_title("Physical links by edge betweenness")
    ax.set_axis_off()
    fig.savefig(folder / "edge_betweenness_map.png", bbox_inches="tight", dpi=180)
    plt.close(fig)

    from matplotlib.lines import Line2D

    fig, ax = plt.subplots(figsize=(8, 8))
    links.plot(ax=ax, color="grey", linewidth=0.8)
    for column, color in (("is_bridge", "red"), ("is_directed_bridge", "orange")):
        selected = links[links[column]]
        if not selected.empty:
            selected.plot(ax=ax, color=color, linewidth=1.8)
    ax.legend(handles=[Line2D([0], [0], color=color, label=label, linewidth=2)
                       for color, label in (("red", "Bridge"), ("orange", "Directed bridge"),
                                            ("grey", "Other link"))])
    ax.set_title("Physical links by redundancy")
    ax.set_axis_off()
    fig.savefig(folder / "redundancy_map.png", bbox_inches="tight", dpi=180)
    plt.close(fig)
