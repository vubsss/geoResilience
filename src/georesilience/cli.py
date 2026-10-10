import argparse
import sys
from pathlib import Path

from . import __version__
from .config import load_config
from .pipeline import run


def main(argv=None):
    parser = argparse.ArgumentParser(prog="georesilience")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run")
    run_parser.add_argument("--config", required=True, type=Path)
    run_parser.add_argument("--out", type=Path)
    run_parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    try:
        run(load_config(args.config), args.out, args.overwrite)
    except (ValueError, OSError) as exc:
        print(f"georesilience: {exc}", file=sys.stderr, flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
