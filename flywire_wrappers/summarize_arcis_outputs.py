#!/usr/bin/env python3
"""Summarize and validate ARCIS output directories."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--summary-name", default="summary_clean.csv")
    return parser.parse_args()


def read_graph_header(graph_path: Path) -> tuple[int, int]:
    with graph_path.open() as handle:
        fields = handle.readline().split()
    return int(fields[0]), int(fields[1])


def selected_indices(solution_path: Path) -> set[int]:
    selected: set[int] = set()
    with solution_path.open() as handle:
        for index, line in enumerate(handle, start=1):
            if line.strip() == "1":
                selected.add(index)
    return selected


def validate_independent_set(graph_path: Path, selected: set[int]) -> tuple[bool, str]:
    with graph_path.open() as handle:
        next(handle)
        for index, line in enumerate(handle, start=1):
            if index not in selected:
                continue
            for target in line.split():
                target_index = int(target)
                if target_index in selected:
                    return False, f"selected adjacent pair: {index},{target_index}"
    return True, ""


def main() -> int:
    args = parse_args()
    converted_dir = args.out_dir / "converted"
    solutions_dir = args.out_dir / "solutions"
    logs_dir = args.out_dir / "logs"
    summary_path = args.out_dir / args.summary_name

    graph_paths = sorted(converted_dir.glob("*.graph"))
    with summary_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "graph",
                "nodes",
                "undirected_edges",
                "seed",
                "independent_set_size",
                "valid_independent_set",
                "validation_error",
                "solution_csv",
                "arcis_membership",
                "stdout_log",
                "stderr_log",
            ]
        )

        for graph_path in graph_paths:
            stem = graph_path.stem
            membership_path = solutions_dir / f"{stem}.seed{args.seed}.arcis.txt"
            solution_csv = solutions_dir / f"{stem}.seed{args.seed}.nodes.csv"
            stdout_log = logs_dir / f"{stem}.seed{args.seed}.stdout.log"
            stderr_log = logs_dir / f"{stem}.seed{args.seed}.stderr.log"
            nodes, edges = read_graph_header(graph_path)

            if membership_path.exists():
                selected = selected_indices(membership_path)
                valid, validation_error = validate_independent_set(graph_path, selected)
                is_size = len(selected)
            else:
                valid, validation_error, is_size = False, "missing membership file", ""

            writer.writerow(
                [
                    stem,
                    nodes,
                    edges,
                    args.seed,
                    is_size,
                    valid,
                    validation_error,
                    solution_csv if solution_csv.exists() else "",
                    membership_path if membership_path.exists() else "",
                    stdout_log if stdout_log.exists() else "",
                    stderr_log if stderr_log.exists() else "",
                ]
            )

    print(summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
