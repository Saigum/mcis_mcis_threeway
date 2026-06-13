#!/usr/bin/env python3
"""Run SymSplit MCS on sampled graphs using selectable biased samplers."""

from __future__ import annotations

import argparse
import csv
import random
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "wrappers"))

from run_symsplit_sampled_mcs import (  # noqa: E402
    SampledGraph,
    graph_stem,
    read_edges,
    run_symsplit,
    sample_weak_bfs,
    write_sample_outputs,
)


STRATEGIES = (
    "high_degree_bfs",
    "low_degree_bfs",
    "random_nodes",
    "random_bfs",
    "degree_band_bfs",
    "sparse_greedy",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "inputs",
        nargs="*",
        type=Path,
        help="Raw directed edge-list CSVs. Defaults to data/raw_graphs/*_edge_list.csv.",
    )
    parser.add_argument("--out-dir", type=Path, default=Path("outputs/symsplit_biased_sampled_mcs"))
    parser.add_argument("--solver", type=Path, default=Path("../symsplit/bin/run.o"))
    parser.add_argument("--sizes", type=int, nargs="+", default=[1000, 2000, 4000])
    parser.add_argument("--sample-id", default="biased_seed1")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--wall-timeout", type=int, default=420)
    parser.add_argument("--reuse-samples", action="store_true")
    parser.add_argument("--rerun-existing", action="store_true")
    parser.add_argument("--top-k-incumbents", type=int, default=10)
    parser.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="Number of pairwise SymSplit jobs to run concurrently.",
    )
    parser.add_argument("--sampling-strategy", choices=STRATEGIES, default="sparse_greedy")
    parser.add_argument(
        "--degree-band-quantile",
        type=float,
        default=0.35,
        help="Degree quantile used by degree_band_bfs. Lower values bias sparser samples.",
    )
    parser.add_argument(
        "--sparse-candidate-pool",
        type=int,
        default=64,
        help="Number of candidate low-degree nodes considered per sparse_greedy step.",
    )
    return parser.parse_args()


def fill_by_order(selected: set[int], ordered_nodes: list[int], size: int) -> None:
    for node in ordered_nodes:
        selected.add(node)
        if len(selected) >= size:
            break


def sample_low_degree_bfs(
    nodes: set[int],
    weak_adj: dict[int, set[int]],
    degree: dict[int, int],
    size: int,
    seed: int,
) -> list[int]:
    if size > len(nodes):
        raise ValueError(f"requested sample size {size}, but graph only has {len(nodes)} nodes")

    rng = random.Random(seed)
    starts = sorted(nodes, key=lambda node: (degree.get(node, 0), node))
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
            neighbors.sort(key=lambda neighbor: (degree.get(neighbor, 0), neighbor))
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

    fill_by_order(selected, starts, size)
    return sorted(selected)


def sample_random_nodes(nodes: set[int], size: int, seed: int) -> list[int]:
    if size > len(nodes):
        raise ValueError(f"requested sample size {size}, but graph only has {len(nodes)} nodes")
    rng = random.Random(seed)
    return sorted(rng.sample(sorted(nodes), size))


def sample_random_bfs(nodes: set[int], weak_adj: dict[int, set[int]], size: int, seed: int) -> list[int]:
    if size > len(nodes):
        raise ValueError(f"requested sample size {size}, but graph only has {len(nodes)} nodes")

    rng = random.Random(seed)
    starts = sorted(nodes)
    rng.shuffle(starts)
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
            rng.shuffle(neighbors)
            for neighbor in neighbors:
                if neighbor not in selected:
                    selected.add(neighbor)
                    queue.append(neighbor)
                    if len(selected) >= size:
                        break

    fill_by_order(selected, starts, size)
    return sorted(selected)


def sample_degree_band_bfs(
    nodes: set[int],
    weak_adj: dict[int, set[int]],
    degree: dict[int, int],
    size: int,
    seed: int,
    quantile: float,
) -> list[int]:
    if size > len(nodes):
        raise ValueError(f"requested sample size {size}, but graph only has {len(nodes)} nodes")

    rng = random.Random(seed)
    ordered = sorted(nodes, key=lambda node: (degree.get(node, 0), node))
    pivot_index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * quantile)))
    pivot_degree = degree.get(ordered[pivot_index], 0)
    starts = sorted(nodes, key=lambda node: (abs(degree.get(node, 0) - pivot_degree), degree.get(node, 0), node))
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
            neighbors.sort(key=lambda neighbor: (abs(degree.get(neighbor, 0) - pivot_degree), degree.get(neighbor, 0), neighbor))
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

    fill_by_order(selected, starts, size)
    return sorted(selected)


def sample_sparse_greedy(
    nodes: set[int],
    weak_adj: dict[int, set[int]],
    degree: dict[int, int],
    size: int,
    seed: int,
    candidate_pool: int,
) -> list[int]:
    if size > len(nodes):
        raise ValueError(f"requested sample size {size}, but graph only has {len(nodes)} nodes")

    rng = random.Random(seed)
    remaining = sorted(nodes, key=lambda node: (degree.get(node, 0), node))
    selected: set[int] = set()
    remaining_set = set(remaining)

    while len(selected) < size:
        pool = [node for node in remaining if node in remaining_set][: max(1, candidate_pool)]
        if not pool:
            break
        rng.shuffle(pool)
        best = min(
            pool,
            key=lambda node: (
                len(weak_adj.get(node, ()) & selected),
                degree.get(node, 0),
                node,
            ),
        )
        selected.add(best)
        remaining_set.remove(best)

    fill_by_order(selected, remaining, size)
    return sorted(selected)


def sample_nodes(args: argparse.Namespace, nodes: set[int], weak_adj: dict[int, set[int]], degree: dict[int, int], size: int) -> list[int]:
    seed = args.seed + size
    if args.sampling_strategy == "high_degree_bfs":
        return sample_weak_bfs(nodes, weak_adj, degree, size, seed)
    if args.sampling_strategy == "low_degree_bfs":
        return sample_low_degree_bfs(nodes, weak_adj, degree, size, seed)
    if args.sampling_strategy == "random_nodes":
        return sample_random_nodes(nodes, size, seed)
    if args.sampling_strategy == "random_bfs":
        return sample_random_bfs(nodes, weak_adj, size, seed)
    if args.sampling_strategy == "degree_band_bfs":
        return sample_degree_band_bfs(nodes, weak_adj, degree, size, seed, args.degree_band_quantile)
    if args.sampling_strategy == "sparse_greedy":
        return sample_sparse_greedy(nodes, weak_adj, degree, size, seed, args.sparse_candidate_pool)
    raise ValueError(f"unknown sampling strategy: {args.sampling_strategy}")


def pair_jobs(samples: list[SampledGraph]) -> list[tuple[SampledGraph, SampledGraph]]:
    jobs: list[tuple[SampledGraph, SampledGraph]] = []
    for left_index in range(len(samples)):
        for right_index in range(left_index + 1, len(samples)):
            left = samples[left_index]
            right = samples[right_index]
            if left.graph == right.graph:
                continue
            jobs.append((left, right))
    return jobs


def main() -> int:
    args = parse_args()
    if not args.inputs:
        args.inputs = sorted((ROOT / "data" / "raw_graphs").glob("*_edge_list.csv"))
    args.out_dir.mkdir(parents=True, exist_ok=True)

    samples_by_size: dict[int, list[SampledGraph]] = {size: [] for size in args.sizes}
    sample_summary_path = args.out_dir / "sample_summary.csv"
    with sample_summary_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "graph",
            "sample_size",
            "sample_id",
            "sampling_strategy",
            "nodes",
            "directed_edges",
            "edge_density",
            "csv_path",
            "dimacs_path",
            "map_path",
        ])
        for input_path in args.inputs:
            graph = graph_stem(input_path)
            print(f"Loading {input_path}", flush=True)
            nodes, edges, weak_adj, degree = read_edges(input_path)
            for size in args.sizes:
                print(f"Sampling {graph} n={size} strategy={args.sampling_strategy}", flush=True)
                sampled_nodes = sample_nodes(args, nodes, weak_adj, degree, size)
                sample = write_sample_outputs(graph, size, args.sample_id, sampled_nodes, edges, args.out_dir, args.reuse_samples)
                samples_by_size[size].append(sample)
                density = sample.edge_count / max(1, sample.node_count * (sample.node_count - 1))
                writer.writerow([
                    graph,
                    size,
                    args.sample_id,
                    args.sampling_strategy,
                    sample.node_count,
                    sample.edge_count,
                    f"{density:.8g}",
                    sample.csv_path,
                    sample.dimacs_path,
                    sample.map_path,
                ])
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
            jobs = pair_jobs(samples)
            if args.jobs <= 1:
                for left, right in jobs:
                    print(f"SymSplit {left.graph} x {right.graph} n={size} strategy={args.sampling_strategy}", flush=True)
                    row = run_symsplit(args, left, right, args.out_dir)
                    writer.writerow(row)
                    handle.flush()
                    print(f"  mcs={row['mcs_size']} aborted={row['aborted']} rc={row['returncode']}", flush=True)
            else:
                print(f"Running {len(jobs)} pair jobs for n={size} with jobs={args.jobs}", flush=True)
                with ThreadPoolExecutor(max_workers=args.jobs) as executor:
                    future_to_pair = {}
                    for left, right in jobs:
                        print(f"Queue SymSplit {left.graph} x {right.graph} n={size} strategy={args.sampling_strategy}", flush=True)
                        future = executor.submit(run_symsplit, args, left, right, args.out_dir)
                        future_to_pair[future] = (left, right)
                    for future in as_completed(future_to_pair):
                        left, right = future_to_pair[future]
                        row = future.result()
                        writer.writerow(row)
                        handle.flush()
                        print(
                            f"Done SymSplit {left.graph} x {right.graph} n={size}: "
                            f"mcs={row['mcs_size']} aborted={row['aborted']} rc={row['returncode']}",
                            flush=True,
                        )

    print(f"Wrote {sample_summary_path}")
    print(f"Wrote {results_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
