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

Next: CN-T02.
