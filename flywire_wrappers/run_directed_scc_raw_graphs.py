#!/usr/bin/env python3
"""Compute strongly connected components for directed FlyWire CSV edge lists."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "inputs",
        nargs="*",
        type=Path,
        help="CSV edge-list files. Defaults to data/raw_graphs/*_edge_list.csv.",
    )
    parser.add_argument("--out-dir", type=Path, default=Path("outputs/scc_raw"))
    return parser.parse_args()


def graph_stem(csv_path: Path) -> str:
    stem = csv_path.stem
    return stem[:-10] if stem.endswith("_edge_list") else stem


def get_index(node_id: int, index_by_id: dict[int, int], node_ids: list[int], adj: list[list[int]], rev: list[list[int]]) -> int:
    index = index_by_id.get(node_id)
    if index is not None:
        return index
    index = len(node_ids)
    index_by_id[node_id] = index
    node_ids.append(node_id)
    adj.append([])
    rev.append([])
    return index


def read_directed_graph(csv_path: Path) -> tuple[list[int], list[list[int]], list[list[int]], int]:
    index_by_id: dict[int, int] = {}
    node_ids: list[int] = []
    adj: list[list[int]] = []
    rev: list[list[int]] = []
    edge_count = 0

    with csv_path.open(newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header is None:
            raise ValueError(f"{csv_path} is empty")

        for row_number, row in enumerate(reader, start=2):
            if len(row) < 2:
                continue
            try:
                source_id = int(row[0])
                target_id = int(row[1])
            except ValueError as exc:
                raise ValueError(f"invalid integer edge at {csv_path}:{row_number}: {row}") from exc

            source = get_index(source_id, index_by_id, node_ids, adj, rev)
            target = get_index(target_id, index_by_id, node_ids, adj, rev)
            adj[source].append(target)
            rev[target].append(source)
            edge_count += 1

    return node_ids, adj, rev, edge_count


def finish_order(adj: list[list[int]]) -> list[int]:
    visited = bytearray(len(adj))
    order: list[int] = []

    for start in range(len(adj)):
        if visited[start]:
            continue
        visited[start] = 1
        stack: list[tuple[int, int]] = [(start, 0)]
        while stack:
            node, next_pos = stack[-1]
            if next_pos < len(adj[node]):
                neighbor = adj[node][next_pos]
                stack[-1] = (node, next_pos + 1)
                if not visited[neighbor]:
                    visited[neighbor] = 1
                    stack.append((neighbor, 0))
            else:
                order.append(node)
                stack.pop()

    return order


def strongly_connected_components(adj: list[list[int]], rev: list[list[int]]) -> tuple[list[int], list[int]]:
    order = finish_order(adj)
    component_by_node = [-1] * len(adj)
    component_sizes: list[int] = []

    for start in reversed(order):
        if component_by_node[start] != -1:
            continue
        component_id = len(component_sizes)
        size = 0
        stack = [start]
        component_by_node[start] = component_id
        while stack:
            node = stack.pop()
            size += 1
            for neighbor in rev[node]:
                if component_by_node[neighbor] == -1:
                    component_by_node[neighbor] = component_id
                    stack.append(neighbor)
        component_sizes.append(size)

    return component_by_node, component_sizes


def write_outputs(
    stem: str,
    out_dir: Path,
    node_ids: list[int],
    edge_count: int,
    component_by_node: list[int],
    component_sizes: list[int],
) -> dict[str, object]:
    sizes_sorted = sorted(enumerate(component_sizes), key=lambda item: (-item[1], item[0]))
    rank_by_component = {component_id: rank for rank, (component_id, _size) in enumerate(sizes_sorted)}

    assignments_path = out_dir / "assignments" / f"{stem}.scc_assignments.csv"
    sizes_path = out_dir / "components" / f"{stem}.scc_components.csv"
    assignments_path.parent.mkdir(parents=True, exist_ok=True)
    sizes_path.parent.mkdir(parents=True, exist_ok=True)

    with sizes_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["component_id", "size", "size_rank"])
        for rank, (component_id, size) in enumerate(sizes_sorted, start=1):
            writer.writerow([component_id, size, rank])

    with assignments_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["node_id", "component_id", "component_size", "component_size_rank"])
        for node_id, component_id in zip(node_ids, component_by_node):
            writer.writerow(
                [
                    node_id,
                    component_id,
                    component_sizes[component_id],
                    rank_by_component[component_id] + 1,
                ]
            )

    largest = sizes_sorted[0][1] if sizes_sorted else 0
    nontrivial = sum(1 for size in component_sizes if size > 1)
    singleton = sum(1 for size in component_sizes if size == 1)
    top10 = ";".join(str(size) for _component_id, size in sizes_sorted[:10])
    return {
        "nodes": len(node_ids),
        "directed_edges": edge_count,
        "scc_count": len(component_sizes),
        "singleton_scc_count": singleton,
        "nontrivial_scc_count": nontrivial,
        "largest_scc_size": largest,
        "largest_scc_fraction": largest / len(node_ids) if node_ids else 0.0,
        "top10_scc_sizes": top10,
        "assignments_csv": assignments_path,
        "components_csv": sizes_path,
    }


def main() -> int:
    args = parse_args()
    repo_root = Path.cwd()
    if not args.inputs:
        args.inputs = sorted((repo_root / "data" / "raw_graphs").glob("*_edge_list.csv"))

    args.out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = args.out_dir / "summary.csv"
    summary_fields = [
        "graph",
        "nodes",
        "directed_edges",
        "scc_count",
        "singleton_scc_count",
        "nontrivial_scc_count",
        "largest_scc_size",
        "largest_scc_fraction",
        "top10_scc_sizes",
        "assignments_csv",
        "components_csv",
    ]

    with summary_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=summary_fields)
        writer.writeheader()

        for input_path in args.inputs:
            input_path = input_path.resolve()
            stem = graph_stem(input_path)
            print(f"Reading {input_path}", flush=True)
            node_ids, adj, rev, edge_count = read_directed_graph(input_path)
            print(f"Computing SCCs for {stem}: {len(node_ids)} nodes, {edge_count} edges", flush=True)
            component_by_node, component_sizes = strongly_connected_components(adj, rev)
            row = write_outputs(stem, args.out_dir, node_ids, edge_count, component_by_node, component_sizes)
            writer.writerow({"graph": stem, **row})
            handle.flush()
            print(
                f"{stem}: {row['scc_count']} SCCs, largest={row['largest_scc_size']}",
                flush=True,
            )

    print(f"Wrote {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
