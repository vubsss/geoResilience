# Tier 4 traffic: shared plan and two-person handoff

Prepared 13 November 2026. Planning document only: creating this file does not implement,
approve numerical assumptions, or validate the complete traffic pipeline.

## Read this first

We are two teammates working on **traffic only**. Our immediate deliverable is a justified,
reproducible **travel cost in seconds for every directed road arc**, named
`congested_time_s`, with the inputs and assumptions that produced it.

- Traffic simulation produces edge costs. Delay, volume/capacity and system travel time are
  supporting indicators.
- Flood estimation produces physical-link failure probabilities. It is another teammate's
  work. Do not implement or merge the flood pipeline as part of this task.
- Do not invent a composite score combining traffic, centrality and flooding.
- Complete baseline traffic before expanding to new closure/reliability/accessibility features.
- Work from the updated `tier-4` branch. Initial inspected baseline: `b81bb22`.
- Read the current `DESIGN.md`, traffic sections of `README.md`, `plan/TIER4.md`,
  `plan/TIER4_HYDERABAD_SOURCES.md`, and the relevant code/tests. Older ticket documents may
  refer to modules removed by the main-branch cleanup. Current calculation contracts take
  precedence over stale status checkboxes.
- `final_lit.pdf` is a submitted reference document. Preserve it. Do not stage unrelated
  old demo data, environments, generated results or presentation files.

## Mandatory first task for the receiving agent

Before implementation, independently review this plan against the current code and sources.
Write `docs/traffic/input_review.md` covering:

1. What is already implemented and what is missing.
2. Data actually obtainable, access conditions and reference years.
3. Parameters supported by a source versus assumptions requiring sensitivity tests.
4. Feasibility or scientific problems in this plan and proposed corrections.
5. Whether the shared contract below works without changing owner A's files.

Do not quietly redesign the interface or edit the other owner's files. Report required
interface changes to the teammate before dependent integration. This is a shared team
checkpoint, not a requirement to request user approval for every routine decision.

## Division of responsibility

### Owner A: AM and AM's agent — solver, edge-cost integration and final assembly

Owns:

- Existing `src/georesilience/traffic.py` and `tests/test_traffic.py`.
- `src/georesilience/config.py`, `cli.py`, `pipeline.py`, `reporting.py` and
  `time_models.py` when traffic changes are necessary.
- New solver/integration tests named `tests/test_traffic_solver*.py` or
  `tests/test_traffic_pipeline*.py`.
- `examples/tier4_core_demo.py` and shared top-level documentation updates.
- Final integration, compatibility checks and publication of the combined traffic result.

Tasks:

1. Reproduce and resolve current integration failure without weakening validation.
2. Verify BPR/conical calculations, assignment convergence, directed/parallel roads and units.
3. Accept owner B's generated OD/capacity inputs through the agreed interface.
4. Wire preprocessing into the CLI/config/pipeline after B's input contract stabilizes.
5. Export directed costs, flows, provenance and convergence diagnostics.
6. Benchmark known small networks independently and run full regression checks.

### Owner B: teammate and their agent — demand, capacity preparation and evidence

Owns **new, separate files**:

- `src/georesilience/traffic_inputs.py`.
- `tests/test_traffic_inputs.py` and `tests/test_traffic_input_evidence.py` if needed.
- `examples/traffic/` preparation helpers and small examples.
- `docs/traffic/input_review.md`, `data_sources.md`, `parameter_register.md`,
  `input_handoff.md` and `sensitivity.md`.
- Optional `profiles/traffic/` for verified, versioned parameter profiles.
- Tiny, synthetic fixtures under `tests/fixtures/traffic/` only when needed.

Tasks:

1. Verify the proposed sources and document usable evidence.
2. Prepare reproducible zones from allocated population and explicit attraction inputs.
3. Generate balanced OD demand or validate supplied OD.
4. Prepare directional capacities, coverage and fallback evidence.
5. Define low/base/high demand and capacity scenarios plus at least two zone resolutions.
6. Supply tested CSVs, metadata and a concise integration handoff to owner A.

**Owner B must not edit** existing `traffic.py`, config, CLI, pipeline, time models,
root README/DESIGN or A's tests. Suggest changes in `input_handoff.md` instead.
Owner A must not concurrently edit B's module, fixtures or documents.

This divides scientific/data preparation from assignment/integration. Both owners cross-review
the other's work. It is not a division into independent models with incompatible definitions.

## Git and coordination rules

1. Each person uses a separate clone or worktree and a personal branch based on the same
   updated `origin/tier-4`, for example `traffic/solver-integration` and
   `traffic/demand-capacity`. Agree on names before creating branches; this document creates none.
2. Never run concurrent branch switches or Git operations in the same working directory.
3. Inspect status before work and stage only owned files. Avoid `git add .`.
4. Exchange the base commit, interface version, owned paths and current task before coding.
5. Use small reviewed changes. Owner A integrates B's reviewed commits/PR, then performs shared
   CLI/config changes sequentially. Never independently replay the same commits by both merge
   and cherry-pick. Do not reset/force-push a shared branch.
6. A handoff states exact commit, files changed, how to run, checks actually executed,
   outputs, assumptions and unresolved issues. Never call unrun checks passed.
7. When an interface changes, update its contract and both owners' tests before integration.
8. Do not modify unrelated tier implementations to make traffic tests pass. Describe a
   genuine cross-tier issue first and arrange the fix with its owner.

## Scientific approach and alternative routes

The first version uses **single-class static user-equilibrium assignment** for one declared
period. Costs change with assigned load. It is an average-period network model, not individual
vehicle animation or second-by-second congestion.

Other supported/plausible routes:

| Route | Appropriate use | Qualification |
| --- | --- | --- |
| Supplied directed travel times | Ingest measured or externally simulated costs | Record origin/period. Costs alone cannot predict closure-induced congestion. |
| Assignment with supplied OD | Prefer when compatible OD evidence exists | Still requires capacities, free-flow costs and validation. |
| Assignment with synthetic gravity OD | Main reproducible fallback | Results describe assumptions, not observed Hyderabad trips. |
| Calibrated/hybrid assignment | Improve demand/capacity using observations | Hold out independent observations for evaluation. |
| Dynamic/vehicle simulation | Later detailed queues, signals, departure patterns | Not the current implementation scope. |
| Multipliers or learned costs | Optional comparison or later evidence-rich extension | Do not substitute unsupported factors for assignment or claim prediction without validation. |

Use `congested_time_s` as the routing cost. Keep V/C dimensionless, per-road delay in seconds,
and network burden in PCU-hours. Do not replace congested time with marginal system cost unless
a separately specified system-optimal experiment requires it.

## Full intended process

### 1. Freeze extent, period and geographic inputs

- Start with a manageable Hyderabad pilot. Record boundary, routing extent, road-network type,
  cleaning settings, input hashes, OSM retrieval date and population product/year.
- Retain the common cleaned directed network and physical-link identities.
- Audit boundary exclusions. Small internal-only demand can omit commuters crossing the pilot.
  Define external/cordon demand scenarios or explicitly report the omission.
- No live downloads during ordinary tests. Freeze real case-study inputs locally with a
  manifest. Large/generated datasets remain ignored and are not copied into commits casually.

### 2. Establish free-flow times

- Obtain speeds from usable road tags, documented class profiles or explicit overrides.
- Free-flow seconds come from road length and speed. A posted speed is a proxy, not a measured
  congested speed or necessarily an achieved free-flow speed.
- Preserve directed differences. Report provenance and missing coverage. Never fabricate
  missing speeds silently or use city-average congestion on every road.
- Owner A supplies the validated directed free-flow mapping to B's preparation routine.

### 3. Construct zones and network attachment

- Aggregate allocated population into deterministic projected grid zones initially.
- Compare at least two resolutions. Use explicit compatible polygon zones later if needed.
- Retain production/attraction totals, zone identity and empty/unallocated-zone accounting.
- Immediate compatibility mode may use representative **existing cleaned nodes** as zone
  anchors. Document that approximation and handle multiple zones choosing the same anchor.
- Full centroid connectors are a later extension unless both agents explicitly agree otherwise:
  they are assignment-only arcs, never physical roads, centrality edges or closure candidates.
  Do not modify the shared graph independently to introduce them.
- Define intrazonal trips explicitly. Current solver OD excludes origin equal to destination;
  report excluded mass and infeasible targets rather than silently redistributing it.

### 4. Generate or supply demand

- Supplied sparse OD must identify cleaned nodes and demand in PCU/h.
- Synthetic demand uses a doubly constrained gravity structure with declared trip productions,
  attractions and travel-time deterrence. IPF balances margins within stated tolerance.
- Population is a production/attraction proxy, not observed OD. Keep production and attraction
  arrays distinct even when an initial population-only scenario makes them equal.
- Convert residents to period demand using declared trips/person/day, represented road-mode
  share, peak-hour share, vehicle occupancy and mean PCU/vehicle, or accept an explicit total
  PCU/h scenario. Do not apply both conversions and scale twice.
- Keep period duration consistent: PCU/h is a rate; totals and PCU-hours depend on duration.
- Decay uses declared time units. If inputs are seconds and lambda is per minute, convert once.
- Audit unreachable pairs, disconnected zones, excluded intrazonal mass and balancing
  feasibility. A balanced matrix alone is not evidence that demand is realistic.
- Include external/through-trip sensitivity where boundary effects matter.

### 5. Assign directional capacities

- Parse usable `lanes`, `lanes:forward`, `lanes:backward`, one-way and road-class information.
- Never assign the total two-way lane count to each direction. Divided carriageways may be
  separate OSM ways. Audit flyover/bypass classifications and ambiguous tags.
- Apply a named, verified per-lane capacity profile or user-supplied per-arc values.
- Export capacity source, class mapping, fallback reason and coverage by count/road length.
- Width, parking, signals, condition and mixed traffic are not automatically measured by lane
  tags. Any effective-capacity adjustments need evidence or sensitivity scenarios.
- Initial integration uses a complete directed capacity CSV. Per-class VDF parameters need
  an agreed extension to A's solver; do not add columns and assume existing code consumes them.

### 6. Assign traffic and obtain costs

- Use fixed OD demand and positive directed times/capacities.
- Begin with BPR as a transparent benchmark. Compare the conical function when its parameters
  and source are verified. Conventional BPR alpha=0.15, beta=4 are illustrative, not local fits.
- Frank-Wolfe alternates shortest-path assignment and load-sensitive cost updates with line
  search. Check convergence with relative gap, not only iteration count or visual stability.
- Export non-convergence explicitly. Do not treat a non-converged assignment as a validated
  baseline. Validate numerical behaviour under high loading and near-zero demand.
- Single-class PCU assignment approximates mixed vehicles. It does not separately model cars,
  motorcycles, buses or freight behaviour.

### 7. Immediate output and integration

- Every non-loop directed road arc has an explicit positive finite cost in seconds.
- Export volume, capacity, V/C, free-flow time, congested time, delay and identity/provenance.
- Report total demand, served demand, TSTT, delay, OD time summaries and convergence separately.
- Supplied times keep unavailable flow/capacity quantities missing. Do not infer flow from speed.
- Existing reliability can consume a static traffic-cost snapshot. Record this as fixed times
  during event sampling; it is not equilibrium reassignment after every sampled failure.
- Existing Hansen remains distance-based. New time-based accessibility needs its own explicit
  time decay/threshold and later integration. Do not change metres to seconds silently.

### 8. Later extensions, after baseline acceptance

- Selected physical-road closures with fixed OD and full reassignment.
- Compare delay only on consistently served demand and report disconnected demand separately.
  A closure cannot look beneficial merely because impossible trips disappeared.
- Expand candidate screening beyond highest flow and check it against exhaustive small cases.
- Congested accessibility and eventual Tier 3 service integration, coordinated with that owner.
- Dynamic queues, signals, multiclass assignment and full Monte Carlo reassignment are deferred.

## Data and justification register

| Input/method | Evidence route | Required qualification |
| --- | --- | --- |
| Road graph/attributes | OpenStreetMap through OSMnx | Geometry and tags, not observed traffic; audit completeness and freeze inputs. |
| Resident population | WorldPop population-count GeoTIFF | Freeze product/year and allocation coverage; neither trips nor employment. |
| Hyderabad speeds/capacities/VDF | HMA-2041 CTS historical tables proposed by the plan | Recover a trustworthy report and verify exact tables before adopting values. The recorded mirror was unreliable in the last check. Old calibration is not current ground truth. |
| Alternative capacity profile | Indo-HCM or documented user values | Match road definitions, lane direction, units and conditions. |
| Attraction improvement | Compatible employment, education or HMDA land-use evidence | Planning land use is not measured current job/visit demand. |
| OD observations | Compatible survey/model or supplied OD CSV | No current public ready-to-use Hyderabad matrix has been verified in this project. Do not promise one. |
| Segment times/counts | Licensed probe data or suitable field/agency observations | Access, licence, map matching, direction, coverage and period must match. |
| Public aggregate congestion | TomTom Traffic Index | Broad plausibility only; cannot validate individual pilot roads or recover OD. |
| Assignment methods | Published BPR/conical and user-equilibrium methods | Methods justify model structure, not every local coefficient. |

Source starting points (verify current access in B's review):

- OSMnx: https://osmnx.readthedocs.io/en/stable/user-reference.html
- WorldPop: https://hub.worldpop.org/project/list/
- HMDA CTS: https://www.hmda.gov.in/developdept9/
- Indo-HCM: https://crridom.gov.in/en/indian-highway-capacity-manual
- AequilibraE: https://www.aequilibrae.com/latest/python/static_traffic_assignment.html
- TomTom observations: https://docs.tomtom.com/traffic-stats/documentation/product-information/introduction

Every selected value needs a register entry: name, units, value/range, reference year,
source/table/page or rationale, provenance label, coverage and sensitivity cases. Labels are
`published_standard`, `locally_calibrated`, `adapted`, `project_assumption`; additionally state
whether the actual input was supplied, measured or generated. Availability is not calibration.

## Shared input contract v0 — validate before implementing

This is the initial proposal, not an existing API. Preserve current public CSVs where possible.

**A provides B:** frozen cleaned directed graph, allocated population keyed by graph node,
validated `free_flow_seconds[(u,v,key)]`, graph/cleaning fingerprint, declared settings and an
output directory. Both agents agree on actual Python types before dependent implementation.

**B's module exposes one documented preparation entry point**, for example
`prepare_traffic_inputs(graph, population_by_node, free_flow_seconds, settings, output_dir)`.
Keep settings validation in B's module initially so A can later adapt CLI/config serially.
The function must not mutate the supplied graph/population/time maps.

**B returns paths and metadata for:**

1. `od.csv`: `origin,destination,demand_pcu_h`, compatible with current `_read_od`.
   IDs must be cleaned node IDs. Positive inter-node demand only in this solver file; the
   metadata retains zero/excluded/intrazonal/unreachable mass and reasons. No silent loss.
2. `capacities.csv`: `u,v,key,capacity_pcu_h`, exactly one positive finite value per non-loop
   directed road arc, compatible with `_read_edges`.
3. `zones.csv`: documented zone/anchor IDs, population, production, attraction and attachment
   information. This is audit output, not a physical-road layer.
4. `traffic_input_manifest.json`: input hashes/fingerprint, period, units, sources, source
   years, conversion parameters, capacity/zone coverage, balancing results, exclusions and
   scenario identity. Additional capacity mapping audit tables may accompany it.

**A consumes OD and capacity CSVs in the existing supplied-input mode.** This avoids competing
gravity implementations inside the solver: B handles richer zonal preparation, A handles
assignment. The current simple `gravity_od` mode remains compatible unless both owners agree
to migrate it later. A records the preprocessing manifest/hash in final provenance.

Single global BPR/conical parameters are the v0 assignment contract. If the verified local
profile needs per-arc parameters, propose a versioned extension, and A implements it with
independent tests. Until then, do not claim the ten-class CTS congestion profile is supported.

## What inspection established at the starting baseline

- Existing core supports supplied OD, equal production/attraction gravity over supplied
  node masses, uniform/directed-CSV capacities, BPR/conical assignment and supplied edge times.
- CLI/pipeline exports traffic outputs and supplies congested times to travel-time reliability.
- Highest-flow physical-road closure reassignment exists. Keep compatibility but do not expand
  it before baseline traffic acceptance.
- Automatic population zoning, richer attractions, lane/profile capacity preparation,
  per-class VDF mapping and a calibrated Hyderabad case study are missing.
- Existing distance-Hansen calculations do not automatically consume congested times.
- Focused test run on 13 November 2026: **6 passed, 1 failed** using
  `PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest --noconftest tests/test_traffic.py -q`.
  Failure: `test_pipeline_exports_traffic_and_uses_congested_times` supplies a `Path` as
  `population.worldpop`, whose schema expects a string. Configuration fails before pipeline
  computation. Reproduce and decide the correct API/test fix; do not broadly coerce inputs or
  claim the full pipeline passed from six core tests.

## Checks and completion gates

### Gate 1: independent review and agreed contract

- B completes input review. A reviews solver/integration assumptions.
- Resolve interface and source problems in writing, including inaccessible CTS evidence.
- Agree on scope, file ownership, units, initial scenario and base commit.

### Gate 2: parallel implementation

**A checks:** exact one-road costs, known two-route equilibrium, flow conservation,
parallel/directed arcs, BPR/conical zero-load behaviour, high loading, non-convergence,
supplied-time mapping, invalid inputs and supported closure regressions. Benchmark a known
small network against an independent analytical reference or established solver. AequilibraE
is a comparison target, not an undeclared mandatory new dependency.

**B checks:** deterministic zoning/attachment, mass conservation, separate asymmetric margins,
gravity row/column sums, infeasible/isolated zones, intrazonal/external demand accounting,
directional lane splits, malformed/missing attributes, profile/fallback coverage, ID mismatch,
units and no graph mutation. Use hand-computable fixtures and independent expected values.

### Gate 3: serialized integration

- B hands over a tiny reproducible input preparation example, API documentation and commits.
- A integrates B's reviewed changes, adapts CLI/config/pipeline and records all consumed inputs.
- Run preparation through assignment through exported edge-cost consumption.
- Verify intended consumers use the supplied costs, not merely that a CSV column exists.
- Run traffic-disabled regression checks and the applicable complete offline suite. Record
  environment, exact commands, failures and actual results. Do not treat skipped tests as passes.

### Gate 4: Hyderabad simulation and sensitivity

- Freeze pilot inputs, period and provenance. Compare two zone sizes.
- Run low/base/high demand and at least an alternative capacity/decay scenario. Keep the
  initial experiment matrix manageable; expand combinations only when needed.
- Inspect demand scale, journey lengths/times, V/C distributions, capacity fallback coverage,
  convergence and sensitivity of costs. Later inspect closure-ranking stability.
- If observations exist, calibrate on one subset and evaluate on held-out data. If absent,
  report conservation, convergence and sensitivity, not observed predictive accuracy.
- Name the result accurately: **Hyderabad-informed simulated traffic under declared assumptions**.

## Immediate definition of done

Both agents can reproduce a tested small example and a documented Hyderabad pilot that exports
positive directed edge travel costs, with demand/capacity provenance, convergence evidence,
sensitivity comparisons and explicit limitations. No unrelated branch merge, composite score,
dynamic traffic system or new flood model is required for this milestone.

## Message to send the teammate

> We are doing Tier 4 traffic together. Please give your agent `TRAFFIC_COLLABORATION.md`
> from the updated tier-4 branch. I own the assignment solver and shared CLI/pipeline integration.
> You own demand/zones, capacity-input preparation and source justification in the separate files
> listed there. First independently validate the plan and input contract, and report corrections.
> Then implement your owned module/tests and hand over OD/capacity CSVs plus provenance. Do not
> edit the shared solver/config/CLI/pipeline files in parallel. Use a separate clone/worktree and
> branch. We will integrate after the contract and your tested outputs are ready. The immediate
> goal is justified congested edge travel time, not flooding or a new composite score.
