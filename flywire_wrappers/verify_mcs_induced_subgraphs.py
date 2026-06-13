#!/usr/bin/env python3
"""Verify saved MCS mappings against sampled and raw induced subgraphs."""

from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

try:
    import pandas as pd
except ImportError:  # pragma: no cover - fallback for minimal environments.
    pd = None


PAIR_RE = re.compile(
    r"(?P<left>.+)__(?P<right>.+)\.n(?P<size>\d+)\.(?P<sample_id>.+?)(?:\.rank\d+\.size\d+)?\.mcs_nodes\.csv$"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path, help="MCS CSV files or output directories to scan.")
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw_graphs"))
    parser.add_argument("--output", type=Path, default=Path("outputs/mcs_induced_verification.csv"))
    parser.add_argument("--top", type=int, default=0, help="Only check largest N files by row count; 0 means all.")
    return parser.parse_args()


def find_mcs_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(path.rglob("*.mcs_nodes.csv")))
        elif path.name.endswith(".mcs_nodes.csv"):
            files.append(path)
    return [path for path in files if parse_mcs_filename(path) is not None]


def parse_mcs_filename(path: Path) -> dict[str, str] | None:
    match = PAIR_RE.match(path.name)
    if not match:
        return None
    return match.groupdict()


def graph_raw_path(raw_dir: Path, graph: str) -> Path:
    return raw_dir / f"{graph}_edge_list.csv"


def read_mcs(path: Path) -> tuple[str, str, list[tuple[int, int]]]:
    with path.open(newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        left_graph, right_graph = header[0], header[1]
        pairs = [(int(row[0]), int(row[1])) for row in reader if row]
    return left_graph, right_graph, pairs


def count_rows(path: Path) -> int:
    with path.open(newline="") as handle:
        return max(0, sum(1 for _ in handle) - 1)


@dataclass
class EdgeCache:
    nodes_edges: dict[Path, tuple[set[int], set[tuple[int, int]]]] = field(default_factory=dict)

    def read_nodes_and_edges(self, path: Path) -> tuple[set[int], set[tuple[int, int]]]:
        path = path.resolve()
        if path not in self.nodes_edges:
            self.nodes_edges[path] = read_nodes_and_edges(path)
        return self.nodes_edges[path]


def read_nodes_and_edges(path: Path) -> tuple[set[int], set[tuple[int, int]]]:
    if pd is not None:
        frame = pd.read_csv(path, usecols=["source neuron id", "target neuron id"])
        sources = frame["source neuron id"].astype("int64")
        targets = frame["target neuron id"].astype("int64")
        nodes = set(sources)
        nodes.update(targets)
        edges = set(zip(sources, targets))
        return nodes, edges

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


def induced_edges(edges: set[tuple[int, int]], nodes: set[int]) -> set[tuple[int, int]]:
    return {(source, target) for source, target in edges if source in nodes and target in nodes}


def compare_under_mapping(
    left_edges: set[tuple[int, int]],
    right_edges: set[tuple[int, int]],
    mapping: dict[int, int],
) -> tuple[int, int]:
    mapped_left_edges = {(mapping[source], mapping[target]) for source, target in left_edges}
    missing_in_right = len(mapped_left_edges - right_edges)
    extra_in_right = len(right_edges - mapped_left_edges)
    return missing_in_right, extra_in_right


def locate_sample_csv(root: Path, graph: str, size: str, sample_id: str) -> Path:
    return root / "samples" / f"{graph}.n{size}.{sample_id}.csv"


def verify_file(path: Path, raw_dir: Path, cache: EdgeCache) -> dict[str, str]:
    parsed = parse_mcs_filename(path)
    if parsed is None:
        raise ValueError(f"cannot parse MCS filename: {path}")

    left_graph, right_graph, pairs = read_mcs(path)
    size = parsed["size"]
    sample_id = parsed["sample_id"]
    output_root = path.parent.parent
    left_sample_csv = locate_sample_csv(output_root, left_graph, size, sample_id)
    right_sample_csv = locate_sample_csv(output_root, right_graph, size, sample_id)
    left_raw_csv = graph_raw_path(raw_dir, left_graph)
    right_raw_csv = graph_raw_path(raw_dir, right_graph)

    left_mcs_nodes = {left for left, _right in pairs}
    right_mcs_nodes = {right for _left, right in pairs}
    mapping = dict(pairs)
    duplicate_left = len(left_mcs_nodes) != len(pairs)
    duplicate_right = len(right_mcs_nodes) != len(pairs)

    left_sample_nodes, left_sample_edges = cache.read_nodes_and_edges(left_sample_csv)
    right_sample_nodes, right_sample_edges = cache.read_nodes_and_edges(right_sample_csv)
    left_raw_nodes, left_raw_edges = cache.read_nodes_and_edges(left_raw_csv)
    right_raw_nodes, right_raw_edges = cache.read_nodes_and_edges(right_raw_csv)

    left_nodes_in_sample = left_mcs_nodes <= left_sample_nodes
    right_nodes_in_sample = right_mcs_nodes <= right_sample_nodes
    left_nodes_in_raw = left_mcs_nodes <= left_raw_nodes
    right_nodes_in_raw = right_mcs_nodes <= right_raw_nodes

    left_sample_induced = induced_edges(left_sample_edges, left_mcs_nodes)
    right_sample_induced = induced_edges(right_sample_edges, right_mcs_nodes)
    left_raw_induced = induced_edges(left_raw_edges, left_mcs_nodes)
    right_raw_induced = induced_edges(right_raw_edges, right_mcs_nodes)

    sample_matches_raw_left = left_sample_induced == left_raw_induced
    sample_matches_raw_right = right_sample_induced == right_raw_induced
    sample_missing, sample_extra = compare_under_mapping(left_sample_induced, right_sample_induced, mapping)
    raw_missing, raw_extra = compare_under_mapping(left_raw_induced, right_raw_induced, mapping)

    node_count = len(pairs)
    denom = max(1, node_count * (node_count - 1))
    return {
        "mcs_csv": str(path),
        "left_graph": left_graph,
        "right_graph": right_graph,
        "sample_size": size,
        "sample_id": sample_id,
        "mcs_nodes": str(node_count),
        "duplicate_left_nodes": str(int(duplicate_left)),
        "duplicate_right_nodes": str(int(duplicate_right)),
        "left_nodes_in_sample": str(int(left_nodes_in_sample)),
        "right_nodes_in_sample": str(int(right_nodes_in_sample)),
        "left_nodes_in_raw": str(int(left_nodes_in_raw)),
        "right_nodes_in_raw": str(int(right_nodes_in_raw)),
        "left_sample_induced_edges": str(len(left_sample_induced)),
        "right_sample_induced_edges": str(len(right_sample_induced)),
        "left_raw_induced_edges": str(len(left_raw_induced)),
        "right_raw_induced_edges": str(len(right_raw_induced)),
        "left_sample_density": f"{len(left_sample_induced) / denom:.8g}",
        "right_sample_density": f"{len(right_sample_induced) / denom:.8g}",
        "sample_induced_matches_raw_left": str(int(sample_matches_raw_left)),
        "sample_induced_matches_raw_right": str(int(sample_matches_raw_right)),
        "mcs_is_directed_induced_match_in_samples": str(int(sample_missing == 0 and sample_extra == 0)),
        "sample_missing_left_edges_in_right": str(sample_missing),
        "sample_extra_right_edges_not_in_left": str(sample_extra),
        "mcs_is_directed_induced_match_in_raw": str(int(raw_missing == 0 and raw_extra == 0)),
        "raw_missing_left_edges_in_right": str(raw_missing),
        "raw_extra_right_edges_not_in_left": str(raw_extra),
        "all_checks_passed": str(int(
            not duplicate_left
            and not duplicate_right
            and left_nodes_in_sample
            and right_nodes_in_sample
            and left_nodes_in_raw
            and right_nodes_in_raw
            and sample_matches_raw_left
            and sample_matches_raw_right
            and sample_missing == 0
            and sample_extra == 0
            and raw_missing == 0
            and raw_extra == 0
        )),
    }


def main() -> int:
    args = parse_args()
    files = find_mcs_files(args.paths)
    files.sort(key=count_rows, reverse=True)
    if args.top > 0:
        files = files[: args.top]
    if not files:
        raise SystemExit("no MCS files found")

    rows: list[dict[str, str]] = []
    cache = EdgeCache()
    for path in files:
        print(f"Verifying {path}", flush=True)
        rows.append(verify_file(path, args.raw_dir, cache))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys())
    with args.output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    passed = sum(row["all_checks_passed"] == "1" for row in rows)
    print(f"Wrote {args.output}")
    print(f"Passed {passed}/{len(rows)} MCS files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
