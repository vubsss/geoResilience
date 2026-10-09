# 05 — Single-link criticality + information centrality

**What to build:** experiment A from the design. Every candidate link and every analytic bridge gets an exact damage score when it is closed: efficiency drop, fraction of trips made impossible, and extra distance. The result is a ranked list of critical roads. Candidate nodes get exact information centrality. This ticket also builds the **affected-source recompute** machinery that 11 reuses.

**Blocked by:** 04

**Status:** ready-for-agent

## Behaviour

### Damage metrics for removing a link (directed analysis graph, N nodes, ordered pairs)
Let `d` be baseline distances and `d'` the distances after removal.

- `eff_drop = (E − E') / E`, using directed efficiency `E = (1/(N(N − 1))) Σ_{i≠j} 1/d_ij`.
- `disc_pair_frac` = (ordered pairs reachable before but not after) / (N(N − 1)).
- `extra_km_total` = Σ over pairs reachable before and after of (d'_ij − d_ij), in km.
- `affected_pairs` = the count of such pairs with d' > d.
- `extra_m_mean_affected` = extra distance per affected pair (NaN if none).
- **Weighted variants**, using node weights W (README conventions):
  - `disc_pair_frac` weighted by `W_i W_j` over `Σ_{i≠j} W_i W_j`.
  - `eff_drop` weighted the same way.

  Only the unweighted columns are written in this ticket, but the code takes W (12 wires it).

### Affected-source shortcut (exact)
Removing link (u→v, length L) can only change distance rows for sources i whose shortest paths use it, i.e. `d(i,u) + L == d(i,v)` (relative tolerance 1e-9). For two-way links, check both directions.

- Get `d(·,u)` and `d(·,v)` from two Dijkstra runs **on the reversed graph**.
- Recompute rows **only for affected sources**, with the chunked engine from 03 on the graph with the link removed.
- Baseline rows for those sources come from the cached float64 baseline matrix if `fits_in_memory`; otherwise they are recomputed alongside.
- Row-wise aggregates give exact global deltas: rows of unaffected sources don't change.

### Analytic bridges (from 04)
For a bridge with small side S, |S| ≤ `bridge_analytic_max_side`:
- `disc_pair_frac = 2·|S|·(N − |S|) / (N(N − 1))`, or the W-weighted equivalent.
- `eff_drop`: subtract the contributions of every pair crossing the cut. Compute Dijkstra from each node in S (forward and on the reversed graph); the pairs inside S and inside the rest don't change.
- `extra_km_total = 0` and `affected_pairs = 0` by definition (pairs are disconnected, not lengthened). Record `damage_method = analytic`.

### Information centrality (undirected analysis graph, Crucitti / Latora–Marchiori)
- `C^I_i = (E − E'_i) / E`, where `E'_i` is the efficiency of the graph with **all edges incident to i removed**, keeping N unchanged.
- Computed for **candidate nodes** (04) with full chunked all-pairs runs on the modified graph. The affected-source shortcut does not apply to nodes. Parallelise over nodes, or over chunks for large N.
- Non-candidates get NaN.
- Record in `summary.json.metrics.information`:
  - `coverage`: `all` if every node was computed, else `candidates`;
  - the candidate count.

### Outputs
- `edges` layer: `eff_drop`, `disc_pair_frac`, `extra_km_total`, `affected_pairs`, `extra_m_mean_affected`, `damage_method` (`full` | `analytic` | NaN if not evaluated), `crit_rank` (1 = most critical by `eff_drop`, ties broken by `disc_pair_frac`; NaN if not evaluated).
- `nodes` layer: `information`.
- `summary.json.metrics.criticality`: number of links evaluated by method, the top 20 by `eff_drop`, and the totals.
- `report.txt` "Critical links" section: the top 20 with `link_id`, `name`, `highway`, the first OSM way ID, `eff_drop`, `disc_pair_frac`, `extra_km_total` and `candidate_reason`.
- Figure: the top 50 critical links over the grey network.
- Progress logs: links done / total, plus an estimated time remaining.

## Acceptance criteria
- [ ] Layer 1:
  - Ring of 4 two-way unit links: removing one gives exactly the hand-computed `eff_drop` and `extra_km_total`, and `disc_pair_frac = 0`.
  - Path graph: removing the middle link gives `disc_pair_frac = 2·2·2/(4·3)` for N = 4.
  - Star: the hub's information centrality = 1. Removing all hub edges leaves E' = 0.
- [ ] Layer 2 on random spatial graphs (about 200 nodes, directed with some one-way links):
  - The affected-source shortcut matches a naive full recompute for every link, to within 1e-9.
  - Analytic-bridge damage matches the full recompute.
  - Information centrality matches a brute-force NetworkX efficiency recompute.
- [ ] Cached-baseline and recomputed-baseline paths give identical results.
- [ ] Outputs (columns, summary, report, figure) are present.
