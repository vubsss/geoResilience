# Presenter notes

Use slides 1–32 for the main presentation. Slides 33–38 are technical backup for questions. There is no imposed time limit; pause on the maps and comparisons rather than reading every equation aloud.

## Speaking points by slide

1. **Title.** Introduce Spatially Abled and the five members. GeoResilient studies structural road resilience, with Hyderabad as the proposed application. This evaluation covers Tiers 1–2.
2. **Problem.** A dense network can still depend on a few roads. Closure can increase distance even when everyone remains connected. We need both network and population measures.
3. **Connecting-road example.** Point to the single connection between two districts. This diagram illustrates the problem; it is not a measured Hyderabad network. Criticality describes consequences, while reliability combines consequences with closure probability.
4. **Scope.** Explain the two tiers. Tickets 01–15 have implementations; the paper comparison reports a mismatch. Facilities, traffic and Ticket 16 are beyond this evaluation.
5. **Data.** Roads come from OSM; WorldPop provides estimated population counts; polygons define reporting zones. Published historical graphs support comparison. Synthetic graphs permit arithmetic checks with known answers.
6. **Evidence.** Separate the saved local demo from recorded earlier Malé and historical-city experiments. The full Hyderabad case study is still an application to perform. Do not call the synthetic maps Hyderabad wards.
7. **Pipeline.** Follow the arrows from roads through cleaning, metrics and disruption, then population, zones and reporting. Seeds, parameters and coverage are recorded to make a run traceable.
8. **Graph.** Junctions are nodes. Simplification merges road shape segments without discarding their length/geometry. Closing a two-way physical road removes both directed arcs. Clipping can create artificial boundary dead ends.
9. **Centrality.** Describe closeness as proximity, betweenness as mediation, straightness as route directness, and information as sensitivity of efficiency to removing incident links. Distribution-based labels are heuristic; the small demo is inconclusive.
10. **Redundancy and criticality.** Ask whether a closed road has an alternative, and how long that detour is. A bridge has no alternate connection. Inverse-distance efficiency counts unreachable pairs as zero.
11. **Cumulative disruptions.** Targeted attacks remove high-ranked roads; failures remove random roads. Largest strongly connected component (SCC) and efficiency answer different questions. AUC summarizes the tested range, not the final ordinate alone.
12. **Reliability.** Repeatedly sample independent road closures, then average connectivity. User probabilities are supported; otherwise length supplies an explicit proxy. This is not a calibrated flood or traffic prediction.
13. **Accessibility.** Hansen accessibility sums opportunities weighted by exponential distance decay. A closed road can reduce access by forcing a detour even without disconnecting destinations. Explain the decay length and cutoff.
14. **Population and zones.** Population cells are allocated to nearby graph nodes with a maximum snap distance. Unallocated population is reported. Zone polygons summarize nodes and road geometry; empty zones remain visible.
15. **Weighting distinctions.** Destination population weights Hansen opportunities; pair products weight connectivity/efficiency; retained population describes residents in the main SCC; resident weights aggregate structural loss by zone. These definitions should not be interchanged.
16. **Known example.** Nine nodes, twelve physical roads, 1.2 km and 45 synthetic residents give independently checkable totals. West has 27 residents; East has 18. Coordinates are schematic local geography.
17. **Connected does not mean unaffected.** SCC remains 1.0 after two road closures, but relative efficiency falls to 0.8729 under attack and 0.8951 on average under random failure. Two of twelve roads is 16.67%; the dotted plateau extends to the requested 20% for AUC. Only two failure runs were used in this demo.
18. **Critical-road ranking.** Link IDs connect the ranked output to the map. Links 11, 10 and 9 have equal structural loss here but different population-weighted consequences. These are separate single-road closures.
19. **Accessibility loss.** Population destinations increase mean loss from 23.51% to 30.84% and p90 from 27.27% to 41.09%. All twelve road closures were evaluated; the distance parameters belong to this example.
20. **Node vulnerability.** Geography helps explain which junctions depend on limited approaches. Structural and population variants can rank nodes differently. Use node IDs to link the picture to the exported table.
21. **Reliability numbers.** The high values reflect short roads and the selected independent closure model. With p0=0.2 per kilometre, a 100 m road has about 2.21% closure probability. The confidence interval reflects sampling uncertainty, not uncertainty in hazards or population estimates.
22. **Zone tradeoff.** East ranks higher by resident-weighted structural loss, but West has greater expected population cut off. Relative severity and absolute people affected can therefore suggest different priorities. These zone losses are not simply averages of the population-destination vulnerability field.
23. **Scorecard.** Show each dimension separately. The composite 0.8715 is an example with explicit user weights, not a default universal rating. Missing metrics preserve their reasons instead of silently becoming zero.
24. **Recorded Malé experiment.** This prior experiment tested real roads and WorldPop allocation. Increasing the snap distance from 100 m to 500 m removes unallocated cells in the recorded example. Full allocation is not proof of more accurate assignment; a longer snap can cross spatial barriers. Raw earlier outputs were not available in this checkout.
25. **Historical comparison.** Four authors' graphs improve comparability with the paper. Information matches 2/4 cities and betweenness 3/4; the criterion requires at least 3/4 in each, so the outcome remains MISMATCH. Report that outcome honestly rather than changing fitting thresholds.
26. **Validation.** The implementation log records 341 passed and 5 skipped in the full offline suite, plus 42 focused tests after the final changes. Independent checks cover totals and results, and saved pre/post outputs agree for existing behaviour. Passing tests does not establish real-world predictive validity.
27. **Observations.** Connect the earlier evidence: connectivity can hide detour loss, population changes priorities, zone ranking depends on the question, and a larger snap radius changes data coverage.
28. **Limitations.** Closure independence, the length proxy, boundaries and population estimates limit interpretation. No full-city Hyderabad, actual facility-access or traffic conclusions are claimed.
29. **Progress.** Explain the implemented ticket groups and the new zone/report work. Tickets 13–14 are automatically verified and committed; user manual review is pending. Ticket 15's research discrepancy remains open although its computation and comparison were implemented and reviewed.
30. **Next work.** Apply and inspect the pipeline on the Hyderabad boundary, validate coverage and sensitivity, and investigate the historical mismatch. Facility opportunities and traffic are later tiers. Ticket 16 is deferred. These are proposed next steps, not edits to the existing project plan.
31. **Demo.** Trace one ranking from report to map and underlying layer. Show missing-metric reporting. Use saved outputs if live execution is unavailable; avoid an unplanned OSM download during evaluation.
32. **References.** Link the literature to disruption, centrality and accessibility. Mention that each result slide points to its source and the package includes provenance.
33–38. **Appendix.** Use only as needed: metric formulas; population weighting and sampling; conditional travel-time reliability; normalisations; historical fit interpretation; evidence locations.

## Demonstration sequence

1. Open `results/ticket14-demo/user-weighted/report.txt` and its scorecard. Explain the explicit weights and component scores.
2. In QGIS open `results/ticket14-demo/population/network.gpkg` and `zones.gpkg`. Show link 11, node 6 and the West/East rows; use feature IDs and coordinates.
3. Compare the uniform and population summaries. Distinguish destination weighting from pair weighting.
4. Open `results/ticket14-demo/missing-metrics/report.txt`. Show a unavailable metric and its reason.
5. If a live run is wanted, use the one-line uniform command in README. The application/environment must be installed. Saved outputs remain an offline fallback.

Packaged copies are under `evidence/` with the same four run names. Input GraphML, synthetic raster and zones are also included there. Their inclusion preserves existing files; it does not constitute a fresh run.

## Likely questions

- **Why demonstrate Malé when the proposal names Hyderabad?** The recorded smaller real-data experiment validated population ingestion/allocation. It is supporting evidence; Hyderabad remains the intended application.
- **Are these population numbers actual residents of Hyderabad?** No. The nine-node example has a synthetic raster with a known total of 45. WorldPop results on slide 24 are explicitly recorded real-data validation.
- **Why is robustness perfect while efficiency declines?** The SCC score measures reachability. Routes within that reachable component can become longer, reducing inverse-distance efficiency.
- **How can a reliability value near one be useful?** It reflects the chosen probabilities and topology, and enables consistent comparisons. Its value should not be interpreted as a city's chance of surviving a flood without calibrated hazards.
- **Does Ticket 15's mismatch mean the software failed?** The comparison completed. It failed the predefined scientific match criterion, while numerical consistency checks were satisfactory. Distribution choices and methodological differences still require investigation.
- **Does every ticket have final acceptance?** Tickets 13–14 await manual review in the current log. Ticket 15's comparison was reviewed, but its classification discrepancy remains open. Avoid claiming everything is fully accepted.
- **Why no one overall resilience rating?** A weighting scheme embodies priorities. The framework exposes dimensions and allows explicit user weights; it does not impose a universal composite.
- **Are essential-service or travel-time results already available?** Essential-service analysis is future work. Travel-time reliability is implemented but runs only with suitable speed/travel-time data; unavailable inputs produce a documented skip.
