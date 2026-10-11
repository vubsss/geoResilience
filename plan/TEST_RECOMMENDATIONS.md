# Additional testing recommendations

Recorded on 11 October 2026. This is a backlog of further validation for **each ticket**,
alongside the acceptance criteria in [tickets/](tickets/). Implementation/completion status
and evidence from tests already run remain in [TICKET_UPDATES.md](../TICKET_UPDATES.md).

These recommendations do not reopen completed tickets. Ticket 09 is completed for now at
your request; its additional experiments remain follow-up work. Ticket 10 is completed and
manually verified by you as of 11 October 2026, with verification evidence in the ticket log.
Ticket 11 is completed and manually verified by you as of 12 October 2026;
its completed checks and further recommendations are recorded below. Tickets 12–14 and 16
remain prospective; Ticket 15's implemented comparisons and remaining experiments are below.

Unchecked items are proposed follow-ups, not claims that the corresponding behavior is
currently untested. Checked items reference existing test evidence. Some recommendations overlap
existing checks but extend their graph families, sizes or parameter ranges. No new experiments
were run when creating this document or recording Ticket 10's manual completion. Record actual
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

## 10 — Travel-time reliability

Ticket 10 is completed and manually verified on 11 October 2026. It includes exact fast/slow
threshold tests, directed/parallel state enumeration,
speed-unit/inference/coverage checks, custom static/scenario time models, fixed-origin MC coverage,
worker/chunk reproducibility and a 200-node sparse bottleneck example. The broader follow-ups
below retain unchecked status; one tested setting does not establish coverage in every regime.
The existing evidence is **45 targeted tests passed** and **221 regression tests passed, 4 skipped**;
these are implementation-stage results, not new runs for this update. See
[tests/test_travel_time.py](../tests/test_travel_time.py) and the
[ticket log](../TICKET_UPDATES.md#current-ticket-10--travel-time-reliability).

- [x] Extend the fast/slow-route exact fixture across the threshold boundary, directed
  disconnections and OD endpoints snapped to the same node; define self-pair treatment explicitly.
- [x] Test mixed speed tags, supported units, missing data and user-table fallbacks. Check
  length-weighted speed coverage and the no-speed-data skip rule without inventing speeds.
- [ ] Extend existing exact small-graph comparisons to selected origin subsets, then vary origin
  counts (for example 2, 8, 24 and all nodes where possible) over predefined seeds on a fixed
  sparse network. Compare with all-origin values and separate origin-selection variability from
  the reported closure-sampling CI. Do not treat destinations within a draw as independent trials.
- [ ] Extend repeated-seed CI coverage checks to trees, cycles and directed bottlenecks at common
  and rare closure probabilities, for network, origin and OD intervals. Record unavailable or
  constant-score cases explicitly; a [1,1] normal interval does not exclude unseen rare failures.
- [ ] Compare histogram p50/p90/p99 and bin bounds with exact pooled ratios on small deterministic
  fixtures containing a large atom at one and a thin high-delay tail. Vary the tail mass around
  percentile cutoffs and exercise underflow/overflow; separate bin approximation from MC error.
- [ ] Run deterministic scenario-time providers with one/four workers and different chunk sizes.
  Include providers depending on failed-link IDs and global sample index, plus asymmetric edge
  times. Check identical results and baseline semantics; verify no mutable worker-local state or
  unseeded randomness changes costs according to execution order.
- [ ] Compare distance/speed and supplied-time models on a frozen real extract with independently
  justified signal/road-condition delays. Vary the selected origins over predefined seeds and
  record sensitivity to model, tau and origin count. Future congestion or time-dependent models
  need their own validation; the replaceable cost interface does not establish those models.
- [ ] Measure peak memory, temporary baseline disk use and runtime on a larger frozen network
  while varying origins, workers and budgets. Verify temporary-file cleanup after a controlled
  failure in a disposable test directory; do not infer city-scale performance from 200-node runs.

## 11 — Hansen accessibility

Completed and manually verified by you on 12 October 2026, using the plan's directed,
truncated exponential definition. Unchecked experiments below remain follow-up recommendations.
Software checks below establish this formula's implementation, not agreement with observed
human travel behaviour or equivalence to the AP3 expression.

- [x] Compare directed affected-source recomputation for every link with independent NetworkX
  full recomputation on five seeded nine-node spatial graphs with unequal destination masses;
  check uniform masses separately in known-answer fixtures. Check forward/reverse analytic
  bridge losses against full recomputation on paths,
  including one-way arcs, radius truncation and zero destination weights. Test exactly at,
  just inside and just outside R; the radius boundary is inclusive.
- [x] Independently check k=2 over the selected pairs on the same seeded graphs. A three-road
  parallel fixture exhausts all pairs and catches synergy between individually harmless
  closures. Check deterministic ties, missing results, JSON/layer/figure exports, memory-budget
  rejection and overwrite cleanup. Evidence: `tests/test_accessibility.py`.
- [x] Run candidate-only and all-link scenarios on the same seeded 100-node spatial graph;
  compare identical baseline A and nondecreasing all-link single-link vulnerability. Evidence:
  `data/ticket11-demo/manifest.json`, `results/ticket11-spatial-*/` and the Ticket 11 log.
- [ ] Quantify the gap between the top-three k=2 heuristic and a global exhaustive pair search
  on networks with more than three roads, including ties and pair synergy. All-link evaluation
  makes the single-link maximum exhaustive; it does not make the selected-pair search exhaustive.
- [ ] Vary half-distance and cutoff independently, recording rank sensitivity and runtime without
  treating one parameter choice as universally representative of accessibility.
- [ ] Repeat on larger frozen directed road extracts and several independent spatial seeds.
  Include multiple bottlenecks, unequal one-way distances and many equal-length alternatives;
  record peak memory and runtime versus R, worker count and candidate coverage. The 100-node
  demo does not validate the original plan's city-scale Ada/laptop cost assumptions.

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

## 15 — Crucitti comparison

- [x] Freeze city inputs, document provenance and settings, then run the predefined comparison
  without retuning thresholds or centres to obtain agreement. Preserve mismatches and abstentions.
  The four-city run on 11 October 2026 returned MISMATCH under both conventions; detailed
  results and substantial fixed-15-m consolidation warnings are recorded in TICKET_UPDATES.
- [x] Run the predefined 15 m versus zero-consolidation comparison on the identical frozen
  inputs, preserving centres, network filter, resources and fitting rules. All four cities
  completed with full information coverage. Match counts stayed unchanged (both MISMATCH),
  while Los Angeles/Richmond information verdicts changed. Independently verify both baseline
  efficiencies and three node removals per city on exported graphs using NetworkX Dijkstra.
- [x] Inspect the frozen sample windows and included highway/access/service tags, with maps,
  physical-length shares and QGIS layers. Audit merge-cluster sizes/displacements: buffer overlap
  is transitive, so a 15 m tolerance does not cap cluster diameter. Offline inspection checks
  preserve source files and reject mismatched settings/hashes and tampered inputs.
- [ ] Examine modest predefined shifts of sample windows separately from the primary experiment,
  to assess sensitivity to approximate historical sample locations. Georeference the original
  windows first. The companion paper explicitly labels Richmond, CA, despite an initial concern
  from Jacobs' Virginia index: do not replace the city on that evidence alone or conflate a
  window change with a consolidation sensitivity experiment.
- [ ] Predefine a street-centreline representation/filter and compare it separately on frozen
  inputs. Distinguish independent pedestrian streets from parallel sidewalks, crossings, parking
  aisles and private-access ways; a motor-vehicle-only filter is not automatically AP2's scope.
  New snapshots should retain footway/sidewalk subtype and mode-access tags, which the current
  GraphML lacks. Do not choose filters by their classification match count.
- [ ] Define spatial/topological quality checks for consolidation before classification, including
  cluster diameter, maximum junction displacement, unusually high degree and preservation of
  distinct crossings. Compare bounded or smaller junction merges against these checks; a buffer
  radius alone does not constrain transitive cluster extent. Keep this separate from filtering
  and window shifts, and preserve the original 15 m baseline.
- [x] Verify complete information-centrality coverage, the two separate match-count conditions
  and report logic using offline integration and mocked verdicts. Hand-check AP2 spatial efficiency
  and compare both information conventions against independent NetworkX recomputation, including
  disconnections, fixed N, metric scaling, worker/chunk changes and one-way component handling.
- [x] Check positive-body exponential versus AP2 Gaussian-shaped CCDF (Rayleigh) fits against
  closed-form likelihoods, separately from Ticket 07's half-normal model. Check input hashes,
  offline reuse, QGIS/CSV/JSON/report outputs, overwrite cleanup and absence of stale aggregate
  results after an interrupted analysis. All-city live findings are documented in TICKET_UPDATES.
- [x] Check geometry orientation through undirected conversion and consolidation, not only
  shortest-path arithmetic on the processed graph. Regression fixtures verify endpoint alignment,
  paired road records and a hand-computed 310 m total after a junction merge. Audit all four
  real outputs for aligned non-loop endpoints and reciprocal physical links. The geometry bug
  found during mismatch review was corrected and the original experiment rerun without retuning.
- [ ] Add small-sample/bootstrap goodness-of-fit diagnostics and tail-threshold sensitivity for
  observed city distributions. Existing likelihood/AIC evidence compares alternatives; it does
  not establish an absolute model fit. Keep density and CCDF exponents distinct.
- [x] Obtain the authors' published historical graphs and cross-check connectivity, coordinates,
  N/K and road-length statistics. The textbook's `cities.zip` release cites the original paper;
  all four validation cities match its counts and the companion paper's rounded length statistics.
  Preserve the archive and hashes; test repeated edge labels, parallel roads, corrupt tables,
  hand-calculated efficiencies, local-CRS exports and refusal to overwrite previous results.
- [x] Run the four published graphs unchanged with exact information for all 5,303 nodes.
  Both conventions give information 2/4 and betweenness 3/4: MISMATCH. Independently verify
  both efficiencies/three removals per city with NetworkX (maximum error 3.30e-15), planned-city
  betweenness (2.78e-17), all source coordinates/lengths and 18-city N/K inventory. Spatial
  information Ginis for Cairo/Richmond round to AP2's 0.23/0.19; exponents and fitting differences
  are documented in TICKET_UPDATES. Preserve modern OSM experiments as separate comparisons.
- [ ] On the published graphs, predefine support/offset and fitting-range diagnostics for
  cumulative curves, then add absolute goodness-of-fit/bootstrap checks. Current whole-positive-
  body exponential/half-normal fits fix location at zero; this differs from reconstructing AP2's
  curve-fitting procedure. Examine planned-city information and Richmond betweenness residuals
  without choosing model settings by their match counts. Gini/exponent agreement supports the
  numerical comparison but does not validate the classification rule or prove a distribution.
- [ ] Geographically register the original Jacobs/AP2 windows and recover curved road geometry
  if those original GIS/map resources become available. Published graph data now supply topology,
  coordinates and metric lengths, so digitisation is unnecessary for this graph comparison.
  Keep modern filter/component/boundary/consolidation sensitivity studies separate and do not
  interpret qualitative agreement as proof of a universal city classification.

## 16 — Ada runbook (prospective)

- [ ] Compare complete versus sharded/merged and interrupted/resumed runs on the same frozen input,
  including stochastic accumulators. Check missing, duplicate, corrupt and incompatible shards.
- [ ] Inject failures around checkpoint/output writes in temporary locations; verify restart
  consistency, config mismatch refusal and recovery/copy behavior without touching valuable data.
- [ ] Before a large run, exercise environment setup and a small scheduled job on the actual
  cluster. Measure memory/runtime, verify resource settings against the applicable policies and
  record results before publishing full-city estimates.
