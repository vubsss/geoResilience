# Ticket 17: Indian source access and initial audit

Checked 13 October 2026. This is an acquisition audit, not a validated completeness study.
No UDISE+ export or independently geocoded official reference inventory has been obtained.
The real-data acceptance item remains **open**.

## Access findings and next steps

| Source | Observed access | Fields/access still unresolved | Action to obtain usable input |
| --- | --- | --- | --- |
| [UDISE+ Data Sharing Portal](https://microdata.udiseplus.gov.in/) | Login/download and registration/request entry points are public. [Registration](https://microdata.udiseplus.gov.in/register) requests identity/contact details and OTPs. | Actual school-level export, geographic coordinates, academic year, capacity fields and permitted reuse have not been verified. | User/institution registers, submits the research request through the portal and obtains approval/export and its conditions. Import that file locally; no undocumented API is assumed. |
| [Know Your School](https://kys.udiseplus.gov.in/home/) and [School GIS](https://schoolgis.udiseplus.gov.in/) | Public school lookup/map interfaces exist; lookup presents CAPTCHA. | A map or individual lookup is not evidence of an approved bulk download. | Use for manual identity/location checks; request a school inventory through the sharing portal. |
| [National Hospital Directory](https://www.data.gov.in/resource/national-hospital-directory-geo-code-and-additional-parameters-updated-till-last-month) | Search-index metadata advertises a CSV and coordinate/name/category fields. Direct page retrieval returned a generic shell with no usable download target. | Actual extract, schema, date, completeness and capacity not established. Cached metadata and the live shell disagree; the resource title's “last month” is not a verified date. | Obtain the actual CSV via the public download UI or source department, retain its licence/metadata and map actual columns. Do not invent an API/resource ID. |
| [ABDM HFR/NHPR](https://facility.abdm.gov.in/) | Redirects to the NHPR web application. [NHA's registry description](https://nha.gov.in/img/resources/Annual-Report-2020-21.pdf) includes facility categories beyond hospitals. | Bulk export, geocodes, current capacity, reuse conditions and hospital-specific filters not verified. | Obtain an approved export and filter facility types explicitly; registration totals are not hospital completeness. |
| [TVVP hospital infrastructure](https://vvp.telangana.gov.in/content.php?U=2) | Downloaded public HTML; name/district/bed tables can be inspected and frozen. | No numeric coordinates or bed reference date in the extracted rows. Hospital entries and other health facilities share the page. King Koti DH/MCH rows may overlap. | Use the stated DH/AH/MCH subset for source-field inspection. Verify identities, operation, bed scope/date and independent locations before a capacity model. |
| [Hyderabad government schools](https://hyderabad.telangana.gov.in/public-utility-category/government-schools/) | Downloaded a three-entry directory with names and linked addresses. | Numeric coordinates, UDISE codes, year, pupil places, enrolment, teachers and classrooms absent from this extracted inventory. This tiny list is not all district schools. | Use as a limited access sample; request UDISE+ export for the actual reference inventory. |
| [Telangana fire station directory](https://tgfireuat.cgg.gov.in/home/Home/knowurfstn) | Downloaded a public station-name list. | No usable numeric locations, appliance/crew inventory or capacity reference date established. Some list items describe equipment/outposts. | Manually verify station type/identity/location or request a geocoded inventory; OSM-only candidates remain supported. |

The school/hospital pages are retained locally for provenance. Their public visibility does
not establish permission for bulk redistribution; no source-specific permission was obtained.
Restricted exports and full source snapshots need not be committed to Git. OSM uses
[ODbL 1.0 and attribution to OpenStreetMap contributors](https://www.openstreetmap.org/copyright).

## Frozen real sample and interpretation

`examples/audit_ticket17_india.py` downloads the three government pages and a small main-API
OSM XML extract, records URLs, UTC retrieval dates and SHA-256 hashes, derives local CSVs,
and runs the production registry importer. Subsequent runs prohibit HTTP and verify the
snapshot manifest. The example deliberately keeps missing coordinates blank.

The reporting sample is a Hyderabad OSM window `[78.465, 17.385, 78.480, 17.400]` (WGS84);
the official page samples have district scope. They cannot yet be geographically restricted
without independent coordinates. OSM features are clipped to that window. An initial larger
main-API bbox `[78.46, 17.38, 78.49, 17.41]` returned HTTP 400; the smaller window succeeded.
This example uses OSM's map API for a small extract; production `osm_bbox` uses cached
Overpass extraction. Neither endpoint is required for offline reruns.

Hospital inclusion is explicitly limited to DH/AH/MCH name prefixes from the TVVP table.
CHC/UCHC/dispensary rows are exported in `inputs/excluded-directory-records.csv`; this
classification is a source-screening convention, not a verified inpatient-service assessment.
Directory row IDs are generated provenance keys, not official HFR identifiers. Duplicate or
historically overlapping King Koti entries cannot be resolved from these tables alone.
No bed totals are summed across them.

The generated `source_findings.json` and `registry/facility_audit.json` record eligible-record
counts, valid official-coordinate counts, OSM matches, supply completeness, reference-year
availability and dates. Zero valid official coordinates means the match fraction is **undefined**,
not 0% coverage. The comparison PNG shows only located records, which here are OSM candidates.
Operational status is unknown; including unknown status and OSM candidates is an explicit
exploratory choice in this example. Official records with missing locations remain in the
registry, flagged ineligible for supply use, and appear in the reject table.

**Provisional first worked service: hospitals with equal supply.** Located OSM hospital
candidates are usable and TVVP publishes a bed field for later validation. A bed-capacity
model is deferred until identity, location, operation and bed reference dates are verified.
Schools await a usable UDISE+ export and school-age demand; enrolment is not student-place
capacity. Fire-service supply and dispatch assumptions need a separate audit.

This provisional choice does not close Ticket 17's real-data criterion. To close it, obtain
an independently geocoded school/hospital reference sample, review OSM matches and local
scope, establish dates/status/supply semantics, and rerun the audit with explicit mappings.

## Reproduction and review

From the repository root with the project environment activated:

```sh
# Explicit online acquisition, once:
python examples/audit_ticket17_india.py --download
# Uses saved, checksum-verified files and forbids HTTP:
python examples/audit_ticket17_india.py --overwrite
# Entirely synthetic known-answer example, also offline:
georesilience facilities --config examples/ticket17-facilities.yaml
```

Open `results/ticket17-india/source_findings.json` first. Inspect
`registry/facility_rejects.csv`, `facility_matches.csv`, `facility_provenance.json`,
`facility_comparison.png` and `registry.gpkg` (layers `facilities` and
`facility_source_records`). The source-record layer preserves original WKT/CRS, source IDs,
reference years and resource attributes. Generated results and downloads remain ignored.
