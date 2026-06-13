#!/usr/bin/env python3
"""Convert FlyWire CSV edge lists to KaHIP format and run ARCIS.

ARCIS/KaMIS solves independent set on undirected graphs. The FlyWire inputs are
directed CSV edge lists, so this wrapper uses the weak/symmetrized graph: any
directed edge u->v or v->u becomes one undirected conflict edge {u, v}.
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "inputs",
        nargs="*",
        type=Path,
        help="CSV edge-list files. Defaults to data/raw_graphs/*_edge_list.csv.",
    )
    parser.add_argument("--arcis", type=Path, default=Path("ARCIS/ARCIS"))
    parser.add_argument("--out-dir", type=Path, default=Path("outputs/arcis"))
    parser.add_argument("--seeds", type=int, nargs="+", default=[1])
    parser.add_argument("--time-limit", type=float, default=300.0)
    parser.add_argument(
        "--wall-timeout",
        type=float,
        default=None,
        help="Optional subprocess wall timeout in seconds. Timed-out runs get returncode 124.",
    )
    parser.add_argument("--M", type=int, default=200000)
    parser.add_argument("--P", type=float, default=0.4)
    parser.add_argument(
        "--vcsolver",
        type=int,
        default=0,
        help="Use 0 when actual independent-set vertices are needed. The bundled vcsolver=1 path only reports sizes unless the graph fully reduces.",
    )
    parser.add_argument("--mode", type=int, default=1)
    parser.add_argument(
        "--threads",
        type=int,
        default=1,
        help="OpenMP thread count for ARCIS. The paper's experiments use single-threaded runs.",
    )
    parser.add_argument(
        "--reuse-converted",
        action="store_true",
        help="Skip conversion when graph and map files already exist.",
    )
    return parser.parse_args()


def graph_stem(csv_path: Path) -> str:
    stem = csv_path.stem
    return stem[:-10] if stem.endswith("_edge_list") else stem


def convert_csv_to_kahip(csv_path: Path, graph_path: Path, map_path: Path) -> tuple[int, int]:
    neighbors: dict[int, set[int]] = defaultdict(set)

    with csv_path.open(newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header is None:
            raise ValueError(f"{csv_path} is empty")

        for row_number, row in enumerate(reader, start=2):
            if len(row) < 2:
                continue
            try:
                source = int(row[0])
                target = int(row[1])
            except ValueError as exc:
                raise ValueError(f"invalid integer edge at {csv_path}:{row_number}: {row}") from exc
            if source == target:
                neighbors.setdefault(source, set())
                continue
            neighbors[source].add(target)
            neighbors[target].add(source)

    node_ids = sorted(neighbors)
    index_by_id = {node_id: index + 1 for index, node_id in enumerate(node_ids)}
    edge_count = sum(len(values) for values in neighbors.values()) // 2

    graph_path.parent.mkdir(parents=True, exist_ok=True)
    with graph_path.open("w", newline="\n") as handle:
        handle.write(f"{len(node_ids)} {edge_count}\n")
        for node_id in node_ids:
            adjacency = sorted(index_by_id[neighbor] for neighbor in neighbors[node_id])
            handle.write(" ".join(map(str, adjacency)))
            handle.write("\n")

    with map_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["arcis_index", "node_id"])
        for index, node_id in enumerate(node_ids, start=1):
            writer.writerow([index, node_id])

    return len(node_ids), edge_count


def read_map(map_path: Path) -> list[int]:
    ids: list[int] = []
    with map_path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            ids.append(int(row["node_id"]))
    return ids


def translate_solution(solution_path: Path, map_path: Path, csv_path: Path) -> int:
    node_ids = read_map(map_path)
    selected: list[int] = []

    with solution_path.open() as handle:
        for index, line in enumerate(handle, start=1):
            value = line.strip()
            if value in {"1", "true", "True"}:
                selected.append(node_ids[index - 1])

    with csv_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["node_id"])
        for node_id in selected:
            writer.writerow([node_id])

    return len(selected)


def run_arcis(args: argparse.Namespace, graph_path: Path, output_path: Path, seed: int) -> subprocess.CompletedProcess[str]:
    command = [
        str(args.arcis),
        str(graph_path),
        f"--seed={seed}",
        f"--M={args.M}",
        f"--P={args.P}",
        f"--time_limit={args.time_limit}",
        f"--vcsolver={args.vcsolver}",
        f"--mode={args.mode}",
        f"--output={output_path}",
        "--console_log",
    ]
    try:
        env = os.environ.copy()
        env["OMP_NUM_THREADS"] = str(args.threads)
        return subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=args.wall_timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode(errors="replace")
        stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode(errors="replace")
        return subprocess.CompletedProcess(command, 124, stdout, stderr + "\nARCIS wrapper wall timeout expired.\n")


def main() -> int:
    args = parse_args()
    repo_root = Path.cwd()

    if not args.inputs:
        args.inputs = sorted((repo_root / "data" / "raw_graphs").glob("*_edge_list.csv"))

    args.arcis = args.arcis.resolve()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    converted_dir = args.out_dir / "converted"
    solutions_dir = args.out_dir / "solutions"
    logs_dir = args.out_dir / "logs"
    converted_dir.mkdir(parents=True, exist_ok=True)
    solutions_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    summary_path = args.out_dir / "summary.csv"
    with summary_path.open("w", newline="") as summary_handle:
        summary = csv.writer(summary_handle)
        summary.writerow(
            [
                "graph",
                "nodes",
                "undirected_edges",
                "seed",
                "returncode",
                "independent_set_size",
                "solution_csv",
                "stdout_log",
                "stderr_log",
            ]
        )

        for input_path in args.inputs:
            input_path = input_path.resolve()
            stem = graph_stem(input_path)
            graph_path = converted_dir / f"{stem}.graph"
            map_path = converted_dir / f"{stem}.map.csv"

            if args.reuse_converted and graph_path.exists() and map_path.exists():
                with graph_path.open() as handle:
                    first = handle.readline().split()
                nodes, undirected_edges = int(first[0]), int(first[1])
            else:
                print(f"Converting {input_path}", flush=True)
                nodes, undirected_edges = convert_csv_to_kahip(input_path, graph_path, map_path)

            for seed in args.seeds:
                raw_solution = solutions_dir / f"{stem}.seed{seed}.arcis.txt"
                solution_csv = solutions_dir / f"{stem}.seed{seed}.nodes.csv"
                stdout_log = logs_dir / f"{stem}.seed{seed}.stdout.log"
                stderr_log = logs_dir / f"{stem}.seed{seed}.stderr.log"

                print(f"Running ARCIS on {stem} seed={seed}", flush=True)
                result = run_arcis(args, graph_path, raw_solution, seed)
                stdout_log.write_text(result.stdout)
                stderr_log.write_text(result.stderr)

                is_size = ""
                if result.returncode == 0 and raw_solution.exists():
                    is_size = translate_solution(raw_solution, map_path, solution_csv)

                summary.writerow(
                    [
                        stem,
                        nodes,
                        undirected_edges,
                        seed,
                        result.returncode,
                        is_size,
                        solution_csv if solution_csv.exists() else "",
                        stdout_log,
                        stderr_log,
                    ]
                )
                summary_handle.flush()

    print(f"Wrote {summary_path}")
    return 0


if __name__ == "__main__":
    os.chdir(Path(__file__).resolve().parents[1])
    sys.exit(main())
