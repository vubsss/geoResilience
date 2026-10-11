# 15 — Crucitti replication (validation layer 3)

**What to build:** a scripted validation that runs the pipeline on 1 square mile samples of cities used by Crucitti, Latora & Porta. It checks that our classification reproduces their **qualitative** pattern:
- self-organised cities: information centrality is a power law and betweenness is exponential;
- planned cities: information centrality is exponential and betweenness is Gaussian.

It writes its own report, which can be cited in the project write-up.

**Blocked by:** 07

**Status:** implemented, tested and manually reviewed, including the published-data rerun.
The planned-city classification discrepancy remains open.
Both modern and published-data comparisons returned MISMATCH; the published graphs improve
agreement to information 2/4 and betweenness 3/4 under both conventions. See TICKET_UPDATES.

## Behaviour

### Samples
For the modern OSM baseline, each sample is a square 1609 m × 1609 m, centred on the point below. Build it as a projected square buffer around the point, then pass it as a `polygon` input. The historical windows have not been geographically registered, so these are approximate historic centres (self-organised) and downtown grids (planned). The authors' published historical graphs were subsequently located; see the separate comparison below.

| City | Class (paper) | Centre (lat, lon) |
|---|---|---|
| Ahmedabad | self-organised | 23.0225, 72.5880 (old walled city) |
| Cairo | self-organised | 30.0478, 31.2625 (historic Cairo, Khan el-Khalili) |
| Los Angeles | planned | 34.0480, −118.2520 (downtown grid) |
| Richmond, CA | planned | 37.9358, −122.3478 (downtown grid) |

**Window review (11 October 2026):** the same authors' [companion paper, §3.1/Figure 1](https://www.udsu-strath.com/wp-content/uploads/2010/06/PA2006_09.pdf)
explicitly labels Richmond, CA, supporting this city's designation. An initial concern from Jacobs'
Virginia index does not establish a wrong-city error. Exact historical window matching remains
unverified; retain the frozen samples for the controlled 15 m / 0 m comparison.

Expected results from the paper:
- Ahmedabad and Cairo: betweenness `exponential`, information `power_law` (γ ≈ 2.74 and 2.63).
- LA and Richmond: betweenness `gaussian`, information `exponential`.

### Run settings
- `network.type: all`. Crucitti mapped all streets, and old-city lanes may not be tagged as drivable.
- Consolidation stays on (15 m).
- These graphs have a few hundred to about 2,000 nodes, so `exact_info_max_nodes` covers them and information is computed for **all** nodes.
- Only stages 01–07 are needed (centralities, information, classification). Reliability, accessibility and population are disabled.

### Interface
- A CLI subcommand `georesilience validate crucitti --out DIR`. It downloads, so it needs network access.
- `DIR/crucitti_report.txt` contains:
  - per city: N, links, the verdict per distribution, α for information (if power law), the network label;
  - the expected vs obtained table;
  - a match count.
- `DIR/figures/`: the information-centrality CCDF of the four cities on one log-log plot, as in the paper's Fig. 3c/d.
- The report always includes the caveat: "OSM 2026 ≠ 1990s street maps used in the paper; sample locations approximate; agreement is qualitative."

### Pass criterion
- **Pass** if ≥ 3 of the 4 cities match on the information-centrality verdict **and** ≥ 3 of 4 match on the betweenness verdict.
- Fail → the report shows the mismatches. This is a finding, not a crash: exit code 0, but the report is headed "MISMATCH".
- Not part of CI. It runs manually or under `@pytest.mark.network` + `@pytest.mark.slow`.

## Acceptance criteria
- [x] The subcommand runs end to end, with network access, and produces the report and figure.
- [x] An offline unit test checks the square-sample construction: a 1609 m side in projected metres, centred correctly.
- [x] An offline unit test checks the report and the pass-criterion logic, using mocked verdicts.
- [x] The README links the validation command and states what it does and doesn't show.

## Implementation refinements agreed after AP2 review

The original specification above remains the baseline. The implementation and interpretation
are refined as follows; details and manual commands are in
[README](../../README.md#crucitti-city-comparison-ticket-15).

- **Two explicit comparisons:** retain the current framework's inverse-distance information
  and Ticket 07 fits, alongside a reference using AP2 spatial efficiency `mean(d_E/d)`.
  The reference uses exponential versus Rayleigh body MLE/AIC to represent the exponential
  versus Gaussian-shaped cumulative curves in AP2 Fig. 3. A half-normal body (Ticket 07) does
  not have that Gaussian-shaped survival function. Reference information still uses modern
  Ticket 07 tail rules; this is not reconstruction of the paper's original fitting procedure.
- **Exponents:** paper gamma refers to the CCDF, not the density. Report density alpha and
  ideal continuous CCDF gamma = alpha - 1 separately, without an exact historical exponent target.
- **Frozen inputs:** preserve unsimplified GraphML, projected-square boundary, retrieval time,
  software versions and input checksums. Provide a derived QGIS input GeoPackage and an offline
  rerun option. The coordinates are the predefined approximate samples, not verified historic
  windows. A fresh download requires a new input directory; overwrite never refreshes snapshots.
- **Undirected cleaning:** ignore one-way restrictions before simplifying/selecting the largest
  connected component. Using a directed SCC first would change AP2's intended street topology.
- **Fixed consolidation:** keep the original 15 m default. Within this validation only, the
  ordinary >=5% dead-end-change guard becomes a visible warning so the predefined experiment
  can finish without retuning tolerance. Record counts/warnings; ordinary analysis keeps its
  strict guard. Sensitivity runs use explicit separate outputs, including tolerance 0 to disable.
- **Exact scope and cost:** AP2 Ahmedabad has 2,870 nodes; modern sizes can differ. Compute
  information for every cleaned node with no candidate fallback, reducing both efficiency
  conventions in the same shortest-path blocks. Skip unrelated link-damage and Monte Carlo stages.
- **Separate outcomes:** show independent framework and reference statuses. The original
  >=3/4 condition for each centrality is retained as a project criterion. The report heading
  describes the framework result. Mismatch/inconclusive evidence is preserved, not retuned away.

## Published historical data follow-up

On 11 October 2026, the authors' [textbook dataset page](https://www.complex-networks.net/datasets.html#chap8)
was located. Its `cities.zip` release cites Crucitti, Latora and Porta (2006) and contains
20 graphs, including all 18 cities listed in AP2. The four validation cities match AP2's
node/edge counts and the companion Chaos paper's rounded edge-length means/standard deviations.

The separate `python -m georesilience.published_cities --archive cities.zip --out DIR`
workflow preserves the authors' topology, local coordinates and metric road lengths without
OSM downloading, projection, simplification, consolidation or component selection. It computes
the same two efficiency conventions and uses the existing fitting rules and pass criteria.
It pins and copies the archive, validates topology against the endpoint table, and retains
parallel roads/repeated source edge labels. Geographic registration and original curved-road
shapes are unavailable in this release. This resolves access to the published graph data;
it does not reproduce the authors' original statistical fitting software. See
[README](../../README.md#published-historical-ap2-networks) for commands and interpretation.
