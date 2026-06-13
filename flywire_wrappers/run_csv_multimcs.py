#!/usr/bin/env python3
import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "Multi-Maximum-Common-Subgraph"
BUILD_DIR = SRC_DIR / "build"
BIN_PATH = BUILD_DIR / "McSplit_Multigraph"


@dataclass
class ConvertedGraph:
    csv_path: Path
    dimacs_path: Path
    index_to_node_id: list[int]
    edge_count: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert directed edge-list CSVs to DIMACS, run Multi-Maximum-Common-Subgraph, and map the result back to original node IDs."
    )
    parser.add_argument("csv_files", nargs="*", help="Directed edge-list CSV files")
    parser.add_argument(
        "--output-csv",
        default="multimcs_solution.csv",
        help="Output CSV with matched node IDs",
    )
    parser.add_argument(
        "--solver",
        default=str(BIN_PATH),
        help="Path to compiled McSplit_Multigraph binary",
    )
    parser.add_argument(
        "--compile",
        action="store_true",
        help="Compile the solver before running",
    )
    parser.add_argument(
        "--compile-command",
        default="module load u22/nvhpc/25.3 && mkdir -p build && nvcc -std=c++17 -O2 mcsp-mt.cu graph.cu -o build/McSplit_Multigraph",
        help="Shell command used when --compile is set",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=1,
        help="Threads passed to the solver",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=0,
        help="Solver timeout in seconds",
    )
    parser.add_argument(
        "--restrict-to-common-node-ids",
        action="store_true",
        help="Restrict every graph to the node IDs present in all input files before building the induced subgraphs",
    )
    parser.add_argument(
        "--max-nodes",
        type=int,
        default=0,
        help="Abort if any converted graph exceeds this many nodes after preprocessing; 0 disables the check",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep the temporary DIMACS files",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run a synthetic directed 3-graph self-test and exit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only preprocess and report graph sizes; do not invoke the solver",
    )
    return parser.parse_args()


def compile_solver(cmd: str) -> None:
    BUILD_DIR.mkdir(exist_ok=True)
    subprocess.run(
        cmd,
        cwd=SRC_DIR,
        shell=True,
        check=True,
        executable="/bin/bash",
    )


def read_edges(csv_path: Path) -> tuple[set[int], list[tuple[int, int]]]:
    nodes: set[int] = set()
    edges: list[tuple[int, int]] = []
    with csv_path.open(newline="") as f:
        reader = csv.DictReader(f)
        expected = {"source neuron id", "target neuron id"}
        if set(reader.fieldnames or []) != expected:
            raise ValueError(f"{csv_path} has unexpected columns: {reader.fieldnames}")
        for row in reader:
            src = int(row["source neuron id"])
            dst = int(row["target neuron id"])
            nodes.add(src)
            nodes.add(dst)
            edges.append((src, dst))
    return nodes, edges


def convert_csv_to_dimacs(
    csv_path: Path, temp_dir: Path, allowed_nodes: set[int] | None
) -> ConvertedGraph:
    nodes, edges = read_edges(csv_path)
    if allowed_nodes is not None:
        nodes &= allowed_nodes
        edges = [(u, v) for (u, v) in edges if u in nodes and v in nodes]
    sorted_nodes = sorted(nodes)
    node_to_index = {node_id: idx + 1 for idx, node_id in enumerate(sorted_nodes)}
    dimacs_path = temp_dir / f"{csv_path.stem}.dimacs"
    with dimacs_path.open("w") as f:
        f.write(f"p edge {len(sorted_nodes)} {len(edges)}\n")
        for src, dst in edges:
            f.write(f"e {node_to_index[src]} {node_to_index[dst]}\n")
    return ConvertedGraph(
        csv_path=csv_path,
        dimacs_path=dimacs_path,
        index_to_node_id=sorted_nodes,
        edge_count=len(edges),
    )


def parse_solver_output(stdout: str, graph_count: int) -> tuple[int, list[list[int]]]:
    matches: list[list[int]] = []
    sol_size = None
    row_re = re.compile(r"^\s*(\d+(?:\s*->\s*\d+){%d})\s*$" % (graph_count - 1))
    for line in stdout.splitlines():
        m = row_re.match(line)
        if m:
            matches.append([int(part.strip()) for part in m.group(1).split("->")])
        if line.startswith(">>>"):
            sol_size = int(line.split()[1])
    if sol_size is None:
        raise RuntimeError(f"Could not parse solution size from solver output:\n{stdout}")
    if sol_size != len(matches):
        raise RuntimeError(
            f"Parsed {len(matches)} match rows, but solver reported size {sol_size}."
        )
    return sol_size, matches


def map_matches_to_node_ids(
    matches: list[list[int]], converted: list[ConvertedGraph]
) -> list[list[int]]:
    mapped: list[list[int]] = []
    for row in matches:
        mapped_row = []
        for graph_idx, one_based_index in enumerate(row):
            mapped_row.append(converted[graph_idx].index_to_node_id[one_based_index])
        mapped.append(mapped_row)
    return mapped


def write_output_csv(output_csv: Path, headers: list[str], rows: list[list[int]]) -> None:
    with output_csv.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)


def run_solver(
    solver: Path,
    converted: list[ConvertedGraph],
    threads: int,
    timeout: int,
) -> tuple[int, list[list[int]], str]:
    cmd = [str(solver), "-d", "-i", "-T", str(threads), "min_product"]
    if timeout:
        cmd.extend(["-t", str(timeout)])
    cmd.extend(str(g.dimacs_path) for g in converted)
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    sol_size, matches = parse_solver_output(proc.stdout, len(converted))
    return sol_size, matches, proc.stdout


def synthetic_test(temp_dir: Path, args: argparse.Namespace) -> int:
    graphs = [
        [(100, 200), (200, 300), (100, 300), (400, 100)],
        [(11, 22), (22, 33), (11, 33), (44, 11)],
        [(7, 8), (8, 9), (7, 9), (10, 7)],
    ]
    paths = []
    for idx, edges in enumerate(graphs, start=1):
        path = temp_dir / f"synthetic_{idx}.csv"
        with path.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["source neuron id", "target neuron id"])
            writer.writerows(edges)
        paths.append(path)

    converted = [convert_csv_to_dimacs(path, temp_dir, None) for path in paths]
    sol_size, matches, stdout = run_solver(Path(args.solver), converted, args.threads, args.timeout)
    mapped = map_matches_to_node_ids(matches, converted)
    if sol_size != 4:
        raise RuntimeError(f"Synthetic self-test expected size 4, got {sol_size}\n{stdout}")
    out_path = ROOT / "synthetic_directed_solution.csv"
    write_output_csv(out_path, [p.stem for p in paths], mapped)
    print(f"Synthetic self-test passed with solution size {sol_size}")
    print(f"Wrote {out_path}")
    return 0


def main() -> int:
    args = parse_args()

    if args.compile:
        compile_solver(args.compile_command)

    solver = Path(args.solver)
    if not solver.exists():
        raise FileNotFoundError(f"Solver binary not found: {solver}")

    temp_dir_ctx = tempfile.TemporaryDirectory(prefix="multimcs_")
    temp_dir = Path(temp_dir_ctx.name)
    try:
        if args.self_test:
            return synthetic_test(temp_dir, args)

        if not args.csv_files:
            raise SystemExit("csv_files are required unless --self-test is used")
        csv_paths = [Path(p).resolve() for p in args.csv_files]
        headers = [p.stem for p in csv_paths]

        common_nodes = None
        if args.restrict_to_common_node_ids:
            common_sets = []
            for path in csv_paths:
                nodes, _ = read_edges(path)
                common_sets.append(nodes)
            common_nodes = set.intersection(*common_sets)
            print(f"Common node IDs across all graphs: {len(common_nodes)}")

        converted = [convert_csv_to_dimacs(path, temp_dir, common_nodes) for path in csv_paths]
        for graph in converted:
            print(
                f"{graph.csv_path.name}: {len(graph.index_to_node_id)} nodes, {graph.edge_count} directed edges after preprocessing"
            )
            if args.max_nodes and len(graph.index_to_node_id) > args.max_nodes:
                raise RuntimeError(
                    f"{graph.csv_path.name} has {len(graph.index_to_node_id)} nodes after preprocessing, which exceeds --max-nodes={args.max_nodes}"
                )

        if args.dry_run:
            return 0

        sol_size, matches, stdout = run_solver(solver, converted, args.threads, args.timeout)
        mapped = map_matches_to_node_ids(matches, converted)

        output_csv = Path(args.output_csv).resolve()
        write_output_csv(output_csv, headers, mapped)
        print(f"Largest common subgraph size: {sol_size}")
        print(f"Wrote {output_csv}")
        print(stdout)
        return 0
    finally:
        if args.keep_temp:
            kept_dir = ROOT / "multimcs_tmp"
            if kept_dir.exists():
                shutil.rmtree(kept_dir)
            shutil.copytree(temp_dir, kept_dir)
            print(f"Kept temp files in {kept_dir}")
        temp_dir_ctx.cleanup()


if __name__ == "__main__":
    sys.exit(main())
