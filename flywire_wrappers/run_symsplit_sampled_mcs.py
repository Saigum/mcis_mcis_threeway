#!/usr/bin/env python3
"""Sample induced FlyWire subgraphs and run pairwise SymSplit MCS."""

from __future__ import annotations

import argparse
import csv
import random
import re
import subprocess
import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class SampledGraph:
    graph: str
    sample_size: int
    sample_id: str
    csv_path: Path
    dimacs_path: Path
    map_path: Path
    node_count: int
    edge_count: int


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


@dataclass
class SolutionBlock:
    metrics: dict[str, str]
    pairs: list[tuple[int, int]]
    ordinal: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "inputs",
        nargs="*",
        type=Path,
        help="Raw directed edge-list CSVs. Defaults to data/raw_graphs/*_edge_list.csv.",
    )
    parser.add_argument("--out-dir", type=Path, default=Path("outputs/symsplit_sampled_mcs"))
    parser.add_argument("--solver", type=Path, default=Path("../symsplit/bin/run.o"))
    parser.add_argument("--sizes", type=int, nargs="+", default=[1000, 2000, 4000])
    parser.add_argument("--sample-id", default="high_degree_bfs_seed1")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--wall-timeout", type=int, default=420)
    parser.add_argument("--reuse-samples", action="store_true")
    parser.add_argument(
        "--rerun-existing",
        action="store_true",
        help="Rerun pairwise MCS even when mcs/log outputs already exist.",
    )
    parser.add_argument(
        "--top-k-incumbents",
        type=int,
        default=1,
        help=(
            "Save up to this many largest solution blocks per pair under incumbents/. "
            "Current SymSplit usually emits only the final block unless built to print intermediate incumbents."
        ),
    )
    return parser.parse_args()


def graph_stem(csv_path: Path) -> str:
    stem = csv_path.stem
    return stem[:-10] if stem.endswith("_edge_list") else stem


def read_edges(csv_path: Path) -> tuple[set[int], list[tuple[int, int]], dict[int, set[int]], dict[int, int]]:
    nodes: set[int] = set()
    edges: list[tuple[int, int]] = []
    weak_adj: dict[int, set[int]] = defaultdict(set)
    degree: dict[int, int] = defaultdict(int)

    with csv_path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            source = int(row["source neuron id"])
            target = int(row["target neuron id"])
            nodes.add(source)
            nodes.add(target)
            edges.append((source, target))
            if source != target:
                weak_adj[source].add(target)
                weak_adj[target].add(source)
            else:
                weak_adj[source]
            degree[source] += 1
            degree[target] += 1

    return nodes, edges, weak_adj, degree


def sample_weak_bfs(nodes: set[int], weak_adj: dict[int, set[int]], degree: dict[int, int], size: int, seed: int) -> list[int]:
    if size > len(nodes):
        raise ValueError(f"requested sample size {size}, but graph only has {len(nodes)} nodes")

    rng = random.Random(seed)
    starts = sorted(nodes, key=lambda node: (-degree.get(node, 0), node))
    selected: set[int] = set()
    queue: deque[int] = deque()

    for start in starts:
        if len(selected) >= size:
            break
        if start in selected:
            continue
        selected.add(start)
        queue.append(start)
        while queue and len(selected) < size:
            node = queue.popleft()
            neighbors = list(weak_adj.get(node, ()))
            neighbors.sort(key=lambda neighbor: (-degree.get(neighbor, 0), neighbor))
            # Shuffle within broad degree locality to avoid identical deterministic shells.
            if len(neighbors) > 32:
                head = neighbors[:32]
                tail = neighbors[32:]
                rng.shuffle(head)
                neighbors = head + tail
            for neighbor in neighbors:
                if neighbor not in selected:
                    selected.add(neighbor)
                    queue.append(neighbor)
                    if len(selected) >= size:
                        break

    if len(selected) < size:
        for node in starts:
            selected.add(node)
            if len(selected) >= size:
                break

    return sorted(selected)


def write_sample_outputs(
    graph: str,
    size: int,
    sample_id: str,
    nodes: list[int],
    edges: list[tuple[int, int]],
    out_dir: Path,
    reuse: bool,
) -> SampledGraph:
    sample_dir = out_dir / "samples"
    dimacs_dir = out_dir / "dimacs"
    map_dir = out_dir / "maps"
    sample_dir.mkdir(parents=True, exist_ok=True)
    dimacs_dir.mkdir(parents=True, exist_ok=True)
    map_dir.mkdir(parents=True, exist_ok=True)

    stem = f"{graph}.n{size}.{sample_id}"
    csv_path = sample_dir / f"{stem}.csv"
    dimacs_path = dimacs_dir / f"{stem}.dimacs"
    map_path = map_dir / f"{stem}.map.csv"
    if reuse and csv_path.exists() and dimacs_path.exists() and map_path.exists():
        with csv_path.open(newline="") as handle:
            edge_count = sum(1 for _ in handle) - 1
        return SampledGraph(graph, size, sample_id, csv_path, dimacs_path, map_path, len(nodes), edge_count)

    allowed = set(nodes)
    induced_edges = [(source, target) for source, target in edges if source in allowed and target in allowed]
    node_to_index = {node_id: index for index, node_id in enumerate(nodes)}

    with csv_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["source neuron id", "target neuron id"])
        writer.writerows(induced_edges)

    with map_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["symsplit_index", "node_id"])
        for index, node_id in enumerate(nodes):
            writer.writerow([index, node_id])

    with dimacs_path.open("w", newline="\n") as handle:
        handle.write(f"p edge {len(nodes)} {len(induced_edges)}\n")
        for source, target in induced_edges:
            handle.write(f"e {node_to_index[source] + 1} {node_to_index[target] + 1}\n")

    return SampledGraph(graph, size, sample_id, csv_path, dimacs_path, map_path, len(nodes), len(induced_edges))


def read_index_map(map_path: Path) -> list[int]:
    node_ids: list[int] = []
    with map_path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            node_ids.append(int(row["node_id"]))
    return node_ids


def parse_metrics_line(line: str) -> dict[str, str] | None:
    if not re.match(r"^\d+,\s*", line):
        return None
    parts = [part.strip() for part in line.split(",")]
    if len(parts) < len(METRIC_KEYS):
        return None
    return dict(zip(METRIC_KEYS, parts[: len(METRIC_KEYS)]))


def parse_symsplit_blocks(stdout: str) -> list[SolutionBlock]:
    blocks: list[SolutionBlock] = []
    current_metrics: dict[str, str] | None = None
    current_pairs: list[tuple[int, int]] = []

    for line in stdout.splitlines():
        metrics = parse_metrics_line(line)
        if metrics is not None:
            if current_metrics is not None:
                blocks.append(SolutionBlock(current_metrics, current_pairs, len(blocks) + 1))
            current_metrics = metrics
            current_pairs = []
        elif line.startswith("M ") and current_metrics is not None:
            parts = line.split()
            if len(parts) == 3:
                current_pairs.append((int(parts[1]), int(parts[2])))

    if current_metrics is not None:
        blocks.append(SolutionBlock(current_metrics, current_pairs, len(blocks) + 1))

    return blocks


def parse_symsplit(stdout: str) -> tuple[dict[str, str], list[tuple[int, int]]]:
    blocks = parse_symsplit_blocks(stdout)
    if blocks:
        return blocks[-1].metrics, blocks[-1].pairs
    metrics: dict[str, str] = {}
    pairs: list[tuple[int, int]] = []
    for line in stdout.splitlines():
        if line.startswith("M "):
            _tag, left, right = line.split()
            pairs.append((int(left), int(right)))
    return metrics, pairs


def ranked_solution_blocks(blocks: list[SolutionBlock], top_k: int) -> list[SolutionBlock]:
    if top_k <= 0:
        return []
    return sorted(
        blocks,
        key=lambda block: (
            int(block.metrics.get("mcs_size") or len(block.pairs) or 0),
            len(block.pairs),
            -block.ordinal,
        ),
        reverse=True,
    )[:top_k]


def write_mcs_csv(
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


def read_edge_set(csv_path: Path) -> set[tuple[int, int]]:
    edges: set[tuple[int, int]] = set()
    with csv_path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            source = int(row["source neuron id"])
            target = int(row["target neuron id"])
            if source != target:
                edges.add((source, target))
    return edges


def induced_edge_set(edges: set[tuple[int, int]], nodes: set[int]) -> set[tuple[int, int]]:
    return {(source, target) for source, target in edges if source in nodes and target in nodes}


def validate_directed_induced_mapping(
    left: SampledGraph,
    right: SampledGraph,
    left_map: list[int],
    right_map: list[int],
    pairs: list[tuple[int, int]],
) -> dict[str, int]:
    left_nodes: list[int] = []
    right_nodes: list[int] = []
    out_of_range = 0
    for left_index, right_index in pairs:
        if 0 <= left_index < len(left_map) and 0 <= right_index < len(right_map):
            left_nodes.append(left_map[left_index])
            right_nodes.append(right_map[right_index])
        else:
            out_of_range += 1

    left_node_set = set(left_nodes)
    right_node_set = set(right_nodes)
    duplicate_left = len(left_node_set) != len(left_nodes)
    duplicate_right = len(right_node_set) != len(right_nodes)
    left_edges = induced_edge_set(read_edge_set(left.csv_path), left_node_set)
    right_edges = induced_edge_set(read_edge_set(right.csv_path), right_node_set)

    mapping = dict(zip(left_nodes, right_nodes))
    mapped_left_edges = {(mapping[source], mapping[target]) for source, target in left_edges if source in mapping and target in mapping}
    missing = len(mapped_left_edges - right_edges)
    extra = len(right_edges - mapped_left_edges)
    valid = (
        out_of_range == 0
        and not duplicate_left
        and not duplicate_right
        and len(left_nodes) == len(pairs)
        and missing == 0
        and extra == 0
    )
    return {
        "external_valid_solution": int(valid),
        "out_of_range_pairs": out_of_range,
        "duplicate_left_nodes": int(duplicate_left),
        "duplicate_right_nodes": int(duplicate_right),
        "left_induced_edges": len(left_edges),
        "right_induced_edges": len(right_edges),
        "missing_left_edges_in_right": missing,
        "extra_right_edges_not_in_left": extra,
    }


def save_topk_incumbents(
    args: argparse.Namespace,
    pair_stem: str,
    left: SampledGraph,
    right: SampledGraph,
    out_dir: Path,
    blocks: list[SolutionBlock],
    left_map: list[int],
    right_map: list[int],
) -> str:
    if args.top_k_incumbents <= 0 or not blocks:
        return ""
    ranked_blocks = ranked_solution_blocks(blocks, len(blocks))

    inc_dir = out_dir / "incumbents"
    inc_dir.mkdir(parents=True, exist_ok=True)
    summary_path = inc_dir / f"{pair_stem}.top{args.top_k_incumbents}.incumbents.csv"
    fields = [
        "candidate_rank",
        "saved_rank",
        "ordinal",
        *METRIC_KEYS,
        "external_valid_solution",
        "out_of_range_pairs",
        "duplicate_left_nodes",
        "duplicate_right_nodes",
        "left_induced_edges",
        "right_induced_edges",
        "missing_left_edges_in_right",
        "extra_right_edges_not_in_left",
        "mapped_pairs",
        "incumbent_csv",
    ]
    with summary_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        saved_count = 0
        for candidate_rank, block in enumerate(ranked_blocks, start=1):
            validation = validate_directed_induced_mapping(left, right, left_map, right_map, block.pairs)
            saved_rank = ""
            csv_path = inc_dir / f"{pair_stem}.rank{saved_count + 1}.size{block.metrics.get('mcs_size', len(block.pairs))}.mcs_nodes.csv"
            if validation["external_valid_solution"] and saved_count < args.top_k_incumbents:
                saved_count += 1
                saved_rank = str(saved_count)
                mapped_pairs = write_mcs_csv(csv_path, left.graph, right.graph, left_map, right_map, block.pairs)
                incumbent_csv = str(csv_path)
            else:
                if csv_path.exists():
                    csv_path.unlink()
                mapped_pairs = 0
                incumbent_csv = ""
            row = {
                "candidate_rank": candidate_rank,
                "saved_rank": saved_rank,
                "ordinal": block.ordinal,
                "mapped_pairs": mapped_pairs,
                "incumbent_csv": incumbent_csv,
            }
            row.update(block.metrics)
            row.update(validation)
            writer.writerow(row)
            if saved_count >= args.top_k_incumbents:
                break
    return str(summary_path)


def run_process_streaming(cmd: list[str], cwd: Path, stdout_log: Path, stderr_log: Path, timeout: int) -> int:
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    def copy_stream(stream, path: Path) -> None:
        with path.open("w") as handle:
            for line in iter(stream.readline, ""):
                handle.write(line)
                handle.flush()
        stream.close()

    stdout_thread = threading.Thread(target=copy_stream, args=(proc.stdout, stdout_log))
    stderr_thread = threading.Thread(target=copy_stream, args=(proc.stderr, stderr_log))
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


def run_symsplit(args: argparse.Namespace, left: SampledGraph, right: SampledGraph, out_dir: Path) -> dict[str, str]:
    pair_stem = f"{left.graph}__{right.graph}.n{left.sample_size}.{left.sample_id}"
    logs_dir = out_dir / "logs"
    mcs_dir = out_dir / "mcs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    mcs_dir.mkdir(parents=True, exist_ok=True)
    stdout_log = logs_dir / f"{pair_stem}.stdout.log"
    stderr_log = logs_dir / f"{pair_stem}.stderr.log"
    mcs_csv = mcs_dir / f"{pair_stem}.mcs_nodes.csv"

    base_row = {
        "left_graph": left.graph,
        "right_graph": right.graph,
        "sample_size": str(left.sample_size),
        "left_nodes": str(left.node_count),
        "left_edges": str(left.edge_count),
        "right_nodes": str(right.node_count),
        "right_edges": str(right.edge_count),
        "mcs_csv": str(mcs_csv),
        "stdout_log": str(stdout_log),
        "stderr_log": str(stderr_log),
    }

    if not args.rerun_existing and mcs_csv.exists() and stdout_log.exists():
        stdout = stdout_log.read_text()
        metrics, pairs = parse_symsplit(stdout)
        existing_rows = max(0, sum(1 for _ in mcs_csv.open()) - 1)
        if metrics or pairs or existing_rows:
            blocks = parse_symsplit_blocks(stdout)
            left_map = read_index_map(left.map_path)
            right_map = read_index_map(right.map_path)
            validation = validate_directed_induced_mapping(left, right, left_map, right_map, pairs)
            if not validation["external_valid_solution"] and mcs_csv.exists():
                mcs_csv.unlink()
            incumbents_summary = save_topk_incumbents(args, pair_stem, left, right, out_dir, blocks, left_map, right_map)
            row = {
                **base_row,
                "returncode": "skipped_existing",
                "incumbents_summary": incumbents_summary,
                "mapped_pairs": str(existing_rows if validation["external_valid_solution"] else 0),
                "mcs_csv": str(mcs_csv) if validation["external_valid_solution"] else "",
            }
            row.update(metrics)
            row.update({key: str(value) for key, value in validation.items()})
            row.setdefault("mcs_size", str(existing_rows))
            row.setdefault("valid_solution", "")
            row.setdefault("solution_time_s", "")
            row.setdefault("total_time_s", "")
            row.setdefault("branches", "")
            row.setdefault("calls_for_optimal", "")
            row.setdefault("cut_branches", "")
            row.setdefault("left_pruned", "")
            row.setdefault("right_pruned", "")
            row.setdefault("aborted", "")
            return row
        print(f"  existing output for {pair_stem} is incomplete; rerunning", flush=True)

    cmd = [
        str(args.solver.resolve()),
        "min_max",
        str(left.dimacs_path.resolve()),
        str(right.dimacs_path.resolve()),
        "-d",
        "-i",
        "-q",
        "-t",
        str(args.timeout),
    ]
    returncode = run_process_streaming(cmd, ROOT, stdout_log, stderr_log, args.wall_timeout)
    stdout = stdout_log.read_text()
    metrics, pairs = parse_symsplit(stdout)
    blocks = parse_symsplit_blocks(stdout)

    left_map = read_index_map(left.map_path)
    right_map = read_index_map(right.map_path)
    validation = validate_directed_induced_mapping(left, right, left_map, right_map, pairs)
    if validation["external_valid_solution"]:
        mapped_pairs = write_mcs_csv(mcs_csv, left.graph, right.graph, left_map, right_map, pairs)
        saved_mcs_csv = str(mcs_csv)
    else:
        if mcs_csv.exists():
            mcs_csv.unlink()
        mapped_pairs = 0
        saved_mcs_csv = ""
    incumbents_summary = save_topk_incumbents(args, pair_stem, left, right, out_dir, blocks, left_map, right_map)

    row = {
        **base_row,
        "returncode": str(returncode),
        "incumbents_summary": incumbents_summary,
        "mapped_pairs": str(mapped_pairs),
        "mcs_csv": saved_mcs_csv,
    }
    row.update(metrics)
    row.update({key: str(value) for key, value in validation.items()})
    row.setdefault("mcs_size", str(len(pairs)))
    row.setdefault("valid_solution", "")
    row.setdefault("solution_time_s", "")
    row.setdefault("total_time_s", "")
    row.setdefault("branches", "")
    row.setdefault("calls_for_optimal", "")
    row.setdefault("cut_branches", "")
    row.setdefault("left_pruned", "")
    row.setdefault("right_pruned", "")
    row.setdefault("aborted", "")
    return row


def main() -> int:
    args = parse_args()
    if not args.inputs:
        args.inputs = sorted((ROOT / "data" / "raw_graphs").glob("*_edge_list.csv"))
    args.out_dir.mkdir(parents=True, exist_ok=True)

    samples_by_size: dict[int, list[SampledGraph]] = {size: [] for size in args.sizes}
    sample_summary_path = args.out_dir / "sample_summary.csv"
    with sample_summary_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["graph", "sample_size", "sample_id", "nodes", "directed_edges", "csv_path", "dimacs_path", "map_path"])
        for input_path in args.inputs:
            graph = graph_stem(input_path)
            print(f"Loading {input_path}", flush=True)
            nodes, edges, weak_adj, degree = read_edges(input_path)
            for size in args.sizes:
                print(f"Sampling {graph} n={size}", flush=True)
                sampled_nodes = sample_weak_bfs(nodes, weak_adj, degree, size, args.seed + size)
                sample = write_sample_outputs(graph, size, args.sample_id, sampled_nodes, edges, args.out_dir, args.reuse_samples)
                samples_by_size[size].append(sample)
                writer.writerow([graph, size, args.sample_id, sample.node_count, sample.edge_count, sample.csv_path, sample.dimacs_path, sample.map_path])
                handle.flush()

    fields = [
        "left_graph",
        "right_graph",
        "sample_size",
        "left_nodes",
        "left_edges",
        "right_nodes",
        "right_edges",
        "returncode",
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
        "external_valid_solution",
        "out_of_range_pairs",
        "duplicate_left_nodes",
        "duplicate_right_nodes",
        "left_induced_edges",
        "right_induced_edges",
        "missing_left_edges_in_right",
        "extra_right_edges_not_in_left",
        "mapped_pairs",
        "incumbents_summary",
        "mcs_csv",
        "stdout_log",
        "stderr_log",
    ]
    results_path = args.out_dir / "pairwise_mcs_summary.csv"
    with results_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for size, samples in samples_by_size.items():
            for left_index in range(len(samples)):
                for right_index in range(left_index + 1, len(samples)):
                    left = samples[left_index]
                    right = samples[right_index]
                    if left.graph == right.graph:
                        continue
                    print(f"SymSplit {left.graph} x {right.graph} n={size}", flush=True)
                    row = run_symsplit(args, left, right, args.out_dir)
                    writer.writerow(row)
                    handle.flush()
                    print(f"  mcs={row['mcs_size']} aborted={row['aborted']} rc={row['returncode']}", flush=True)

    print(f"Wrote {sample_summary_path}")
    print(f"Wrote {results_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
