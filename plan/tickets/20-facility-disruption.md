# 20 - Facility-access disruption, road rankings and Indian validation

**What to build:** single-road closure impacts on 2SFCA and service coverage, with
per-service critical-road rankings and a frozen, reviewable Indian worked example.

**Blocked by:** 19, 04 and 05 (existing screening and physical-link closures).

**Status:** planned; not started.

**Methodology:** [Tier 3 plan](../TIER3.md). This ticket includes result interpretation
and real-data sensitivity checks; it does not introduce traffic or hazard models.

## Work

- Close a physical road and all associated directed/split arcs. Keep demand, facilities and
  attachment locations fixed. Recalculate facility catchment demand, ratios and origin scores.
- Compute population-weighted positive losses and gains separately, demand with declining
  scores, newly zero-access demand, stranded supply and changes in nearest-time/coverage.
- Rank roads per service by `sum_i P_i max(0, A_i_baseline - A_i_closed)`. Optionally normalize
  by baseline population-weighted accessibility; zero denominators remain undefined.
- Record per-origin worst positive loss over evaluated closures with the responsible link.
  Preserve the distinction between accessibility loss, gains and actual service utilisation.
- Use structural candidates plus facility attachment/access roads, with explicit reasons and
  an all-links option. Export coverage and leave unevaluated road damage missing.
- Start with full facility recomputation for correctness. Optimize only against this reference;
  Hansen affected-origin and analytic-bridge logic is not automatically valid for changing ratios.
- Freeze a small Indian example chosen after 17's audit. Compare official-led and OSM-only
  inventories, supply conventions, threshold, consolidation/attachment settings and buffer extent.
  Quantify changes in coverage and leading road ranks; report limitations and runtime/resources.

## Deliverables

- Per-service critical-road tables, origin vulnerability scores and facility-impact summaries.
- Damage/zero-access maps, summary/report sections and documented evaluated-link scope.
- Frozen input manifest, rerunnable offline example and an inspection guide. Respect source
  reuse conditions; use locally supplied files where raw exports cannot be redistributed.
- Update implementation status with actual checks and residual limitations, keeping optional
  follow-up experiments distinct from completed evidence.

## Acceptance criteria

- [ ] A known-answer closure makes one group lose access and another group's score rise;
  the loss metric captures harm even when the full-domain weighted mean is unchanged.
- [ ] Recomputing only origin paths with frozen facility ratios demonstrably fails a fixture;
  the implemented method matches full two-step recomputation.
- [ ] Newly zero-access demand excludes origins already at zero. Tolerances and baseline-zero
  relative losses are handled explicitly; stranded supply is reported without infinite ratios.
- [ ] Physical closures respect overlay lineage, parallel alternatives and both service directions.
- [ ] Candidate results match exhaustive evaluation on the same evaluated roads; missed high-impact
  roads are quantified on a small exhaustive benchmark, and the shortlist is adjusted if needed.
- [ ] Conservation is checked over full-domain demand in baseline and closure scenarios;
  reporting-subarea averages are not incorrectly assumed constant.
- [ ] At least one frozen Indian real-data example reruns offline with provenance, maps and
  documented source/attachment/threshold/buffer sensitivity. Synthetic examples alone do not
  satisfy this criterion; unavailable official data remains a recorded limitation/blocker.
- [ ] Existing regression checks pass and memory/worker limits are respected.
