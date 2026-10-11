# Additional testing recommendations

Recorded on 11 October 2026. This is a backlog of further validation for **each ticket**,
alongside the acceptance criteria in [tickets/](tickets/). Implementation/completion status
and evidence from tests already run remain in [TICKET_UPDATES.md](../TICKET_UPDATES.md).

These recommendations do not reopen completed tickets. Ticket 09 is completed for now at
your request; its additional experiments remain follow-up work. Tickets 10–16 are prospective:
their recommendations should be reviewed when those tickets are implemented.

Unchecked items are proposed follow-ups, not claims that the corresponding behavior is
currently untested. Some overlap existing checks but extend their graph families, sizes or
parameter ranges. No new experiments were run when creating this document. Record actual
commands, configs, seeds, results and limitations before marking an item complete.

## How to use this backlog

- Start with small independent known-answer references, then broaden to multiple graph families
  and predefined seeds. Random graphs alone are insufficient when the same topology stays easy.
- Choose probabilities, sample sizes and comparisons before inspecting results. Retain
  inconclusive classifications and unsuccessful scientific comparisons.
- Separate software correctness, numerical/statistical behavior, performance and real-world
  validity. Passing one does not establish the others.
- Keep expensive, live-data and cluster experiments optional. Use frozen local inputs and record
  their provenance so results can be reproduced without downloading new data.
- For probabilistic intervals, examine repeated-run coverage and interval widths; one interval
  containing one exact answer is limited evidence. Individual intervals are not simultaneous
  guarantees for every node or road.

## 01 — Tracer bullet and outputs

- [ ] Run the CLI from a different working directory and with paths containing spaces. Check
  documented relative-path resolution, output overrides and resolved-config reuse.
- [ ] Compare shared values across report, JSON and GeoPackage, accounting for report rounding;
  distinguish null/not-computed values from genuine zeros.
- [ ] Exercise an interrupted output write in a temporary directory, then rerun with overwrite;
  check that incomplete or stale artifacts cannot be mistaken for a successful new run.

## 02 — Inputs and cleaning

- [ ] Freeze a small real OSM extract containing one-way roads, parallel roads, a bridge/underpass,
  access restrictions and small disconnected components. Independently check retained topology.
- [ ] Compare equivalent XML and GraphML inputs with their source/filter differences documented.
  Include a polygon in another CRS and check projected lengths and boundary metadata.
- [ ] Repeat a real sample with consolidation off/on and several predefined tolerances; record
  changes to node count, road length, retained components and downstream rankings.
- [ ] Compare clipped and buffered study areas to quantify boundary sensitivity.

## 03 — Path centralities

- [ ] Broaden independent shortest-path and centrality comparisons to sparse grids, trees,
  irregular spatial networks, tied shortest paths and unequal parallel-road lengths.
- [ ] Change chunk budgets and worker counts on the same medium input; compare values and measure
  peak memory. Run the existing opt-in large benchmark separately before claiming city-scale cost.
- [ ] Rescale all lengths by a known factor. Check each metric's expected units, including the
  documented efficiency convention, and distinguish invariant rankings from invariant values.

## 04 — Screening and candidates

- [ ] Compare every road's screening result against brute-force removal on small graphs with
  directed bottlenecks, parallel bypasses and equal-length alternatives.
- [ ] Test deterministic candidate membership under tied scores and increasing candidate limits;
  on one larger sample, quantify how many high-damage roads the default candidates capture.
- [ ] Include a road that is safe in the undirected projection but essential in one direction;
  verify the report keeps physical-bridge and directed-detour meanings distinct.

## 05 — Link criticality and information centrality

- [ ] Cross-check optimized/analytic damage against full recomputation on several sparse spatial
  seeds, including equal shortest-path alternatives and directed asymmetric roads.
- [ ] Compare default candidate rankings with exhaustive evaluation on a manageable real extract;
  report missed high-damage roads and candidate coverage rather than assuming completeness.
- [ ] Check fixed-denominator information centrality when isolating nodes and when a removal
  disconnects pairs; independently verify distance units and reachable-pair exclusions.

## 06 — Attack versus failure

- [ ] Extend the existing ER/scale-free examples with sparse grids, trees and spatial bottlenecks,
  using predefined seeds and comparable sizes/densities. Treat family differences as findings.
- [ ] Compare sampled-source efficiency against all-source efficiency as the source sample grows;
  measure random-failure variability across repeated seeds.
- [ ] Compare static and adaptive attack on the same input. Check removal counts, endpoints, AUC
  integration and retained denominators through severe fragmentation.

## 07 — Distribution classification

- [ ] Run the already discussed 1,000-node ER/BA follow-up with the same five seeds and fixed
  thresholds. Report conclusive coverage, agreements, disagreements and abstentions separately.
- [ ] Extend reference-distribution experiments across sample sizes and distribution mixtures,
  including nearly competing families. Track how often the rule abstains or selects each family.
- [ ] Check sensitivity to thin tails, selected xmin and information coverage; keep degree-family
  diagnostics separate from centrality-based labels and from city-formation interpretations.
- [ ] Use frozen real-road samples for external comparison; reserve the paper-pattern experiment
  for Ticket 15. Successful fits or synthetic family agreement do not establish that hypothesis.

## 08 — Failure probabilities

- [ ] Round-trip edited templates for a frozen real extract with shared/multiple way IDs and
  repeated street names. Match physical roads by stable identifiers, not names alone.
- [ ] Compare equal-share mixed-link calculations against inputs with known original segment
  lengths to quantify the approximation introduced by simplification.
- [ ] Vary CSV coverage while holding graph and supplied values fixed; independently check source
  percentages, effective length shares and warning boundaries.
- [ ] For real risk interpretation, compare supplied/proxy probabilities with independently
  justified event data. Synthetic randomized probabilities test arithmetic, not calibration.

## 09 — Connectivity reliability: priority follow-up

The existing small fixtures provide exact-answer checks. The three 200-node spatial scenarios
exercise coverage and integration, but are highly redundant: at the primary p0, proxy/mixed
observed network scores were always one. Their zero observed variance produces normal intervals
of [1,1]; this cannot exclude rare disconnections. Zero importance estimates in these runs also
provide no meaningful ranking among tied roads.

- [ ] **Sparse spatial bottleneck:** build two sparse spatial/grid regions joined by one road,
  plus a version with an alternative route. Use predefined per-road failure probabilities
  0.05, 0.20 and 0.50 and seeds 42–46. Examine network scores, node memberships, OD failures,
  importance intervals and count guards. Record the full probability assignment for each case.
  Expect a mixture of successful/failed connections and reduced bridge dependence with a bypass;
  do not require every noisy estimate or ranking to follow an exact ordering.
- [ ] **Broader interval coverage:** independently enumerate several graphs with at most 15 roads
  (tree, cycle, parallel routes, directed bottleneck) at common and rare failure probabilities.
  Repeat at least 100 predefined seeds per selected setting. Record empirical coverage and widths
  for network, node, OD and available importance intervals, including unavailable-state counts.
  Keep interval confidence level separate from the tolerance used to judge empirical coverage.
  The existing 100-seed check covers the network interval on one triangle, not every interval.
- [ ] **Convergence:** use the same graph/probabilities and stable sample prefixes at 1,000,
  10,000 and 50,000 samples. Compare against small-graph exact values; for larger graphs report
  stability across independent seeds. Investigate rare-event cases whose score stays constant;
  do not treat [1,1] as certainty or demand monotone error reduction in a single realization.
- [ ] **Real-road example:** use a frozen local extract of roughly 200–1,000 cleaned nodes with
  genuine directionality and several meaningful OD pairs. Record cleaning losses, snap distances,
  probability sources and reproducibility with different worker counts. Use explicit hypothetical
  failure scenarios unless calibrated probabilities are available.
- [ ] **Failure-model sensitivity:** document how an independent-road baseline differs from a
  plausible common-hazard scenario. Correlated failures require an explicit model extension;
  they cannot be tested by claiming the current independent sampler already supports them.

These experiments strengthen statistical and practical evidence. The implementation's current
test suite and documented assumptions support completion for now; calibrated real-world
reliability claims require additional evidence.

## 10 — Travel-time reliability (prospective)

- [ ] Extend the fast/slow-route exact fixture across the threshold boundary, directed
  disconnections and OD endpoints snapped to the same node; define self-pair treatment explicitly.
- [ ] Test mixed speed tags, supported units, missing data and user-table fallbacks. Check
  length-weighted speed coverage and the no-speed-data skip rule without inventing speeds.
- [ ] On a small graph, compare all-origin/all-state answers against sampled origins and closures;
  separately assess origin-sampling and failure-sampling uncertainty and percentile approximation.

## 11 — Hansen accessibility (prospective)

- [ ] Broaden full-recompute comparisons to directed spatial bottlenecks and nodes exactly at,
  just inside and just outside the truncation radius, with uniform and unequal destination masses.
- [ ] Compare candidate-only and all-link vulnerability on a manageable graph; state the scope of
  each maximum. For k=2, distinguish checking the selected top-three pairs from finding the global
  worst pair over all roads; quantify any gap on a small exhaustive example.
- [ ] Vary half-distance and cutoff independently, recording rank sensitivity and runtime without
  treating one parameter choice as universally representative of accessibility.

## 12 — Population weighting (prospective)

- [ ] Extend synthetic rasters to nodata, zero cells, boundary cells, differing CRSs and snap-limit
  ties. Check conservation: clipped positive population equals allocated plus unallocated totals.
- [ ] Check all-ones and unequal weights across accessibility, damage and exact-enumerated
  reliability; verify that uniform outputs remain available and unchanged.
- [ ] Test missing/corrupt cached downloads and recorded catalogue fixtures. Keep live acquisition
  separate and record dataset provenance. Distinguish weighted pair fractions from counts of people;
  test units before labeling any quantity as people disconnected.

## 13 — Zone aggregation (prospective)

- [ ] Include adjacent polygons, holes, multipolygons, boundary nodes, duplicate IDs and positive-area
  overlaps; establish deterministic boundary assignment without rejecting valid shared borders.
- [ ] Independently check zone sums, weighted means and zero-population/empty-zone handling.
  Account explicitly for unassigned nodes/roads when comparing zone totals with network totals.
- [ ] Add/remove/reproject zones and verify all network-level analysis values stay unchanged.
  Check that midpoint assignment can differ from geometric road-length apportionment.

## 14 — Scorecard and report (prospective)

- [ ] Cross-check headline/table values against JSON, CSV and GeoPackage with explicit rounding
  tolerances. Verify correct units and definitions, especially mutual pairs versus directed trips.
- [ ] Exercise disabled, missing, inconclusive and constant-score cases; preserve reasons and
  uncertainty limits. Verify no default composite appears and unavailable metrics cannot be weighted.
- [ ] Review maps and long-name/non-ASCII inputs manually as well as checking report order/width;
  verify coordinates, legends, scale bars and labels convey the computed quantity correctly.

## 15 — Crucitti comparison (prospective)

- [ ] Freeze city inputs, document provenance and settings, then run the predefined comparison
  without retuning thresholds or centres to obtain agreement. Preserve mismatches and abstentions.
- [ ] Examine modest predefined shifts of sample windows and consolidation settings separately
  from the primary experiment, to assess sensitivity to approximate historical sample locations.
- [ ] Verify complete information-centrality coverage, the two separate match-count conditions
  and report logic. Treat modern-data qualitative agreement as limited evidence, not historical
  numerical replication or proof of a universal city classification.

## 16 — Ada runbook (prospective)

- [ ] Compare complete versus sharded/merged and interrupted/resumed runs on the same frozen input,
  including stochastic accumulators. Check missing, duplicate, corrupt and incompatible shards.
- [ ] Inject failures around checkpoint/output writes in temporary locations; verify restart
  consistency, config mismatch refusal and recovery/copy behavior without touching valuable data.
- [ ] Before a large run, exercise environment setup and a small scheduled job on the actual
  cluster. Measure memory/runtime, verify resource settings against the applicable policies and
  record results before publishing full-city estimates.
