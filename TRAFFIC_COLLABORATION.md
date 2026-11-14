# Tier 4 traffic: final plan and two-person work split

Updated 13 November 2026. Reviewed baseline: `fac39b7` on `tier-4`.
This replaces the previous collaboration plan. This file assigns future work; it does not claim that the implementation or Hyderabad study is complete.

## 1. Goal and scope

Deliver a justified, reproducible **congested_time_s for every directed road arc** for one declared period. Flood estimation separately supplies `p_fail` and is not our task.

Use single-class static user-equilibrium assignment, initially BPR. Retain supplied OD and supplied edge-time inputs. Add a CTS/conical comparison only after verifying the original parameters and applicability.

Supporting indicators are volume, capacity, V/C, delay, system travel time, reachability and convergence. No new composite score. Complete baseline traffic first. New closure/accessibility experiments follow acceptance. Dynamic queues, signals, individual vehicles, multiclass traffic and full reassignment inside Monte Carlo are deferred.

## 2. Current implementation: retain and improve

Already present:
- BPR/conical assignment, supplied directed times and OD CSVs.
- Balanced gravity over supplied zone masses.
- Automatic population-grid demand and generic lanes/width capacity inference.
- CLI/pipeline integration, GIS/CSV exports and congested-time handoff to reliability.
- Highest-flow physical-road closure reassignment.

Inspection and focused testing found:
- Confirmed defect: requested population zone limit 2 can produce 4 zones.
- Focused traffic tests: **7 passed, 1 failed** on 13 November 2026. The integration test supplies a Path where `population.worldpop` expects a string. Configuration fails before the pipeline runs. Reproduce and resolve the correct API/test mismatch.
- Automatic population demand conserves one total but does not enforce per-zone production/attraction margins.
- Two-way capacity uses equal lane splits; directional lane tags are not yet used.
- Independent solver comparison, parameter evidence and Hyderabad sensitivity remain unfinished.
- Existing Hansen remains distance-based. Monte Carlo reliability reuses fixed assigned times.

Defaults of 0.1 PCU/person/hour, decay 0.08/minute, 1000 PCU/hour/lane and width 3.5 m/lane are illustrative assumptions, not Hyderabad measurements.

## 3. Ownership

### A: AM and AM's agent — solver, integration, final verification

Tasks:
1. Resolve the integration-test failure without weakening validation.
2. Establish the input-module boundary described below.
3. Verify assignment, convergence, flow conservation, units and directed/parallel roads.
4. Cross-check a small equilibrium case independently.
5. Integrate B's reviewed demand/capacity preparation into configuration, CLI and pipeline.
6. Verify exports and actual consumption of congested edge costs.
7. Run combined regressions and assemble pilot results and comparison figures.

Owned files:
- `src/georesilience/traffic.py` after the extraction checkpoint.
- Existing `config.py`, `cli.py`, `pipeline.py`, `reporting.py`, `network.py`, `time_models.py` when traffic changes require them.
- `tests/test_traffic.py`, new `tests/test_traffic_solver*.py` and `tests/test_traffic_pipeline*.py`.
- Shared `README.md`, `DESIGN.md`, `plan/TIER4.md`, this document.
- New `examples/traffic/run_pilot.py` and `docs/traffic/results.md`.

### B: teammate and teammate's agent — demand, capacity preparation, scientific inputs

Tasks:
1. Independently validate the plan, current code and source availability.
2. Correct zoning and validate representative-node attachment and mass accounting.
3. Implement separate productions/attractions and constrained gravity balancing as the main synthetic mode. Retain globally normalized population-product demand as an explicit comparison mode.
4. Improve directional capacity inference and source/fallback coverage.
5. Prepare justified Hyderabad input/parameter scenarios and provenance.
6. Define demand/capacity/zoning sensitivity cases and provide tested inputs to A.

Owned files:
- New `src/georesilience/traffic_inputs.py`, created at the extraction checkpoint.
- New `tests/test_traffic_inputs.py`, `tests/test_traffic_capacity.py`, `tests/test_traffic_zoning.py` as needed.
- Tiny synthetic fixtures in new `tests/fixtures/traffic/`.
- New `examples/traffic/prepare_inputs.py`.
- New `docs/traffic/input_review.md`, `input_contract.md`, `data_sources.md`, `parameter_register.md`, `sensitivity.md`, `handoff.md`.
- `plan/TIER4_HYDERABAD_SOURCES.md`; optional verified profiles in `profiles/traffic/`.

Do not edit the other owner's files concurrently. B proposes CLI/config requirements in the handoff; A implements shared integration. A sends input-module issues for B to fix. Preserve unrelated tier behaviour and `final_lit.pdf`.

## 4. First checkpoint: extract once before parallel coding

Demand/capacity functions currently live in shared `traffic.py`. Do not have both agents change it.

1. B first writes `input_review.md` and proposes `input_contract.md`, checking scientific assumptions and actual interfaces.
2. A performs a small **behaviour-preserving extraction** of input preparation into `traffic_inputs.py`, with delegation/import adjustments. Preserve caller compatibility and avoid circular imports. Record actual test results and the known failure.
3. Agree on that commit and contract. B then owns the extracted module.
4. A works on solver/integration while B improves zoning, demand and capacities.

Before extraction, B can research sources and parameters without touching shared code. This checkpoint requires teammate coordination, not user approval for every routine choice.

## 5. Shared input contract

Agree on concrete Python types before dependent implementation. This describes required behaviour, not an existing named API.

A supplies:
- Frozen cleaned directed graph and identity/fingerprint.
- Population keyed by actual graph node ID; array adapters must validate node order.
- Positive free-flow seconds keyed by `(u,v,key)`.
- Explicit period, zoning, demand and capacity settings.

B returns:
- OD mapping `(origin,destination) -> PCU/hour` on actual cleaned nodes.
- Capacity mapping `(u,v,key) -> PCU/hour`, complete for non-loop road arcs.
- Zone membership, population, productions, attractions, anchors and attachment metadata.
- Original mass, intrazonal/excluded/unreachable demand, feasibility and balancing diagnostics.
- Per-arc capacity source, directional lanes, profile/fallback and coverage.
- Provenance: sources, years/hashes, units, assumptions, parameters and scenario identity.

Preparation must not mutate supplied graphs or mappings. Initially use existing road-node anchors. Artificial connectors require an agreed extension and must never become physical closure roads or centrality edges.

Preserve public CSV compatibility:
- OD: `origin,destination,demand_pcu_h`
- Capacity: `u,v,key,capacity_pcu_h`
- Supplied times: `u,v,key,travel_time_s`

Keep audit metadata separately and record it in final provenance. Omitting a pair from solver CSV must not silently erase excluded demand. Current VDF parameters are global: per-road CTS parameters need an explicit versioned solver extension, not merely extra CSV columns.

## 6. Final methodological choices

| Item | Agreed approach | Why / qualification |
| --- | --- | --- |
| Cost | Congested seconds per directed arc | Additive travel cost with interpretable units |
| Model | Static single-class user equilibrium | Feasible average-period congestion/rerouting model |
| Initial VDF | BPR benchmark | Disclose coefficients; test alternatives |
| CTS/conical | Optional after verifying source and mapping | Historical calibration is not current ground truth |
| Main synthetic OD | Separate production/attraction margins, constrained gravity | Makes zone assumptions inspectable |
| Existing simple OD | Retained comparison mode | Valid scenario shortcut, not margin-preserving |
| Capacity | Directional tags/profile/overrides with explicit fallback | Avoid total-lane double counting |
| Observed times | Alternative supplied-cost path | Alone cannot predict closure-induced congestion or volumes |

Constrained balancing does not make demand realistic by itself. Targets still need evidence. Population can supply both margins initially as a disclosed fallback. Prefer compatible employment/education evidence when obtainable. Report/reject infeasible margins rather than silently redistributing trips.

## 7. Full process and checks

### Stage 1: define the geographic pilot — B prepares, A checks integration

- Select a manageable Hyderabad area and one declared modelled period.
- Freeze OSM/population product/date/year, boundary, network type, cleaning and hashes.
- Use projected metre coordinates for zoning/attachment; preserve travel direction and grade separation.
- Report retained-network losses and population allocation coverage.
- Define routing extent and external/through-trip demand, or disclose its omission.
- Compare two zone resolutions. Define intrazonal treatment and representative-node limitations.

### Stage 2: demand and capacity — B leads

- Convert residents using declared trip rate, road-mode share, peak share, occupancy and PCU conversion, or one explicitly bundled effective rate. Never apply both conversions and scale twice.
- Keep PCU/hour rates distinct from period totals. Declare gravity decay units and convert seconds/minutes once.
- Validate separate margins, total demand, unreachable pairs, intrazonal exclusions, empty zones and duplicate anchors.
- Fix the maximum-zone defect; test non-square limits and degenerate spatial layouts.
- Parse directional lanes, one-way tags and split carriageways. Audit shared narrow roads and ambiguous/list-valued tags.
- Width-derived lanes need a usable-carriageway-width assumption. Parking, condition and signals are not automatically captured.
- Export capacity/profile/fallback coverage and source evidence, not just final numbers.

### Stage 3: assignment verification — A leads

- Reproduce/fix integration failure and test the intended contract.
- Check exact one-road cost, known two-route equilibrium, parallel/directed arcs and flow conservation.
- Check low/high demand, invalid inputs, complete cost mapping and non-convergence.
- Report target/achieved gap and iterations; reaching iteration limit does not imply convergence.
- Compare a small case with an independent analytical answer or established solver.
- Preserve supplied-cost mode and existing supported closure behaviour.

### Stage 4: serialized integration and comparisons — A integrates, B reviews

- Integrate B's reviewed preparation module, then adapt CLI/config/pipeline under A's ownership.
- Verify preparation through assignment through export and actual consumer use of costs.
- Compare distance, free-flow and congested routes on identical inputs. Changed rankings are possible findings, not a required result.
- Export per-arc volume/capacity/V/C/times/delay plus network/OD summaries and provenance.
- Label reliability as fixed assigned times during failure samples.
- Do not silently turn distance Hansen into time Hansen. Later time accessibility needs stated time decay/thresholds.
- Run applicable complete offline tests and traffic-disabled regressions. Record environment, commands, passes, failures and skips honestly.

### Stage 5: sensitivity and Hyderabad report — B defines cases, A runs/reports

- Low/base/high demand, an alternative capacity scenario, alternative decay and two zone sizes.
- Begin with manageable cases, not every possible parameter combination.
- B checks changed-input accounting; A checks convergence and cost results.
- Inspect trip lengths/times, V/C distributions, fallback coverage and spatial patterns.
- If observations exist, calibrate on a subset and evaluate on held-out observations.
- Without observations, report correctness, convergence and scenario stability, not predictive accuracy for current Hyderabad traffic.

### Later extension after baseline acceptance

Selected physical-road closures with fixed OD and full reassignment. Compare added delay for consistently served demand and report newly unreachable demand separately. Extend screening beyond highest flow and compare against exhaustive small cases. Flood/facility integration remains separately coordinated.

## 8. Data and parameter justification — B verifies, both use

| Source | Role | Qualification |
| --- | --- | --- |
| OSM/OSMnx | Roads, direction, lane/speed information | Incomplete tags; speed limits are proxies |
| WorldPop | Resident count raster | Freeze product/year; not observed OD or jobs |
| HMDA CTS | Proposed historical speed/capacity/conical evidence | Recover original report and verify tables before using exact values |
| Indo-HCM / documented overrides | Capacity comparison | Match units, direction and operating conditions; verify access |
| Employment/land-use evidence | Better attraction | Planning maps or POIs are not measured visits |
| Matched traffic counts/probe times | Optional calibration/evaluation | Align period, geography, direction, licence and coverage |
| TomTom public aggregates | Broad plausibility | Cannot validate individual pilot roads or identify OD |

No current ready-to-use public Hyderabad OD matrix has been verified for this project. The CTS mirror in the old plan was unreliable in the last check. Our Markdown parameter table is not independent source verification.

Each parameter register entry must include name, units, value/range, year, source/table/page or assumption rationale, coverage and sensitivity cases. Distinguish published method, historical local calibration, adaptation and project assumption. A citation for a method does not justify every local coefficient.

Source starting points:
- https://osmnx.readthedocs.io/en/stable/user-reference.html
- https://hub.worldpop.org/project/list/
- https://www.hmda.gov.in/developdept9/
- https://crridom.gov.in/en/indian-highway-capacity-manual
- https://www.aequilibrae.com/latest/python/static_traffic_assignment.html
- https://docs.tomtom.com/traffic-stats/documentation/product-information/introduction

## 9. Git and handoff rules

1. Separate clones/worktrees and personal branches from an agreed updated `tier-4` commit. Suggested names: `traffic/solver-integration` and `traffic/demand-capacity`. This document creates no branches.
2. Complete extraction/interface agreement before parallel module changes. Never concurrently switch branches in one working directory.
3. Exchange base commit, task and owned paths. Material interface changes need communication and updated contract/tests.
4. Stage only intended files. Do not commit unrelated old demos, environments or generated results. No force-push/reset of shared work.
5. B hands over commits/PR, tested preparation example, schemas, evidence register, actual checks and unresolved issues. A integrates once; do not both merge and cherry-pick the same commits.
6. Shared CLI/config changes happen sequentially under A. Input-module fixes remain under B unless ownership is explicitly transferred.
7. Do not incidentally merge flood/facility branches or alter unrelated tier definitions to make traffic tests pass.

## 10. Immediate next actions and acceptance

**A now:** reproduce integration failure, agree the input API with B, do the small extraction, establish independent solver checks.

**B now:** review this document and source availability, write input review/contract, then fix zoning and implement constrained demand, directional capacities and parameter evidence in the extracted module.

**Done:** reproducible known-answer example plus documented Hyderabad pilot, positive directed edge costs, conserved/accounted demand, provenance/coverage, convergence, simpler-cost comparisons and sensitivity. Successful execution or a map alone does not establish empirical accuracy.

Defensible claim:
> We add demand-sensitive travel costs to the resilience framework, verify the calculations, document geographic and traffic assumptions, and evaluate changes under Hyderabad-informed scenarios. Predicting current traffic requires matched observations.

## Message to the teammate

> Pull the updated TRAFFIC_COLLABORATION.md. We will retain your prototype and improve it. You own demand/zoning, directional capacity preparation and source/parameter justification. I own solver verification and shared CLI/pipeline integration. First review the plan and agree the input contract. I will extract input preparation from traffic.py so we can work in separate modules. Please avoid shared solver/config/pipeline edits during that step. Then hand over your tested module, commits and reproducible inputs for combined verification. The immediate goal is congested edge travel time, not flooding, a composite score or dynamic vehicle simulation.
