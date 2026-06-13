#!/usr/bin/env python3
"""Revalidate triplet-parallel MCS summaries and restore valid mapping CSVs."""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_symsplit_sampled_mcs as base  # noqa: E402
from run_symsplit_triplet_parallel_mcs import mcis_edge_counts  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dirs", nargs="+", type=Path)
    parser.add_argument("--write", action="store_true", help="Rewrite summaries and mcs_csv files.")
    return parser.parse_args()


def parse_pairs(stdout_log: Path) -> list[tuple[int, int]]:
    pairs: list[tuple[int, int]] = []
    for line in stdout_log.read_text().splitlines():
        if line.startswith("M "):
            _tag, left, right = line.split()
            pairs.append((int(left), int(right)))
    return pairs


def parse_sample_id(row: dict[str, str]) -> str:
    if row.get("sample_id"):
        return row["sample_id"]
    match = re.search(r"\.n\d+\.([^./]+)\.stdout\.log$", row.get("stdout_log", ""))
    if match:
        return match.group(1)
    raise ValueError(f"cannot infer sample_id for row: {row}")


def sampled_graph(root: Path, graph: str, size: int, sample_id: str) -> base.SampledGraph:
    return base.SampledGraph(
        graph=graph,
        sample_size=size,
        sample_id=sample_id,
        csv_path=root / "samples" / f"{graph}.n{size}.{sample_id}.csv",
        dimacs_path=root / "dimacs" / f"{graph}.n{size}.{sample_id}.dimacs",
        map_path=root / "maps" / f"{graph}.n{size}.{sample_id}.map.csv",
        node_count=0,
        edge_count=0,
    )


def default_mcs_csv(root: Path, stdout_log: Path) -> Path:
    return root / "mcs" / stdout_log.name.replace(".stdout.log", ".mcs_nodes.csv")


def revalidate_summary(summary_path: Path, write: bool) -> tuple[int, int, int]:
    root = summary_path.parent
    rows = list(csv.DictReader(summary_path.open(newline="")))
    if not rows:
        return 0, 0, 0

    valid_count = 0
    saved_count = 0
    changed_count = 0
    for row in rows:
        if not row.get("stdout_log") or row.get("returncode") not in {"0", "skipped_existing"}:
            continue

        size = int(row["sample_size"])
        sample_id = parse_sample_id(row)
        left = sampled_graph(root, row["left_graph"], size, sample_id)
        right = sampled_graph(root, row["right_graph"], size, sample_id)
        left_map = base.read_index_map(left.map_path)
        right_map = base.read_index_map(right.map_path)
        pairs = parse_pairs(Path(row["stdout_log"]))
        validation = base.validate_directed_induced_mapping(left, right, left_map, right_map, pairs)
        mcis_nodes, left_edges, right_edges = mcis_edge_counts(left.csv_path, right.csv_path, left_map, right_map, pairs)
        sym_valid = row.get("valid_solution") == "1"
        externally_valid = validation["external_valid_solution"] == 1
        is_valid = sym_valid and externally_valid

        old = dict(row)
        row.update({key: str(value) for key, value in validation.items()})
        row["final_mcis_nodes"] = str(mcis_nodes)
        row["final_mcis_left_edges"] = str(left_edges)
        row["final_mcis_right_edges"] = str(right_edges)
        row["final_mcis_edges"] = str(min(left_edges, right_edges))
        if is_valid:
            valid_count += 1
            mcs_csv = Path(row.get("mcs_csv") or default_mcs_csv(root, Path(row["stdout_log"])))
            row["mapped_pairs"] = str(len(pairs))
            row["mcs_csv"] = str(mcs_csv)
            if write:
                mcs_csv.parent.mkdir(parents=True, exist_ok=True)
                base.write_mcs_csv(mcs_csv, row["left_graph"], row["right_graph"], left_map, right_map, pairs)
            saved_count += 1
        else:
            row["mapped_pairs"] = "0"
            row["mcs_csv"] = ""

        if row != old:
            changed_count += 1

    if write and changed_count:
        with summary_path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    return len(rows), valid_count, saved_count


def main() -> int:
    args = parse_args()
    for output_dir in args.output_dirs:
        paths = []
        for name in ("triplet_pair_mcs_summary.csv", "final_mcis_summary.csv"):
            path = output_dir / name
            if path.exists():
                paths.append(path)
        if not paths:
            print(f"{output_dir}: no summary CSV found")
            continue
        for path in paths:
            rows, valid, saved = revalidate_summary(path, args.write)
            mode = "rewrote" if args.write else "checked"
            print(f"{mode} {path}: rows={rows} valid={valid} saved_mcs_csv={saved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
