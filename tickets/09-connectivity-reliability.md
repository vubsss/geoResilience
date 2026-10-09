# 09 — Connectivity reliability

**What to build:** Taylor et al.'s connectivity reliability, estimated by Monte Carlo from the link failure probabilities (08). Outputs:
- **network:** expected share of trips (ordered node pairs) still possible;
- **node:** probability each node stays in the main network;
- **link:** how much each link's failure matters;
- **OD pair:** probability for pairs the user chooses.

All values come with confidence intervals and are reproducible.

**Blocked by:** 08

**Status:** ready-for-agent

## Behaviour

### Config additions
```yaml
reliability:
  samples: 10000
  od_pairs_csv: null    # columns: label, origin_lon, origin_lat, dest_lon, dest_lat
  min_down_count: 30    # minimum failures needed to report a link's importance
```

### Monte Carlo (directed analysis graph)
For each sample s:
1. Each non-self-loop link fails independently with `p_fail` (primary p0). Remove all of the failed link's directed edges.
2. Strongly connected components: `scipy.sparse.csgraph.connected_components(connection='strong')`.
3. Record:
   - `pair_frac_s = Σ_c W_c² − Σ_i W_i²`, normalised by `(Σ W)² − Σ W_i²`, with W = 1 here. With unit weights this is `Σ_c n_c(n_c − 1) / (N(N − 1))`.
     - **Decision:** a pair counts as connected when i and j are in the same SCC (mutually reachable). This is conservative and exact per sample in O(m). Ordered one-way reachability is not counted.
   - `in_main_s(i)`: node i is in the largest SCC.
   - Per link: whether it was down, plus `pair_frac_s` (for the conditional estimates).
4. **OD pairs:**
   - Snap each origin and destination to the nearest graph node (KD-tree on projected coordinates). Warn if the snap distance is over 500 m.
   - Per sample, run one BFS reachability per distinct origin on the directed graph. This checks **true directed** i→j reachability.

### Estimates
- `conn_reliability` = mean of `pair_frac_s`, with a 95% CI of mean ± 1.96·sd/√samples.
- Node `p_connected` = mean of `in_main_s(i)`. The report gives the maximum Wilson 95% CI half-width across nodes.
- Link `rel_importance` (Birnbaum-style) = mean(`pair_frac` | link up) − mean(`pair_frac` | link down).
  - Reported only if the link was down in ≥ `min_down_count` samples; otherwise NaN.
  - `rel_down_count` is always stored.
- OD `p_od` = the fraction of samples where the destination was reachable, with a Wilson CI.
- **p0 sweep:** repeat the network-level estimate (only `conn_reliability` and its CI) for each sweep p0. Node and link outputs use the primary p0 only.
- **Do not** report P(whole network connected). The docs explain why: it is about 0 at city scale.

### Parallelism and reproducibility
- Samples are split into batches. Each batch gets a spawned child seed, assigned **by batch index**, so results don't depend on `n_jobs`.
- Accumulate sufficient statistics (sums, counts), not per-sample arrays, except for `pair_frac_s`, which is needed for the CI and the conditional means.

### Outputs
- `nodes` layer: `p_connected`.
- `edges` layer: `rel_importance`, `rel_down_count`.
- `od_reliability.csv` (when OD pairs are given): `label`, snapped node IDs, snap distances, `p_od`, `ci_low`, `ci_high`.
- `summary.json.reliability`:
  - `conn_reliability` + CI;
  - the sweep table {p0: value, CI};
  - node `p_connected` mean and p10;
  - samples, seed.
- `report.txt` "Connectivity reliability" section:
  - the network value with its CI;
  - the sweep table, plus one sentence on how much `conn_reliability` changes between the smallest and largest p0;
  - the 20 least reliable nodes;
  - the top 20 links by `rel_importance`;
  - the OD table.
- Figure: a map of nodes coloured by `p_connected`.

## Acceptance criteria
- [ ] Layer 1:
  - A two-node graph with one two-way link and p = 0.5: `conn_reliability` → 0.5 (within the CI), `p_connected` = 0.5·1 + 0.5·0.5 = 0.75 for each node (with a tie in the largest SCC, choose the component with the smallest min node id).
  - With p = 0, reliability = 1 and all importances are NaN (never down).
- [ ] Layer 2: on graphs with ≤ 15 links, an exact enumeration of all 2^m failure states gives exact `conn_reliability`. The MC estimate must fall within its 99% CI in ≥ 95 of 100 seeded repetitions; use a smaller sample count for test speed.
- [ ] OD reachability respects direction (a one-way fixture: p_od(A→B) ≠ p_od(B→A)).
- [ ] Same seed → identical outputs for `n_jobs` = 1 and 4.
- [ ] Outputs (columns, CSV, summary, report, figure) are present.
