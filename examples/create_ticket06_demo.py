"""Reproducible ER and Barabasi-Albert networks with QGIS input copies."""

import argparse
import json
from pathlib import Path

import networkx as nx
import numpy as np
import osmnx as ox


def create_examples(folder, n=500, seed=42):
    if n < 20:
        raise ValueError("use at least 20 nodes (the default is 500)")
    folder.mkdir(parents=True, exist_ok=True)
    er_seed, ba_seed, er_layout, ba_layout = np.random.SeedSequence(seed).spawn(4)
    rng = np.random.default_rng(er_seed)
    probability = 6 / (n - 1)
    # Resample rather than connecting components artificially: this is G(n,p)
    # conditioned on connectedness, with all requested nodes retained.
    for attempt in range(1, 1001):
        chosen_er_seed = int(rng.integers(0, 2**32))
        er = nx.fast_gnp_random_graph(n, probability, seed=chosen_er_seed)
        if nx.is_connected(er):
            break
    else:
        raise ValueError("could not sample a connected ER graph in 1000 attempts")
    chosen_ba_seed = int(np.random.default_rng(ba_seed).integers(0, 2**32))
    ba = nx.barabasi_albert_graph(n, 3, seed=chosen_ba_seed)
    manifest = {"seed": seed, "nodes_requested": n, "length_m": 1000,
                "description": "Synthetic topology models; schematic coordinates, not real roads.", "graphs": {}}
    drawn = []
    for name, simple, topology_seed, layout_seed, parameters in (
        ("er", er, chosen_er_seed, er_layout, {"model": "Erdos-Renyi G(n,p), conditioned connected",
                                             "p": probability, "sampling_attempts": attempt}),
        ("scale-free", ba, chosen_ba_seed, ba_layout, {"model": "Barabasi-Albert preferential attachment", "m": 3}),
    ):
        chosen_layout_seed = int(np.random.default_rng(layout_seed).integers(0, 2**32))
        positions = nx.spring_layout(simple, seed=chosen_layout_seed, iterations=100, scale=300)
        graph = nx.MultiDiGraph(crs="EPSG:32644", simplified=True, synthetic_model=parameters["model"])
        for node in sorted(simple):
            x, y = positions[node]
            graph.add_node(node, x=float(500000 + x), y=float(1900000 + y))
        for way, (u, v) in enumerate(sorted(tuple(sorted(edge)) for edge in simple.edges), start=1):
            for a, b in ((u, v), (v, u)):
                graph.add_edge(a, b, length=1000.0, osmid=way,
                               name=f"{name} link {way}", highway="residential")
        ox.save_graphml(graph, filepath=folder / f"{name}.graphml")
        nodes, edges = ox.graph_to_gdfs(graph)
        target = folder / f"{name}-input.gpkg"
        nodes.to_file(target, layer="nodes", driver="GPKG", engine="pyogrio")
        edges.to_file(target, layer="edges", driver="GPKG", engine="pyogrio")
        degree = [simple.degree[node] for node in simple]
        manifest["graphs"][name] = {**parameters, "topology_seed": topology_seed, "layout_seed": chosen_layout_seed,
                                    "node_count": len(simple), "link_count": simple.number_of_edges(),
                                    "mean_degree": float(np.mean(degree)), "max_degree": max(degree)}
        drawn.append((name, simple, positions, degree))
        print(f"{name}: {len(simple)} nodes, {simple.number_of_edges()} links, max degree {max(degree)}")
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 2, figsize=(12, 9))
    for column, (name, simple, positions, degree) in enumerate(drawn):
        nx.draw_networkx(simple, pos=positions, ax=axes[0, column], with_labels=False,
                         node_size=3 + 1.5 * np.array(degree), node_color=degree, cmap="viridis",
                         edge_color="grey", width=0.25)
        axes[0, column].set_title(f"{name}: {len(simple)} nodes (node size/colour = degree)")
        axes[0, column].set_axis_off()
        values, counts = np.unique(degree, return_counts=True)
        axes[1, column].plot(values, counts, "o-")
        axes[1, column].set(xlabel="Degree", ylabel="Node count", title="Degree distribution (finite sample)")
        if name == "scale-free":
            from matplotlib.ticker import FuncFormatter, LogLocator, NullFormatter

            axes[1, column].set_xscale("log")
            axes[1, column].set_yscale("log")
            axes[1, column].xaxis.set_major_locator(LogLocator(base=10, subs=(1, 3)))
            axes[1, column].xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}"))
            axes[1, column].xaxis.set_minor_formatter(NullFormatter())
        axes[1, column].grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(folder / "models.png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nodes", type=int, default=500)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=Path("data/ticket06-demo"))
    args = parser.parse_args()
    create_examples(args.out, args.nodes, args.seed)


if __name__ == "__main__":
    main()
