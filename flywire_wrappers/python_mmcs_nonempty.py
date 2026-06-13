#!/usr/bin/env python3

import argparse
import csv
import itertools
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

MASK = (1 << 64) - 1


def mix_tuple(values: Tuple[int, ...]) -> int:
    value = 0xCBF29CE484222325
    for item in values:
        value ^= (item + 0x9E3779B97F4A7C15) & MASK
        value = (value * 0x100000001B3) & MASK
    return value


@dataclass
class SparseDiGraph:
    name: str
    nodes: List[int]
    out_neighbors: Dict[int, Set[int]]
    in_neighbors: Dict[int, Set[int]]
    label: Dict[int, Tuple[int, int]]
    nodes_by_label: Dict[Tuple[int, int], List[int]]


def load_graph(path: Path) -> SparseDiGraph:
    out_neighbors: Dict[int, Set[int]] = defaultdict(set)
    in_neighbors: Dict[int, Set[int]] = defaultdict(set)
    nodes: Set[int] = set()

    with path.open(newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        for row in reader:
            if len(row) < 2:
                continue
            u = int(row[0])
            v = int(row[1])
            out_neighbors[u].add(v)
            in_neighbors[v].add(u)
            nodes.add(u)
            nodes.add(v)

    node_list = sorted(nodes)
    for node in node_list:
        out_neighbors.setdefault(node, set())
        in_neighbors.setdefault(node, set())

    base = {node: (len(in_neighbors[node]), len(out_neighbors[node])) for node in node_list}
    base_hash = {node: mix_tuple(base[node]) for node in node_list}

    label: Dict[int, Tuple[int, int]] = {}
    nodes_by_label: Dict[Tuple[int, int], List[int]] = defaultdict(list)
    for node in node_list:
        deg_pair = base[node]
        label[node] = deg_pair
        nodes_by_label[deg_pair].append(node)

    return SparseDiGraph(path.stem, node_list, out_neighbors, in_neighbors, label, nodes_by_label)


def induced_matrix(graph: SparseDiGraph, nodes: Sequence[int]) -> Tuple[Tuple[int, ...], ...]:
    return tuple(
        tuple(1 if dst in graph.out_neighbors[src] else 0 for dst in nodes)
        for src in nodes
    )


def undirected_connected(graph: SparseDiGraph, subset: Sequence[int]) -> bool:
    subset_set = set(subset)
    seen = {subset[0]}
    stack = [subset[0]]
    while stack:
        node = stack.pop()
        for nbr in graph.out_neighbors[node] | graph.in_neighbors[node]:
            if nbr in subset_set and nbr not in seen:
                seen.add(nbr)
                stack.append(nbr)
    return len(seen) == len(subset)


def has_nonempty_edge(graph: SparseDiGraph, subset: Sequence[int]) -> bool:
    subset_set = set(subset)
    for node in subset:
        if graph.out_neighbors[node] & subset_set:
            return True
    return False


def pattern_key(graph: SparseDiGraph, subset: Sequence[int]) -> Tuple[Tuple[int, int, int, int], ...]:
    return tuple(sorted(graph.label[node] for node in subset))


def search_mapping(
    graph: SparseDiGraph,
    pattern_nodes: Sequence[int],
    pattern_adj: Tuple[Tuple[int, ...], ...],
    pattern_labels: Sequence[Tuple[int, int]],
) -> Optional[List[int]]:
    n = len(pattern_nodes)
    candidates = [graph.nodes_by_label.get(label, []) for label in pattern_labels]
    if any(not c for c in candidates):
        return None

    order = sorted(range(n), key=lambda i: len(candidates[i]))
    assigned_pat_to_target = [-1] * n
    used_targets: Set[int] = set()

    def rec(depth: int) -> bool:
        if depth == n:
            return True
        p_idx = order[depth]
        for t_node in candidates[p_idx]:
            if t_node in used_targets:
                continue
            ok = True
            for other_p in range(n):
                other_t = assigned_pat_to_target[other_p]
                if other_t == -1:
                    continue
                edge_po = pattern_adj[p_idx][other_p]
                edge_op = pattern_adj[other_p][p_idx]
                if (1 if other_t in graph.out_neighbors[t_node] else 0) != edge_po:
                    ok = False
                    break
                if (1 if t_node in graph.out_neighbors[other_t] else 0) != edge_op:
                    ok = False
                    break
            if not ok:
                continue
            assigned_pat_to_target[p_idx] = t_node
            used_targets.add(t_node)
            if rec(depth + 1):
                return True
            used_targets.remove(t_node)
            assigned_pat_to_target[p_idx] = -1
        return False

    if not rec(0):
        return None
    return assigned_pat_to_target


def enumerate_candidates(
    graph: SparseDiGraph,
    common_labels: Set[Tuple[int, int]],
    max_neighborhood: int,
    max_degree: int,
    max_patterns: int,
    max_k: int,
    min_k: int,
) -> Iterable[List[int]]:
    rarity = Counter(graph.label[node] for node in graph.nodes if graph.label[node] in common_labels)
    seeds = [
        node
        for node in graph.nodes
        if graph.label[node] in common_labels
        and len(graph.out_neighbors[node]) + len(graph.in_neighbors[node]) <= max_degree
    ]
    seeds.sort(key=lambda node: (rarity[graph.label[node]], len(graph.out_neighbors[node]) + len(graph.in_neighbors[node]), node))

    seen = set()
    produced = 0
    for seed in seeds:
        nbrs = [
            node
            for node in (graph.out_neighbors[seed] | graph.in_neighbors[seed])
            if graph.label[node] in common_labels
        ]
        nbrs.sort(key=lambda node: (rarity[graph.label[node]], len(graph.out_neighbors[node]) + len(graph.in_neighbors[node]), node))
        neighborhood = [seed] + nbrs[: max_neighborhood - 1]
        if len(neighborhood) < min_k:
            continue
        for k in range(min(max_k, len(neighborhood)), min_k - 1, -1):
            for extra in itertools.combinations(neighborhood[1:], k - 1):
                subset = [seed, *extra]
                subset_key = tuple(sorted(subset))
                if subset_key in seen:
                    continue
                seen.add(subset_key)
                if not has_nonempty_edge(graph, subset):
                    continue
                if not undirected_connected(graph, subset):
                    continue
                produced += 1
                yield subset
                if produced >= max_patterns:
                    return


def main() -> None:
    parser = argparse.ArgumentParser(description="Heuristic non-empty multigraph common induced subgraph search in Python")
    parser.add_argument("graphs", nargs=3, help="Three directed edge-list CSVs")
    parser.add_argument("--max-k", type=int, default=6)
    parser.add_argument("--min-k", type=int, default=3)
    parser.add_argument("--max-neighborhood", type=int, default=10)
    parser.add_argument("--max-degree", type=int, default=16)
    parser.add_argument("--max-patterns", type=int, default=5000)
    parser.add_argument("--output-csv", default="python_nonempty_common_subgraph_solution.csv")
    args = parser.parse_args()

    graphs = [load_graph(Path(path)) for path in args.graphs]
    source = min(graphs, key=lambda graph: len(graph.nodes))
    targets = [graph for graph in graphs if graph is not source]

    common_sigs = set.intersection(*(set(graph.nodes_by_label) for graph in graphs))
    print(f"source_graph={source.name}")
    print(f"common_labels={len(common_sigs)}")

    best_source_subset: Optional[List[int]] = None
    best_target_subsets: Optional[List[List[int]]] = None
    best_k = 0

    tried = 0
    for subset in enumerate_candidates(
        source,
        common_sigs,
        args.max_neighborhood,
        args.max_degree,
        args.max_patterns,
        args.max_k,
        args.min_k,
    ):
        tried += 1
        k = len(subset)
        if k < best_k:
            continue
        sigs = [source.label[node] for node in subset]
        if any(min(len(graph.nodes_by_label[sig]) for graph in graphs) < sigs.count(sig) for sig in set(sigs)):
            continue
        adj = induced_matrix(source, subset)
        target_matches: List[List[int]] = []
        ok = True
        for target in targets:
            match = search_mapping(target, subset, adj, sigs)
            if match is None:
                ok = False
                break
            target_matches.append(match)
        if not ok:
            continue
        if k > best_k:
            best_k = k
            best_source_subset = subset
            best_target_subsets = target_matches
            print(f"found k={k} after {tried} patterns")
            if best_k == args.max_k:
                break

    if best_source_subset is None or best_target_subsets is None:
        raise SystemExit("no non-empty common induced subgraph found in search budget")

    ordered_graphs = [source, *targets]
    ordered_subsets = [best_source_subset, *best_target_subsets]
    output_path = Path(args.output_csv)
    with output_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([graph.name for graph in ordered_graphs])
        for row in zip(*ordered_subsets):
            writer.writerow(row)

    print(f"best_k={best_k}")
    print(f"patterns_tried={tried}")
    print(f"output_csv={output_path}")
    for graph, subset in zip(ordered_graphs, ordered_subsets):
        print(graph.name, subset)


if __name__ == "__main__":
    main()
