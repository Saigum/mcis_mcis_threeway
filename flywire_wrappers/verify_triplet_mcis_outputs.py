#!/usr/bin/env python3
"""Verify triplet-sweep pair MCIS outputs against the raw directed graphs."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict, deque
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
        "path",
        type=Path,
        help="Triplet output directory, or a final_mcis_summary.csv file.",
    )
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw_graphs"))
    parser.add_argument(
        "--detail-output",
        type=Path,
        default=None,
        help="Detailed verification CSV. Defaults next to final_mcis_summary.csv.",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=None,
        help="Summary JSON. Defaults next to final_mcis_summary.csv.",
    )
    return parser.parse_args()


@dataclass
class EdgeCache:
    edges: dict[Path, set[tuple[int, int]]] = field(default_factory=dict)
    nodes: dict[Path, set[int]] = field(default_factory=dict)

    def read(self, path: Path) -> tuple[set[int], set[tuple[int, int]]]:
        path = path.resolve()
        if path not in self.edges:
            self.nodes[path], self.edges[path] = read_nodes_and_edges(path)
        return self.nodes[path], self.edges[path]


def read_nodes_and_edges(path: Path) -> tuple[set[int], set[tuple[int, int]]]:
    if pd is not None:
        frame = pd.read_csv(path, usecols=["source neuron id", "target neuron id"])
        sources = frame["source neuron id"].astype("int64")
        targets = frame["target neuron id"].astype("int64")
        nodes = set(sources)
        nodes.update(targets)
        return nodes, set(zip(sources, targets))

    nodes: set[int] = set()
    edges: set[tuple[int, int]] = set()
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            source = int(row["source neuron id"])
            target = int(row["target neuron id"])
            nodes.add(source)
            nodes.add(target)
            edges.add((source, target))
    return nodes, edges


def read_mapping(path: Path) -> tuple[str, str, list[tuple[int, int]]]:
    with path.open(newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        return header[0], header[1], [(int(row[0]), int(row[1])) for row in reader if row]


def induced_edges(edges: set[tuple[int, int]], nodes: set[int]) -> set[tuple[int, int]]:
    return {(source, target) for source, target in edges if source in nodes and target in nodes}


def compare_mapping(
    left_edges: set[tuple[int, int]],
    right_edges: set[tuple[int, int]],
    mapping: dict[int, int],
) -> tuple[int, int]:
    mapped_left_edges = {(mapping[source], mapping[target]) for source, target in left_edges}
    return len(mapped_left_edges - right_edges), len(right_edges - mapped_left_edges)


def weak_components(nodes: set[int], edges: set[tuple[int, int]]) -> tuple[int, int, bool]:
    if not nodes:
        return 0, 0, False
    adj: dict[int, set[int]] = defaultdict(set)
    for source, target in edges:
        adj[source].add(target)
        adj[target].add(source)

    seen: set[int] = set()
    sizes: list[int] = []
    for node in nodes:
        if node in seen:
            continue
        queue: deque[int] = deque([node])
        seen.add(node)
        size = 0
        while queue:
            current = queue.popleft()
            size += 1
            for nxt in adj.get(current, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        sizes.append(size)
    return len(sizes), max(sizes), len(sizes) == 1


def raw_path(raw_dir: Path, graph: str) -> Path:
    return raw_dir / f"{graph}_edge_list.csv"


def summary_path_from_arg(path: Path) -> Path:
    if path.is_dir():
        return path / "final_mcis_summary.csv"
    return path


def numeric_stats(values: list[int]) -> dict[str, float | int | None]:
    if not values:
        return {"min": None, "max": None, "mean": None, "median": None}
    return {
        "min": min(values),
        "max": max(values),
        "mean": mean(values),
        "median": median(values),
    }


def verify_row(row: dict[str, str], raw_dir: Path, cache: EdgeCache) -> dict[str, str]:
    mcs_csv = Path(row["mcs_csv"])
    left_graph, right_graph, pairs = read_mapping(mcs_csv)
    if left_graph != row["left_graph"] or right_graph != row["right_graph"]:
        raise ValueError(f"summary/mapping graph mismatch for {mcs_csv}")

    left_nodes = {left for left, _right in pairs}
    right_nodes = {right for _left, right in pairs}
    mapping = dict(pairs)

    left_raw_nodes, left_raw_edges_all = cache.read(raw_path(raw_dir, left_graph))
    right_raw_nodes, right_raw_edges_all = cache.read(raw_path(raw_dir, right_graph))
    left_edges = induced_edges(left_raw_edges_all, left_nodes)
    right_edges = induced_edges(right_raw_edges_all, right_nodes)
    missing, extra = compare_mapping(left_edges, right_edges, mapping)

    left_components, left_largest, left_connected = weak_components(left_nodes, left_edges)
    right_components, right_largest, right_connected = weak_components(right_nodes, right_edges)
    duplicate_left = len(left_nodes) != len(pairs)
    duplicate_right = len(right_nodes) != len(pairs)
    left_nodes_in_raw = left_nodes <= left_raw_nodes
    right_nodes_in_raw = right_nodes <= right_raw_nodes
    raw_isomorphic = (
        not duplicate_left
        and not duplicate_right
        and left_nodes_in_raw
        and right_nodes_in_raw
        and missing == 0
        and extra == 0
    )

    out = {
        "triplet": row["triplet"],
        "left_graph": left_graph,
        "right_graph": right_graph,
        "heldout_graph": row["heldout_graph"],
        "sample_size": row["sample_size"],
        "sample_id": row["sample_id"],
        "sampling_strategy": row["sampling_strategy"],
        "mcs_csv": str(mcs_csv),
        "summary_valid_solution": row.get("valid_solution", ""),
        "summary_aborted": row.get("aborted", ""),
        "summary_returncode": row.get("returncode", ""),
        "nodes": str(len(pairs)),
        "duplicate_left_nodes": str(int(duplicate_left)),
        "duplicate_right_nodes": str(int(duplicate_right)),
        "left_nodes_in_raw": str(int(left_nodes_in_raw)),
        "right_nodes_in_raw": str(int(right_nodes_in_raw)),
        "left_raw_induced_edges": str(len(left_edges)),
        "right_raw_induced_edges": str(len(right_edges)),
        "raw_missing_left_edges_in_right": str(missing),
        "raw_extra_right_edges_not_in_left": str(extra),
        "raw_directed_induced_isomorphic": str(int(raw_isomorphic)),
        "both_weakly_connected": str(int(left_connected and right_connected)),
        "left_weakly_connected": str(int(left_connected)),
        "right_weakly_connected": str(int(right_connected)),
        "left_weak_components": str(left_components),
        "right_weak_components": str(right_components),
        "left_largest_weak_component_nodes": str(left_largest),
        "right_largest_weak_component_nodes": str(right_largest),
        "both_edgeless": str(int(len(left_edges) == 0 and len(right_edges) == 0)),
    }
    return out


def build_summary(rows: list[dict[str, str]]) -> dict[str, object]:
    nodes = [int(row["nodes"]) for row in rows]
    left_edges = [int(row["left_raw_induced_edges"]) for row in rows]
    right_edges = [int(row["right_raw_induced_edges"]) for row in rows]
    min_edges = [min(left, right) for left, right in zip(left_edges, right_edges)]
    max_edges = [max(left, right) for left, right in zip(left_edges, right_edges)]
    return {
        "rows": len(rows),
        "raw_directed_induced_isomorphic": sum(row["raw_directed_induced_isomorphic"] == "1" for row in rows),
        "not_raw_directed_induced_isomorphic": sum(row["raw_directed_induced_isomorphic"] != "1" for row in rows),
        "summary_valid_solution_1": sum(row["summary_valid_solution"] == "1" for row in rows),
        "summary_valid_solution_0": sum(row["summary_valid_solution"] == "0" for row in rows),
        "aborted_1": sum(row["summary_aborted"] == "1" for row in rows),
        "both_weakly_connected": sum(row["both_weakly_connected"] == "1" for row in rows),
        "left_weakly_connected": sum(row["left_weakly_connected"] == "1" for row in rows),
        "right_weakly_connected": sum(row["right_weakly_connected"] == "1" for row in rows),
        "both_edgeless": sum(row["both_edgeless"] == "1" for row in rows),
        "nodes": numeric_stats(nodes),
        "left_raw_induced_edges": numeric_stats(left_edges),
        "right_raw_induced_edges": numeric_stats(right_edges),
        "min_side_raw_induced_edges": numeric_stats(min_edges),
        "max_side_raw_induced_edges": numeric_stats(max_edges),
    }


def main() -> int:
    args = parse_args()
    final_summary = summary_path_from_arg(args.path)
    if not final_summary.exists():
        raise SystemExit(f"missing final summary: {final_summary}")

    detail_output = args.detail_output or final_summary.with_name("triplet_mcis_raw_verification.csv")
    summary_output = args.summary_output or final_summary.with_name("triplet_mcis_raw_verification_summary.json")

    with final_summary.open(newline="") as handle:
        input_rows = [row for row in csv.DictReader(handle) if row.get("mcs_csv")]

    cache = EdgeCache()
    rows = []
    for index, row in enumerate(input_rows, start=1):
        print(f"Verifying {index}/{len(input_rows)} {row['left_graph']} x {row['right_graph']} n={row['sample_size']}", flush=True)
        rows.append(verify_row(row, args.raw_dir, cache))

    detail_output.parent.mkdir(parents=True, exist_ok=True)
    with detail_output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    summary = build_summary(rows)
    with summary_output.open("w") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True)
        handle.write("\n")

    print(f"Wrote {detail_output}")
    print(f"Wrote {summary_output}")
    print(
        "Raw directed induced isomorphic: "
        f"{summary['raw_directed_induced_isomorphic']}/{summary['rows']}"
    )
    print(f"Both weakly connected: {summary['both_weakly_connected']}/{summary['rows']}")
    print(f"Both edgeless: {summary['both_edgeless']}/{summary['rows']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
