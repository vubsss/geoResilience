# Tier 4 Hyderabad data and literature audit

Audit date: 4 November 2026; framework scope clarified 5 November 2026.

This document is the Hyderabad case-study source audit for the reusable Tier 4 framework in
[TIER4.md](TIER4.md). The framework can simulate traffic on a Hyderabad OSM network using a
declared OD-demand scenario and explicit speed/capacity assumptions. The published CTS profile is
a candidate prior; automatic mapping of OSM road tags to its classes is not implemented yet. A
run needs no current observed link-level data, but outputs are scenario estimates, not measured
Hyderabad congestion.
Each source below either supplies an input assumption, supports a method, or checks plausibility;
a citation is not automatically an available dataset.

## Recommended evidence stack

Build the simulated case study in this order:

1. Build the directed network from OpenStreetMap and audit its lane/one-way/divided-road tags.
2. Use the HMA-2041 Comprehensive Transportation Study (CTS) `hmda_cts_2011` capacity, free-flow
   speed and conical-function profile as the explicitly dated Hyderabad prior.
3. Generate zonal demand from WorldPop only for the first demonstration. Add HMDA land use and,
   if obtainable, employment and student-enrolment data to represent attractions.
4. Run static assignment to generate directed volumes, V/C ratios and congested travel times.
5. Feed those times into the framework's routing, accessibility and closure analyses.
6. Run sensitivity cases using demand scales, Indo-HCM capacities and the BPR function. Compare
   the scenario results with the public TomTom aggregate as a plausibility check.

The CTS TAZ polygons, OD matrices, classified counts, screen-line counts and observed speeds can
improve later scenarios if HMDA/UMTA shares them. A public raw-data release has not been found.
Licensed probe times or a small field survey can support calibration, but they are optional.

## Source audit

| Source | What it provides | Proposed Tier 4 use | Access and limitation |
| --- | --- | --- | --- |
| [HMDA CTS overview](https://www.hmda.gov.in/developdept9/) | Official confirmation of the HMA comprehensive transport study and its 2041 planning purpose | Establishes official local study provenance | Summary page, not raw data |
| [HMA-2041 CTS Volume I](https://theasthmafiles.org/sites/default/files/artifacts/media/pdf/report_on_long_term_strategy_for_the_transport_sector_of_hma-2041_volume-i_main_report_3_1.pdf) | Base-year 2011 four-stage model; 695 TAZs; household, cordon, screen-line and other surveys; road classes; calibrated conical VDF | Primary Hyderabad prior for capacity, free-flow speed and VDF parameters; methodological benchmark | Public third-party mirror; old base year; underlying matrices/counts were not found as machine-readable files |
| [OpenStreetMap](https://www.openstreetmap.org/copyright) through OSMnx | Road geometry, direction, class and partial lane/max-speed/divided-road tags | Simulation network and mapping to CTS road classes | Tag completeness must be measured and uncertain mappings retained; not traffic observations |
| [WorldPop](https://www.worldpop.org/faq/) | Gridded resident population estimates | Trip-production mass and, only as a labelled fallback, attraction mass | Does not supply trips, employment, schools, vehicle ownership or time-of-day demand |
| [HMDA Master Plan 2031](https://www.hmda.gov.in/planning-2/) | Published land-use plans/maps | Improve attraction weights and define comparison zones | Mostly planning-era/raster material; requires georeferencing and does not equal current employment |
| [TomTom Hyderabad Traffic Index](https://www.tomtom.com/traffic-index/city/hyderabad/) | Current city-level congestion, speed and 10 km travel-time summaries by period | Aggregate plausibility check for simulated peak speeds and delays | Not an OD matrix, link count dataset or calibration target at road level |
| [TomTom Traffic Stats](https://docs.tomtom.com/traffic-stats/documentation/product-information/introduction) and [Area Analytics](https://docs.tomtom.com/area-analytics/documentation/product-information/faq) | Historical/custom-area probe travel times and speeds | Optional directed-link/time-period calibration and validation | Commercial/licensed; coverage and map matching must be documented; do not make it required for reproducibility |
| [Hyderabad Police Annual Report 2024](https://www.hyderabadpolice.gov.in/assets/annual-reports/HYDCP_ANNUAL%20REPORT_2024_FINALN.pdf) | Reported registered-vehicle and enforcement/traffic context | Fleet-growth context and scenario discussion | Does not provide a network OD matrix or continuous link flows |
| [VAHAN public analytics](https://analytics.parivahan.gov.in/analytics/vahanpublicreport) | Vehicle-registration composition and trends | Inform fleet/PCU sensitivity and growth narrative | Registered stock is not peak-hour road demand and geography/time filters must be recorded |
| [TiHAN, IIT Hyderabad datasets](https://tihan.iith.ac.in/TiAND.html) | Autonomous-driving/sensor datasets available through its process | Possible local perception/trajectory experiments or validation samples | Not a ready city-wide OD/count source; coverage and access require confirmation |
| [Indo-HCM, CSIR-CRRI](https://crridom.gov.in/en/indian-highway-capacity-manual) | Indian capacity-analysis methodology | Named national comparison/sensitivity profile | Not Hyderabad calibration; the manual's definitions must be matched before transferring values |

These sources are sufficient to build and test a simulated Hyderabad case study. Current,
time-stamped counts and matched travel times would improve the accuracy of its local predictions;
they are not required to test the framework's traffic integration, scenario comparisons or
closure logic.

### Current aggregate benchmark

The TomTom page reports the following 2025 Hyderabad city values: 55.5% average congestion,
32 min 37 s for an average 10 km trip, and 16.1 km/h average rush-hour speed. Its morning and
evening 10 km figures are respectively 34 min 53 s at 17.2 km/h and 39 min 28 s at 15.2 km/h.
Store the page edition/year with the result because these values change. These figures can reject
an obviously implausible city-level simulation, but agreement with them does not validate spatial
flows or individual links.

## Formula provenance ledger

### Conical volume-delay function: published and Hyderabad-calibrated

```text
t(v) = t0 * (2 + sqrt(alpha^2 * (1 - v/c)^2 + beta^2)
                  - alpha * (1 - v/c) - beta)
```

- **Did this project make the equation?** No.
- **Published backing:** Spiess, H. (1990), [Conical Volume-Delay
  Functions](https://doi.org/10.1287/trsc.24.2.153), *Transportation Science*.
- **Hyderabad backing:** the HMA-2041 CTS reports selecting the conical form after comparing
  standard BPR, modified BPR, empirical and conical functions. Its Tables 8-29 to 8-31 provide
  ten locally calibrated road-class combinations of capacity, free-flow speed, `alpha` and
  `beta`, reproduced in [TIER4.md](TIER4.md#hyderabad-cts-road-profile).
- **What is ours?** Mapping present-day OSM edges into those CTS classes and using the resulting
  congested seconds in GeoResilience. That mapping is an adaptation and must be auditable.

### BPR volume-delay function: directly published, not Hyderabad-calibrated here

```text
t(v) = t0 * (1 + alpha * (v/c)^beta)
```

- **Did this project make the equation?** No.
- **Published backing:** US Bureau of Public Roads (1964), [Traffic Assignment Manual](https://libraryarchives.metro.net/dpgtl/us-department-of-commerce/1964-traffic-assignment-manual-for-application-with-a-large-high-speed-computer.pdf).
- **Parameter warning:** `alpha=0.15`, `beta=4` is a conventional comparison pair, not evidence
  fitted to Hyderabad. The recent Fateh Nagar study below is local corridor evidence, but its
  fitted parameters must not automatically be generalized city-wide.

### Doubly constrained gravity model: standard family, adapted inputs

```text
q_ij = A_i O_i B_j D_j exp(-lambda * t0_ij),  i != j
```

- **Did this project make the model family?** No. Entropy-maximizing, doubly constrained spatial
  interaction models are established in Wilson (1970), [Entropy in Urban and Regional
  Modelling](https://doi.org/10.1111/j.1538-4632.1970.tb00859.x).
- **What is ours?** Using WorldPop resident population to construct both `O_i` and `D_j` is a
  data-limited project adaptation. It has conceptual backing as a gravity simulation but is not
  directly taken from the Hyderabad CTS and is not an observed OD matrix.
- **Hyderabad difference:** the CTS used purpose-specific production/attraction variables,
  including population, earners, resident students, enrolled students and total employment, and
  selected a purpose-specific Tanner deterrence form. That is the better destination model if
  compatible inputs can be acquired.

The conversion from residents to hourly PCU demand in [TIER4.md](TIER4.md#3-od-demand-generate-or-supply)
is our accounting assumption. Its trip rate, road-mode share, peak-hour share, occupancy and PCU
factor need declared values and sensitivity runs; the cited papers do not supply a universal
Hyderabad setting for them.

### Edge cost and diagnostic indices: definitions and project integration

```text
edge_cost_e       = congested_time_s_e
vc_ratio_e        = assigned_volume_pcu_h_e / capacity_pcu_h_e
delay_s_e         = congested_time_s_e - free_flow_time_s_e
delay_pcu_hours_e = volume_pcu_h_e * period_h * delay_s_e / 3600
TSTT_pcu_hours    = sum_e(volume_pcu_h_e * period_h * congested_time_s_e / 3600)
```

- `V/C`, delay and total system travel time are standard traffic-engineering quantities, not
  proposed as new scientific formulas.
- Choosing `congested_time_s` as the routing weight is this project's design decision, backed by
  static traffic assignment: a traveller experiences time, whereas `V/C` is dimensionless and
  should remain a saturation diagnostic.
- Combining those outputs with the repository's accessibility and physical-road closure analyses
  is original integration work. It must be described as a project method, not attributed to the
  CTS or another paper.
- No default weighted “traffic accessibility score” is proposed. Any later composite needs
  declared normalization, user-supplied weights and sensitivity analysis.

The first implementation's [Frank-Wolfe assignment](https://doi.org/10.1002/nav.3800030109)
solves the static equilibrium problem formulated by [Beckmann, McGuire and
Winsten (1956)](https://cowles.yale.edu/research/publications/archive). The algorithm and
equilibrium model are published methods; the NetworkX/SciPy implementation and connection to
GeoResilience are this project's code.

## Hyderabad-related research to cite

| Study | Relevance | Correct interpretation |
| --- | --- | --- |
| Kuchu et al. (2025), [Towards Sustainable Transport: An Analysis of Urban Mobility in Hyderabad, Telangana Using Uber Movement Data](https://doi.org/10.3311/PPtr.36936) | Hyderabad travel-time/speed analysis for 2016-2019; congestion, friction and accessibility indices | Supports local probe-time analysis and validation design; confirm whether underlying processed data can still be obtained |
| Omar and Mallikarjuna (2016), [Analysis of the Macroscopic Relations for No-Lane Based Heterogeneous Traffic Stream](https://doi.org/10.1016/j.proeng.2016.02.038) | Jubilee Hills observations under heterogeneous, weak-lane-discipline traffic | Strong reason to calibrate locally; one arterial is not a city-wide capacity table |
| Kumar et al. (2026), [Integrated BPR-VISSIM-ANN Modelling Framework for Traffic Delay Prediction and Mitigation: A Case Study of the Fateh Nagar Flyover, Hyderabad](https://doi.org/10.1007/s13177-026-00720-y) | Recent Hyderabad corridor study using field data, BPR and VISSIM | Useful current corridor benchmark and field-method example; do not transfer one corridor's calibration to every road |
| [Modernizing the Transportation Infrastructure of Hyderabad Using ITS (2017)](https://www.ijert.org/research/modernizing-the-transportation-infrastructure-of-hyderabad-using-its-in-relation-to-capacity-levels-and-road-accident-severity-IJERTV6IS080227.pdf) | Reports Hyderabad mid-block speed-flow relationships | Secondary plausibility evidence due age and venue; verify definitions/sample before using coefficients |

## Minimum defensible course experiment

Use a manageable Hyderabad pilot rather than the full metropolitan area first. Freeze its OSM
and WorldPop inputs, then run this scenario matrix:

| Dimension | Cases |
| --- | --- |
| VDF/capacity | CTS 2011 conical; CTS capacities with BPR comparison; Indo-HCM comparison |
| Demand | low/base/high scale; at least two decay values; boundary/through-trip sensitivity |
| Zones | at least two grid resolutions |
| Validation | city-level TomTom plausibility; field/licensed link observations if acquired |
| Disruption | intact assignment; selected physical-road closures with full reassignment |

Report whether top-road rankings remain stable across cases. Without observed counts or link
times, describe the result as **“a framework evaluation using Hyderabad-informed simulated
traffic under stated assumptions.”** The simulated volumes and times are useful test data; their
match to current Hyderabad traffic remains unmeasured.

