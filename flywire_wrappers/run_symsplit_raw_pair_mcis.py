#!/usr/bin/env python3
"""Run SymSplit MCIS on two complete raw FlyWire edge-list CSVs."""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
import threading
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
METRIC_KEYS = [
    "mcs_size",
    "valid_solution",
    "solution_time_s",
    "total_time_s",
    "branches",
    "calls_for_optimal",
    "cut_branches",
    "left_pruned",
    "right_pruned",
    "aborted",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path, help="Left raw edge-list CSV.")
    parser.add_argument("right", type=Path, help="Right raw edge-list CSV.")
    parser.add_argument("--out-dir", type=Path, default=Path("outputs/symsplit_raw_pair_mcis"))
    parser.add_argument("--solver", type=Path, default=Path("../symsplit/bin/run.o"))
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--wall-timeout", type=int, default=2100)
    parser.add_argument("--rerun-existing", action="store_true")
    return parser.parse_args()


def graph_stem(csv_path: Path) -> str:
    stem = csv_path.stem
    return stem[:-10] if stem.endswith("_edge_list") else stem


def read_raw_edges(csv_path: Path) -> tuple[list[int], list[tuple[int, int]]]:
    nodes: set[int] = set()
    edges: list[tuple[int, int]] = []
    with csv_path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            source = int(row["source neuron id"])
            target = int(row["target neuron id"])
            nodes.add(source)
            nodes.add(target)
            edges.append((source, target))
    return sorted(nodes), edges


def write_dimacs_and_map(csv_path: Path, out_dir: Path) -> tuple[Path, Path, int, int]:
    graph = graph_stem(csv_path)
    dimacs_dir = out_dir / "dimacs"
    map_dir = out_dir / "maps"
    dimacs_dir.mkdir(parents=True, exist_ok=True)
    map_dir.mkdir(parents=True, exist_ok=True)

    dimacs_path = dimacs_dir / f"{graph}.full.dimacs"
    map_path = map_dir / f"{graph}.full.map.csv"
    if dimacs_path.exists() and map_path.exists():
        node_count = 0
        edge_count = 0
        with map_path.open(newline="") as handle:
            node_count = sum(1 for _ in handle) - 1
        with dimacs_path.open() as handle:
            for line in handle:
                if line.startswith("p edge "):
                    parts = line.split()
                    edge_count = int(parts[3])
                    break
        return dimacs_path, map_path, node_count, edge_count

    nodes, edges = read_raw_edges(csv_path)
    node_to_index = {node_id: index + 1 for index, node_id in enumerate(nodes)}

    with map_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["symsplit_index", "node_id"])
        for index, node_id in enumerate(nodes):
            writer.writerow([index, node_id])

    with dimacs_path.open("w", newline="\n") as handle:
        handle.write(f"p edge {len(nodes)} {len(edges)}\n")
        for source, target in edges:
            handle.write(f"e {node_to_index[source]} {node_to_index[target]}\n")

    return dimacs_path, map_path, len(nodes), len(edges)


def read_index_map(map_path: Path) -> list[int]:
    node_ids: list[int] = []
    with map_path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            node_ids.append(int(row["node_id"]))
    return node_ids


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
                metrics = dict(zip(METRIC_KEYS, parts[: len(METRIC_KEYS)]))
    return metrics, pairs


def write_mcis_csv(
    path: Path,
    left_graph: str,
    right_graph: str,
    left_map: list[int],
    right_map: list[int],
    pairs: list[tuple[int, int]],
) -> int:
    written = 0
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([left_graph, right_graph, "left_symsplit_index", "right_symsplit_index"])
        for left_index, right_index in pairs:
            if 0 <= left_index < len(left_map) and 0 <= right_index < len(right_map):
                writer.writerow([left_map[left_index], right_map[right_index], left_index, right_index])
                written += 1
    return written


def run_process_streaming(cmd: list[str], cwd: Path, stdout_log: Path, stderr_log: Path, timeout: int) -> int:
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    def pump(stream, path: Path) -> None:
        with path.open("w") as handle:
            for line in iter(stream.readline, ""):
                handle.write(line)
                handle.flush()

    stdout_thread = threading.Thread(target=pump, args=(proc.stdout, stdout_log))
    stderr_thread = threading.Thread(target=pump, args=(proc.stderr, stderr_log))
    stdout_thread.start()
    stderr_thread.start()
    try:
        returncode = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        returncode = 124
        proc.wait()
    stdout_thread.join()
    stderr_thread.join()
    if returncode == 124:
        with stderr_log.open("a") as handle:
            handle.write("\nwrapper wall timeout expired\n")
    return returncode


def dense_matrix_estimate_gib(node_count: int) -> float:
    return (node_count * node_count * 4) / (1024**3)


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    left_csv = args.left.resolve()
    right_csv = args.right.resolve()
    left_graph = graph_stem(left_csv)
    right_graph = graph_stem(right_csv)
    pair_stem = f"{left_graph}__{right_graph}.full"

    logs_dir = args.out_dir / "logs"
    mcis_dir = args.out_dir / "mcis"
    logs_dir.mkdir(parents=True, exist_ok=True)
    mcis_dir.mkdir(parents=True, exist_ok=True)

    stdout_log = logs_dir / f"{pair_stem}.stdout.log"
    stderr_log = logs_dir / f"{pair_stem}.stderr.log"
    mcis_csv = mcis_dir / f"{pair_stem}.mcis_nodes.csv"
    summary_csv = args.out_dir / f"{pair_stem}.summary.csv"

    left_dimacs, left_map_path, left_nodes, left_edges = write_dimacs_and_map(left_csv, args.out_dir)
    right_dimacs, right_map_path, right_nodes, right_edges = write_dimacs_and_map(right_csv, args.out_dir)

    print(f"Left:  {left_graph}: {left_nodes} nodes, {left_edges} edges")
    print(f"Right: {right_graph}: {right_nodes} nodes, {right_edges} edges")
    print(
        "Approx dense matrix storage only: "
        f"{dense_matrix_estimate_gib(left_nodes) + dense_matrix_estimate_gib(right_nodes):.1f} GiB "
        "(actual peak can be higher).",
        file=sys.stderr,
    )

    if not args.rerun_existing and mcis_csv.exists() and stdout_log.exists() and summary_csv.exists():
        print(f"Existing result: {summary_csv}")
        return 0

    cmd = [
        str(args.solver.resolve()),
        "min_max",
        str(left_dimacs.resolve()),
        str(right_dimacs.resolve()),
        "-d",
        "-i",
        "-q",
        "-t",
        str(args.timeout),
    ]
    print("Running:", " ".join(cmd))
    returncode = run_process_streaming(cmd, ROOT, stdout_log, stderr_log, args.wall_timeout)

    stdout = stdout_log.read_text()
    metrics, pairs = parse_symsplit(stdout)
    left_map = read_index_map(left_map_path)
    right_map = read_index_map(right_map_path)
    mapped_pairs = write_mcis_csv(mcis_csv, left_graph, right_graph, left_map, right_map, pairs)

    fields = [
        "left_graph",
        "right_graph",
        "left_nodes",
        "left_edges",
        "right_nodes",
        "right_edges",
        "returncode",
        *METRIC_KEYS,
        "mapped_pairs",
        "left_dimacs",
        "right_dimacs",
        "mcis_csv",
        "stdout_log",
        "stderr_log",
    ]
    row = {
        "left_graph": left_graph,
        "right_graph": right_graph,
        "left_nodes": left_nodes,
        "left_edges": left_edges,
        "right_nodes": right_nodes,
        "right_edges": right_edges,
        "returncode": returncode,
        "mapped_pairs": mapped_pairs,
        "left_dimacs": left_dimacs,
        "right_dimacs": right_dimacs,
        "mcis_csv": mcis_csv,
        "stdout_log": stdout_log,
        "stderr_log": stderr_log,
    }
    row.update(metrics)
    row.setdefault("mcs_size", len(pairs))
    for key in METRIC_KEYS:
        row.setdefault(key, "")

    with summary_csv.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow(row)

    print(f"Summary: {summary_csv}")
    print(f"MCIS nodes: {mcis_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
