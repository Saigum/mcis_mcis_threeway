#!/usr/bin/env python3
"""Smoke-test SymSplit on random directed graphs and verify induced validity."""

from __future__ import annotations

import argparse
import random
import re
import subprocess
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solver", type=Path, default=Path("../symsplit/bin/run.o"))
    parser.add_argument("--nodes", type=int, default=50)
    parser.add_argument("--edge-prob", type=float, default=0.08)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--work-dir", type=Path, default=Path("/tmp/symsplit_random_directed_test"))
    return parser.parse_args()


def random_directed_edges(n: int, p: float, seed: int) -> set[tuple[int, int]]:
    rng = random.Random(seed)
    edges: set[tuple[int, int]] = set()
    for source in range(n):
        for target in range(n):
            if source != target and rng.random() < p:
                edges.add((source, target))
    return edges


def write_dimacs(path: Path, n: int, edges: set[tuple[int, int]]) -> None:
    with path.open("w", newline="\n") as handle:
        handle.write(f"p edge {n} {len(edges)}\n")
        for source, target in sorted(edges):
            handle.write(f"e {source + 1} {target + 1}\n")


def parse_solution(stdout: str) -> tuple[dict[str, str], list[tuple[int, int]]]:
    metrics: dict[str, str] = {}
    pairs: list[tuple[int, int]] = []
    for line in stdout.splitlines():
        if re.match(r"^\d+,\s*", line):
            parts = [part.strip() for part in line.split(",")]
            metrics = {
                "mcs_size": parts[0],
                "valid_solution": parts[1],
                "solution_time_s": parts[2],
                "total_time_s": parts[3],
                "aborted": parts[9] if len(parts) > 9 else "",
            }
        elif line.startswith("M "):
            _tag, left, right = line.split()
            pairs.append((int(left), int(right)))
    return metrics, pairs


def induced_edges(edges: set[tuple[int, int]], nodes: set[int]) -> set[tuple[int, int]]:
    return {(source, target) for source, target in edges if source in nodes and target in nodes}


def verify_induced(
    left_edges_all: set[tuple[int, int]],
    right_edges_all: set[tuple[int, int]],
    pairs: list[tuple[int, int]],
) -> tuple[bool, int, int, int, int]:
    left_nodes = {left for left, _right in pairs}
    right_nodes = {right for _left, right in pairs}
    mapping = dict(pairs)
    left_edges = induced_edges(left_edges_all, left_nodes)
    right_edges = induced_edges(right_edges_all, right_nodes)
    mapped_left_edges = {(mapping[source], mapping[target]) for source, target in left_edges}
    missing = len(mapped_left_edges - right_edges)
    extra = len(right_edges - mapped_left_edges)
    return missing == 0 and extra == 0, len(left_edges), len(right_edges), missing, extra


def main() -> int:
    args = parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    left_edges = random_directed_edges(args.nodes, args.edge_prob, args.seed)
    right_edges = random_directed_edges(args.nodes, args.edge_prob, args.seed + 1)
    left_path = args.work_dir / "left.dimacs"
    right_path = args.work_dir / "right.dimacs"
    write_dimacs(left_path, args.nodes, left_edges)
    write_dimacs(right_path, args.nodes, right_edges)

    cmd = [
        str(args.solver.resolve()),
        "min_max",
        str(left_path),
        str(right_path),
        "-d",
        "-i",
        "-q",
        "-t",
        str(args.timeout),
    ]
    proc = subprocess.run(cmd, cwd=Path(__file__).resolve().parent.parent, capture_output=True, text=True, check=False)
    metrics, pairs = parse_solution(proc.stdout)
    induced_ok, left_mcs_edges, right_mcs_edges, missing, extra = verify_induced(left_edges, right_edges, pairs)

    print(f"returncode={proc.returncode}")
    print(f"metrics={metrics}")
    print(f"pairs={len(pairs)}")
    print(f"left_mcs_edges={left_mcs_edges}")
    print(f"right_mcs_edges={right_mcs_edges}")
    print(f"missing_mapped_left_edges_in_right={missing}")
    print(f"extra_right_edges_not_in_left={extra}")
    print(f"external_induced_valid={int(induced_ok)}")
    if proc.stderr.strip():
        print("stderr:")
        print(proc.stderr.strip())

    solver_valid = metrics.get("valid_solution") == "1"
    return 0 if proc.returncode == 0 and solver_valid and induced_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

