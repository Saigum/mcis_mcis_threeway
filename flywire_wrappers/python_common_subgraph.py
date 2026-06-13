#!/usr/bin/env python3

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence, Tuple


@dataclass
class UndirectedGraph:
    name: str
    node_ids: List[int]
    neighbors: List[List[int]]


def load_undirected_projection(path: Path) -> UndirectedGraph:
    node_to_idx = {}
    node_ids: List[int] = []
    neighbors: List[List[int]] = []

    def get_idx(node_id: int) -> int:
        idx = node_to_idx.get(node_id)
        if idx is None:
            idx = len(node_ids)
            node_to_idx[node_id] = idx
            node_ids.append(node_id)
            neighbors.append([])
        return idx

    with path.open(newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        for row in reader:
            if len(row) < 2:
                continue
            u = int(row[0])
            v = int(row[1])
            if u == v:
                get_idx(u)
                continue
            ui = get_idx(u)
            vi = get_idx(v)
            neighbors[ui].append(vi)
            neighbors[vi].append(ui)

    return UndirectedGraph(path.stem, node_ids, neighbors)


def splitmix64(value: int) -> int:
    value = (value + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
    value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
    value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
    return value ^ (value >> 31)


def greedy_independent_set(graph: UndirectedGraph, seed: int) -> List[int]:
    order = list(range(len(graph.node_ids)))
    order.sort(key=lambda idx: (len(graph.neighbors[idx]), splitmix64(idx ^ seed)))

    blocked = bytearray(len(order))
    chosen: List[int] = []

    for idx in order:
        if blocked[idx]:
            continue
        blocked[idx] = 1
        chosen.append(idx)
        for nbr in graph.neighbors[idx]:
            blocked[nbr] = 1

    return chosen


def verify_independent(graph: UndirectedGraph, chosen: Sequence[int]) -> None:
    chosen_set = set(chosen)
    for idx in chosen:
        for nbr in graph.neighbors[idx]:
            if nbr in chosen_set and nbr != idx:
                raise ValueError(f"{graph.name}: selected set is not independent")


def best_independent_set(graph: UndirectedGraph, trials: int) -> List[int]:
    best: List[int] = []
    for seed in range(trials):
        candidate = greedy_independent_set(graph, seed)
        if len(candidate) > len(best):
            best = candidate
    verify_independent(graph, best)
    return best


def write_solution(
    graphs: Sequence[UndirectedGraph],
    selections: Sequence[Sequence[int]],
    output_csv: Path,
) -> int:
    common_size = min(len(selection) for selection in selections)
    trimmed = [selection[:common_size] for selection in selections]

    with output_csv.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([graph.name for graph in graphs])
        for row_idx in range(common_size):
            writer.writerow(
                [graph.node_ids[trimmed[col_idx][row_idx]] for col_idx, graph in enumerate(graphs)]
            )

    return common_size


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Find a large valid common directed induced subgraph on multiple edge-list CSVs "
            "by selecting independent sets in each graph. The resulting common subgraph is edgeless."
        )
    )
    parser.add_argument("graphs", nargs="+", help="Input CSV edge lists")
    parser.add_argument("--trials", type=int, default=8, help="Greedy restarts per graph")
    parser.add_argument(
        "--output-csv",
        default="python_common_subgraph_solution.csv",
        help="Submission-style CSV output path",
    )
    args = parser.parse_args()

    graphs = [load_undirected_projection(Path(path)) for path in args.graphs]
    selections = [best_independent_set(graph, args.trials) for graph in graphs]

    for graph, selection in zip(graphs, selections):
        print(f"{graph.name}: nodes={len(graph.node_ids)} independent_set={len(selection)}")

    common_size = write_solution(graphs, selections, Path(args.output_csv))
    print(f"common_edgeless_subgraph_size={common_size}")
    print(f"output_csv={args.output_csv}")


if __name__ == "__main__":
    main()
