"""Read and test the authors' published historical city networks, unchanged."""

import argparse
from collections import Counter
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
import shutil
import zipfile

import networkx as nx
import numpy as np

from .config import AnalysisConfig
from .crucitti import (CITIES, _json, _log, _sha256, analyse_graph, comparison_report,
                      comparison_summary, write_comparison_csv, write_comparison_figures)
from .pipeline import _versions

SOURCE_URL = "https://www.complex-networks.net/datasets/cities.zip"
ARCHIVE_SHA256 = "29552883de03463dbf5c2b2df69c1583d30014f83477c355fd7cd7eb1e9c3c61"
PAPER_COUNTS = {"ahmedabad": (2870, 4387), "cairo": (1496, 2255),
                "los-angeles": (240, 340), "richmond": (697, 1086)}
# Companion Chaos 16, 015113 (2006), Table I, in metres; rounded to .01.
PAPER_LENGTHS = {"ahmedabad": (27.59, 17.03), "cairo": (37.47, 25.42),
                 "los-angeles": (113.87, 64.86), "richmond": (57.65, 45.49)}
LOCAL_CRS = ('ENGCRS["AP2 local Cartesian coordinates",EDATUM["Unknown local datum"],'
             'CS[Cartesian,2],AXIS["x",east,ORDER[1],LENGTHUNIT["metre",1]],'
             'AXIS["y",north,ORDER[2],LENGTHUNIT["metre",1]]]')
SOURCE_NOTE = (
    "Authors' published historical street networks (2017 archive citing Crucitti et al., 2006). "
    "Topology, coordinates and metric road lengths preserved; no cleaning/consolidation. "
    "Coordinates are local Cartesian metres with unknown geographic registration. "
    "Displayed edges join endpoints; original curved road geometry is unavailable. "
    "The statistical fits use project rules, not the authors' original fitting software."
)


def read_city(archive, slug, *, expected_counts=None, expected_lengths=None):
    """Cross-check topology against the separate endpoint/length table before use."""
    with zipfile.ZipFile(archive) as bundle:
        table = np.loadtxt(StringIO(bundle.read(f"cities/{slug}_edge_info.txt").decode()), ndmin=2)
        topology = np.loadtxt(StringIO(bundle.read(f"cities/{slug}.net").decode()), ndmin=2)
    if table.shape[1] != 8 or topology.shape[1] != 2:
        raise ValueError("expected 8 endpoint columns and 2 topology columns")
    if not np.isfinite(table).all() or not np.isfinite(topology).all():
        raise ValueError("nonfinite published data")
    for identifiers in (table[:, [0, 1, 4]], topology):
        if not np.equal(identifiers, np.floor(identifiers)).all():
            raise ValueError("edge/node identifiers must be integers")
    if np.any(table[:, 7] <= 0):
        raise ValueError("nonpositive lengths")
    pairs = lambda rows: Counter(tuple(sorted(map(int, row))) for row in rows)
    if pairs(topology) != pairs(table[:, [1, 4]]):
        raise ValueError("topology and endpoint table disagree")
    graph = nx.MultiGraph(crs=LOCAL_CRS, source=SOURCE_URL)
    for row_index, (edge, u, x1, y1, v, x2, y2, length) in enumerate(table, start=1):
        for node, xy in ((int(u), (x1, y1)), (int(v), (x2, y2))):
            if node in graph and not np.allclose(
                    (graph.nodes[node]["x"], graph.nodes[node]["y"]), xy, rtol=0, atol=1e-6):
                raise ValueError(f"node {node} has inconsistent coordinates")
            graph.add_node(node, x=float(xy[0]), y=float(xy[1]))
        # Published edge_num is not unique in Ahmedabad/Cairo. Use the file row
        # as physical identity, retaining the source label separately. In
        # particular, never collapse parallel roads or repeated source labels.
        graph.add_edge(int(u), int(v), key=row_index, osmid=row_index,
                       published_edge_id=int(edge), length=float(length))
    counts = (len(graph), graph.number_of_edges())
    if expected_counts is not None and counts != tuple(expected_counts):
        raise ValueError(f"published N/K mismatch: {counts} != {expected_counts}")
    lengths = table[:, 7]
    stats = (float(lengths.mean()), float(lengths.std()))
    if expected_lengths is not None and not np.allclose(stats, expected_lengths, rtol=0, atol=.0051):
        raise ValueError(f"published length statistics mismatch: {stats} != {expected_lengths}")
    return graph, {"nodes": counts[0], "edges": counts[1], "mean_length_m": stats[0],
                   "repeated_edge_labels": len(table) - len(np.unique(table[:, 0])),
                   "parallel_or_repeated_pairs": len(table) - len(pairs(table[:, [1, 4]])),
                   "std_length_m": stats[1], "connected_components": nx.number_connected_components(graph),
                   "coordinate_bounds": [table[:, [2, 5]].min(), table[:, [3, 6]].min(),
                                         table[:, [2, 5]].max(), table[:, [3, 6]].max()],
                   "topology_matches_endpoint_table": True,
                   "paper_counts_match": expected_counts is not None,
                   "paper_length_statistics_match": expected_lengths is not None}


def validate_published(archive, out_dir, *, n_jobs=2, max_memory_gb=1.0):
    """Offline validation with a pinned archive; refuse to replace existing results."""
    archive, out_dir = Path(archive), Path(out_dir)
    config = AnalysisConfig(n_jobs=n_jobs, max_memory_gb=max_memory_gb)
    if _sha256(archive) != ARCHIVE_SHA256:
        raise ValueError("archive checksum differs from the verified authors' release")
    if out_dir.exists() and any(out_dir.iterdir()):
        raise ValueError("output directory is not empty; choose a new directory")
    # Validate all four inputs before starting the expensive calculations.
    prepared = [(city, *read_city(archive, city.slug,
                 expected_counts=PAPER_COUNTS[city.slug], expected_lengths=PAPER_LENGTHS[city.slug]))
                for city in CITIES]
    out_dir.mkdir(parents=True, exist_ok=True)
    inputs = out_dir / "inputs"
    inputs.mkdir()
    shutil.copyfile(archive, inputs / "cities.zip")
    with zipfile.ZipFile(archive) as bundle:
        # Copy only explicitly named files, never extract arbitrary archive paths.
        names = ["README.txt"] + [name for city in CITIES for name in
                 (f"{city.slug}.net", f"{city.slug}_edge_info.txt")]
        for name in names:
            (inputs / name).write_bytes(bundle.read(f"cities/{name}"))
    manifest = {"source_url": SOURCE_URL, "archive_sha256": ARCHIVE_SHA256,
                "verified_utc": datetime.now(timezone.utc).isoformat(),
                "source_note": SOURCE_NOTE, "versions": _versions(),
                "files": {path.name: _sha256(path) for path in inputs.iterdir()},
                "validation": {city.slug: audit for city, _, audit in prepared}}
    _json(inputs / "manifest.json", manifest)
    _json(out_dir / "run_config.json", {"dataset": "authors_published_historical",
          "archive_sha256": ARCHIVE_SHA256, "information_coverage": "all", "cleaning": "none",
          "n_jobs": n_jobs, "max_memory_gb": max_memory_gb, "versions": _versions(),
          "runner_sha256": _sha256(__file__)})
    results, values = [], {}
    for city, graph, _ in prepared:
        _log(f"Published network: {city.name}")
        result, city_values = analyse_graph(city, graph, manifest, out_dir / city.slug,
            analysis_config=config, cleaning={"applied": False, "component_selection": "none"},
            source_note=SOURCE_NOTE, cleaning_lines=["Published graph unchanged: no cleaning or node removal."])
        results.append(result)
        values[city.slug] = city_values
    summary = comparison_summary(results)
    summary["caveat"] = SOURCE_NOTE
    _json(out_dir / "comparison.json", summary)
    write_comparison_csv(summary, out_dir / "comparison.csv")
    (out_dir / "crucitti_report.txt").write_text(comparison_report(summary), encoding="utf-8")
    write_comparison_figures(values, out_dir / "figures", summary,
        information_title="Published historical networks: information CCDF (AP2 Fig. 3 comparison)")
    _log(f"{summary['status']}: {out_dir / 'crucitti_report.txt'}")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True, help="Authors' cities.zip; verified offline")
    parser.add_argument("--out", type=Path, required=True, help="New or empty results directory")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--max-memory-gb", type=float, default=1.0)
    args = parser.parse_args()
    validate_published(args.archive, args.out, n_jobs=args.jobs, max_memory_gb=args.max_memory_gb)


if __name__ == "__main__":
    main()
