#!/usr/bin/env python3
"""Search an existing pairwise MCS pattern inside a third sampled graph."""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mcs-csv", type=Path, required=True)
    parser.add_argument(
        "--pattern-side",
        choices=["left", "right"],
        default="left",
        help="Which side of the pairwise MCS to use as the pattern graph.",
    )
    parser.add_argument(
        "--source-sample-csv",
        type=Path,
        default=None,
        help="Sample CSV containing the pattern-side nodes. Inferred from --mcs-csv when omitted.",
    )
    parser.add_argument("--third-dimacs", type=Path, required=True)
    parser.add_argument("--third-map", type=Path, required=True)
    parser.add_argument("--solver", type=Path, default=Path("../symsplit/bin/run.o"))
    parser.add_argument("--out-dir", type=Path, default=Path("outputs/symsplit_third_search"))
    parser.add_argument("--timeout", type=int, default=540)
    parser.add_argument("--wall-timeout", type=int, default=660)
    parser.add_argument("--rerun-existing", action="store_true")
    return parser.parse_args()


def infer_source_sample_csv(mcs_csv: Path, side: str) -> Path:
    # Expected pair filename:
    # left__right.n1000.sample_id.mcs_nodes.csv
    name = mcs_csv.name.removesuffix(".mcs_nodes.csv")
    left_right, rest = name.split(".n", 1)
    left_graph, right_graph = left_right.split("__", 1)
    sample_suffix = f"n{rest}"
    graph = left_graph if side == "left" else right_graph
    return mcs_csv.parents[1] / "samples" / f"{graph}.{sample_suffix}.csv"


def read_mcs_nodes(mcs_csv: Path, side: str) -> tuple[str, list[int]]:
    with mcs_csv.open(newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        graph_name = header[0] if side == "left" else header[1]
        column = 0 if side == "left" else 1
        nodes = [int(row[column]) for row in reader if row]
    return graph_name, nodes


def write_pattern_files(
    graph_name: str,
    nodes: list[int],
    source_sample_csv: Path,
    out_dir: Path,
    pattern_stem: str,
) -> tuple[Path, Path, Path, int]:
    pattern_dir = out_dir / "patterns"
    pattern_dir.mkdir(parents=True, exist_ok=True)
    pattern_csv = pattern_dir / f"{pattern_stem}.csv"
    pattern_dimacs = pattern_dir / f"{pattern_stem}.dimacs"
    pattern_map = pattern_dir / f"{pattern_stem}.map.csv"

    allowed = set(nodes)
    ordered_nodes = sorted(allowed)
    node_to_index = {node_id: index + 1 for index, node_id in enumerate(ordered_nodes)}
    edges: list[tuple[int, int]] = []

    with source_sample_csv.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            source = int(row["source neuron id"])
            target = int(row["target neuron id"])
            if source in allowed and target in allowed:
                edges.append((source, target))

    with pattern_csv.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["source neuron id", "target neuron id"])
        writer.writerows(edges)

    with pattern_map.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["symsplit_index", "node_id"])
        for index, node_id in enumerate(ordered_nodes):
            writer.writerow([index, node_id])

    with pattern_dimacs.open("w", newline="\n") as handle:
        handle.write(f"p edge {len(ordered_nodes)} {len(edges)}\n")
        for source, target in edges:
            handle.write(f"e {node_to_index[source]} {node_to_index[target]}\n")

    return pattern_csv, pattern_dimacs, pattern_map, len(edges)


def read_index_map(map_path: Path) -> list[int]:
    values: list[int] = []
    with map_path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            values.append(int(row["node_id"]))
    return values


def parse_symsplit(stdout: str) -> tuple[dict[str, str], list[tuple[int, int]]]:
    metrics: dict[str, str] = {}
    pairs: list[tuple[int, int]] = []
    for line in stdout.splitlines():
        if line.startswith("M "):
            _tag, left, right = line.split()
            pairs.append((int(left), int(right)))
        elif re.match(r"^\d+,\s*", line):
            parts = [part.strip() for part in line.split(",")]
            if len(parts) >= 10:
                metrics = {
                    "mcs_size": parts[0],
                    "valid_solution": parts[1],
                    "solution_time_s": parts[2],
                    "total_time_s": parts[3],
                    "branches": parts[4],
                    "calls_for_optimal": parts[5],
                    "cut_branches": parts[6],
                    "left_pruned": parts[7],
                    "right_pruned": parts[8],
                    "aborted": parts[9],
                }
    return metrics, pairs


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    source_sample_csv = args.source_sample_csv or infer_source_sample_csv(args.mcs_csv, args.pattern_side)

    graph_name, pattern_nodes = read_mcs_nodes(args.mcs_csv, args.pattern_side)
    third_stem = args.third_dimacs.stem
    pattern_stem = f"{args.mcs_csv.stem}.{args.pattern_side}_pattern"
    result_stem = f"{pattern_stem}__in__{third_stem}"

    logs_dir = args.out_dir / "logs"
    matches_dir = args.out_dir / "matches"
    logs_dir.mkdir(parents=True, exist_ok=True)
    matches_dir.mkdir(parents=True, exist_ok=True)
    stdout_log = logs_dir / f"{result_stem}.stdout.log"
    stderr_log = logs_dir / f"{result_stem}.stderr.log"
    match_csv = matches_dir / f"{result_stem}.nodes.csv"
    summary_csv = args.out_dir / f"{result_stem}.summary.csv"

    if not args.rerun_existing and match_csv.exists() and stdout_log.exists() and summary_csv.exists():
        print(f"Existing result: {summary_csv}")
        return 0

    pattern_csv, pattern_dimacs, pattern_map, pattern_edges = write_pattern_files(
        graph_name,
        pattern_nodes,
        source_sample_csv,
        args.out_dir,
        pattern_stem,
    )

    cmd = [
        str(args.solver.resolve()),
        "min_max",
        str(pattern_dimacs.resolve()),
        str(args.third_dimacs.resolve()),
        "-d",
        "-i",
        "-q",
        "-t",
        str(args.timeout),
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=args.wall_timeout,
        )
        stdout = proc.stdout
        stderr = proc.stderr
        returncode = proc.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode(errors="replace")
        stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode(errors="replace")
        stderr += "\nwrapper wall timeout expired\n"
        returncode = 124

    stdout_log.write_text(stdout)
    stderr_log.write_text(stderr)
    metrics, pairs = parse_symsplit(stdout)
    pattern_map_values = read_index_map(pattern_map)
    third_map_values = read_index_map(args.third_map)

    with match_csv.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([f"{graph_name}_pattern", "third_graph", "pattern_symsplit_index", "third_symsplit_index"])
        for pattern_index, third_index in pairs:
            if 0 <= pattern_index < len(pattern_map_values) and 0 <= third_index < len(third_map_values):
                writer.writerow([pattern_map_values[pattern_index], third_map_values[third_index], pattern_index, third_index])

    fields = [
        "source_mcs_csv",
        "pattern_side",
        "source_sample_csv",
        "pattern_csv",
        "pattern_dimacs",
        "pattern_nodes",
        "pattern_edges",
        "third_dimacs",
        "third_map",
        "returncode",
        "mcs_size",
        "pattern_fully_present",
        "valid_solution",
        "solution_time_s",
        "total_time_s",
        "branches",
        "calls_for_optimal",
        "cut_branches",
        "aborted",
        "match_csv",
        "stdout_log",
        "stderr_log",
    ]
    row = {
        "source_mcs_csv": args.mcs_csv,
        "pattern_side": args.pattern_side,
        "source_sample_csv": source_sample_csv,
        "pattern_csv": pattern_csv,
        "pattern_dimacs": pattern_dimacs,
        "pattern_nodes": len(pattern_nodes),
        "pattern_edges": pattern_edges,
        "third_dimacs": args.third_dimacs,
        "third_map": args.third_map,
        "returncode": returncode,
        "mcs_size": metrics.get("mcs_size", len(pairs)),
        "pattern_fully_present": str(int(int(metrics.get("mcs_size", len(pairs))) == len(pattern_nodes))),
        "valid_solution": metrics.get("valid_solution", ""),
        "solution_time_s": metrics.get("solution_time_s", ""),
        "total_time_s": metrics.get("total_time_s", ""),
        "branches": metrics.get("branches", ""),
        "calls_for_optimal": metrics.get("calls_for_optimal", ""),
        "cut_branches": metrics.get("cut_branches", ""),
        "aborted": metrics.get("aborted", ""),
        "match_csv": match_csv,
        "stdout_log": stdout_log,
        "stderr_log": stderr_log,
    }
    with summary_csv.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow(row)

    print(summary_csv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
