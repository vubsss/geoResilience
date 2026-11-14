# Old Hyderabad and Gachibowli: traffic pilot results

Run date: 13 November 2026. Baseline repository commit: `9f3febd`.
Experiment: `results/traffic_comparison/experiment.json` (includes the pilot script hash).

The subsequent [full Tier 1/2 metric recalculation](metrics_comparison.md) includes
time accessibility, centrality, redundancy, reliability and both composite/attack
protocols. This document reports the original traffic-assignment experiment.

The later [traffic audit and reassignment study](traffic_audit.md) resolves
order-dependent simplified-road tags and adds fresh traffic assignment after
road failures. Use it for the updated simulation and service comparison.

## Finding

With the same resident-based trip rate, gravity method, fallback rules and traffic
assignment settings, **Old Hyderabad has greater modelled congestion** in the
base, low-demand, high-demand, lower-capacity, coarser-zone and uniform-capacity
cases. These are synthetic scenarios, not measured Hyderabad traffic.

The equal-total-demand control gives a different congestion ordering. Therefore
the study supports a conditional traffic comparison, not the claim that Old
Hyderabad's network is intrinsically worse under every load. Structural
redundancy and operational congestion can also rank areas differently without
either metric being incorrect.

## Base case

| Quantity | Gachibowli | Old Hyderabad |
| --- | ---: | ---: |
| Retained road nodes | 593 | 3,265 |
| Directed non-loop arcs | 1,305 | 8,435 |
| Allocated residents, archived 2020 raster | 58,489 | 200,473 |
| Synthetic demand, PCU/hour | 5,849 | 20,047 |
| Occupied 500 m population zones | 19 | 49 |
| Demand-weighted free-flow trip time, minutes | 3.256 | 3.675 |
| Demand-weighted congested trip time, minutes | 3.285 | 4.411 |
| Additional delay per trip, seconds | 1.71 | 44.17 |
| Travel-time index, congested / free-flow | 1.009 | 1.200 |
| Increase above free-flow trip time | 0.88% | 20.03% |
| Directed arc length with V/C > 1 | 0.04% | 3.27% |

Old Hyderabad's loaded graph has 8,437 arcs including two self-loop arcs. The solver
excludes self-loops, leaving the 8,435 traffic arcs listed above.

Trip times are OD-demand-weighted averages. The travel-time index compares the
same area's OD pattern under free-flow and congested costs. Arc-length percentage
counts directed arcs, not unique physical-road kilometres. Raw system travel time
is exported but should not be used alone to rank areas with different demand.

## Every scenario, including the counterexample

| Case | Gachibowli delay, seconds/trip | Old Hyderabad delay, seconds/trip | Gachibowli time index | Old Hyderabad time index |
| --- | ---: | ---: | ---: | ---: |
| Base: 0.1 PCU/person/hour | 1.71 | 44.17 | 1.009 | 1.200 |
| Low demand: 0.05 PCU/person/hour | 0.11 | 6.47 | 1.001 | 1.029 |
| High demand: 0.2 PCU/person/hour | 23.72 | 161.63 | 1.121 | 1.733 |
| Lower capacity: 500 PCU/hour/lane | 23.72 | 161.63 | 1.121 | 1.733 |
| Coarser zones: 750 m | 5.14 | 65.99 | 1.028 | 1.293 |
| Uniform capacity: 1,000 PCU/hour/arc | 29.50 | 44.91 | 1.151 | 1.204 |
| Equal demand: 10,000 PCU/hour per area | 13.03 | 6.43 | 1.067 | 1.029 |

High demand and lower capacity produce the same travel costs here: doubling all
OD rates or halving all capacities gives the same volume/capacity ratios in this
static BPR model. They are not independent evidence of robustness.

The equal-demand control retains each area's population-based spatial OD shares;
it controls total traffic volume, not trip lengths, destinations or geography.
Old Hyderabad's mean congested trip time is still longer (3.782 versus 3.473
minutes), but its additional delay and time index are lower. Say which outcome
is being compared rather than calling one area universally better or worse.

The uniform-capacity control reduces the base delay gap substantially. Missing
lane data and the assumed capacity assignment therefore materially affect the
comparison. Do not explain the base result as measured proof of narrower roads.

## What was done

1. Extracted supplied archives into an isolated data directory without changing
   their contents or executing bundled scripts.
2. Used the current network loader with consolidation disabled, then verified
   exact cleaned node identities and coordinates against the archived population
   GeoPackage. Population totals matched the archived allocated counts.
3. Formed projected 500 m population cells and selected a population-weighted
   representative existing road node in each occupied cell. Repeated with 750 m.
4. Used the existing doubly constrained gravity adapter. Population supplies both
   origin and destination margins; this is a resident-to-resident scenario, not
   measured commuter OD. The effective hourly trip rate already bundles modal,
   occupancy and PCU assumptions. It is not multiplied by those factors again.
5. Retained maxspeed tags and applied one shared assumed road-class fallback
   table (see the script and manifest). Gravity uses free-flow costs and fixed
   decay 0.08/minute. No observed-speed calibration was performed.
6. Applied the existing lanes/width capacity inference with common defaults:
   1,000 PCU/hour/lane, one fallback lane/direction, 3.5 m assumed lane width.
   Tested lower and uniform capacities. No Old-Hyderabad-specific penalty was used.
7. Ran static single-class user equilibrium with BPR alpha 0.15, beta 4,
   relative-gap target 0.001 and at most 600 iterations. All declared cases ran
   for both areas, regardless of the resulting ordering.
8. Exported per-directed-arc congestion costs, flows, capacities, OD costs, GIS,
   accounting diagnostics, source hashes and comparison figures.

## What is still assumed or missing

| Issue | Evidence / effect |
| --- | --- |
| Population coverage differs | Gachibowli has 14.67% unallocated population; Old Hyderabad has 0%. Their traffic demand is calculated from allocated residents. |
| Retained road coverage differs | Earlier SCC cleaning dropped 34.74% of Gachibowli road length versus 1.76% for Old Hyderabad. Buffered boundaries and external access need investigation. |
| Capacity data is sparse | Gachibowli has 127 lane-tagged and 2 width-tagged non-loop arcs; Old Hyderabad has 19 lane-tagged arcs and no width-tagged arcs. Most capacities are assumptions. |
| Speeds are partly imputed | Retained physical-road maxspeed-tag coverage is about 29.4% and 8.6%, respectively. Tags are speed limits, not observed average speeds. |
| Demand is resident-only | No workplace, commercial, tourist, freight, school or through-trip demand was estimated. This can especially distort employment-centre comparisons. |
| Within-zone demand | Generated demand is entirely interzonal. Intrazonal trips are not estimated or recovered from a survey. |
| Representative-node effects | Anchoring a whole zone at one node concentrates loading. Different zoning changes delay; 500/750 m is only an initial sensitivity check. |
| Static congestion model | No signal timings, spillback, queues, illegal parking, road condition or mixed-traffic vehicle classes. |
| Limited calibration | Trip rates, decay, speeds, lane capacity and BPR coefficients have not been fitted to local observations. |
| Map overlap | Opposite directed arcs can overlap visually. Inspect the arc CSV/GIS for both directions; a colour map is not a substitute for the numerical comparison. |

Both original study boxes are approximately 3 km on a side, but their retained
road networks and allocated populations are different. Equal boxes do not solve
boundary truncation or establish equal travel demand.

Next evidence to collect: matched-period travel times and directional counts on
representative corridors in both areas; verified carriageway/lane information;
employment/visitor attraction evidence; and buffered network coverage. Apply the
same collection protocol to both areas. Use observations to calibrate and then
evaluate on separate observations, rather than choosing coefficients to match a
preferred conclusion. Decay and speed assumptions also need further sensitivity.

## Verification and relation to the existing project

- All 14 assignments converged to relative gap <= 0.001; maximum achieved gap
  was approximately 0.000986.
- Independent output audits checked positive capacities/times, OD demand totals,
  zone production/attraction margins and node flow conservation in all 14 runs.
  Maximum flow residual was below 3e-12 PCU/hour and margin error below 4e-9.
- Seven existing focused traffic tests passed, including analytical one-road and
  parallel-route answers, gravity balancing, input/export and closure checks.
  The previously known full-pipeline integration test was excluded from this
  focused run; this experiment does not resolve or certify that test.
- Plot outputs were rendered and visually inspected.
- No production modules, historical outputs or metric definitions changed.
  Previous distance-Hansen and graph robustness results remain separate. This
  pilot adds traffic evidence; it does not create an overall resilience score or
  rerun every metric from the old archives.
- The original full-region population GeoTIFF is absent from these archives. The
  pilot intentionally reuses verified exported node counts. A complete pipeline
  replay needs the original raster as well as a resolved integration test.

## Presentation wording

> Our earlier analysis assessed network structure and distance-based access.
> We then tested congestion using the same traffic model and per-resident demand
> assumptions for both areas. Old Hyderabad shows greater delay under those
> resident-based scenarios, despite its structural redundancy. An equal-total-
> demand control changes the congestion ordering, so traffic loading and spatial
> demand matter alongside road structure. These are scenario results that still
> require validation against local traffic observations.

Use the comparison chart and maps with the label **synthetic traffic simulation**.
Show the equal-demand control and the coverage limitations as part of the findings.

## Outputs and reproduction

- [Scenario comparison](../../results/traffic_comparison/scenario_comparison.png)
- [Base V/C maps](../../results/traffic_comparison/base_vc_maps.png)
- [All numerical results](../../results/traffic_comparison/comparison.csv)
- [Assumptions and provenance](../../results/traffic_comparison/experiment.json)
- [Runner and reproduction instructions](../../examples/traffic/README.md)

The result directory is ignored by the repository's existing rules. Inputs and
new runner/documentation have not been committed or pushed.

## Method references

- [AequilibraE assignment and convergence](https://www.aequilibrae.com/latest/python/traffic_assignment/traffic_assignment_insights.html):
  reference for equilibrium assignment and relative gap; not a source for our local coefficients.
- [OSMnx routing documentation](https://osmnx.readthedocs.io/en/stable/user-reference.html#module-osmnx.routing):
  reference for speed imputation and free-flow time calculation.
- [HMDA CTS overview](https://www.hmda.gov.in/cts/):
  transport-study context; does not validate these two areas' modelled values or
  establish a current measured ranking.
