# Tier 4: simulated traffic, congested edge costs and disruption

Planning baseline: 4 November 2026; framework scope clarified 5 November 2026.
Status: initial assignment and population-derived demand/capacity are integrated with the current CLI; calibration and CTS class mapping remain planned.
Scope: reusable road-network testing framework; Hyderabad is the first case study.

## Objective

Add traffic-aware costs to the existing road-network framework. Generate reproducible traffic
scenarios from road attributes and synthetic or supplied OD demand, or ingest supplied directed
edge travel times. Use those costs to test intact-network accessibility and the effects of road
closures. Hyderabad provides one worked example, not a dependency of the framework.

Simulation is the main first-version workflow. It generates modelled edge volumes, speeds and
travel times; current link-level Hyderabad observations are not required to run it. Population,
trip rates, capacities and route choice are declared inputs or assumptions. Export them and vary
the uncertain ones in sensitivity runs. Observations can later calibrate or replace inputs.

The framework has one directed-edge cost contract and two input paths:

```text
road graph + zones + synthetic/supplied OD + capacity/VDF -> traffic assignment
                                                        -> simulated volume and edge time
supplied directed-edge times -----------------------------> edge time
                                                           |
                                                           v
                                      routing, accessibility, reliability
                                                           |
                              assignment + OD -> closure reassignment and delay impact
```

`congested_time_s` is the primary traffic-aware edge cost in both paths. Assignment also produces
volume and V/C. Supplied times alone support time-based routing and accessibility; they do not
imply a traffic volume or a new equilibrium after a closure. Keep delay, accessibility and
closure impact as separate outputs with their own units.

## What already exists

Tier 4 should extend existing interfaces rather than introduce a second road pipeline:

- `population.py` allocates WorldPop counts to cleaned network nodes when that demand input is used.
- `time_models.py` supplies positive directed-edge seconds independently of routing.
- `travel_time.py` already accepts a static cost snapshot and calculates directed journey-time
  reliability under physical-road failures.
- Physical `link_id` values group reciprocal arcs and define the unit of closure.
- Population-weighted criticality, connectivity and Hansen accessibility already establish the
  output and weighting conventions.

The existing `PreparedTimeModel.scenario_times` callback is not the traffic-assignment engine.
Running a full equilibrium assignment inside every Monte Carlo sample would be extremely costly
and awkward in worker processes. Tier 4 should calculate named assignment scenarios first, then
pass their static directed-edge seconds to existing routing analyses. Stochastic reassignment is
a later extension after targeted closures are practical.

Traffic-aware reliability reuses the current `PreparedTimeModel` interface. Traffic zones and
OD/capacity CSVs refer to node and directed-edge IDs in the cleaned input graph. The current CLI
can also aggregate Tier 2 node population into projected-coordinate grid zones and infer generic
directional capacity from OSM width/lanes tags; it does not yet map roads to calibrated CTS classes.
Future accessibility work can reuse the congested-time baseline when that analysis is enabled.

## Formula provenance and Hyderabad example

The formulas below are not all original to this project. Keep four provenance labels in code,
configuration and reports:

- `published_standard`: directly implements a published general method;
- `locally_calibrated`: functions or parameters reported from a named local study;
- `adapted`: a published method simplified or connected to the available inputs;
- `project_assumption`: introduced here and requiring sensitivity tests.

| Model element                                              | Provenance                                                                               | Tier 4 use                                                                                                              |
| ---------------------------------------------------------- | ---------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| BPR `t=t0*(1+alpha*(v/c)^beta)`                          | `published_standard`; Bureau of Public Roads (1964)                                    | Benchmark and sensitivity model. The common `alpha=0.15`, `beta=4` pair is illustrative, not Hyderabad calibration. |
| Conical volume-delay function                              | `published_standard`; Spiess (1990)                                                    | Supported by AequilibraE and adopted by the Hyderabad CTS after local calibration.                                      |
| Ten Hyderabad conical parameter/capacity classes           | `locally_calibrated`; HMDA HMA-2041 CTS, base year 2011, Tables 8-29 to 8-31           | Named Hyderabad case-study profile, followed by sensitivity runs.                                                       |
| Doubly constrained gravity balancing                       | `published_standard`; Wilson entropy/spatial-interaction family                        | General OD-matrix structure.                                                                                            |
| Frank-Wolfe user-equilibrium assignment                    | `published_standard`; Beckmann et al. (1956), Frank and Wolfe (1956)                   | First slice implements shortest-path assignment and line search; the code is ours.                                      |
| Population-to-population exponential gravity demand        | `adapted`; general gravity structure with WorldPop at both ends                        | Reproducible synthetic-demand scenario. It is not the HMDA model or an observed Hyderabad OD matrix.                    |
| Existing structural candidates plus top traffic indicators | `project_assumption`                                                                   | Screen expensive closure reassignments; validate exhaustively on a small area.                                          |
| Congested seconds as the GeoResilience edge cost           | `adapted`; standard assignment output connected to the existing replaceable time model | Primary Tier 4 routing weight.                                                                                          |

The main local source is HMDA's **Comprehensive Transportation Study for Hyderabad Metropolitan
Area (HMA), Long Term Strategy for the Transport Sector of HMA-2041**, with base-year 2011
modelling. It used a conventional four-stage model, 695 traffic-analysis zones, a 33,300-household
interview survey, roadside/cordon/screen-line surveys, population and employment,
purpose-specific trip generation/distribution/mode choice, and assigned-flow validation against
observed screen lines. Its coded road network was about 4,900 km.

The CTS is a useful case-study parameter source, not current ground truth. Its raw 695-zone OD
matrices, TAZ geometry and link-level count/speed database have not yet been found in a public
machine-readable download. The framework and Hyderabad simulation can run without them. If they
are later obtained, they can improve the case study; aggregate tables alone do not reproduce the
CTS model.

### Hyderabad CTS road profile

The CTS compared standard BPR, modified BPR, empirical and conical functions and reports that it
adopted calibrated conical functions. For a directed road arc, the Spiess form is:

```text
t(v) = t0 * (2 + sqrt(alpha^2 * (1 - v/c)^2 + beta^2)
                  - alpha * (1 - v/c) - beta)
```

The reported 2011 Hyderabad classes are:

| Total road configuration   | Operation | Capacity (PCU/h/lane) | Free-flow km/h | alpha | beta |
| -------------------------- | --------- | --------------------: | -------------: | ----: | ---: |
| 2-lane undivided           | two-way   |                 1,200 |             40 |  1.58 | 1.86 |
| 2-lane undivided           | one-way   |                 1,400 |             40 |  1.49 | 2.02 |
| 3-lane undivided           | one-way   |                 1,600 |             50 |  1.10 | 6.00 |
| 4-lane divided             | two-way   |                 1,600 |             60 |  1.26 | 2.92 |
| 4-lane undivided           | one-way   |                 1,800 |             60 |  2.07 | 1.47 |
| 4-lane undivided           | two-way   |                 1,600 |             60 |  1.90 | 1.56 |
| 4-lane flyover, divided    | two-way   |                 1,800 |             60 |  1.24 | 3.07 |
| 6-lane divided             | two-way   |                 1,800 |             80 |  1.24 | 3.12 |
| 8-lane divided             | two-way   |                 2,000 |             80 |  1.98 | 1.51 |
| 8-lane bypass/ORR, divided | two-way   |                 2,200 |            100 |  4.00 | 1.17 |

These values are taken from the CTS tables, not made by this project. Mapping incomplete OSM
`lanes`, divided-carriageway and one-way tags into the classes is our implementation work. Total
lanes on a two-way undivided road must be split directionally before multiplying by per-lane
capacity. Flyover/ORR identification needs explicit rules and manual audit. Retain the reported
CTS class and every fallback decision in output.

The CTS profile should be a named `hmda_cts_2011` option, never a universal default. Compare it
with Indo-HCM or user-supplied capacities because Hyderabad's network and fleet have changed
substantially since 2011.

## Model definition

### 1. Analysis period and units

Model one declared period, initially a one-hour weekday peak. Use:

- OD demand: passenger-car-equivalent trips per modelled hour (`pcu/h`);
- directed capacity: passenger-car equivalents per hour (`pcu/h`);
- edge time: seconds;
- edge volume: passenger-car equivalents per hour (`pcu/h`).

The period name and duration are metadata, not implied by the input. Daily WorldPop population
does not become hourly traffic without explicit trip-rate, motorized-mode-share and peak-hour
parameters.

### 2. Traffic zones and centroids

Do not construct an all-network-node dense OD matrix. Aggregate the chosen demand input into a
small, deterministic traffic-zone system, then attach one centroid per nonempty zone to eligible
road nodes. For WorldPop scenarios, start with a regular projected grid because it needs no new
spatial-index dependency; allow an input polygon layer later. Preserve the production/attraction
mass assigned to every zone and report empty, unallocated and disconnected zones.

Centroid connectors are assignment-only arcs. They must have stable IDs, a stated connector cost
and effectively unconstrained capacity. They are never exported as physical roads, closure
candidates or centrality edges. Compare at least two grid sizes to expose the modifiable areal
unit and centroid-connector effects.

If the study boundary cuts across commuting corridors, add explicit external/cordon zones or a
through-trip scenario. A population-only OD matrix inside a small pilot omits trips entering or
crossing it; report this boundary assumption and vary external demand.

### 3. OD demand: generate or supply

**Implemented population mode (prototype):** all Tier 2 resident counts are conserved while nodes
are aggregated into up to 100 projected-coordinate grid cells. Each nonempty cell is represented by
the populated road node nearest its population-weighted centroid. The currently implemented OD
weighting is:

```text
w_ij = P_i P_j exp(-lambda * free_flow_minutes_ij), i != j
q_ij = sum(P) * effective_pcu_trips_per_person_hour * w_ij / sum(w_kl)
```

This deterministic normalization allocates a single total demand across reachable pairs; it is not
the doubly constrained balancing model described below. The exact population-product formula is a
project-specific gravity adaptation, not directly copied from a research paper or Hyderabad CTS.
The defaults (`0.1 PCU/person/hour`, `lambda=0.08/minute`) are illustrative assumptions, not local
measurements. The effective rate bundles trip generation, motorized share and PCU conversion and
must be calibrated or varied before volumes are interpreted as realistic. The zone limit and all
these parameters are recorded in outputs.

**Planned alternative:**

Use a doubly constrained gravity model to generate one reproducible simulation scenario:

```text
q_ij = A_i O_i B_j D_j exp(-lambda * t0_ij), i != j
```

`O_i` is the zone's peak-hour trip production and `D_j` its attraction. This is a standard
entropy/gravity-family structure; it was not invented here. Initially both may be derived from
population, but that substitution is our adaptation and the output must say
**population-to-population synthetic demand**. It is not the Hyderabad CTS model and does not
represent work trips specifically because WorldPop does not locate jobs, schools or trip purposes.
Balance the matrix by iterative proportional fitting so row and column targets are met. Exclude
unreachable OD pairs and report their demand before renormalization rather than silently moving it.

For a population-driven, single-class scenario, convert residents to PCU/h explicitly:

```text
O_i = population_i * trips_per_person_day * road_mode_share * peak_hour_share
      / mean_road_vehicle_occupancy * mean_pcu_per_vehicle
```

This is a project accounting choice, not a Hyderabad coefficient or a formula copied from a
paper. `peak_hour_share` is the fraction of daily trips in the modelled hour; occupancy converts
person trips to vehicles and the PCU factor converts vehicles to passenger-car equivalents.
Supply or vary every factor. Balance total attraction to total production. The synthetic OD
matrix is then distributed using the published gravity family above.

Required explicit parameters are those conversion factors, gravity decay `lambda` (or a target
mean trip time used to fit it), the intrazonal-trip rule and zone resolution. Also accept a sparse
user OD CSV so another synthetic scenario or an observed/external demand estimate can use the
same assignment code.

The default CLI must not invent authoritative local values. Ship a clearly labelled
`illustrative` profile for the frozen demonstration and require a profile or OD file for a real
run.

The CLI currently supplies explicit illustrative defaults so the framework can run without an OD
file; they are not authoritative local values. For a richer Hyderabad scenario, add destination attraction from employment, enrolled students
and land use. The CTS used Population, Earners, Resident Students, Students Enrolled and Total
Employment and calibrated separate Work, Education, Other and Non-Home-Based purposes. It tested
eight deterrence functions and selected a purpose-specific Tanner alternative instead of one
exponential decay. Its coefficients require matching variable definitions, time period, impedance
units and zones; until then, they are documented priors or comparison scenarios.

### 4. Free-flow time and directional capacity

The current prototype uses the OSM `lanes` tag first, otherwise infers lane-equivalents from
`width` using the configured 3.5 m lane-width assumption. Two-way totals are split evenly;
one-way tags apply their lane count to the directed arc. If both tags are absent it assumes one
lane per direction. Each effective lane is assigned the illustrative default of 1000 PCU/h. These
are generic project assumptions, not the CTS class-specific calibrated capacities. The traffic
summary records directed-arc coverage for tagged lanes, width-only inference and fallbacks; the
arc CSV retains each edge's input width/lanes and derived capacity source.

Reuse the existing time-model interface for `t0`, with
`t0_s = 3.6 * length_m / free_flow_speed_kph`. Record whether speed came from an OSM tag, the
selected road-class profile or an explicit override. The Hyderabad CTS scenario uses its
class-specific free-flow speeds; other scenarios may select different profiles. Infer directional
capacity from:

```text
capacity_e = usable_directional_lanes_e * capacity_per_lane(highway_class)
```

The next capacity step is to parse `lanes:forward` and `lanes:backward` where usable and select a named road-class
capacity profile or user-supplied capacities; Hyderabad's `hmda_cts_2011` table above is one
option. Retain `capacity_source` on every arc. Never interpret total two-way lanes as lanes in
each direction. OSM tags are incomplete and do not encode all intersection, parking, encroachment
or mixed-traffic effects, so inferred capacities are scenario inputs rather than measurements.

Support a directed-edge capacity CSV override keyed by stable OSM/link identity. Validate finite
positive time and capacity on every non-connector arc. Report tag, class-default and override
coverage by physical-road length.

### 5. Static traffic assignment

Use a single-class static user-equilibrium assignment for the first implementation. Select a
volume-delay function (VDF) with explicit parameters. The Hyderabad example uses the CTS conical
function and class-specific parameters as its main scenario, with BPR as a comparison:

```text
t_e(v_e) = t0_e * (1 + alpha * (v_e / capacity_e) ** beta)
```

The BPR equation is directly taken from the published BPR method; we did not make it. Connecting
its congested seconds to GeoResilience is our adaptation. The initial `0.15/4` parameter pair is
only a conventional comparison and must not be described as Hyderabad-calibrated.

The first slice implements Frank-Wolfe assignment using the existing NetworkX and SciPy
dependencies. It accepts a sparse OD CSV or a small, explicit zone-mass CSV, free-flow edge
times, uniform or directed-edge capacities, and a global BPR or conical VDF. It exports simulated
arc flows/times and can rerun selected physical-road closures. This small-network implementation
has no new dependency; benchmark it against AequilibraE before city-scale use. AequilibraE's
optimized assignment and the class-specific CTS mapping remain planned extensions.

The reported result uses Frank-Wolfe equilibrium, with all-or-nothing shortest-path assignment
at each iteration and line search. Record iterations, relative gap and target gap. A run that
does not meet its target is marked non-converged; closure reassignment requires a converged
baseline. Biconjugate Frank-Wolfe in AequilibraE can be assessed for later scale-up.

Static assignment represents an average condition during one period. It does not model queues
spilling across junctions, signals, departure-time choice, incidents, stochastic route choice,
induced demand or within-period dynamics.

### 6. Supplied edge times

Accept a directed-edge CSV of positive travel times in seconds, mapped unambiguously to a frozen
cleaned road graph. Reject unmatched or ambiguous arcs; an explicitly chosen free-flow fallback
may fill gaps and must be reported. This uses the existing `PreparedTimeModel` cost contract and
can represent another model's output or measured travel times. Record the source, period, graph
identity and match coverage. A time-only input
supports time-based routing and accessibility. Optional supplied volumes and capacities enable
V/C and system-delay summaries, but those columns must be validated independently. Closure
analysis with this input keeps the remaining edge times fixed and is labelled `fixed_time`; full
traffic reassignment requires OD demand and an assignment model.

The input CSV contract contains directed graph edge identity, `travel_time_s`, period and source;
volume and capacity columns are optional. These are traffic observations only if their source
actually measured traffic. Externally simulated times retain a simulated provenance label.

## Edge cost and related indices

### Primary routing cost

The Tier 4 edge cost is `congested_time_s` on each directed edge. Parallel arcs retain their own
costs. Physical-link output may summarize directions, but routing never replaces asymmetric arc
times with a physical-link average.

For assignment runs, export on every directed road arc:

- `free_flow_time_s`;
- `capacity_pcu_h` and `capacity_source`;
- `assigned_volume_pcu_h`;
- `vc_ratio = volume / capacity`;
- `congested_time_s` and its source/provenance;
- `delay_s = congested_time_s - free_flow_time_s`;
- `speed_kph` implied by congested time;
- `delay_pcu_hours = volume_pcu_h * duration_h * delay_s / 3600`, the total PCU-hours of
  delay contributed during the modelled period;
- `marginal_time_s` from the selected VDF as a diagnostic of the cost an additional vehicle
  imposes. Under BPR this is
  `t0 * (1 + alpha * (1 + beta) * (v/c)^beta)`; do not apply that derivative to the conical VDF.

`vc_ratio` is a saturation indicator, not the routing cost. `delay_pcu_hours` is a system-burden
indicator, not an individual trip time. Marginal time is useful for bottleneck prioritisation but
does not replace user-equilibrium travel time.

For supplied-edge-time runs, export the supplied time and source on every matched arc. Compute
volume-based indicators only when corresponding valid flow and capacity inputs exist. Missing
traffic quantities stay missing; they are not inferred from speed alone.

### Network and accessibility indicators

Report separately:

- total system travel time (TSTT), when link flows exist,
  `sum_e volume_pcu_h * duration_h * time_s / 3600` PCU-hours;
- total PCU-hours of delay, when link flows and free-flow times exist,
  `sum_e volume_pcu_h * duration_h * (time_s - t0_s) / 3600`;
- demand-weighted mean and selected percentiles of OD time and delay, when OD demand exists;
- share of demand reachable and share within configured absolute or relative time thresholds,
  when OD demand exists;
- congested/free-flow OD time ratio;
- optional Hansen or facility accessibility recomputed with congested time, clearly separated
  from the existing distance-only Hansen definition;
- assignment convergence for simulated runs, plus capacity/data-coverage diagnostics where
  their inputs exist.

Avoid a default composite index. If a later score combines delay, disconnection and access, its
weights and normalization must be user-supplied, as with the existing scorecard convention.

## Road-closure criticality under load

For a named assignment closure scenario, remove every directed arc belonging to the physical
`link_id`, keep the OD demand fixed, and rerun equilibrium. Compare the scenario with the intact
assignment.
Initially evaluate the existing structural candidate set plus the highest baseline `vc_ratio`,
`delay_pcu_hours` and assigned-volume roads. Use exhaustive closure assignment only on a small frozen
example to measure how many high-impact roads the candidate screen misses.

For each evaluated physical road report:

- change in TSTT for OD demand served in both scenarios;
- change in total PCU-hours of delay;
- demand-weighted mean and percentile OD delay;
- newly unreachable demand and number of affected OD pairs;
- maximum and spatial distribution of zone accessibility loss;
- convergence status for both assignments.

Do not let disconnected trips disappear from the denominator: that can make a damaging closure
appear beneficial by reducing served TSTT. Keep `newly_unreachable_demand` beside the delay
metrics. The default ranking should be lexicographic: newly unreachable demand first, then added
TSTT among demand served in both scenarios. A single scalar that assigns a finite penalty to an
unserved trip is optional and must expose that penalty.

This is the Tier 4 meaning of traffic-aware road criticality: the road's loss changes equilibrium
routes and the cost borne by modelled demand. Baseline congestion alone does not establish that a
road is critical, and an uncongested road can be critical if it is the only viable bypass.

Do not start by reassigning all Monte Carlo failure samples. First make baseline and targeted
single-road scenarios correct, convergent and auditable. A later approximation may use baseline
congested costs without reassignment for large Monte Carlo runs, but it must be labelled
`fixed_flow` and compared with full reassignment on small cases.

## Verification and sensitivity

Simulation is a valid framework test without observed traffic. It can answer how rankings and
accessibility change under specified traffic scenarios. Validate in this order:

1. **Software correctness:** conservation of OD demand and link flow, known equilibrium networks,
   BPR and conical VDF arithmetic, directional/parallel roads, connectors and closures.
2. **Internal validity:** convergence, plausible trip lengths, capacity coverage, stable results
   under finer zones and tighter relative-gap targets.
3. **Sensitivity:** vary demand scale, gravity decay, zone size, lane/capacity profile and VDF
   parameters; compare changes in both values and road rankings.
4. **Optional observed comparison:** if counts or travel times exist for the same place/period,
   estimate demand scale/capacity factors on a calibration subset and evaluate on held-out data.

Do not make Uber Movement a required source. Its continued city coverage and access are not a
safe project dependency. Accept generic observed-count and directed-edge-time CSVs. Commercial
historical floating-car sources such as TomTom Traffic Stats can be optional calibration inputs
when licensing and coverage permit; preserve source, period, map-matching method and licence
constraints. The simulated pipeline must remain reproducible offline with frozen inputs.

Calibration cannot identify every parameter from travel times alone. Record whether each value is
generated, supplied, locally calibrated or assumed. If observations are available, report fit
measures such as weighted MAE/MAPE for time and GEH for counts where appropriate, spatial coverage
and held-out error. If not, report convergence, conservation, sensitivity and scenario stability
without claiming an observed-data fit.

## Implemented first-slice configuration

```yaml
traffic:
  enabled: true
  source: assignment                 # assignment | edge_times_csv
  period: illustrative_one_hour
  duration_h: 1.0
  demand_source: gravity             # gravity | od_csv
  zone_mass_csv: zones.csv           # node,mass; nodes in the cleaned graph
  total_demand_pcu_h: 300            # explicit scenario assumption
  gravity_lambda_per_min: 0.1
  capacity_pcu_h: 100                # illustrative uniform directed-arc capacity
  vdf: bpr                           # bpr | conical
  alpha: 0.15
  beta: 4.0
  relative_gap: 0.0001
  max_iterations: 200
  closure_top_n: 1                   # 0 disables closure reassignment
```

For supplied OD, set `demand_source: od_csv` and `od_csv` with columns
`origin,destination,demand_pcu_h`. For externally supplied travel times, set
`source: edge_times_csv` and `edge_times_csv` with columns `u,v,key,travel_time_s`. A
`capacity_csv` with `u,v,key,capacity_pcu_h` can replace the uniform capacity. CSV IDs refer
to the cleaned directed graph and require complete arc coverage for times or capacities.

The demonstrated `0.15/4` BPR pair and uniform capacity are illustrative assumptions. The
Hyderabad CTS profile and city-scale WorldPop zone aggregation described above are not yet
implemented. Conical runs currently accept one explicitly configured `alpha`/`beta` pair across
all arcs; applying the ten CTS road classes requires later per-class mapping and validation.

## Outputs

Keep existing artifacts and add:

- `network.gpkg`: a directed `traffic_arcs` layer; physical-link summaries, zones and connectors
  remain planned.
- `traffic_od.csv`: the supplied or generated OD matrix used by assignment, with free-flow and
  congested shortest-path times and delay for each pair.
- `traffic_arcs.csv`: directed volume, capacity, V/C, free-flow and congested seconds.
- `traffic_closures.csv`: top-flow physical road closures, reassigned system time and separately
  reported disconnected demand when `closure_top_n > 0`.
- `summary.json.traffic`: demand totals, assumptions, coverage, convergence, TSTT, delay,
  reachability, sensitivity/run identity and closure ranking.
- `report.txt`: a Traffic section that identifies assignment or supplied-time source and marks
  generated, supplied and calibrated quantities.
- figures remain planned: V/C or delay map, OD-time distribution, convergence trace and top
  closure impacts.

Large OD/scenario tables should be optional artifacts rather than embedded in JSON. Every output
records units. A traffic-disabled run must preserve all existing results byte-for-byte where
timestamps and normal serialization allow.

## Validation

Ordinary tests remain offline.

- One link: assigned volume equals OD demand and the selected BPR/conical time is exact.
- Two parallel links: user-equilibrium path costs match within the configured gap; increasing one
  capacity cannot increase its equilibrium time in the simple fixture.
- Directed diamond: one-way legality and parallel alternatives are preserved.
- Disconnected zones: unreachable demand is retained and reported, never silently reassigned.
- Physical closure: all reciprocal/parallel arcs belonging to that `link_id` close together.
- Demand balance: gravity row/column sums match targets and total link entry/exit flow is
  conserved within tolerance.
- Zero demand: congested time equals free-flow time and all delays are zero.
- Supplied-time import: directed costs map to the correct arcs; invalid or missing times fail
  explicitly, and flow-dependent fields remain missing without flow inputs.
- Adapter cross-check: small assignments match an independently constructed AequilibraE example
  and a brute-force/all-or-nothing reference where applicable.
- Regression: traffic disabled does not change Tier 1-3 metrics.
- Frozen framework examples: a small synthetic known-answer network and one Hyderabad study area
  with WorldPop, OSM capacity coverage, convergence evidence, at least two zone sizes and a
  declared sensitivity grid. The latter is a simulated case study unless observed counts/times
  are acquired.

## Implementation tickets

| Ticket | Deliverable                                                                         | Dependencies             |
| ------ | ----------------------------------------------------------------------------------- | ------------------------ |
| 21     | Directed cost/import contract, capacity profile and known-answer assignment adapter | 02, 10                   |
| 22     | Deterministic zones, centroid connectors, gravity demand and sparse OD import       | 21; 12 for WorldPop      |
| 23     | Baseline assignment, supplied-time input and `PreparedTimeModel` integration      | 21, 22                   |
| 24     | Congested accessibility/reliability summaries and traffic-specific figures          | 23; 11 and optionally 19 |
| 25     | Targeted physical-road closure reassignment and delay criticality                   | 04, 05, 23               |
| 26     | Frozen Hyderabad example, sensitivity study and optional observed-data calibration  | 22-25                    |

The first vertical slice is Tickets 21-23 on a tiny offline graph: explicit OD demand and
capacity in, equilibrium `congested_time_s` out, then one existing travel-time calculation using
that cost. The same directed-cost contract also accepts supplied edge times. Expand to WorldPop
gravity scenarios and large-area closure batches after the small assignment is verified.

## Deliberately deferred

- dynamic traffic assignment and queue spillback;
- signal timing and turn penalties/restrictions beyond the current graph representation;
- departure-time and stochastic route choice;
- induced/suppressed demand after closures;
- multi-class cars, buses and freight;
- emissions;
- live traffic ingestion;
- equilibrium reassignment inside every Monte Carlo failure sample.

These are valuable extensions, but none is needed to answer the initial question: how simulated
traffic changes the effective edge cost and the ranking of roads whose loss harms accessibility.

## References and current tool notes

- [HMDA Comprehensive Transportation Study summary](https://www.hmda.gov.in/developdept9/)
  identifies the HMA-2041 study, consultant and modelling horizon.
- [HMA-2041 CTS Volume I report](https://theasthmafiles.org/sites/default/files/artifacts/media/pdf/report_on_long_term_strategy_for_the_transport_sector_of_hma-2041_volume-i_main_report_3_1.pdf)
  is the source for the Hyderabad survey/model description, conical VDF adoption and the
  2011 capacity, speed and parameter tables reproduced above. The host is a public mirror, not
  HMDA; preserve a checksum if it becomes a frozen project input.
- [Bureau of Public Roads Traffic Assignment Manual (1964)](https://libraryarchives.metro.net/dpgtl/us-department-of-commerce/1964-traffic-assignment-manual-for-application-with-a-large-high-speed-computer.pdf)
  is the original source family for the BPR volume-delay function.
- [Spiess (1990), Conical Volume-Delay Functions](https://doi.org/10.1287/trsc.24.2.153) is the
  published source for the conical VDF family.
- [Wilson (1970), Entropy in Urban and Regional Modelling](https://doi.org/10.1111/j.1538-4632.1970.tb00859.x)
  supports the entropy/spatial-interaction family behind doubly constrained gravity balancing;
  it does not specifically validate using population for both Hyderabad productions and
  attractions.
- [AequilibraE traffic assignment](https://www.aequilibrae.com/docs/python/v1.4.2/traffic_assignment/assignment_procedures.html)
  documents BPR, capacity/free-flow fields, equilibrium algorithms and congested skims. It is a
  reference for validating the current solver and a possible later scale-up adapter.
- [Beckmann, McGuire and Winsten (1956)](https://cowles.yale.edu/research/publications/archive)
  formulated the static user-equilibrium assignment problem; [Frank and Wolfe
  (1956)](https://doi.org/10.1002/nav.3800030109) introduced the optimization algorithm used
  by the first small-network implementation.
- [AequilibraE sparse assignment example](https://www.aequilibrae.com/docs/python/v1.3.1/_auto_examples/traffic_assignment/plot_sparse_matrix_assignment.html)
  demonstrates sparse demand and BFW assignment.
- [TomTom Traffic Stats](https://docs.tomtom.com/traffic-stats/documentation/product-information/introduction)
  is an optional historical speed/travel-time calibration source with access and licensing
  requirements, not a core dependency.
- [TomTom Hyderabad Traffic Index](https://www.tomtom.com/traffic-index/city/hyderabad/) is a
  current city-level plausibility benchmark, not an OD matrix or link-level calibration dataset.
- [Kuchu et al. (2025)](https://doi.org/10.3311/PPtr.36936) analysed Hyderabad Uber Movement
  travel times from 2016-2019 and provides local precedent for congestion, friction and
  accessibility indices; availability of the underlying platform data must be checked.
- [Omar and Mallikarjuna (2016)](https://doi.org/10.1016/j.proeng.2016.02.038) calibrated a
  macroscopic traffic relation on a Jubilee Hills road and supports treating Hyderabad's
  heterogeneous, weak-lane-discipline traffic as a local calibration problem.
- [Kumar et al. (2026)](https://doi.org/10.1007/s13177-026-00720-y) is a recent Hyderabad
  corridor study using BPR/VISSIM; it is corridor evidence, not a city-wide parameter source.
- [Indo-HCM, CSIR-CRRI](https://crridom.gov.in/en/indian-highway-capacity-manual) is the national
  capacity-method reference for a comparison profile.
- [WorldPop](https://www.worldpop.org/faq/) remains a population estimate. It supplies spatial
  mass, not observed trips or vehicle ownership.
- See [Hyderabad data and literature audit](TIER4_HYDERABAD_SOURCES.md) for access, intended use
  and limitations of each source.
