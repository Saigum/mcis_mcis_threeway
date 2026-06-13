#!/usr/bin/env python3
"""Analyze three-way induced subgraphs from a sampled-output directory.

This script expects a directory layout like:

  outputs/<run_name>/
    threeway_summary.csv
    threeway_node_triplets/*.threeway_nodes.csv

It verifies each three-way node correspondence against the raw directed graphs,
ignoring self-loops, and writes a CSV containing only the rows whose three
induced subgraphs are mutually isomorphic under the row-wise node mapping.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, median

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output_dir",
        type=Path,
        help="Output directory containing threeway_summary.csv and threeway_node_triplets/.",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=Path("raw_graphs"),
        help="Directory containing <graph>_edge_list.csv files.",
    )
    parser.add_argument(
        "--detail-output",
        type=Path,
        default=None,
        help=(
            "Detailed CSV for isomorphic three-way rows. "
            "Defaults to <output_dir>/threeway_isomorphic_stats_ignore_self_loops.csv."
        ),
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=None,
        help=(
            "Summary JSON. "
            "Defaults to <output_dir>/threeway_isomorphic_stats_ignore_self_loops.summary.json."
        ),
    )
    parser.add_argument(
        "--all-rows-output",
        type=Path,
        default=None,
        help=(
            "Optional CSV for all analyzed rows, including non-isomorphic rows. "
            "Defaults to <output_dir>/threeway_all_rows_stats_ignore_self_loops.csv."
        ),
    )
    return parser.parse_args()


@dataclass
class GraphCache:
    nodes: dict[str, set[int]] = field(default_factory=dict)
    out_adj: dict[str, dict[int, set[int]]] = field(default_factory=dict)

    def load(self, raw_dir: Path, graph: str) -> tuple[set[int], dict[int, set[int]]]:
        if graph in self.out_adj:
            return self.nodes[graph], self.out_adj[graph]

        path = raw_dir / f"{graph}_edge_list.csv"
        nodes: set[int] = set()
        out_adj: dict[int, set[int]] = defaultdict(set)

        if pd is not None:
            frame = pd.read_csv(path, usecols=["source neuron id", "target neuron id"])
            for source, target in zip(
                frame["source neuron id"].astype("int64"),
                frame["target neuron id"].astype("int64"),
            ):
                source = int(source)
                target = int(target)
                nodes.add(source)
                nodes.add(target)
                out_adj.setdefault(source, set())
                out_adj.setdefault(target, set())
                if source != target:
                    out_adj[source].add(target)
        else:
            with path.open(newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    source = int(row["source neuron id"])
                    target = int(row["target neuron id"])
                    nodes.add(source)
                    nodes.add(target)
                    out_adj.setdefault(source, set())
                    out_adj.setdefault(target, set())
                    if source != target:
                        out_adj[source].add(target)

        self.nodes[graph] = nodes
        self.out_adj[graph] = out_adj
        return nodes, out_adj


def resolve_threeway_csv(output_dir: Path, csv_path_str: str) -> Path:
    candidate = Path(csv_path_str)
    if candidate.exists():
        return candidate
    return output_dir / "threeway_node_triplets" / candidate.name


def induced_edges_by_position(out_adj: dict[int, set[int]], nodes: list[int]) -> set[tuple[int, int]]:
    pos = {node: idx for idx, node in enumerate(nodes)}
    edges: set[tuple[int, int]] = set()
    for source in nodes:
        source_idx = pos[source]
        for target in out_adj.get(source, ()):
            target_idx = pos.get(target)
            if target_idx is not None:
                edges.add((source_idx, target_idx))
    return edges


def weak_component_sizes(nodes: list[int], out_adj: dict[int, set[int]]) -> list[int]:
    undirected: dict[int, set[int]] = defaultdict(set)
    for source in nodes:
        for target in out_adj.get(source, ()):
            if target in out_adj:
                undirected[source].add(target)
                undirected[target].add(source)

    seen: set[int] = set()
    sizes: list[int] = []
    for node in nodes:
        if node in seen:
            continue
        stack = [node]
        seen.add(node)
        size = 0
        while stack:
            current = stack.pop()
            size += 1
            for nxt in undirected.get(current, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        sizes.append(size)
    sizes.sort(reverse=True)
    return sizes


def strong_component_sizes(nodes: list[int], out_adj: dict[int, set[int]]) -> list[int]:
    node_set = set(nodes)
    filtered_out = {
        node: {nbr for nbr in out_adj.get(node, ()) if nbr in node_set}
        for node in nodes
    }
    reverse_adj: dict[int, set[int]] = {node: set() for node in nodes}
    for source, nbrs in filtered_out.items():
        for target in nbrs:
            reverse_adj[target].add(source)

    seen: set[int] = set()
    order: list[int] = []

    for start in nodes:
        if start in seen:
            continue
        stack: list[tuple[int, bool]] = [(start, False)]
        seen.add(start)
        while stack:
            node, expanded = stack.pop()
            if expanded:
                order.append(node)
                continue
            stack.append((node, True))
            for nxt in filtered_out[node]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append((nxt, False))

    seen.clear()
    sizes: list[int] = []
    for start in reversed(order):
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        size = 0
        while stack:
            node = stack.pop()
            size += 1
            for nxt in reverse_adj[node]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        sizes.append(size)
    sizes.sort(reverse=True)
    return sizes


def numeric_stats(values: list[int]) -> dict[str, float | int | None]:
    if not values:
        return {"min": None, "max": None, "mean": None, "median": None}
    return {
        "min": min(values),
        "max": max(values),
        "mean": mean(values),
        "median": median(values),
    }


def analyze_row(
    row_index: int,
    row: dict[str, str],
    output_dir: Path,
    raw_dir: Path,
    cache: GraphCache,
) -> dict[str, str] | None:
    threeway_csv_str = row.get("threeway_csv", "")
    if not threeway_csv_str or row.get("threeway_nodes", "0") in {"", "0"}:
        return None

    threeway_csv = resolve_threeway_csv(output_dir, threeway_csv_str)
    if not threeway_csv.exists():
        raise FileNotFoundError(f"missing threeway CSV: {threeway_csv}")

    with threeway_csv.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or len(reader.fieldnames) < 3:
            raise ValueError(f"unexpected threeway CSV header: {threeway_csv}")
        graphs = reader.fieldnames[:3]
        records = list(reader)

    node_lists = {
        graph: [int(record[graph]) for record in records]
        for graph in graphs
    }
    duplicate_nodes = {
        graph: len(set(nodes)) != len(nodes)
        for graph, nodes in node_lists.items()
    }

    graph_nodes_in_raw: dict[str, bool] = {}
    induced_edges: dict[str, set[tuple[int, int]]] = {}
    weak_sizes: dict[str, list[int]] = {}
    strong_sizes: dict[str, list[int]] = {}

    for graph in graphs:
        raw_nodes, raw_out_adj = cache.load(raw_dir, graph)
        nodes = node_lists[graph]
        graph_nodes_in_raw[graph] = set(nodes) <= raw_nodes
        node_set = set(nodes)
        filtered_out = {
            node: {nbr for nbr in raw_out_adj.get(node, ()) if nbr in node_set}
            for node in nodes
        }
        induced_edges[graph] = induced_edges_by_position(filtered_out, nodes)
        weak_sizes[graph] = weak_component_sizes(nodes, filtered_out)
        strong_sizes[graph] = strong_component_sizes(nodes, filtered_out)

    first, second, third = graphs
    iso12 = induced_edges[first] == induced_edges[second]
    iso13 = induced_edges[first] == induced_edges[third]
    iso23 = induced_edges[second] == induced_edges[third]
    isomorphic = (
        not any(duplicate_nodes.values())
        and all(graph_nodes_in_raw.values())
        and iso12
        and iso13
        and iso23
    )

    base = {
        "row_index": str(row_index),
        "triplet": row["triplet"],
        "left_graph": row["left_graph"],
        "right_graph": row["right_graph"],
        "heldout_graph": row["heldout_graph"],
        "sample_size": row["sample_size"],
        "sample_id": row["sample_id"],
        "sampling_strategy": row["sampling_strategy"],
        "threeway_nodes": str(len(records)),
        "threeway_csv": str(threeway_csv),
        "graph_a": first,
        "graph_b": second,
        "graph_c": third,
        "graph_a_nodes_in_raw": str(int(graph_nodes_in_raw[first])),
        "graph_b_nodes_in_raw": str(int(graph_nodes_in_raw[second])),
        "graph_c_nodes_in_raw": str(int(graph_nodes_in_raw[third])),
        "graph_a_duplicate_nodes": str(int(duplicate_nodes[first])),
        "graph_b_duplicate_nodes": str(int(duplicate_nodes[second])),
        "graph_c_duplicate_nodes": str(int(duplicate_nodes[third])),
        "graph_a_edges_no_self_loops": str(len(induced_edges[first])),
        "graph_b_edges_no_self_loops": str(len(induced_edges[second])),
        "graph_c_edges_no_self_loops": str(len(induced_edges[third])),
        "iso_graph_a_b": str(int(iso12)),
        "iso_graph_a_c": str(int(iso13)),
        "iso_graph_b_c": str(int(iso23)),
        "raw_directed_induced_threeway_isomorphic_no_self_loops": str(int(isomorphic)),
    }

    for prefix, graph in (("graph_a", first), ("graph_b", second), ("graph_c", third)):
        weak = weak_sizes[graph]
        strong = strong_sizes[graph]
        node_count = len(node_lists[graph])
        base[f"{prefix}_weak_components"] = str(len(weak))
        base[f"{prefix}_largest_weak_component"] = str(weak[0] if weak else 0)
        base[f"{prefix}_isolated_nodes_weak"] = str(sum(size == 1 for size in weak))
        base[f"{prefix}_largest_weak_ratio"] = f"{((weak[0] / node_count) if weak else 0):.6f}"
        base[f"{prefix}_strong_components"] = str(len(strong))
        base[f"{prefix}_largest_strong_component"] = str(strong[0] if strong else 0)
        base[f"{prefix}_largest_strong_ratio"] = f"{((strong[0] / node_count) if strong else 0):.6f}"

    # For valid three-way isomorphisms, all three profiles should match. Record a
    # canonical copy to make downstream analysis simple.
    base["weak_components"] = base["graph_a_weak_components"]
    base["largest_weak_component"] = base["graph_a_largest_weak_component"]
    base["isolated_nodes_weak"] = base["graph_a_isolated_nodes_weak"]
    base["largest_weak_ratio"] = base["graph_a_largest_weak_ratio"]
    base["strong_components"] = base["graph_a_strong_components"]
    base["largest_strong_component"] = base["graph_a_largest_strong_component"]
    base["largest_strong_ratio"] = base["graph_a_largest_strong_ratio"]
    base["edges_no_self_loops"] = base["graph_a_edges_no_self_loops"]
    return base


def build_summary(rows: list[dict[str, str]], isomorphic_rows: list[dict[str, str]]) -> dict[str, object]:
    summary: dict[str, object] = {
        "rows_analyzed": len(rows),
        "threeway_isomorphic_rows_no_self_loops": len(isomorphic_rows),
        "non_isomorphic_or_invalid_rows": len(rows) - len(isomorphic_rows),
    }
    for key in [
        "threeway_nodes",
        "edges_no_self_loops",
        "weak_components",
        "largest_weak_component",
        "isolated_nodes_weak",
        "strong_components",
        "largest_strong_component",
    ]:
        summary[key] = numeric_stats([int(row[key]) for row in isomorphic_rows])
    return summary


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir
    summary_csv = output_dir / "threeway_summary.csv"
    if not summary_csv.exists():
        raise SystemExit(f"missing summary CSV: {summary_csv}")

    detail_output = (
        args.detail_output
        or output_dir / "threeway_isomorphic_stats_ignore_self_loops.csv"
    )
    summary_output = (
        args.summary_output
        or output_dir / "threeway_isomorphic_stats_ignore_self_loops.summary.json"
    )
    all_rows_output = (
        args.all_rows_output
        or output_dir / "threeway_all_rows_stats_ignore_self_loops.csv"
    )

    with summary_csv.open(newline="") as handle:
        summary_rows = list(csv.DictReader(handle))

    cache = GraphCache()
    analyzed_rows: list[dict[str, str]] = []
    for index, row in enumerate(summary_rows, start=1):
        analyzed = analyze_row(index, row, output_dir, args.raw_dir, cache)
        if analyzed is not None:
            analyzed_rows.append(analyzed)

    if not analyzed_rows:
        raise SystemExit("no three-way rows with node lists found")

    isomorphic_rows = [
        row
        for row in analyzed_rows
        if row["raw_directed_induced_threeway_isomorphic_no_self_loops"] == "1"
    ]

    with all_rows_output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(analyzed_rows[0].keys()))
        writer.writeheader()
        writer.writerows(analyzed_rows)

    with detail_output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(analyzed_rows[0].keys()))
        writer.writeheader()
        writer.writerows(isomorphic_rows)

    summary = build_summary(analyzed_rows, isomorphic_rows)
    with summary_output.open("w") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True)
        handle.write("\n")

    print(f"Wrote {all_rows_output}")
    print(f"Wrote {detail_output}")
    print(f"Wrote {summary_output}")
    print(
        "Three-way isomorphic rows (ignoring self-loops): "
        f"{len(isomorphic_rows)}/{len(analyzed_rows)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
