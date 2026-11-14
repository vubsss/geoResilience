# Full Tier 1/2 metric comparison with simulated traffic

This earlier fixed-cost experiment is preserved as a reference. The subsequent
[traffic audit](traffic_audit.md) documents a tag-order defect, deterministic
input preparation and fresh traffic reassignment during road-failure states.
Use that study for the updated traffic/service comparison.

Calculated 13 November 2026 from the base traffic case. All traffic values are synthetic.
The presentation PDF supplied by the user provides the historical comparison; the archive summaries provide its unrounded values.

With the original composite weights and mid-evaluation attack protocol, the new unweighted composite is 0.594247 for Gachibowli and 0.625160 for Old Hyderabad. This aggregate must be interpreted alongside delay, accessibility and its chosen weighting, rather than treated as a measured overall traffic ranking.

## New values in the previous presentation format

| Metric | Gachibowli | Old Hyderabad |
| --- | ---: | ---: |
| Bridge redundancy index | 0.746309 | 0.809469 |
| Median finite time detour | 6.111870 | 5.068129 |
| Detour redundancy index | 0.163616 | 0.197311 |
| Attack robustness: mid-evaluation protocol | 0.188978 | 0.335782 |
| Raw unit-opportunity Hansen mean | 442.487266 | 1966.196750 |
| Normalized time Hansen, 6-minute half-life | 0.747445 | 0.602389 |
| Travel-time reliability | 0.993511 | 0.999358 |
| Mutual-pair connectivity reliability | 0.995805 | 0.999568 |
| Composite: original weights and mid-evaluation attack | 0.594247 | 0.625160 |

These use the original directed, 20-batch attack protocol so that the attack definition remains consistent with mid-evaluation. The composite coefficients remain exactly the user-specified 25% attack plus 15% each for bridge, detour, Hansen, travel-time reliability and connectivity reliability.

## Population-weighted version

| Metric | Gachibowli | Old Hyderabad |
| --- | ---: | ---: |
| Bridge redundancy index | 0.746309 | 0.809469 |
| Median finite time detour | 6.111870 | 5.068129 |
| Detour redundancy index | 0.163616 | 0.197311 |
| Attack robustness: mid-evaluation protocol | 0.151359 | 0.278384 |
| Normalized time Hansen, 6-minute half-life | 0.710924 | 0.610890 |
| Travel-time reliability | 0.992902 | 0.998847 |
| Mutual-pair connectivity reliability | 0.992653 | 0.999249 |
| Composite: original weights and mid-evaluation attack | 0.578800 | 0.611961 |

Population counts are unchanged. Population weights apply to Hansen, efficiency/information, event-pair reliability and SCC population share. Bridge and detour remain road-topology/cost measures; inventing population weights for them would define different metrics.

## Matched free-flow to congestion comparison

| Area | Free-flow Hansen | Congested Hansen | Free-flow composite, mid protocol | Congested composite, mid protocol |
| --- | ---: | ---: | ---: | ---: |
| gachibowli | 0.748882 | 0.747445 | 0.595151 | 0.594247 |
| old-hyderabad | 0.645734 | 0.602389 | 0.638894 | 0.625160 |

This is the comparison that isolates congestion: identical roads, populations, speeds, demand scenario, accessibility half-life, attack protocol and event draws, with free-flow versus assigned congested costs. Comparing the old distance index directly against a new time index does not isolate congestion.

## Current pipeline attack protocol, reported separately

| Metric | Gachibowli | Old Hyderabad |
| --- | ---: | ---: |
| Attack normalized AUC | 0.134217 | 0.082319 |
| Attack raw AUC | 0.026843 | 0.016460 |
| Composite using current attack protocol | 0.580557 | 0.561794 |

The current pipeline removes one road and updates an undirected betweenness ranking after every removal; it reports raw AUC to the actual integer horizon. The mid-evaluation code used directed betweenness, updated in 20 batches, and normalized area to the requested 20% horizon. The comparison adapter exports both protocols. A raw AUC near 0.02 must not be inserted into a formula expecting a normalized 0-1 attack index.

Current-protocol distance/free-flow/congested baselines are all in metrics_comparison.csv. A ranking difference already present in the recomputed distance baseline cannot be attributed to traffic. The two attack protocols must not be mixed in one before/after claim.

## Historical checks

| Area | Archived distance Hansen | Replayed historical attack | Reconstructed old composite |
| --- | ---: | ---: | ---: |
| gachibowli | 0.591433 | 0.197828 | 0.573931 |
| old-hyderabad | 0.509697 | 0.358924 | 0.618581 |

Distance bridge shares, median detours and normalized Hansen reproduce the archives. Historical directed attack AUC also replays to floating-point precision after restoring the archived road IDs used to break ties. Reconstructed composites round to the slide values 0.5739 and 0.6186.

Historical reliability estimates are not an exact replay: the current simulator has different event-draw/link-order conventions, and evaluates all travel-time origins rather than the old 100-origin sample. Small old-versus-new connectivity changes are Monte Carlo/implementation differences, not effects of congestion. Connectivity is exactly identical in the paired new free-flow and congested runs.

## What changed in the calculations

- Physical road grouping, directions, parallel roads, populations and failure probabilities stay fixed. Asymmetric arc times must never split one physical road into two failure events.
- Routing cost is seconds in the new time variants. Betweenness, detours, efficiency, information centrality and Hansen are recomputed against those costs.
- Undirected node/edge betweenness retains the current pipeline convention: select the minimum-cost physical road per unordered node pair. For time costs, each road uses its mean directional time. Directed accessibility and reliability retain each individual arc time.
- Time detour uses alternative travel time divided by the original road time in that same direction, then takes the worst direction. It is not divided by physical metres.
- Distance Hansen uses the original 2 km half-distance. Time Hansen uses a common six-minute half-life and 30-minute cutoff, corresponding to 2 km at an assumed reference speed of 20 km/h. This is a declared scenario choice, not a fitted accessibility threshold. Three- and twelve-minute sensitivity is also exported.
- Efficiencies have units 1/metre or 1/second. Compare time efficiency before/after congestion; do not compare its raw magnitude against distance efficiency.
- Bridge share and the existence of an alternative cannot change when only positive travel costs change. Mutual connectivity reliability is identical across the paired free-flow/congested runs because the same physical failures are used.
- Travel-time reliability compares event times with 1.5 times the corresponding intact time. Baseline congestion can therefore leave this index unchanged or increase it slightly. It is not a direct measure of everyday congestion.
- Event probabilities retain the existing physical-length proxy: p0=0.01 per km under independent closures. Traffic alone does not provide new flood/link failure probabilities.
- Reliability uses 1,024 connectivity events, 512 travel-time events, seed 42 and all original origins/pairs. Population and unweighted views share the draws. The old travel-time calculation sampled 100 origins, so its six-decimal result need not replay under the current all-origin estimator.
- Every closure/removal uses fixed intact free-flow or assigned costs. Traffic demand is not reassigned after each event. These are fixed-cost resilience calculations, not full disruption-induced congestion simulations.

## Local metrics and evaluated coverage

Each area/cost folder contains node_metrics.csv and link_metrics.csv. Betweenness and Hansen are calculated for every node; edge betweenness, bridge flags and detours for every applicable physical road. Information centrality and single-removal consequences are exact on a declared common screening set, not on every possible removal. local_coverage.json records the IDs and selection method. Unevaluated values are blank with a reason, never zero.

The common set is the union of top-30 betweenness nodes/roads from all three cost views, plus the archived top-10 information nodes and access-drop roads. Results on these candidates must be labelled "highest among evaluated candidates", not claimed as proven global maxima. The historical node-information implementation was undirected; current directed information is reported with a matched directed baseline.

| Area | Evaluated node isolations per cost | Evaluated road removals per cost |
| --- | ---: | ---: |
| gachibowli | 51 | 53 |
| old-hyderabad | 57 | 68 |

### Other cost-dependent indices, congested case

| Metric | Gachibowli | Old Hyderabad |
| --- | ---: | ---: |
| Directed network efficiency, 1/second | 0.00995323 | 0.00524765 |
| Population-weighted efficiency, 1/second | 0.01157412 | 0.00509851 |
| Mean node betweenness | 0.03096736 | 0.01285814 |
| Maximum node betweenness | 0.30854141 | 0.29222420 |
| Mean physical-edge betweenness | 0.02590833 | 0.00987270 |
| Maximum physical-edge betweenness | 0.26748439 | 0.21074209 |

### Highest local values among the evaluated candidates

| Area | Node with highest information | Information value | Road with highest access drop | Access drop | Road with highest population access drop | Population access drop |
| --- | --- | ---: | --- | ---: | --- | ---: |
| gachibowli | 1318404779 | 0.132595 | Old Bombay Road (ID 372) | 0.179229 | Old Bombay Road (ID 372) | 0.269234 |
| old-hyderabad | 11539566601 | 0.020681 | High Court Road (ID 3560) | 0.010309 | High Court Road (ID 3560) | 0.022892 |

## Limitations and interpretation

The input coverage and demand/capacity limitations documented in docs/traffic/results.md still apply. Most capacities are fallback assumptions; resident-only OD omits jobs, visitors and through trips. Gachibowli has substantial clipped-road and unallocated-population losses. No measured traffic validation has been performed.

Monte Carlo intervals are exported in each reliability.json; six printed decimals describe the numerical estimate, not six-decimal empirical accuracy. The conservative 95% Hoeffding interval half-widths are about 0.0424 for connectivity and 0.0600 for travel-time reliability. Small differences near one are not established as statistically significant by these intervals.

The original composite is an aggregation preference, not ground truth. An area can have lower time accessibility and greater delay yet retain a higher composite because bridge/detour and attack scores receive substantial weight. Do not change weights or failure probabilities to force a preferred ordering.

## Outputs

- metrics_comparison.csv: all three costs, both population views, both attack/composite protocols.
- historical_comparison.csv: original unrounded values and reconstructed composite.
- previous_critical_roads.csv and previous_information_nodes.csv: new values on the same historical example roads/nodes, for all three costs.
- metrics_comparison.png: matched time-Hansen and composite plots.
- <area>/<cost>/node_metrics.csv and link_metrics.csv: detailed metric rows and coverage.
- <area>/<cost>/attack_curve.csv and legacy_attack_curve.csv: both attack definitions.
- <area>/<cost>/reliability.json: values, intervals and simulation settings (time modes).
- <area>/<cost>/baseline.json: redundancy, Hansen sensitivity, efficiency and centrality statistics.
- manifest_*.json and audit/: code/input hashes and settings.

Validation: 33 targeted metric/traffic tests passed. One previously known full-pipeline integration test was explicitly excluded; this experiment does not certify that test or a full raster-based CLI run. Physical identities, units, directional detours, current attack equivalence on a known graph, historical distance results and paired-connectivity invariance were checked.

Production code and presentation files were not edited. Reproduction commands are in examples/traffic/README.md.
