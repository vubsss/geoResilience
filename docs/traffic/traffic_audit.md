# Traffic simulation audit and reassignment results

Both areas were simulated again. The same resident trip rate, fallback capacities, BPR parameters, failure model and predeclared service budgets were used. No area-specific penalty was introduced to force a ranking.

## Findings

1. The earlier experiment did assign traffic and use congested costs. The original per-arc BPR equations and node flow conservation pass, and the solver reproduces the saved results exactly when its saved inputs are frozen.
2. A real input-preparation defect was found: simplified roads can have multiple lane tags, and selecting the first list value makes capacity depend on list order. A rerun changed six Gachibowli capacities. The audited experiment now resolves these lists deterministically using a bottleneck minimum. Mixed speed/highway lists are also resolved deterministically with conservative shared rules. This is still an assumption, not measured capacity.
3. Reliability relative to an already-congested intact network measures additional disruption. It can be high even when ordinary traffic is slow. A separate free-flow-reference service measure is now reported without overwriting the original definition.
4. Failure states now receive a fresh traffic assignment. Unreachable demand remains in the original service denominator and is reported as unserved. Both reference metrics use the same event times and failures.

## Ordinary traffic, before road failures

| Metric | Gachibowli | Old Hyderabad |
| --- | ---: | ---: |
| Synthetic demand, PCU/hour | 5848.932085 | 20047.333502 |
| Mean congested trip time, minutes | 3.306424 | 4.411490 |
| Added delay per trip, seconds | 1.763486 | 44.166580 |
| Travel-time index | 1.008969 | 1.200281 |
| Time accessibility, six-minute half-life | 0.747292 | 0.602320 |
| Population-weighted time accessibility | 0.709795 | 0.610782 |
| All-pair service within 1.5 times free flow | 100.000% | 99.044% |
| Demand-weighted service within 1.5 times free flow | 100.000% | 98.401% |

The ordinary service rows contain no road-failure sampling. They measure the intact congested snapshot against the same type of free-flow budget in each area. They are not substitutes for the original failure-conditioned reliability.

## Road failures with traffic reassignment: primary 50% time allowance

| Metric | Gachibowli | Old Hyderabad |
| --- | ---: | ---: |
| Original disruption-relative reliability | 0.995476 | 0.999065 |
| Free-flow-reference service during failures | 0.995393 | 0.986017 |
| Mutual-pair connectivity reliability | 0.994927 | 0.999532 |
| Composite retaining original reference and weights | 0.594387 | 0.625113 |
| Alternative composite with free-flow-reference service | 0.594375 | 0.623155 |

The alternative composite changes the service question while retaining the coefficients. It must not be passed off as the original composite. Each area has 64 event samples; these are pilot estimates with a conservative 95% Hoeffding half-width of about 0.170. Printing six decimals does not establish that accuracy or statistical significance.

## All predeclared time-budget sensitivities

| Area | Allowed multiple of free-flow time | Failure-state service, uniform pairs | Original-reference composite | Alternative-reference composite |
| --- | ---: | ---: | ---: | ---: |
| gachibowli | 1.2 | 0.990871 | 0.593745 | 0.593697 |
| gachibowli | 1.5 | 0.995393 | 0.594387 | 0.594375 |
| gachibowli | 2.0 | 0.996768 | 0.594584 | 0.594581 |
| old-hyderabad | 1.2 | 0.618304 | 0.624690 | 0.567998 |
| old-hyderabad | 1.5 | 0.986017 | 0.625113 | 0.623155 |
| old-hyderabad | 2.0 | 0.999158 | 0.625175 | 0.625127 |

The primary factor 1.5 retains the project's previous 50% allowance. Factors 1.2 and 2.0 were declared before these results. Do not select a threshold solely because it produces a preferred ordering. None of these project thresholds is claimed as a measured local service standard.

## Why the composite can still favour Old Hyderabad

The original composite assigns 25% to attack robustness and 15% each to bridge, detour, accessibility, travel reliability and connectivity. Redundancy/attack/connectivity together receive 70%. A dense network can have high congestion while retaining many alternative routes under failures. A faster network can depend on a few bottlenecks. Ordinary traffic performance and robustness to failures are different properties.
Changing positive travel times does not change bridges or whether a pair is connected. A higher connectivity score for Old Hyderabad is not evidence that traffic was omitted. The original composite is not an objective ground-truth ranking of ordinary driving conditions.

## Validation and retained limitations

- Fresh assignments cover all 1,305 Gachibowli and 8,435 Old Hyderabad directed non-loop arcs. Saved arc files contain actual assigned volumes, capacities, V/C, free-flow and congested times.
- The arc-wise BPR residual is zero to stored precision. Node-flow residuals are below 3e-12 PCU/hour. An independent stricter 1e-4 solver-gap check also converged; its outputs are recorded separately.
- The audit confirms changed time betweenness for 131 nodes/158 roads in Gachibowli and 2,217 nodes/3,132 roads in Old Hyderabad. Accessibility, efficiency, detours and attack are explicitly calculated from congested costs in metrics/.
- The corrected tag-resolution rule is implemented in the isolated experiment. Production input parsing has not been silently changed; its first-list-value handling still needs coordinated integration with the demand/capacity owner.
- OD is resident-based, not measured travel demand. Missing job/visitor/through-trip flows, sparse lane data and boundary/population allocation losses remain. Most capacities are fallback assumptions.
- Static BPR does not represent queues, traffic signals, parking interference or observed daily variability. Simulation results remain scenarios until checked against matched travel times/counts from both areas.
- All events and convergence states are retained. Unconverged states would have produced missing-state bounds rather than being silently omitted; all headline values require complete convergence.

## Reproduction and evidence

Run examples/traffic/validate_traffic_service.py, then examples/traffic/summarize_traffic_validation.py --stage global and --stage report. The output root is results/traffic_validation_v2/. Earlier results are preserved.
Evidence: experiment.json; <area>/previous_assignment_audit.json; assignment_audit.json; resolved_tags.csv; strict_solver_check.json; events.csv; service_summary.json; fresh_assignment/<area>/base/traffic_arcs.csv; and metrics/<area>/<cost>/.
Comparison files: ordinary_traffic_comparison.csv and reassignment_comparison.csv. Population-weighted and demand-weighted results are exported alongside uniform-pair results.
The first audit attempt under results/traffic_validation/ stopped on the detected non-reproducibility. It is not a completed comparison and should not be used.

## Reference for the interpretation

[FHWA travel-time performance definitions](https://ops.fhwa.dot.gov/perf_measurement/ucr/documentation.htm) distinguish a free-flow-referenced travel-time index from reliability measures. The free-flow reference is useful for congestion performance, but does not make our project's synthetic failures, 1.5 threshold or local parameters empirically validated.
