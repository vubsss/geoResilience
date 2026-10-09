# 06 — Attack vs failure curves

**What to build:** experiment B from the design (after Albert, Jeong & Barabási). The run removes links (headline) and nodes (classification evidence), either by adaptive targeted attack or at random. It outputs robustness curves and their areas (AUC), so a user can see how fast the network falls apart and compare attack with failure.

**Blocked by:** 03

**Status:** ready-for-agent

## Behaviour

### Config additions
```yaml
robustness:
  removal: [links, nodes]   # either or both
  steps: 50
  f_max: 0.20               # max fraction of links (or nodes) removed
  adaptive: true            # recompute betweenness after every step
  node_attack_metric: betweenness   # or degree (Albert's original)
  failure_runs: 10
  efficiency_sources: 500   # sampled sources for the efficiency estimate
```

### Procedure (directed analysis graph)
- Each step removes `Δ = round(f_max/steps × total)` elements: links (non-self-loop) or nodes.
- **Attack, links:**
  - Before each step, compute **exact** edge betweenness on the *current* directed graph with networkit, in parallel with all threads (about 15–30 s at 60k nodes).
  - Remove the top Δ active links. A link's score is the max of its directed edges.
  - With `adaptive: false`, rank once from the step-0 values.
- **Attack, nodes:** the same, using node betweenness, or degree on the undirected graph when `node_attack_metric: degree`. Removing a node removes all its links.
- **Failure:** a random permutation of the elements, removed in Δ-sized steps.
  - `failure_runs` permutations from spawned seeds.
  - Report the mean and the 5–95% band per step.
- **Tracked per step**, with fractions over the **original** N:
  - `S_scc`: largest strongly connected component size / N;
  - `S_wcc`: largest weakly connected component size / N;
  - `E_rel = Ê(step) / Ê(0)`.

  `Ê` is the efficiency estimated from a **fixed** random sample of `efficiency_sources` original nodes (seeded): mean over sampled sources s, and over all j ≠ s, of 1/d_sj, with removed nodes contributing 0. Sampled sources that get removed stay in the denominator and contribute 0.
- **AUC** for each curve (S_scc and E_rel): `(1/f_max) ∫₀^{f_max} curve df` by the trapezoid rule, so it lies in [0, 1] and 1 means no damage.

### Outputs
- A tidy table `robustness_curves.csv` in the output folder, with columns `element` (links | nodes), `mode` (attack | failure), `run` (attack = 0), `step`, `f`, `S_scc`, `S_wcc`, `E_rel`.
- `summary.json.metrics.robustness`, per element:
  - `auc_attack_S`, `auc_attack_E`, `auc_failure_S` (mean), `auc_failure_E` (mean);
  - `f_half_attack`: the first f where S_scc < 0.5, else null;
  - the parameters used.
  - `links` is flagged as the **headline**.
- `report.txt` "Robustness" section: the AUC table with links first and labelled headline. One plain-language line: "Targeted removal of X% of links reduces the largest connected component to Y%."
- Figures: S_scc and E_rel vs f, attack vs failure (failure as a mean with a band), one panel per element.

### Runtime note
Expected cost on a 60k-node graph, adaptive, both elements: about 50 steps × (betweenness + sampled efficiency) ≈ 1 h on a 22-core laptop. Log progress with an estimated time remaining.

## Acceptance criteria
- [ ] Layer 1:
  - Star graph, node attack by degree: the hub goes first, and S_scc drops to 1/N after step 1.
  - Ring: link failure and link attack give the same S_scc at f where 1 link is removed (the ring stays connected).
- [ ] Layer 2: on random spatial graphs with `efficiency_sources` ≥ N, `E_rel` equals exact efficiency ratios from NetworkX at every step.
- [ ] Determinism: same seed → identical curves; different `n_jobs` → identical curves.
- [ ] `adaptive: false` gives the static ranking; a test checks that the step-2 removal set differs between adaptive and static on a fixture where it should.
- [ ] Outputs (CSV, summary, report, figures) are present.
