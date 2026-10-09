# 14 — Scorecard and final report

**What to build:** every run ends with a **resilience scorecard**: a few headline numbers, each with a plain-language meaning and its source paper. There is also an optional composite score, computed only from weights the user supplies. `report.txt` becomes a finished, readable document, and the maps are clean enough to drop into a report.

**Blocked by:** 05, 06, 07, 09, 11

**Status:** ready-for-agent

## Behaviour

### Scorecard (always; uses `_pop` variants when population is present, and shows both)
| Dimension | Metric(s) | Source key | Normalised score (1 = resilient) |
|---|---|---|---|
| Structural robustness | Link attack AUC (S), link failure AUC (S) | 06 | the AUC itself |
| Redundancy | % of links that are bridges; median detour ratio | 04 | `1 − bridge_frac`; `1 / median_detour` |
| Connectivity reliability | Expected % of pairs (and population) still connected | 09 | the value itself |
| Accessibility vulnerability | Mean and p90 node accessibility loss | 11 | `1 − mean_vuln` |
| Network class | scale-free / exponential / inconclusive, with its basis | 07 | not scored |

- Each row in the report gives: the value, a one-sentence meaning (e.g. "if 20% of the most-used roads close, the largest connected part keeps X% of junctions"), and the citation (Albert 2000; Crucitti 2006; Taylor 2006).
- Metrics that weren't computed (stage skipped or disabled) appear as "not computed", together with the reason.

### Composite (only on request)
```yaml
composite:
  weights: null   # e.g. {robustness_attack: 0.3, robustness_failure: 0.1, redundancy_bridges: 0.1,
                  #       redundancy_detour: 0.1, reliability: 0.2, accessibility: 0.2}
```
- Valid keys: exactly the normalised scores in the table above.
- Weights are normalised to sum to 1. Unknown keys raise an error. A weight whose metric wasn't computed → error.
- Output: `composite_user_weighted` in the summary. The report labels it **"user-weighted composite — weights chosen by the user, not part of the method"** and prints the weights.
- **No default weights are shipped.** The docs explain why: the literature shows the choice of metric changes the ranking.

### Final report.txt structure (in order)
1. Header: run metadata.
2. **Scorecard** (first, so a reader sees the answer immediately).
3. Data and coverage warnings, collected from all stages:
   - p_fail proxy share;
   - unallocated population;
   - dropped components;
   - information coverage;
   - skipped stages.
4. Cleaning, Centralities, Network class, Redundancy, Critical links, Robustness, Failure probabilities, Connectivity reliability, Travel-time reliability, Accessibility, Population, Zones: each existing section, in pipeline order.
5. Method notes: a short paragraph per metric naming its definition and paper, plus the stated limitations (boundary effect, per-event p, WorldPop estimate, undirected centralities).

**Critical tables:** the top 20 critical links and the top 20 vulnerable nodes, showing `link_id`/`node_id`, the street name (for nodes: the names of incident links), `highway`, the first OSM way ID, and lat/lon of the midpoint or node, so the user can find it on a map.

### Maps (figures/)
- A consistent style across all maps:
  - base network in light grey;
  - metric layers on top;
  - one colormap family per metric type: sequential for magnitudes, red highlights for top-N;
  - a scale bar and a north arrow, plus a title giving the metric and the run name.
- `scorecard.png`: a simple horizontal bar chart of the normalised scores (no composite unless configured).

## Acceptance criteria
- [ ] A full run on a fixture produces a scorecard with every row filled. Disabling stages (e.g. no maxspeed, no population) shows "not computed" with a reason, and the run does not crash.
- [ ] Composite: the weighted mean of the normalised scores is checked by hand on a fixture. Unknown keys and missing metrics raise errors. Without weights, no composite key appears.
- [ ] `report.txt` sections appear in the specified order (a test checks the section headings), and every line is ≤ 100 characters and ASCII-only.
- [ ] Top tables include lat/lon in WGS84.
- [ ] Figures are generated with the shared style (smoke test: the files exist and are non-empty).
