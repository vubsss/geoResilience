# 17 - Facility sources, reconciliation and India data audit

**What to build:** a common school/hospital/fire-station registry from official files and
OSM, with a small Indian study-area audit that establishes usable sources and supply fields.

**Blocked by:** 02 (existing input infrastructure).

**Status:** planned; not started.

**Methodology:** [Tier 3 plan](../TIER3.md). This ticket owns acquisition and facility
identity; road attachment belongs to 18.

## Work

- Accept local CSV/GeoPackage inventories with explicit column/CRS mappings and retain raw
  inputs, hashes and source metadata. Add cached OSM feature extraction and an offline input.
- Prefer UDISE+ for school identity/inventory. Verify school-level export access, coordinates,
  academic year and reuse conditions. Record how an actual export is obtained; registration
  or a data request is an external prerequisite, not a reason to invent an API.
- Inspect the National Hospital Directory; investigate HFR/state directories as alternatives
  or cross-checks. Record unavailable fields and access constraints. Investigate a local
  fire-service inventory; support OSM-only inputs if no usable official source is obtainable.
- Preserve source IDs as strings, operational status, service level, management, geometry,
  reference year and attribute-level provenance. Validate coordinates and record rejects.
- Reconcile official and OSM records using IDs where present, then contextual matching.
  Support a review/override file; do not silently merge ambiguous matches or nearby schools.
- Provide explicit equal-supply and single-unit capacity modes, with missing-supply policy.
  Keep enrolment distinct from capacity and teachers/classrooms as labelled resource fields.
- Audit school and hospital samples against OSM. Select and justify the first worked service
  based on access and data quality, without assuming official inventories are exhaustive.

## Deliverables

- Import/extraction configuration and a registry suitable for later pipeline stages.
- Registry GeoPackage, match/reject tables and a coverage/supply audit with a comparison map.
- Provenance manifest and source-access notes; fixture-based offline demo.
- Proposed code home: `src/georesilience/facilities.py` with adapters separated as needed.
  Command/config names are chosen during implementation and documented as new capabilities.

## Acceptance criteria

- [ ] Official-only and OSM-only facilities survive with source/status flags.
- [ ] Duplicate point/site representations resolve reproducibly; separate institutions sharing
  a site remain separate. Ambiguous matches are exported for review.
- [ ] Leading-zero IDs survive; invalid coordinates and missing supply are reported.
- [ ] Equal supply and capacity units cannot be silently mixed; enrolment is not called capacity.
- [ ] Cached/offline reruns reproduce the registry and audit; ordinary tests make no HTTP calls.
- [ ] Real-data audit records eligible counts, valid-coordinate counts, OSM matches, supply
  completeness, dates and selection decisions. If access is unavailable, clearly record the
  external blocker and keep this criterion open; synthetic data does not satisfy it.
