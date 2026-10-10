"""Exported figures for degree, centralities, redundancy, and road criticality."""

import numpy as np

from .classification import CLASSIFICATION_FIGURES

NODE_MEASURES = ("closeness", "straightness", "betweenness")
FIGURE_FILENAMES = ("degree_hist.png", *(f"{name}_ccdf.png" for name in NODE_MEASURES),
                    "edge_betweenness_map.png", "redundancy_map.png", "critical_links_map.png",
                    "robustness_scc.png", "robustness_efficiency.png", *CLASSIFICATION_FIGURES)


def _critical_map_canvas(links):
    import matplotlib.pyplot as plt

    xmin, ymin, xmax, ymax = links.total_bounds
    width, height = max(xmax - xmin, 1), max(ymax - ymin, 1)
    size = ((8, max(2.5, 8 * height / width)) if width >= height
            else (max(2.5, 8 * width / height), 8))
    fig, ax = plt.subplots(figsize=size)
    # Automatic limits on a zero-height/width network at large UTM coordinates
    # can pad by kilometres and make the roads invisible.
    padding = max(width, height) * 0.08
    ax.set_xlim(xmin - padding, xmax + padding)
    ax.set_ylim(ymin - padding, ymax + padding)
    return fig, ax


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

    fig, ax = _critical_map_canvas(links)
    links.plot(ax=ax, color="lightgrey", linewidth=0.7)
    critical = links[links.crit_rank.notna() & (links.crit_rank <= 50)].copy()
    if not critical.empty:
        critical.plot(ax=ax, column="eff_drop", cmap="YlOrRd", linewidth=2,
                      vmin=0, vmax=max(float(critical.eff_drop.max()), 1e-12),
                      legend=True, legend_kwds={"label": "Relative efficiency drop", "shrink": 0.65})
    ax.set_title(f"Top {len(critical)} critical physical links")
    ax.set_axis_off()
    fig.savefig(folder / "critical_links_map.png", bbox_inches="tight", dpi=180)
    plt.close(fig)


def write_robustness_figures(result, folder):
    import matplotlib.pyplot as plt

    folder.mkdir(exist_ok=True)
    elements = [element for element in ("links", "nodes") if element in result.summary]
    for measure, filename, ylabel in (
        ("S_scc", "robustness_scc.png", "Largest strongly connected component / original N"),
        ("E_rel", "robustness_efficiency.png", "Efficiency / baseline efficiency"),
    ):
        fig, axes = plt.subplots(1, len(elements), figsize=(6 * len(elements), 4), squeeze=False)
        for ax, element in zip(axes[0], elements):
            attack = [row for row in result.rows if row["element"] == element and row["mode"] == "attack"]
            band = result.summary[element]["failure_band"]
            fraction = [row["f"] for row in attack]
            means = [np.nan if row[f"{measure}_mean"] is None else row[f"{measure}_mean"] for row in band]
            lower = [np.nan if row[f"{measure}_p05"] is None else row[f"{measure}_p05"] for row in band]
            upper = [np.nan if row[f"{measure}_p95"] is None else row[f"{measure}_p95"] for row in band]
            ax.plot(fraction, [row[measure] for row in attack], color="tab:red", label="Targeted attack")
            ax.plot(fraction, means, color="tab:blue", label="Random failure mean")
            ax.fill_between(fraction, lower, upper, color="tab:blue", alpha=0.2, label="Failure 5-95% band")
            if measure == "E_rel" and not np.isfinite(means).any():
                ax.text(0.5, 0.5, "Efficiency undefined: baseline is zero", ha="center", transform=ax.transAxes)
            ax.set(xlabel=f"Fraction of original {element} removed", ylabel=ylabel,
                   xlim=(0, result.summary["parameters"]["f_max"]), ylim=(0, 1.05),
                   title=f"{element.capitalize()}{' (headline)' if element == 'links' else ''}")
            ax.grid(alpha=0.25)
            ax.legend(fontsize="small")
        fig.tight_layout()
        fig.savefig(folder / filename, bbox_inches="tight", dpi=180)
        plt.close(fig)
