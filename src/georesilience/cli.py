import argparse
import sys
from pathlib import Path

from requests.exceptions import RequestException

from . import __version__
from .config import load_config
from .pipeline import run
from .failure_probabilities import export_edge_template
from .network import load_and_clean


def main(argv=None):
    parser = argparse.ArgumentParser(prog="georesilience")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run")
    run_parser.add_argument("--config", required=True, type=Path)
    run_parser.add_argument("--out", type=Path)
    run_parser.add_argument("--overwrite", action="store_true")
    facilities_parser = commands.add_parser("facilities", help="Import and audit facility inventories without road analysis")
    facilities_parser.add_argument("--config", required=True, type=Path)
    facilities_parser.add_argument("--out", type=Path)
    facilities_parser.add_argument("--overwrite", action="store_true")
    template_parser = commands.add_parser("template", help="Export per-event OSM-way probability CSV")
    template_parser.add_argument("--config", required=True, type=Path)
    template_parser.add_argument("--out", required=True, type=Path)
    template_parser.add_argument("--overwrite", action="store_true")
    validate_parser = commands.add_parser("validate", help="Run literature comparisons")
    validations = validate_parser.add_subparsers(dest="validation", required=True)
    crucitti_parser = validations.add_parser("crucitti", help="Compare four modern city samples with AP2")
    crucitti_parser.add_argument("--out", required=True, type=Path)
    crucitti_parser.add_argument("--inputs", type=Path, help="Frozen inputs directory (default: OUT/inputs)")
    crucitti_parser.add_argument("--offline", action="store_true", help="Require saved, checksum-verified inputs")
    crucitti_parser.add_argument("--download-only", action="store_true", help="Freeze the four inputs without analysis")
    crucitti_parser.add_argument("--overwrite", action="store_true", help="Replace results, preserving frozen inputs")
    crucitti_parser.add_argument("--jobs", type=int, default=1)
    crucitti_parser.add_argument("--max-memory-gb", type=float, default=1.0)
    crucitti_parser.add_argument("--consolidation-m", type=float, default=15.0,
                                help="Fixed intersection tolerance in metres; 0 disables (default: 15)")
    crucitti_parser.add_argument("--no-figures", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "facilities":
            from .facility_config import load_facility_config
            from .facilities import run_facilities
            run_facilities(load_facility_config(args.config), args.out, args.overwrite)
            return 0
        if args.command == "validate":
            from .crucitti import validate_crucitti
            validate_crucitti(args.out, inputs_dir=args.inputs, offline=args.offline,
                              download_only=args.download_only, overwrite=args.overwrite,
                              n_jobs=args.jobs, max_memory_gb=args.max_memory_gb,
                              tolerance_m=args.consolidation_m, figures=not args.no_figures)
            return 0
        config = load_config(args.config)
        if args.command == "template":
            if args.out.exists() and not args.overwrite:
                raise ValueError(f"template output exists: {args.out} (use --overwrite)")
            graph, _, _ = load_and_clean(config)
            export_edge_template(graph, args.out)
        else:
            run(config, args.out, args.overwrite)
    except (ValueError, OSError, NotImplementedError, RequestException) as exc:
        print(f"georesilience: {exc}", file=sys.stderr, flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
