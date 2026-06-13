#!/usr/bin/env python3
"""Export per-graph node lists from a single three-way node-match CSV."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "threeway_csv",
        type=Path,
        help="Path to a *.threeway_nodes.csv file.",
    )
    parser.add_argument(
        "--outdir",
        type=Path,
        default=None,
        help=(
            "Output directory for the three node-list files. "
            "Defaults to a sibling directory named after the input file."
        ),
    )
    return parser.parse_args()


def default_outdir(path: Path) -> Path:
    stem = path.name.removesuffix(".csv")
    return path.parent / f"{stem}.node_lists"


def sanitize_filename(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name)


def main() -> int:
    args = parse_args()
    threeway_csv = args.threeway_csv
    if not threeway_csv.exists():
        raise SystemExit(f"missing input file: {threeway_csv}")

    outdir = args.outdir or default_outdir(threeway_csv)

    with threeway_csv.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or len(reader.fieldnames) < 3:
            raise SystemExit(f"expected at least 3 columns in {threeway_csv}")
        graph_names = reader.fieldnames[:3]
        rows = list(reader)

    outdir.mkdir(parents=True, exist_ok=True)

    for graph_name in graph_names:
        out_path = outdir / f"{sanitize_filename(graph_name)}_nodes.txt"
        with out_path.open("w", newline="") as handle:
            for row in rows:
                handle.write(f"{row[graph_name]}\n")
        print(f"Wrote {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
