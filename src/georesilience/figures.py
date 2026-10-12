"""Exported figures for degree, centralities, redundancy, and road criticality."""

import textwrap

import numpy as np

from .classification import CLASSIFICATION_FIGURES
from .cartography import finish_map, map_canvas

NODE_MEASURES = ("closeness", "straightness", "betweenness")
FIGURE_FILENAMES = ("degree_hist.png", *(f"{name}_ccdf.png" for name in NODE_MEASURES),
                    "edge_betweenness_map.png", "redundancy_map.png", "critical_links_map.png",
                    "robustness_scc.png", "robustness_efficiency.png", "connectivity_nodes_map.png",
                    "hansen_a_map.png", "vuln_map.png", "access_drop_map.png",
                    "scorecard.png", *CLASSIFICATION_FIGURES)
POPULATION_FIGURES = ("population_map.png",)


def write_scorecard_figure(scorecard, folder, *, run_name=None):
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    folder.mkdir(parents=True, exist_ok=True)
    rows = [row for row in scorecard["rows"] if row["key"] in scorecard["normalised_scores"]]
    if "composite" in scorecard:
        rows.append({"label": "User-weighted composite", "normalised_score": scorecard["composite"]["value"]})
    fig, ax = plt.subplots(figsize=(10, .6*len(rows)+2))
    values = [row["normalised_score"] for row in rows]
    maximum = max([1.] + [value for value in values if value is not None])
    for index, (row, value) in enumerate(zip(rows, values)):
        uniform = row.get("uniform_normalised_score") if row.get("basis") == "population" else None
        if value is not None:
            ax.barh(index, value, color="tab:blue", height=.55)
            ax.text(max(value, uniform or 0)+.015*maximum, index, f"{value:.4g}", va="center", fontsize=9)
        else:
            ax.text(.02*maximum, index, "not computed", va="center", color="grey", fontsize=9)
        if uniform is not None:
            ax.plot(uniform, index, "|", color="black", markersize=17, markeredgewidth=2)
    labels = {"robustness_attack": "Link attack robustness (AUC)", "robustness_failure": "Link failure robustness (AUC)",
              "redundancy_bridges": "Bridge redundancy (1 - bridge share)", "redundancy_detour": "Detour redundancy (1 / median)",
              "reliability": "Mutual-pair connectivity reliability", "accessibility": "Accessibility retained (1 - mean loss)"}
    ax.set_yticks(range(len(rows)), [labels.get(row.get("key"), row["label"]) for row in rows])
    ax.invert_yaxis()
    ax.set_xlim(0, maximum*1.15)
    ax.set_xlabel("Project-normalised score (1 = resilient under each metric)")
    name = str(run_name or "network run").encode("ascii", "backslashreplace").decode()
    ax.set_title("Resilience scorecard\n" + textwrap.fill(" ".join(name.split()), 64))
    if scorecard["population_present"]:
        ax.legend(handles=[Line2D([0], [0], color="tab:blue", linewidth=8, label="Selected score (population where defined)"),
                           Line2D([0], [0], color="black", marker="|", linestyle="none", markersize=14, label="Structural counterpart")],
                  loc="upper center", bbox_to_anchor=(.5, -.18), fontsize=8)
    caption = "Normalisations are project choices; read definitions and coverage in report.txt."
    if "composite" in scorecard:
        caption += "\nComposite weights chosen by the user, not part of the method."
    fig.text(.5, -.02, caption, ha="center", fontsize=8)
    ax.grid(axis="x", alpha=.2)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(folder / "scorecard.png", bbox_inches="tight", dpi=180, facecolor="white")
    plt.close(fig)


def write_zones_figure(zones, links, folder, *, run_name=None):
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    folder.mkdir(parents=True, exist_ok=True)
    fig, ax = _critical_map_canvas(zones)
    zones.plot(ax=ax, color="lightgrey", edgecolor="white", linewidth=.7)
    finite = zones[zones.rank_vulnerability.notna()].copy()
    if not finite.empty:
        finite["rank_vulnerability"] = finite.rank_vulnerability.astype(float)
        finite.plot(ax=ax, column="rank_vulnerability", cmap="YlOrRd_r", edgecolor="white", linewidth=.7,
                    vmin=1, vmax=max(2, float(finite.rank_vulnerability.max())),
                    legend=True, legend_kwds={"label": "Vulnerability rank (1 = most vulnerable)", "shrink": .65})
    if not links.empty:
        bounds = zones.total_bounds
        # Roads provide context without extending the map beyond the supplied zones.
        links.cx[bounds[0]:bounds[2], bounds[1]:bounds[3]].plot(ax=ax, color="#aaaaaa", linewidth=.35)
    if zones.rank_vulnerability.isna().any():
        ax.legend(handles=[Patch(facecolor="lightgrey", label="Vulnerability undefined")], loc="lower right")
    if finite.empty:
        ax.text(.5, .98, "No defined zone vulnerability", ha="center", va="top", transform=ax.transAxes)
    finish_map(fig, ax, zones, "Zone vulnerability: aggregation of network results",
               folder / "zones_vulnerability_map.png", run_name)


def _critical_map_canvas(frame):
    return map_canvas(frame)


def write_figures(nodes, links, folder, *, run_name=None):
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

    fig, ax = _critical_map_canvas(links if not links.empty else nodes)
    links.plot(ax=ax, color="lightgrey", linewidth=0.6)
    active = links[np.isfinite(links.edge_betweenness)].copy()
    if not active.empty:
        values = active.edge_betweenness.to_numpy()
        widths = 0.7 + 0.6 * np.searchsorted(np.quantile(values, [.25, .5, .75, .9]), values, side="right")
        active.plot(ax=ax, column="edge_betweenness", cmap="viridis", linewidth=widths,
                    vmin=0, vmax=float(values.max()) if values.max() > 0 else 1,
                    legend=True, legend_kwds={"label": "Edge betweenness", "shrink": 0.65})
    finish_map(fig, ax, nodes, "Physical links by edge betweenness", folder / "edge_betweenness_map.png", run_name)

    from matplotlib.lines import Line2D

    fig, ax = _critical_map_canvas(links if not links.empty else nodes)
    links.plot(ax=ax, color="lightgrey", linewidth=0.8)
    for column, color in (("is_bridge", "red"), ("is_directed_bridge", "orange")):
        selected = links[links[column]]
        if not selected.empty:
            selected.plot(ax=ax, color=color, linewidth=1.8)
    ax.legend(handles=[Line2D([0], [0], color=color, label=label, linewidth=2)
                       for color, label in (("red", "Bridge"), ("orange", "Directed bridge"),
                                            ("lightgrey", "Other link"))])
    finish_map(fig, ax, nodes, "Physical links by redundancy", folder / "redundancy_map.png", run_name)

    fig, ax = _critical_map_canvas(links if not links.empty else nodes)
    links.plot(ax=ax, color="lightgrey", linewidth=0.7)
    critical = links[links.crit_rank.notna() & (links.crit_rank <= 50)].copy()
    if not critical.empty:
        critical.plot(ax=ax, color="tab:red", linewidth=2, label="Top evaluated efficiency losses")
        ax.legend(loc="lower right", fontsize=8)
    finish_map(fig, ax, nodes, f"Top {len(critical)} structural efficiency-critical links", folder / "critical_links_map.png", run_name)


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


def write_connectivity_figure(nodes, links, folder, *, run_name=None):
    import matplotlib.pyplot as plt

    folder.mkdir(exist_ok=True)
    fig, ax = _critical_map_canvas(links if not links.empty else nodes)
    links.plot(ax=ax, color="lightgrey", linewidth=0.6)
    nodes.plot(ax=ax, column="p_connected", cmap="viridis", vmin=0, vmax=1, markersize=18,
               legend=True, legend_kwds={"label": "P(node in main SCC)", "shrink": .65})
    finish_map(fig, ax, nodes, "Main-component membership probability", folder / "connectivity_nodes_map.png", run_name)


def write_population_figure(nodes, links, folder, *, run_name=None):
    import matplotlib.pyplot as plt

    folder.mkdir(exist_ok=True)
    fig, ax = _critical_map_canvas(links if not links.empty else nodes)
    links.plot(ax=ax, color="lightgrey", linewidth=.7)
    nodes.plot(ax=ax, column="population", cmap="viridis", vmin=0,
               vmax=max(float(nodes.population.max()), 1e-12), markersize=25,
               legend=True, legend_kwds={"label": "Allocated population per node", "shrink": .65})
    finish_map(fig, ax, nodes, "WorldPop population assigned to analysis nodes", folder / "population_map.png", run_name)


def write_accessibility_figures(nodes, links, folder, *, run_name=None):
    import matplotlib.pyplot as plt

    folder.mkdir(exist_ok=True)
    for name, title, label in (("hansen_a", "Hansen structural accessibility", "Accessibility A"),
                                ("vuln", "Structural node vulnerability to evaluated single-link closures", "Relative accessibility drop")):
        fig, ax = _critical_map_canvas(links if not links.empty else nodes)
        links.plot(ax=ax, color="lightgrey", linewidth=.7)
        finite = nodes[np.isfinite(nodes[name])]
        missing = nodes[~np.isfinite(nodes[name])]
        if not finite.empty:
            finite.plot(ax=ax, column=name, cmap="viridis", markersize=25, vmin=0,
                        vmax=1 if name == "vuln" else max(float(finite[name].max()), 1e-12),
                        legend=True, legend_kwds={"label": label, "shrink": .65})
        if not missing.empty:
            missing.plot(ax=ax, color="grey", marker="x", markersize=25, label="Undefined")
            ax.legend()
        finish_map(fig, ax, nodes, title, folder / f"{name}_map.png", run_name)
    fig, ax = _critical_map_canvas(links if not links.empty else nodes)
    links.plot(ax=ax, color="lightgrey", linewidth=.7)
    selected = links[links.access_rank.notna() & (links.access_rank <= 50)]
    if not selected.empty:
        selected.plot(ax=ax, color="tab:red", linewidth=2, label="Top evaluated accessibility losses")
        ax.legend(loc="lower right", fontsize=8)
    finish_map(fig, ax, nodes, f"Top {len(selected)} structural accessibility-critical links", folder / "access_drop_map.png", run_name)
