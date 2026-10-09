# 11 — Hansen accessibility (uniform masses)

**What to build:** each node gets a Hansen accessibility score with exponential distance decay. Using Taylor et al.'s definitions, the run identifies **vulnerable nodes** (accessibility collapses when a nearby link is lost) and **critical links** (the network's total accessibility drops most when they close). With no population data, every node has mass 1, which gives purely structural accessibility. 12 swaps in population without code changes.

**Blocked by:** 05 (reuses the affected-source recompute and analytic-bridge machinery, and the candidate sets from 04)

**Status:** ready-for-agent

## Behaviour

### Config additions
```yaml
accessibility:
  half_distance_km: 2.0     # weight halves every 2 km
  cutoff_factor: 5          # truncate at R = cutoff_factor × half_distance (weight 2^-5 ≈ 3%)
  k: 1                      # 1 or 2 links removed per node test
  all_links: false          # evaluate every link (see cost note)
```

### Definition (directed analysis graph, distance only, no speeds)
- `β = ln 2 / (half_distance_km × 1000)` per metre.
- `R = cutoff_factor × half_distance`.
- `A_i = Σ_{j≠i, d_ij ≤ R} W_j · exp(−β · d_ij)`, using outbound distances d_ij from i. The self term is excluded.
- The truncation at R is **part of the definition**, so the local recomputation is exact.
- Baseline: truncated Dijkstra (`limit=R`) from every node, via the chunked engine (03).

### Critical links
For every candidate link and every analytic bridge (04), and for every link when `all_links: true`:
- Affected sources: the nodes i with `d(i,u) ≤ R` **and** the link on a shortest path (`d(i,u) + L == d(i,v)`, either direction). These come from reversed truncated Dijkstra runs from u and v.
- Recompute `A_i'` for the affected sources only (truncated, with the link removed).
- Analytic bridges with small side S:
  - nodes outside S lose the contributions of S;
  - nodes in S lose everything outside S.

  Both are computed from truncated Dijkstra runs from S (forward and reversed).
- `access_drop = (Σ_i A_i − Σ_i A_i') / Σ_i A_i`.
- `access_rank`: 1 = largest drop.
- Each evaluated removal gives per-node relative drops `(A_i − A_i')/A_i`. Keep, **for each node**, its 3 largest drops and the links that caused them. Use a streaming top-3 per node, not a dense matrix.

### Vulnerable nodes
- `k = 1`: `vuln = max` relative drop over all evaluated links, and `vuln_link_id` is the link that caused it.
- `k = 2`: additionally, for each node, remove each pair from its top-3 links together (3 pairs) and recompute `A_i` for that node only (one truncated Dijkstra per pair). `vuln_k2` is the max.
- Nodes with `A_i = 0` (nothing within R): `vuln` = NaN, flagged `isolated_in_R`.
- **Scope note** (report and docs): node vulnerability is the max over *evaluated* links, i.e. the candidate set by default. It is exact for all links only when `all_links: true`.
- **Cost note** (docs): with `all_links: true`, the cost grows with the number of nodes within R. At a 2 km half-distance (R = 10 km), a whole-city run is Ada-only. At ≤ 1 km it is laptop-feasible overnight.

### Outputs
- `nodes` layer: `hansen_a`, `vuln`, `vuln_link_id`, `vuln_k2` (if k = 2), `isolated_in_R`.
- `edges` layer: `access_drop`, `access_rank`.
- `summary.json.metrics.accessibility`:
  - β, R, half-distance;
  - Σ A, mean A;
  - `vuln` mean and p90;
  - links evaluated;
  - the top 20 links by `access_drop`;
  - the top 20 nodes by `vuln`.
- `report.txt` "Accessibility" section with those values. State that the masses are uniform ("structural accessibility"); 12 changes this line.
- Figures: a map of `hansen_a` and a map of `vuln` (nodes), plus the top 50 `access_drop` links.

## Acceptance criteria
- [ ] Layer 1:
  - A two-node two-way link of 1 km with half-distance 1 km: `A = 0.5` for each node. Removing the link gives `A' = 0` and `vuln = 1`.
  - Nodes farther than R contribute 0.
- [ ] Layer 2 on random spatial graphs:
  - Affected-source recomputation matches a naive full truncated recompute for every link, to within 1e-9.
  - Analytic bridges match a full recompute.
  - `k = 2` matches brute force for sampled nodes.
- [ ] W is respected: a test with non-uniform W gives the hand-computed A.
- [ ] Outputs (columns, summary, report, figures) are present.
