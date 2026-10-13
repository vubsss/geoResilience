# 19 - Baseline directed 2SFCA and service coverage

**What to build:** original travel-time-cutoff 2SFCA for a declared facility service,
supply unit and demand layer, plus maps and diagnostics that explain the resulting scores.

**Blocked by:** 18 and 10 (existing replaceable travel-time models).

**Status:** planned; not started.

**Methodology:** [Tier 3 plan](../TIER3.md). This ticket owns the intact baseline;
road-failure experiments belong to 20.

## Work

- Add opt-in service configuration: eligible facilities, supply convention/unit, demand,
  network mode, travel-time provider, connector costs and threshold. Record all assumptions.
- Implement `D_j = sum_i P_i B_ij`, `R_j = S_j / D_j` for positive `D_j`, and
  `A_i = sum_j B_ij R_j`. Include trips exactly at the threshold and co-located origin/supply.
- Use population-to-facility direction for hospitals/schools; facility-to-population for fire
  stations. Both steps use the same incidence relation. Reuse bounded-memory routing with
  searches from facilities/reversed facilities; do not require a dense all-pairs matrix.
- Explicitly handle zero-demand facilities, zero-access origins, missing supply, unallocated
  demand, empty service inventories and incompatible travel modes. Real 2SFCA requires demand;
  an empty/unknown inventory must not be presented as verified absence of services.
- Report nearest-facility travel time, reachable-facility count, zero-access demand, threshold
  coverage and facility catchment demand. Distinguish within-threshold and network-unreachable.
- Keep school levels and hospital supply units separate. Fire diagnostics are travel proxies,
  with dispatch delay, traffic and emergency access exemptions outside the initial model.

## Deliverables

- Proposed `src/georesilience/facility_accessibility.py`, integrated into the pipeline.
- Per-service origin scores and facility catchment ratios, with coverage/accessibility maps.
- `summary.json`, `report.txt` and resolved config showing demand/supply totals, units,
  thresholds, mode, analysis extent, boundary quality and provenance. Use normalized tables
  for multiple services/thresholds and expose aligned scores on existing nodes where suitable.
- An offline known-answer demo and interpretation documentation alongside Hansen outputs.

## Acceptance criteria

- [ ] Hand calculations with overlapping catchments and unequal supply/demand match exactly
  within tolerance, including co-location and threshold equality.
- [ ] An asymmetric one-way fixture distinguishes hospital access from fire-response direction.
- [ ] No division by zero; uncomputed values remain missing, while verified no-access is zero.
- [ ] `sum_i P_i A_i = sum_{j:D_j>0} S_j` over the complete modelled demand domain.
- [ ] Independent NetworkX calculations match on small spatial graphs with connector costs.
- [ ] Equal-supply versus capacity results are labelled correctly; school-age/proxy demand
  and reference year appear in reports rather than being inferred from enrolment.
- [ ] Bounded-memory and worker-count checks preserve results; outputs and offline demo work.
- [ ] Existing Tier 1-2 runs remain unchanged with the feature disabled.
