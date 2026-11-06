# Critical nodes implementation handoff

Each ticket gets a separate goal and commit. After committing, use this record
and the next ticket's acceptance criteria as the fresh working scope.
The ignored plan/ticket files remain the dependency specification.

## CN-I01 — Contracts and configuration

Implemented optional typed service settings, CLI flags, canonical string-ID CSV
records and strict row diagnostics; documented mode, unit, catchment, capacity,
provenance and zero-supply policies in DESIGN.md. No service input remains opt-in.
Verified: CSV/string-ID/zero-capacity and JSON smoke checks; 29 existing CLI/input
regressions passed. CN-I01 complete.

## CN-T01 — Contract tests

Complete: 72 focused input/CLI tests passed, including no-service regressions,
invalid headers/IDs/numbers, units, provenance, catchments and real CLI errors.


## CN-I02

Complete: Canonical records attach with projected metre coordinates, inclusive snap limits and stable node-ID ties; distinct facilities and per-type coverage/provenance retained. Smoke checks passed for co-location, zero snap limit, independent totals and graph non-mutation.


## CN-T02

Complete: 70 focused facility/cleaning tests passed. Exact limits, projections, coincident/equidistant IDs, co-location, totals, shuffled rows, unknown capacity and consolidated graph attachment checked. Fixed missing-CRS diagnostics exposed by the tests.


## CN-I03

Complete: Count importance and category node fields implemented independently of capacity. Directed P_i*w_j reachability and length Hansen include co-location and preserve original closure denominators; independent numeric smoke checks passed.


## CN-T03

Complete: 51 service-weight and existing baseline/population tests passed. Explicit directed path enumeration checks diagonals, zero masses, fixed denominators, category coefficients and capacity scaling. Fixed transit through an isolated node exposed by the oracle.


## CN-I04

Complete: Extracted reusable seconds topology with link closures, retained node isolation, transpose queries and budgeted static reductions. Missing times remain unavailable; dynamic custom providers explicitly rejected for 2SFCA. Existing time/reliability regression suite passed.


## CN-T04

Complete: 72 shared-time and existing provider/reliability tests passed. NetworkX oracle verifies direction, transpose, fastest parallel arcs, reciprocal-link closure, isolated nodes, inclusive seconds cutoff, serial/parallel small blocks, invalid costs, unavailable speeds and dynamic rejection.


## CN-I05

Complete: Implemented standard per-category 2SFCA in two bounded transposed passes with separate facility ratios, raw/per-1000 summaries and explicit absent, zero-population, zero-demand, zero-supply and missing-time policies. Numeric co-location/closure smoke checks passed.


## CN-T05

Complete: 25 2SFCA/routing tests passed. Independent NetworkX oracle verifies paper ratios 1/8, 1/4 and overlap 3/8; capacity/population scaling, conservation, independent types, co-location, raw values above one, zero demand/supply, unavailable states and bounded worker consistency.


## CN-I06

Complete: Expanded paired candidate rules for positive-weight service nodes and incident links. Closure recomputation publishes category shortfall, newly unserved share, damaged means, signed raw mean changes, combined losses, evaluated flags/reasons and deterministic rankings. Existing closure suites plus smoke checks passed.


## CN-T06

Complete: 25 criticality and existing closure tests passed. Every local closure matches independent full NetworkX recomputation; competition gains do not cancel shortfall; node supply/demand semantics, road co-location, category baselines, exact screened/all candidates, null omissions and rankings verified.


## CN-I07

Complete: Added original service share/AUC in the same attack SCC and directed P_i*w_j reachability/time reliability on existing event draws and p0 sweeps. Existing attack/time/reliability regressions and certain-closure co-location smoke checks passed; disabled public outputs unchanged.


## CN-T07

Complete: 56 service/event/attack tests passed. Independent seeded-event oracle confirms original P_i*w_j demand and exact directed/co-located outcomes. Old views/order unchanged, worker/p0 consistency, SCC ties, conditional CSV, raw AUC, zero masses and confidence bounds verified.

Next: CN-I08 (include user-requested optional population with uniform demand fallback).
