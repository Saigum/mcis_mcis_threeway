#!/usr/bin/env python3
"""Compute weakly connected components for directed FlyWire CSV edge lists."""

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
    parser.add_argument("--out-dir", type=Path, default=Path("outputs/wcc_raw"))
    return parser.parse_args()


def graph_stem(csv_path: Path) -> str:
    stem = csv_path.stem
    return stem[:-10] if stem.endswith("_edge_list") else stem


def get_index(node_id: int, index_by_id: dict[int, int], node_ids: list[int], parent: list[int], rank: list[int]) -> int:
    index = index_by_id.get(node_id)
    if index is not None:
        return index
    index = len(node_ids)
    index_by_id[node_id] = index
    node_ids.append(node_id)
    parent.append(index)
    rank.append(0)
    return index


def find(parent: list[int], node: int) -> int:
    while parent[node] != node:
        parent[node] = parent[parent[node]]
        node = parent[node]
    return node


def union(parent: list[int], rank: list[int], a: int, b: int) -> None:
    root_a = find(parent, a)
    root_b = find(parent, b)
    if root_a == root_b:
        return
    if rank[root_a] < rank[root_b]:
        parent[root_a] = root_b
    elif rank[root_a] > rank[root_b]:
        parent[root_b] = root_a
    else:
        parent[root_b] = root_a
        rank[root_a] += 1


def read_and_union(csv_path: Path) -> tuple[list[int], list[int], int]:
    index_by_id: dict[int, int] = {}
    node_ids: list[int] = []
    parent: list[int] = []
    rank: list[int] = []
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

            source = get_index(source_id, index_by_id, node_ids, parent, rank)
            target = get_index(target_id, index_by_id, node_ids, parent, rank)
            union(parent, rank, source, target)
            edge_count += 1

    for index in range(len(parent)):
        parent[index] = find(parent, index)

    return node_ids, parent, edge_count


def write_outputs(stem: str, out_dir: Path, node_ids: list[int], parent: list[int], edge_count: int) -> dict[str, object]:
    root_to_component: dict[int, int] = {}
    component_by_node: list[int] = []
    component_sizes: list[int] = []

    for root in parent:
        component_id = root_to_component.get(root)
        if component_id is None:
            component_id = len(component_sizes)
            root_to_component[root] = component_id
            component_sizes.append(0)
        component_by_node.append(component_id)
        component_sizes[component_id] += 1

    sizes_sorted = sorted(enumerate(component_sizes), key=lambda item: (-item[1], item[0]))
    rank_by_component = {component_id: rank for rank, (component_id, _size) in enumerate(sizes_sorted, start=1)}

    assignments_path = out_dir / "assignments" / f"{stem}.wcc_assignments.csv"
    sizes_path = out_dir / "components" / f"{stem}.wcc_components.csv"
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
            writer.writerow([node_id, component_id, component_sizes[component_id], rank_by_component[component_id]])

    largest = sizes_sorted[0][1] if sizes_sorted else 0
    singleton = sum(1 for size in component_sizes if size == 1)
    nontrivial = sum(1 for size in component_sizes if size > 1)
    top10 = ";".join(str(size) for _component_id, size in sizes_sorted[:10])

    return {
        "nodes": len(node_ids),
        "directed_edges": edge_count,
        "wcc_count": len(component_sizes),
        "singleton_wcc_count": singleton,
        "nontrivial_wcc_count": nontrivial,
        "largest_wcc_size": largest,
        "largest_wcc_fraction": largest / len(node_ids) if node_ids else 0.0,
        "top10_wcc_sizes": top10,
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
    fields = [
        "graph",
        "nodes",
        "directed_edges",
        "wcc_count",
        "singleton_wcc_count",
        "nontrivial_wcc_count",
        "largest_wcc_size",
        "largest_wcc_fraction",
        "top10_wcc_sizes",
        "assignments_csv",
        "components_csv",
    ]

    with summary_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for input_path in args.inputs:
            input_path = input_path.resolve()
            stem = graph_stem(input_path)
            print(f"Reading {input_path}", flush=True)
            node_ids, parent, edge_count = read_and_union(input_path)
            row = write_outputs(stem, args.out_dir, node_ids, parent, edge_count)
            writer.writerow({"graph": stem, **row})
            handle.flush()
            print(f"{stem}: {row['wcc_count']} WCCs, largest={row['largest_wcc_size']}", flush=True)

    print(f"Wrote {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
