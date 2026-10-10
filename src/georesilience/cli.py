import argparse
import sys
from pathlib import Path

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
    template_parser = commands.add_parser("template", help="Export per-event OSM-way probability CSV")
    template_parser.add_argument("--config", required=True, type=Path)
    template_parser.add_argument("--out", required=True, type=Path)
    template_parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "template":
            if args.out.exists() and not args.overwrite:
                raise ValueError(f"template output exists: {args.out} (use --overwrite)")
            graph, _, _ = load_and_clean(config)
            export_edge_template(graph, args.out)
        else:
            run(config, args.out, args.overwrite)
    except (ValueError, OSError, NotImplementedError) as exc:
        print(f"georesilience: {exc}", file=sys.stderr, flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
