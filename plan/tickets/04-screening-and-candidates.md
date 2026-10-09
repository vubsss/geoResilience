# 04 — Screening and candidate sets

**What to build:** every link gets a cheap redundancy screen: whether it is a bridge, how many nodes it cuts off, and its detour ratio. Every node gets an articulation-point flag. The run then produces the **candidate sets** of links and nodes that the expensive recomputations (05, 11) work on. On its own, this ticket already answers "which roads have no alternative".

**Blocked by:** 02, 03

**Status:** ready-for-agent

## Behaviour

### Config additions
```yaml
criticality:
  k_betweenness: 250        # top non-bridge links by edge betweenness
  k_detour: 250             # top non-bridge links by detour ratio
  k_nodes: 300              # top nodes by node betweenness (information-centrality candidates)
  exact_info_max_nodes: 5000  # graphs this small: every node is a candidate
  bridge_analytic_max_side: 2000
  all: false                # true: every non-self-loop link and every node is a candidate (Ada)
```

### Bridges (undirected sense)
- Computed on the undirected **link multigraph**, where every non-self-loop link is one undirected edge and parallel links are kept.
- A link is a bridge iff it is a bridge of the simple graph **and** has no parallel link. Use `networkx.bridges` on the simple graph, then drop pairs with multiplicity > 1.
- Side sizes: contract 2-edge-connected components into the **bridge tree**, with node weight = number of graph nodes. One rooted DFS gives the subtree weights. For each bridge, `cut_side_nodes` = the smaller side's node count, and `cut_side_frac` = cut_side_nodes / N.
- Articulation points: `networkx.articulation_points` on the simple undirected graph. Store `is_articulation`, and `artic_max_cut` = the largest number of nodes separated from the main part by removing the node. Compute it from the block-cut tree, or from the bridge-tree-like DFS on biconnected components. Any exact method is acceptable.

### Detour ratio (directed)
- For every non-self-loop link (u, v, length L) on the **directed analysis graph** with the link removed:
  - `detour_ratio = d'(u→v) / L`;
  - for two-way links, the **max** over both directions.
- If no alternative path exists, the value is `inf`. This also catches "directed bridges": links whose removal breaks reachability only because of one-way streets. Set `is_directed_bridge = true` when the link is not an undirected bridge but the detour is `inf`.
- Use a bidirectional Dijkstra with the link's edges masked: NetworkX `bidirectional_dijkstra` on a filtered view, parallelised over links with joblib. The search is local, so this is fast enough (about 90k links × a few ms).

### Candidate sets
- **Analytic bridges:** undirected bridges with `cut_side_nodes ≤ bridge_analytic_max_side`. 05 and 11 handle these analytically, with no full recompute.
- **Candidate links (full recompute):**
  - the top `k_betweenness` non-bridge links by `edge_betweenness`,
  - ∪ the top `k_detour` non-bridge links by `detour_ratio` (`inf` first, ties broken by `edge_betweenness`),
  - ∪ every directed bridge,
  - ∪ undirected bridges with `cut_side_nodes > bridge_analytic_max_side`.
- **Candidate nodes:**
  - all nodes if N ≤ `exact_info_max_nodes` or `all: true`;
  - otherwise the top `k_nodes` by `betweenness`, ∪ the articulation points with the 50 largest `artic_max_cut`.
- `all: true` makes every non-self-loop non-analytic-bridge link a candidate link.
- Store `candidate_reason` per link: a `;`-joined subset of `betweenness`, `detour`, `directed_bridge`, `large_bridge`, `analytic_bridge`, or empty.

### Outputs
- `edges` layer: `is_bridge`, `cut_side_nodes`, `cut_side_frac`, `detour_ratio` (inf written as NaN plus `detour_none = true`), `is_directed_bridge`, `candidate_reason`.
- `nodes` layer: `is_articulation`, `artic_max_cut`, `is_info_candidate`.
- `summary.json.metrics.redundancy`:
  - `bridge_frac` (bridges / non-self-loop links);
  - `bridge_length_frac`;
  - `detour_ratio` median, p90 and p99 over finite values;
  - `directed_bridge_count`;
  - `articulation_frac`;
  - candidate-set sizes by reason.
- `report.txt` "Redundancy" section:
  - those numbers;
  - the top 20 bridges by `cut_side_nodes`;
  - the top 20 non-bridges by detour ratio.

  Each row shows `link_id`, `name`, `highway` and the first OSM way ID.
- Figure: a map with bridges in red, directed bridges in orange and the rest in grey.

## Acceptance criteria
- [ ] Layer 1:
  - In a tree, every link is a bridge, and `cut_side_nodes` matches the hand-computed subtree sizes.
  - In a ring of 6 two-way links of length 1, every detour ratio is 5, and there are no bridges.
  - Two parallel links between A and B: neither is a bridge.
  - A ring where one segment is one-way: its reverse-direction partner breaks reachability, so the expected link is flagged as a directed bridge.
- [ ] Layer 2: on random spatial graphs:
  - `cut_side_nodes` matches brute force (remove each bridge, count components);
  - `detour_ratio` matches NetworkX `dijkstra_path_length` on a copy without the link.
- [ ] Candidate-set construction is deterministic, and the sizes match the config arithmetic on a fixture.
- [ ] Outputs (columns, summary, report, figure) are present.
