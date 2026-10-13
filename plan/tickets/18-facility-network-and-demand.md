# 18 - Consolidated-network attachment, demand and boundaries

**What to build:** traceable facility and population attachments to a routing view built
from the existing consolidated roads, including disconnected demand and boundary context.

**Blocked by:** 17, 02 and 12.

**Status:** planned; not started.

**Methodology:** [Tier 3 plan](../TIER3.md). This ticket supplies the routing/demand contract
used by 19, without changing existing structural metrics when Tier 3 is disabled.

## Work

- Expose original-to-consolidated node lineage and physical-link mappings. Keep facilities
  separate from junctions and from each other even when their routing attachment is shared.
- Select usable entrances where mapped, with a documented representative-location fallback.
  Add nearest-eligible-node attachment with distance limit, deterministic ties and connectors.
- Add an edge-attachment routing overlay for long simplified roads. Partition costs by
  distance, preserve arc direction/parallel alternatives, and associate every split road
  segment with its parent physical closure. Connectors are not free or independent supplies.
- Check access eligibility and flag ambiguous barrier/campus cases. Retain rejected/far
  facilities in audit outputs; do not force attachment across disconnected components.
- Retain relevant consolidated components before largest-SCC pruning in a facility routing
  view. Keep the existing structural graph intact and map shared nodes/links explicitly.
- Reuse population raster allocation against this routing view. Report allocated/unallocated
  demand. Support a declared school-age demand input; a total-population school proxy is an
  explicit exploratory choice, not the default interpretation of school accessibility.
- Separate reporting and buffered analysis boundaries. Include competing outside demand
  and test growing extents. Add explicit boundaries for offline XML/GraphML population runs.
- Define mode-compatible edge and connector travel times, including walking where requested.
  Require graph/provider compatibility; never silently use vehicle speeds for a walking run.

## Deliverables

- Facility attachment and demand-origin layers, connectors and consolidated-node lineage.
- Attachment/component/allocation audit in summary/report and resolved configuration.
- Buffered acquisition/offline-boundary support and a small overlay inspection example.
- Reuse `network.py`, `population.py` and `time_models.py`; isolate overlay logic in a dedicated
  module if it would otherwise complicate structural analyses.

## Acceptance criteria

- [ ] Consolidated IDs are traceable, and shared attachments do not merge facility identities.
- [ ] Attachment limits, tie handling, entrance fallback and connector cost are reproducible.
- [ ] A facility midway along a long road demonstrates node-versus-edge attachment sensitivity.
- [ ] One-way/parallel-edge fixtures preserve legal direction and total split-road costs;
  closing a parent physical road removes all its inherited routing segments.
- [ ] Disconnected demand is retained as an origin and cannot be snapped onto another component
  merely because the structural graph discarded its component.
- [ ] Allocated plus unallocated demand equals input demand within numerical tolerance;
  school demand convention and uncovered boundary context are reported.
- [ ] A boundary-crossing fixture includes outside supply and competing outside demand.
- [ ] Tier 3 disabled preserves existing cleaned graphs and outputs.
