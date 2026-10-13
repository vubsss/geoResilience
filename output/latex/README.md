# GeoResilient mid-evaluation presentation

Prepared for Spatially Abled, Spatial Informatics, 13 October 2026.

The deck contains 32 main slides and 6 technical appendix slides. It covers the problem, data, methodology, saved results, observations, limitations, implementation progress and future work. Mid-evaluation scope is Tiers 1–2 / Tickets 01–15. Ticket 15's classification discrepancy and pending manual review of Tickets 13–14 are stated explicitly.

## Rebuild the PDF

All required figures and numerical macros are included. No Python, internet data acquisition or project analysis run is needed to rebuild with an installed LaTeX distribution.

From this directory, using Tectonic:

```powershell
tectonic -X compile mid_evaluation.tex
```

Or, using TeX Live / MiKTeX:

```powershell
pdflatex -interaction=nonstopmode -halt-on-error mid_evaluation.tex
pdflatex -interaction=nonstopmode -halt-on-error mid_evaluation.tex
```

The resulting file is `mid_evaluation.pdf`. The delivered copy is named `GeoResilient_Mid_Evaluation.pdf`. The deck uses Beamer, Latin Modern, TikZ, listings and booktabs; an installed full TeX distribution provides these packages. Tectonic downloads TeX resources on a first build, then uses its cache. The delivered PDF was compiled locally with Tectonic 0.17.0.

Edit the title frame in `mid_evaluation.tex` to change names or date. `results_macros.tex` contains values extracted from the saved results. `PRESENTER_NOTES.md` provides speaking points and a demo guide.

## Evidence and figures

- `assets/`: existing output maps plus vector charts generated from saved metrics. The connecting-road schematic is explicitly illustrative.
- `asset_sources.json`: original source paths, evidence types and source hashes for figures.
- `evidence/`: copies of local summaries, reports, curves, configurations, verification files and demo layers/inputs, plus selected excerpts documenting prior validation.
- `layout_validation.json`: page count, layout checks and PDF hash.

The nine-node example is synthetic. Earlier real-data Malé and historical-city results are quoted from the repository's recorded validation; those original raw result directories were absent from this checkout. These results are not presented as a new experiment. Hyderabad is the proposed application, not a completed city-wide study. Facilities and traffic are future work.

`build_assets.py` is optional: it regenerates figures when placed in `output/latex/` inside the original project checkout, using its existing Python dependencies and `results/ticket14-demo/`. It is not needed for standalone LaTeX compilation. Regeneration expects the original repository paths listed in the provenance file.

## Demonstration in the original checkout

Use the existing saved outputs for an offline demonstration. Show `report.txt`, the scorecard, and the nodes/edges/zones GeoPackage layers in QGIS. The packaged evidence also permits viewing these files without the checkout.

To run the uniform controlled example from the project root with the environment activated, enter this as one line:

```powershell
georesilience run --config data/ticket14-demo/uniform.yaml --out results/mid-demo --overwrite
```

Use `examples/create_ticket14_demo.py` for controlled population examples. Running the bbox-based population YAML directly acquires real OSM roads instead of freezing the demonstration grid. The presentation itself does not run or modify the application.

The PDF was compiled, rendered and visually checked on all 38 pages. No LaTeX overflow warnings or text outside page bounds remained. Application source and existing ticket plans were unchanged during presentation authoring.
