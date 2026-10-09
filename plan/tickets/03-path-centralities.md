# 03 — Exact path-based centralities

**What to build:** every run outputs exact closeness, straightness, node betweenness and edge (link) betweenness, plus global efficiency. A city-sized graph (about 60k nodes) finishes in minutes on a laptop, and memory use stays within budget. This ticket also creates the **row-chunked shortest-path engine** that 04, 05, 06 and 11 reuse.

**Blocked by:** 01

**Status:** ready-for-agent

## Behaviour

### Definitions (Crucitti, Latora & Porta 2006)
All are computed on the **undirected analysis graph** with metric lengths (when `analysis.directed_centrality` is false; directed is a flag for later and must raise NotImplementedError for now). N is the node count, d is the shortest-path length, d^E is Euclidean distance between projected node coordinates.

- Closeness: `C^C_i = (N − 1) / Σ_{j≠i} d_ij`.
- Straightness: `C^S_i = (1/(N − 1)) · Σ_{j≠i} d^E_ij / d_ij`.
- Node betweenness:
  - `C^B_i = (1/((N − 1)(N − 2))) · Σ_{j≠k≠i} n_jk(i)/n_jk` over **ordered** pairs.
  - For an undirected graph this equals NetworkX `betweenness_centrality(normalized=True, weight="length")`, and that is the cross-check.
- Edge betweenness:
  - Fraction of **unordered** node pairs whose shortest paths use the edge: raw Brandes edge score / (N(N − 1)/2).
  - Each undirected edge's score goes to the link that supplied its minimum length. Parallel longer links get 0. Self-loops get NaN.
- Global efficiency: `E = (1/(N(N − 1))) · Σ_{i≠j} 1/d_ij` (unreachable pairs contribute 0).

### Engine: row-chunked all-pairs
- A reusable capability: given a CSR graph, a list of sources and a **reducer** (a function from a distance block (rows = chunk sources) to per-row or aggregate results), it runs `scipy.sparse.csgraph.dijkstra(…, indices=chunk)` chunk by chunk and in parallel (joblib processes). The distance matrix is never stored.
- Chunk rows = `floor(budget_bytes / (N × 8 × 3 × n_jobs))`, at least 1, where budget comes from `analysis.max_memory_gb`. The 8 is bytes per float64; the 3 covers the distance block, the Euclidean block and a temporary.
- This ticket's reducer computes closeness, straightness and efficiency contributions from the same block. The Euclidean block is computed per chunk from the node coordinate arrays.
- Optional `limit` (cutoff distance) and `directed` parameters. 11 and 05 need them.
- A helper `fits_in_memory(N, dtype)` reports whether a full N×N matrix fits in the budget. 05 uses it to cache a baseline.

### Betweenness
- Use **networkit** `Betweenness(G, normalized=False, computeEdgeCentrality=True)` on a weighted networkit graph built from the undirected analysis graph, with threads = `n_jobs`. Normalise as defined above.
- Keep a mapping between networkit edge IDs and links.

### Outputs
- `nodes` layer: `closeness`, `straightness`, `betweenness`.
- `edges` layer: `edge_betweenness`.
- `summary.json.metrics`:
  - `global_efficiency`;
  - for each of the three node measures and for edge betweenness: mean, median, p90, max;
  - runtime in seconds for each stage.
- `report.txt`: a "Centralities" section with those statistics and the **top 20 links by edge betweenness**: `link_id`, `name`, `highway`, the first OSM way ID, `edge_betweenness`.
- Figures:
  - cumulative distribution (log-y) of each node measure;
  - a map of links coloured by edge betweenness (grey base, viridis, linewidth by quantile).

## Acceptance criteria
- [ ] **Layer 1 (known answers):**
  - Path graph of 5 nodes with collinear coordinates: straightness = 1 for all nodes.
  - Star with hub + 4 leaves: hub betweenness = 1 (normalised); leaves = 0.
  - 3×3 unit grid: closeness of the centre = 8/12.
  - A two-node graph has efficiency 1/length.
- [ ] **Layer 2 (cross-check):** on 5 random spatial graphs of about 200 nodes, the following match to within 1e-9:
  - closeness and node betweenness vs NetworkX (`closeness_centrality(distance="length")`; `betweenness_centrality(weight="length", normalized=True)`);
  - edge betweenness vs `edge_betweenness_centrality(weight="length", normalized=False)` / (N(N − 1)/2);
  - efficiency vs a brute-force Floyd–Warshall.
- [ ] Results are identical (to within 1e-12) for `n_jobs` = 1 and 4, and for a forced tiny memory budget (many chunks) vs a large one.
- [ ] Benchmark test (`@pytest.mark.slow`): a synthetic 60k-node perturbed grid (as in the design benchmark) finishes all of 03 in under 10 minutes with 8 jobs, and peak RSS stays under budget + 1 GB.
- [ ] GPKG columns, summary keys, report section and figures are present.
