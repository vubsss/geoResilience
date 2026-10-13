# Tier 3: facility accessibility and road criticality

Planning baseline: 13 October 2026. Branch: `tier-3`.
Status: planned; no Tier 3 implementation or data acquisition is claimed here.

## Objective

Extend the consolidated road network with real service locations and population demand.
Calculate two-step floating catchment area (2SFCA) accessibility, then identify residents
and facilities affected by road closures and the roads whose loss causes the greatest harm.
Keep hospital, fire-service and school results separate: their supply units differ.

This document supplements [DESIGN.md](DESIGN.md) for Tier 3. Tickets 17-20 below are the
implementation backlog. Tier 3 is opt-in; existing Tier 1-2 runs keep their behaviour.

## Scope and implementation order

1. Audit a small Indian study area using official facility records and OSM.
2. Build a source-independent facility registry and attach it to the consolidated network.
3. Implement original, travel-time-cutoff 2SFCA and baseline coverage diagnostics.
4. Recalculate accessibility under single physical-road closures and rank impacts.

Audit schools and hospitals first. Prefer UDISE+ as the school reference inventory; use
official hospital inventories where usable. Select the first real worked example after
checking data access, location quality and supply completeness. Equal-supply facilities
are a valid initial model if explicitly labelled. Fire stations share the same pipeline.

Not in this tier: traffic assignment, congestion feedback, recovery simulation, automatic
hazard-derived closures, exhaustive two-road failures, or a combined cross-service score.
Distance-decay/E2SFCA variants are follow-up work after validating original 2SFCA.
Zone summaries can later reuse Ticket 13; they are not a dependency for these tickets.

## Facility sources for India

| Service | Preferred inventory to investigate | OSM role | Supply and demand |
| --- | --- | --- | --- |
| Schools | UDISE+ school directory/GIS and school-level exports | Match sites, footprints and entrances; flag additional candidates | Student places where documented; otherwise equal supply or a separately labelled resource proxy. Demand: resident school-age population. |
| Hospitals | National Hospital Directory; investigate ABDM HFR and relevant state directories | Supplement inventory and geometry; cross-check locations | Physicians or beds in separate models; otherwise equal supply. Demand: resident population. |
| Fire stations | Relevant state/city fire-service directory where obtainable | Supplement or initial inventory | Available appliances/crews where documented; otherwise equal supply. Demand: population proxy, not incident demand. |

Official does not mean complete, current or positionally accurate. Audit reference year,
operational status, coordinate validity, public/private scope and local completeness.
Public map access does not imply a bulk export or API is available. Support local
CSV/GeoPackage imports from the beginning; do not make the pipeline depend on scraping.

UDISE+ documents school locations and school characteristics. Its data-sharing portal has
registration/request access. Verify the obtainable export's fields, academic year,
coordinates and reuse conditions before committing to automated acquisition. Use school
aggregates, not individual student records. Store UDISE codes as strings.

The hospital directory is a candidate geocoded source, not a verified usable extract yet.
HFR includes facility types beyond hospitals; verify access and filter types explicitly.
Neither hospital source is assumed to provide complete capacity data.

OSM extraction uses nodes, ways and relations with `amenity=hospital` or
`healthcare=hospital`, `amenity=fire_station`, and `amenity=school`. Exclude explicitly
inactive facilities and retain uncertain status for review. A building-type tag alone is
not proof of an operating service. OSMnx tag queries return a union of matching tags.

## Common facility registry

Preserve raw source files and map them to a stable internal registry containing:

- Facility identity, service category/subtype, name and operational status.
- Source name, source identifier, reference year, retrieval date and file hash.
- Original geometry, coordinate CRS and chosen service-access location.
- Supply value, unit, source and convention; missing values remain missing.
- Matching/deduplication decisions, confidence and any manual overrides.

Match by official identifier when available, then by name/address, distance and site
containment. Proximity alone must not merge facilities. Official-only facilities remain
eligible; OSM-only entries are labelled supplementary candidates until resolved. Separate
institutions on one campus or at one road node retain their identities. Keep attribute-level
provenance when location and supply come from different sources.

Audit eligible official records, valid coordinates, OSM matches, unmatched records and
supply completeness. The OSM match fraction is coverage relative to the chosen reference
inventory, not an estimate of all facilities in existence. Align years and service definitions.

Supply modes are explicit per service:

- `equal`: one unit per eligible facility, reported as facilities per person.
- `capacity`: a single documented unit, with external overrides and explicit missing-data
  handling. Never silently mix actual bed counts with one-unit defaults.
- Resource/enrolment proxies require their own labels and sensitivity comparisons.

Enrolment is observed use, not available student-place capacity. School enrolment also does
not locate residential demand. Separate primary/secondary provision and eligible demand;
total population may be used only as a disclosed exploratory proxy.

## Consolidation, attachment and analysis extent

Use two distinct operations: consolidate road junctions; reconcile facility records.
Facility attachment happens after road consolidation and before accessibility computation.
Retain original-road-node to consolidated-node lineage, plus mappings for physical links.

Prefer a mapped usable entrance; otherwise choose a representative location and record the
fallback. The initial attachment mode is nearest eligible consolidated node with a maximum
distance, deterministic ties and an exported connector. Never force an unmatched facility
onto a distant or disconnected road.

Before interpreting city-scale results, implement and compare attachment to an eligible road
edge for facilities midway along long simplified roads. Use an auxiliary routing overlay:
structural centralities and physical closure identities remain unchanged. Edge splits inherit
their parent physical-road closure, preserve travel direction and partition its travel cost.
Nearby roads separated by barriers/grade or inaccessible campus boundaries require checks;
a short straight connector is an approximation, not evidence of legal access.

Allocate population using the existing raster/allocation machinery with declared demand
weights. Report unallocated demand and missing facilities separately from measured zero
accessibility. Include explicit study/analysis boundaries for offline GraphML/XML runs;
the present population configuration cannot yet support those inputs.

Separate the reporting polygon from a larger analysis extent. Roads, facilities and demand
must cover outside facilities and the people competing for their supply. Demand may need a
wider extent than the facilities contributing to reported origins. Use configurable buffers
and compare increasing extents; do not claim a universal buffer width eliminates edge effects.

The current cleaner keeps the largest strongly connected component. For facility routing,
retain the relevant consolidated components in an auxiliary view before that pruning, so
isolated populations are not dropped or snapped across disconnected components. Preserve the
existing structural graph and disclose the facility routing view's different scope. Export
demand origins outside the structural graph in a separate layer with traceable identifiers.

## Original 2SFCA definition

For one service and one supply unit, let `P_i` be demand, `S_j` supply and `T` the configured
travel-time threshold. Define `B_ij = 1` when the required directed trip takes at most `T`,
including declared connector time, and `0` otherwise. Then:

```text
D_j = sum_i P_i * B_ij
R_j = S_j / D_j                    when D_j > 0
A_i = sum_j B_ij * R_j             over facilities with D_j > 0
```

Flag facilities with `D_j = 0` as having no reachable positive demand. Their ratio is undefined
and they contribute no score; never divide by zero. A valid demand origin with no reachable
eligible supply has `A_i = 0`. Missing/uncomputed inputs are not zero. A co-located origin
and facility is included; do not inherit Hansen's exclusion of the self term.

Use population-to-facility travel for hospitals/schools and facility-to-population travel for
fire response. Both steps must use the same directed incidence relation. Reversed-graph
searches from hospitals can efficiently find incoming demand; ordinary outbound searches
serve fire stations. Use bounded-memory facility searches, not a dense all-pairs matrix.

Reuse travel-time providers rather than the distance-only Hansen reducer. Declare network
mode, speed assumptions, connector costs, threshold and units per run/service. Schools need
an explicit walking or transport model; vehicle free-flow speeds cannot stand in for walking.
Fire response initially respects the selected directed graph and is labelled a travel-time
proxy without dispatch delay, traffic or special emergency-vehicle exemptions. Thresholds
are configurable and tested for sensitivity, not presented as Indian service standards.

Require explicit nonnegative demand for real 2SFCA; do not silently substitute one person
per junction. Baseline diagnostics include nearest-facility time, reachable-facility count,
zero-access demand, demand within threshold, facility catchment demand and supply units.

## Road failures and interpretation

Remove one physical link, including all its directed arcs and inherited routing segments.
Keep facility identities, attachments, population and total demand fixed between scenarios.
Recompute both catchment demand and accessibility; do not freeze `R_j` after a closure.

With consistent catchments over the full modelled demand domain:

```text
sum_i P_i * A_i = sum_{j: D_j > 0} S_j
```

Consequently, the population-weighted average can remain constant when some people lose
access and others face less competition. This identity is a validation check, not the main
damage metric. It does not imply a fixed average over a reporting subarea with outside demand.

For each closure `e`, report separately:

- Positive accessibility loss `L_e = sum_i P_i * max(0, A_i - A_i_after_e)`.
- Positive gain `G_e = sum_i P_i * max(0, A_i_after_e - A_i)`.
- Demand experiencing decline and newly falling from positive to zero accessibility.
- Capacity with no reachable positive demand, nearest-time changes and coverage changes.

Rank roads per service by `L_e`; optionally normalize by baseline `sum_i P_i * A_i`, returning
undefined if that denominator is zero. These scores measure potential spatial access, not
observed users or actual patient/student displacement. Define numerical tolerance explicitly.

Start with existing structural candidates plus facility attachment/access roads. Compare
against exhaustive single-link closures on a small frozen study area. Export evaluated
link IDs, reasons and coverage; unevaluated links have missing damage values. Do not reuse
Hansen's local-update/analytic-bridge shortcuts without a separate correctness proof:
changed facility ratios can affect residents whose own paths did not change.

## Outputs and validation

Reuse `network.gpkg`, `summary.json`, `report.txt` and `run_config.yaml`. Add facility,
attachment and demand-origin layers, with a normalized service-score table where multiple
services/thresholds are requested. Expose scores for existing structural nodes where aligned.
Export data-quality counts, boundaries, provenance, supply conventions, routing assumptions,
baseline coverage, closure rankings and maps. Every new parameter is recorded in the resolved
configuration. Put frozen real-data inputs/manifests in a reproducible example with an
offline rerun; large or restricted datasets need not be committed to Git.

Validation progresses from hand-calculated networks to an independent NetworkX reference
and a small Indian real-data example. Cover directional reachability, cutoff equality,
co-location, duplicates, missing capacity, disconnected demand, zero demand, component
pruning, attachment sensitivity and closures that improve some scores. Compare buffer,
threshold and supply assumptions. Use the conservation identity over the full demand domain.
No network access in ordinary tests. Existing Tier 1-2 results must remain unchanged when
Tier 3 is disabled. Record checks actually performed separately from planned acceptance.

## Broad tickets

| Ticket | Deliverable | Dependencies |
| --- | --- | --- |
| [17: Facility sources and registry](tickets/17-facility-sources-and-registry.md) | Official/OSM imports, reconciliation, small-area coverage and supply audit | Existing input infrastructure (02) |
| [18: Network attachment and demand](tickets/18-facility-network-and-demand.md) | Consolidation lineage, routing attachments/components, demand and buffered extent | 17; existing cleaning/population (02, 12) |
| [19: Baseline 2SFCA](tickets/19-facility-2sfca.md) | Directed cutoff algorithm, baseline diagnostics and maps | 18; existing travel-time models (10) |
| [20: Facility disruption and validation](tickets/20-facility-disruption.md) | Closure impacts, per-service road rankings and frozen Indian example | 19; existing screening/physical closures (04, 05) |

Tickets 13-16 are not new blockers. Tickets remain broad; each owns its configuration,
documentation, outputs and relevant verification. Data access uncertainty in 17 should not
prevent offline implementation with representative synthetic fixtures, but a synthetic
import does not establish successful acquisition of the official Indian data.

## References and access checks

- Luo and Wang (2003), *Measures of Spatial Accessibility to Healthcare in a GIS Environment:
  Synthesis and a Case Study in Chicago Region*, DOI [10.1068/b29120](https://doi.org/10.1068/b29120).
  Local paper: [VNB1-accesibility.pdf](../papers/VNB1-accesibility.pdf).
- [UDISE+](https://www.udiseplus.gov.in/),
  [School GIS](https://schoolgis.udiseplus.gov.in/), and
  [Data Sharing Portal](https://microdata.udiseplus.gov.in/).
- [National Hospital Directory with Geo Code](https://www.data.gov.in/resource/national-hospital-directory-geo-code-and-additional-parameters-updated-till-last-month).
- [ABDM HFR](https://facility.abdm.gov.in/) and
  [official description of registry scope](https://www.pib.gov.in/PressReleasePage.aspx?PRID=2288848&lang=1&reg=1).
- [OSMnx feature extraction and consolidation](https://osmnx.readthedocs.io/en/stable/user-reference.html).
- OSM tags: [hospital](https://wiki.openstreetmap.org/wiki/Tag:amenity%3Dhospital),
  [fire station](https://wiki.openstreetmap.org/wiki/Tag:amenity%3Dfire_station),
  [school](https://wiki.openstreetmap.org/wiki/Tag:amenity%3Dschool).

Portal discovery and documentation were checked during planning on 13 October 2026.
Bulk access, actual export schemas, local completeness and capacity fields remain checks
for Ticket 17; none is asserted available merely because a portal exists.
