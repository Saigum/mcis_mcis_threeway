#!/usr/bin/env python3
"""Run pairwise RRSplit MCS between WCC-induced subgraphs from different graphs."""

from __future__ import annotations

import argparse
import csv
import itertools
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class ComponentSpec:
    graph: str
    component_id: int
    size: int
    source_csv: Path
    assignment_csv: Path
    output_csv: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw_graphs"))
    parser.add_argument("--wcc-dir", type=Path, default=Path("outputs/wcc_raw"))
    parser.add_argument("--out-dir", type=Path, default=Path("outputs/rrsplit_wcc_gt140"))
    parser.add_argument("--solver", type=Path, default=Path("../SIGMOD25-MCSS/RRSplit/mcsp"))
    parser.add_argument("--min-nodes", type=int, default=141)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument(
        "--memory-cap-gib",
        type=float,
        default=24.0,
        help="Skip pairs whose estimated dense-load footprint exceeds this cap.",
    )
    parser.add_argument(
        "--run-skipped-anyway",
        action="store_true",
        help="Ignore the memory estimate and try every pair.",
    )
    parser.add_argument("--reuse-induced", action="store_true")
    return parser.parse_args()


def graph_stem(csv_path: Path) -> str:
    stem = csv_path.stem
    return stem[:-10] if stem.endswith("_edge_list") else stem


def read_large_components(wcc_dir: Path, min_nodes: int) -> list[ComponentSpec]:
    specs: list[ComponentSpec] = []
    components_dir = wcc_dir / "components"
    assignments_dir = wcc_dir / "assignments"
    for components_csv in sorted(components_dir.glob("*.wcc_components.csv")):
        graph = components_csv.name.removesuffix(".wcc_components.csv")
        source_csv = ROOT / "data" / "raw_graphs" / f"{graph}_edge_list.csv"
        assignment_csv = assignments_dir / f"{graph}.wcc_assignments.csv"
        with components_csv.open(newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                size = int(row["size"])
                if size >= min_nodes:
                    specs.append(
                        ComponentSpec(
                            graph=graph,
                            component_id=int(row["component_id"]),
                            size=size,
                            source_csv=source_csv,
                            assignment_csv=assignment_csv,
                            output_csv=Path(),
                        )
                    )
    return specs


def load_component_nodes(assignment_csv: Path, component_id: int) -> set[int]:
    nodes: set[int] = set()
    with assignment_csv.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if int(row["component_id"]) == component_id:
                nodes.add(int(row["node_id"]))
    return nodes


def write_induced_component(spec: ComponentSpec, out_dir: Path, reuse: bool) -> ComponentSpec:
    induced_dir = out_dir / "induced_csv"
    induced_dir.mkdir(parents=True, exist_ok=True)
    out_csv = induced_dir / f"{spec.graph}.wcc{spec.component_id}.n{spec.size}.csv"
    if reuse and out_csv.exists():
        return ComponentSpec(**{**spec.__dict__, "output_csv": out_csv})

    allowed = load_component_nodes(spec.assignment_csv, spec.component_id)
    with spec.source_csv.open(newline="") as in_handle, out_csv.open("w", newline="") as out_handle:
        reader = csv.DictReader(in_handle)
        writer = csv.writer(out_handle)
        writer.writerow(["source neuron id", "target neuron id"])
        for row in reader:
            source = int(row["source neuron id"])
            target = int(row["target neuron id"])
            if source in allowed and target in allowed:
                writer.writerow([source, target])

    return ComponentSpec(**{**spec.__dict__, "output_csv": out_csv})


def csv_to_dimacs(csv_path: Path, dimacs_path: Path) -> tuple[int, int]:
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

    sorted_nodes = sorted(nodes)
    node_to_index = {node_id: index + 1 for index, node_id in enumerate(sorted_nodes)}
    with dimacs_path.open("w", newline="\n") as handle:
        handle.write(f"p edge {len(sorted_nodes)} {len(edges)}\n")
        for source, target in edges:
            handle.write(f"e {node_to_index[source]} {node_to_index[target]}\n")

    return len(sorted_nodes), len(edges)


def estimate_dense_load_gib(n1: int, n2: int) -> float:
    # RRSplit stores original and sorted dense unsigned-int matrices for each graph.
    # This ignores vector overhead and adjacency-list structures, so it is a lower bound.
    bytes_needed = 2 * 4 * (n1 * n1 + n2 * n2)
    return bytes_needed / (1024**3)


def run_pair(args: argparse.Namespace, left: ComponentSpec, right: ComponentSpec, run_dir: Path) -> dict[str, object]:
    pair_name = f"{left.graph}_wcc{left.component_id}__{right.graph}_wcc{right.component_id}"
    dimacs_dir = run_dir / "dimacs"
    logs_dir = run_dir / "logs"
    dimacs_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    left_dimacs = dimacs_dir / f"{left.graph}.wcc{left.component_id}.dimacs"
    right_dimacs = dimacs_dir / f"{right.graph}.wcc{right.component_id}.dimacs"
    left_nodes, left_edges = csv_to_dimacs(left.output_csv, left_dimacs)
    right_nodes, right_edges = csv_to_dimacs(right.output_csv, right_dimacs)

    estimate_gib = estimate_dense_load_gib(left_nodes, right_nodes)
    base_row: dict[str, object] = {
        "left_graph": left.graph,
        "left_component_id": left.component_id,
        "left_nodes": left_nodes,
        "left_edges": left_edges,
        "right_graph": right.graph,
        "right_component_id": right.component_id,
        "right_nodes": right_nodes,
        "right_edges": right_edges,
        "estimated_dense_load_gib": f"{estimate_gib:.3f}",
        "timeout_s": args.timeout,
        "status": "",
        "mcs_size": "",
        "branches": "",
        "runtime_ms": "",
        "stdout_log": logs_dir / f"{pair_name}.stdout.log",
        "stderr_log": logs_dir / f"{pair_name}.stderr.log",
    }

    if not args.run_skipped_anyway and estimate_gib > args.memory_cap_gib:
        base_row["status"] = f"skipped_memory_estimate_gt_{args.memory_cap_gib:g}GiB"
        return base_row

    cmd = [
        str(args.solver.resolve()),
        "-d",
        "-i",
        "-q",
        "-t",
        str(args.timeout),
        "min_max",
        str(left_dimacs.resolve()),
        str(right_dimacs.resolve()),
    ]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
    Path(base_row["stdout_log"]).write_text(proc.stdout)
    Path(base_row["stderr_log"]).write_text(proc.stderr)

    base_row["status"] = "ok" if proc.returncode == 0 else f"returncode_{proc.returncode}"
    match = re.search(r"^#2:\s+(\d+)(?:\s+(\d+)\s+(\d+))?", proc.stdout, re.MULTILINE)
    if match:
        base_row["mcs_size"] = match.group(1)
        base_row["branches"] = match.group(2) or ""
        base_row["runtime_ms"] = match.group(3) or ""
    return base_row


def main() -> int:
    args = parse_args()
    args.raw_dir = args.raw_dir.resolve()
    args.wcc_dir = args.wcc_dir.resolve()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    specs = read_large_components(args.wcc_dir, args.min_nodes)
    induced_specs = [write_induced_component(spec, args.out_dir, args.reuse_induced) for spec in specs]

    summary_path = args.out_dir / "pairwise_mcs_summary.csv"
    fields = [
        "left_graph",
        "left_component_id",
        "left_nodes",
        "left_edges",
        "right_graph",
        "right_component_id",
        "right_nodes",
        "right_edges",
        "estimated_dense_load_gib",
        "timeout_s",
        "status",
        "mcs_size",
        "branches",
        "runtime_ms",
        "stdout_log",
        "stderr_log",
    ]

    with summary_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for left, right in itertools.combinations(induced_specs, 2):
            if left.graph == right.graph:
                continue
            print(f"Pair {left.graph}.wcc{left.component_id} x {right.graph}.wcc{right.component_id}", flush=True)
            row = run_pair(args, left, right, args.out_dir)
            writer.writerow(row)
            handle.flush()
            print(f"  {row['status']} mcs={row['mcs_size']} est={row['estimated_dense_load_gib']}GiB", flush=True)

    print(f"Wrote {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
