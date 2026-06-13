#!/usr/bin/env python3
"""Analyze saved MCS incumbent mappings for connectivity and induced validity."""

from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict, deque
from pathlib import Path


PAIR_RE = re.compile(r"(?P<left>.+)__(?P<right>.+)\.n(?P<size>\d+)\.(?P<sample_id>.+?)\.rank\d+\.size(?P<mcs_size>\d+)\.mcs_nodes\.csv$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path, help="Incumbent mcs_nodes.csv files or directories to scan.")
    parser.add_argument("--top", type=int, default=25, help="Analyze the largest N incumbent CSVs found.")
    parser.add_argument("--output", type=Path, default=Path("outputs/mcs_incumbent_analysis.csv"))
    return parser.parse_args()


def find_mcs_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(path.rglob("*.mcs_nodes.csv")))
        elif path.name.endswith(".mcs_nodes.csv"):
            files.append(path)
    return files


def parse_mcs_path(path: Path) -> dict[str, str] | None:
    match = PAIR_RE.match(path.name)
    if not match:
        return None
    return match.groupdict()


def read_edges(path: Path) -> set[tuple[int, int]]:
    edges: set[tuple[int, int]] = set()
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            edges.add((int(row["source neuron id"]), int(row["target neuron id"])))
    return edges


def read_mcs(path: Path) -> tuple[str, str, list[tuple[int, int]]]:
    with path.open(newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        left_graph, right_graph = header[0], header[1]
        pairs = [(int(row[0]), int(row[1])) for row in reader if row]
    return left_graph, right_graph, pairs


def weak_component_sizes(nodes: set[int], edges: set[tuple[int, int]]) -> list[int]:
    adj: dict[int, set[int]] = {node: set() for node in nodes}
    for source, target in edges:
        if source in nodes and target in nodes:
            adj[source].add(target)
            adj[target].add(source)

    seen: set[int] = set()
    sizes: list[int] = []
    for start in nodes:
        if start in seen:
            continue
        seen.add(start)
        queue: deque[int] = deque([start])
        count = 0
        while queue:
            node = queue.popleft()
            count += 1
            for neighbor in adj[node]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        sizes.append(count)
    return sorted(sizes, reverse=True)


def strong_component_sizes(nodes: set[int], edges: set[tuple[int, int]]) -> list[int]:
    adj: dict[int, list[int]] = {node: [] for node in nodes}
    rev: dict[int, list[int]] = {node: [] for node in nodes}
    for source, target in edges:
        if source in nodes and target in nodes:
            adj[source].append(target)
            rev[target].append(source)

    seen: set[int] = set()
    order: list[int] = []
    for start in nodes:
        if start in seen:
            continue
        stack: list[tuple[int, bool]] = [(start, False)]
        seen.add(start)
        while stack:
            node, done = stack.pop()
            if done:
                order.append(node)
                continue
            stack.append((node, True))
            for neighbor in adj[node]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    stack.append((neighbor, False))

    seen.clear()
    sizes: list[int] = []
    for start in reversed(order):
        if start in seen:
            continue
        seen.add(start)
        stack = [start]
        count = 0
        while stack:
            node = stack.pop()
            count += 1
            for neighbor in rev[node]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
        sizes.append(count)
    return sorted(sizes, reverse=True)


def analyze_file(path: Path) -> dict[str, str]:
    parsed = parse_mcs_path(path)
    if parsed is None:
        raise ValueError(f"cannot parse incumbent filename: {path}")

    left_graph, right_graph, pairs = read_mcs(path)
    root = path.parent.parent
    size = parsed["size"]
    sample_id = parsed["sample_id"]
    left_sample = root / "samples" / f"{left_graph}.n{size}.{sample_id}.csv"
    right_sample = root / "samples" / f"{right_graph}.n{size}.{sample_id}.csv"
    if not left_sample.exists() or not right_sample.exists():
        raise FileNotFoundError(f"missing sample CSV for {path}")

    left_edges_all = read_edges(left_sample)
    right_edges_all = read_edges(right_sample)
    left_nodes = {left for left, _right in pairs}
    right_nodes = {right for _left, right in pairs}
    mapping = dict(pairs)

    left_induced_edges = {
        (source, target)
        for source, target in left_edges_all
        if source in left_nodes and target in left_nodes
    }
    right_induced_edges = {
        (source, target)
        for source, target in right_edges_all
        if source in right_nodes and target in right_nodes
    }

    missing_in_right = 0
    extra_in_right = 0
    mapped_left_edges: set[tuple[int, int]] = set()
    for source, target in left_induced_edges:
        mapped_edge = (mapping[source], mapping[target])
        mapped_left_edges.add(mapped_edge)
        if mapped_edge not in right_induced_edges:
            missing_in_right += 1
    for edge in right_induced_edges:
        if edge not in mapped_left_edges:
            extra_in_right += 1

    left_weak = weak_component_sizes(left_nodes, left_induced_edges)
    right_weak = weak_component_sizes(right_nodes, right_induced_edges)
    left_strong = strong_component_sizes(left_nodes, left_induced_edges)
    right_strong = strong_component_sizes(right_nodes, right_induced_edges)
    node_count = len(pairs)
    denom = max(1, node_count * (node_count - 1))

    return {
        "mcs_csv": str(path),
        "left_graph": left_graph,
        "right_graph": right_graph,
        "sample_size": size,
        "sample_id": sample_id,
        "mcs_nodes": str(node_count),
        "left_induced_edges": str(len(left_induced_edges)),
        "right_induced_edges": str(len(right_induced_edges)),
        "left_density": f"{len(left_induced_edges) / denom:.8g}",
        "right_density": f"{len(right_induced_edges) / denom:.8g}",
        "induced_isomorphic_under_mapping": str(int(missing_in_right == 0 and extra_in_right == 0)),
        "missing_left_edges_in_right": str(missing_in_right),
        "extra_right_edges_not_in_left": str(extra_in_right),
        "left_weak_components": str(len(left_weak)),
        "right_weak_components": str(len(right_weak)),
        "left_largest_weak_component": str(left_weak[0] if left_weak else 0),
        "right_largest_weak_component": str(right_weak[0] if right_weak else 0),
        "left_weak_connected": str(int(len(left_weak) == 1)),
        "right_weak_connected": str(int(len(right_weak) == 1)),
        "left_strong_components": str(len(left_strong)),
        "right_strong_components": str(len(right_strong)),
        "left_largest_strong_component": str(left_strong[0] if left_strong else 0),
        "right_largest_strong_component": str(right_strong[0] if right_strong else 0),
        "left_strong_connected": str(int(len(left_strong) == 1)),
        "right_strong_connected": str(int(len(right_strong) == 1)),
    }


def main() -> int:
    args = parse_args()
    files = find_mcs_files(args.paths)
    files = [path for path in files if parse_mcs_path(path) is not None]
    files.sort(key=lambda path: int(parse_mcs_path(path)["mcs_size"]), reverse=True)
    if args.top > 0:
        files = files[: args.top]
    if not files:
        raise SystemExit("no incumbent mcs_nodes.csv files found")

    rows = []
    for path in files:
        print(f"Analyzing {path}", flush=True)
        rows.append(analyze_file(path))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys())
    with args.output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

