#!/usr/bin/env python3
"""Sample all graphs first, then run triplet-pair SymSplit MCS jobs in parallel."""

from __future__ import annotations

import argparse
import csv
import itertools
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import run_symsplit_sampled_mcs as base
import run_symsplit_biased_sampled_mcs as biased


ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class TripletPairJob:
    atomic_job_index: int
    size: int
    triplet: tuple[base.SampledGraph, base.SampledGraph, base.SampledGraph]
    left: base.SampledGraph
    right: base.SampledGraph
    heldout: base.SampledGraph


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "inputs",
        nargs="*",
        type=Path,
        help="Raw directed edge-list CSVs. Defaults to data/raw_graphs/*_edge_list.csv.",
    )
    parser.add_argument("--out-dir", type=Path, default=Path("outputs/symsplit_triplet_parallel_mcs"))
    parser.add_argument("--solver", type=Path, default=Path("../symsplit/bin/run.o"))
    parser.add_argument("--sizes", type=int, nargs="+", default=[1000, 2000, 4000])
    parser.add_argument("--sample-id", default="high_degree_bfs_seed1")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--wall-timeout", type=int, default=240)
    parser.add_argument("--n-jobs", type=int, default=1)
    parser.add_argument("--top-k-incumbents", type=int, default=10)
    parser.add_argument("--sampling-strategy", choices=biased.STRATEGIES, default="sparse_greedy")
    parser.add_argument("--degree-band-quantile", type=float, default=0.35)
    parser.add_argument("--sparse-candidate-pool", type=int, default=64)
    parser.add_argument("--reuse-samples", action="store_true")
    parser.add_argument("--rerun-existing", action="store_true")
    return parser.parse_args()


def sample_all(args: argparse.Namespace) -> dict[int, list[base.SampledGraph]]:
    if not args.inputs:
        args.inputs = sorted((ROOT / "data" / "raw_graphs").glob("*_edge_list.csv"))
    args.out_dir.mkdir(parents=True, exist_ok=True)

    samples_by_size: dict[int, list[base.SampledGraph]] = {size: [] for size in args.sizes}
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
            "csv_path",
            "dimacs_path",
            "map_path",
        ])
        for input_path in args.inputs:
            graph = base.graph_stem(input_path)
            print(f"Loading {input_path}", flush=True)
            nodes, edges, weak_adj, degree = base.read_edges(input_path)
            for size in args.sizes:
                print(f"Sampling {graph} n={size} strategy={args.sampling_strategy}", flush=True)
                sampled_nodes = biased.sample_nodes(args, nodes, weak_adj, degree, size)
                sample = base.write_sample_outputs(graph, size, args.sample_id, sampled_nodes, edges, args.out_dir, args.reuse_samples)
                samples_by_size[size].append(sample)
                writer.writerow([
                    graph,
                    size,
                    args.sample_id,
                    args.sampling_strategy,
                    sample.node_count,
                    sample.edge_count,
                    sample.csv_path,
                    sample.dimacs_path,
                    sample.map_path,
                ])
                handle.flush()
    print(f"Wrote {sample_summary_path}", flush=True)
    return samples_by_size


def make_jobs(samples_by_size: dict[int, list[base.SampledGraph]]) -> list[TripletPairJob]:
    jobs: list[TripletPairJob] = []
    for size, samples in samples_by_size.items():
        for triplet in itertools.combinations(samples, 3):
            for atomic_job_index, (left, right) in enumerate(itertools.combinations(triplet, 2), start=1):
                heldout = next(sample for sample in triplet if sample.graph not in {left.graph, right.graph})
                jobs.append(TripletPairJob(
                    atomic_job_index=atomic_job_index,
                    size=size,
                    triplet=triplet,
                    left=left,
                    right=right,
                    heldout=heldout,
                ))
    return jobs


def read_sample_edges(csv_path: Path) -> set[tuple[int, int]]:
    edges: set[tuple[int, int]] = set()
    with csv_path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            source = int(row["source neuron id"])
            target = int(row["target neuron id"])
            if source != target:
                edges.add((source, target))
    return edges


def count_induced_edges(csv_path: Path, nodes: set[int]) -> int:
    if not nodes:
        return 0
    return sum(1 for source, target in read_sample_edges(csv_path) if source in nodes and target in nodes)


def mcis_edge_counts(
    left_csv: Path,
    right_csv: Path,
    left_map: list[int],
    right_map: list[int],
    pairs: list[tuple[int, int]],
) -> tuple[int, int, int]:
    left_nodes = {left_map[left_index] for left_index, _right_index in pairs if 0 <= left_index < len(left_map)}
    right_nodes = {right_map[right_index] for _left_index, right_index in pairs if 0 <= right_index < len(right_map)}
    left_edges = count_induced_edges(left_csv, left_nodes)
    right_edges = count_induced_edges(right_csv, right_nodes)
    return len(left_nodes), left_edges, right_edges


def job_stem(job: TripletPairJob) -> str:
    triplet_name = "--".join(sample.graph for sample in job.triplet)
    return (
        f"triplet_{triplet_name}"
        f"__pair_{job.left.graph}__{job.right.graph}"
        f"__heldout_{job.heldout.graph}"
        f".n{job.size}.{job.left.sample_id}"
    )


def run_job(args: argparse.Namespace, job: TripletPairJob) -> dict[str, str]:
    pair_stem = job_stem(job)
    logs_dir = args.out_dir / "logs"
    mcs_dir = args.out_dir / "mcs"
    inc_dir = args.out_dir / "incumbents"
    logs_dir.mkdir(parents=True, exist_ok=True)
    mcs_dir.mkdir(parents=True, exist_ok=True)
    inc_dir.mkdir(parents=True, exist_ok=True)

    stdout_log = logs_dir / f"{pair_stem}.stdout.log"
    stderr_log = logs_dir / f"{pair_stem}.stderr.log"
    mcs_csv = mcs_dir / f"{pair_stem}.mcs_nodes.csv"
    left_map = base.read_index_map(job.left.map_path)
    right_map = base.read_index_map(job.right.map_path)

    row = {
        "triplet": "|".join(sample.graph for sample in job.triplet),
        "atomic_job_index": str(job.atomic_job_index),
        "left_graph": job.left.graph,
        "right_graph": job.right.graph,
        "heldout_graph": job.heldout.graph,
        "sample_size": str(job.size),
        "sample_id": job.left.sample_id,
        "sampling_strategy": args.sampling_strategy,
        "left_nodes": str(job.left.node_count),
        "left_edges": str(job.left.edge_count),
        "right_nodes": str(job.right.node_count),
        "right_edges": str(job.right.edge_count),
        "mcs_csv": str(mcs_csv),
        "stdout_log": str(stdout_log),
        "stderr_log": str(stderr_log),
    }

    if not args.rerun_existing and mcs_csv.exists() and stdout_log.exists():
        stdout = stdout_log.read_text()
        metrics, pairs = base.parse_symsplit(stdout)
        blocks = base.parse_symsplit_blocks(stdout)
        validation = base.validate_directed_induced_mapping(job.left, job.right, left_map, right_map, pairs)
        if not validation["external_valid_solution"] and mcs_csv.exists():
            mcs_csv.unlink()
        incumbents_summary = base.save_topk_incumbents(args, pair_stem, job.left, job.right, args.out_dir, blocks, left_map, right_map)
        mcis_nodes, left_mcis_edges, right_mcis_edges = mcis_edge_counts(
            job.left.csv_path,
            job.right.csv_path,
            left_map,
            right_map,
            pairs,
        )
        row.update(metrics)
        row.update(
            {
                "returncode": "skipped_existing",
                "mapped_pairs": str(mcis_nodes if validation["external_valid_solution"] else 0),
                "final_mcis_nodes": str(mcis_nodes),
                "final_mcis_left_edges": str(left_mcis_edges),
                "final_mcis_right_edges": str(right_mcis_edges),
                "final_mcis_edges": str(min(left_mcis_edges, right_mcis_edges)),
                "incumbents_summary": incumbents_summary,
                "mcs_csv": str(mcs_csv) if validation["external_valid_solution"] else "",
            }
        )
        row.update({key: str(value) for key, value in validation.items()})
        for key in base.METRIC_KEYS:
            row.setdefault(key, "")
        return row

    cmd = [
        str(args.solver.resolve()),
        "min_max",
        str(job.left.dimacs_path.resolve()),
        str(job.right.dimacs_path.resolve()),
        "-d",
        "-i",
        "-q",
        "-t",
        str(args.timeout),
    ]
    returncode = base.run_process_streaming(cmd, ROOT, stdout_log, stderr_log, args.wall_timeout)
    stdout = stdout_log.read_text()
    metrics, pairs = base.parse_symsplit(stdout)
    blocks = base.parse_symsplit_blocks(stdout)
    validation = base.validate_directed_induced_mapping(job.left, job.right, left_map, right_map, pairs)
    if validation["external_valid_solution"]:
        mapped_pairs = base.write_mcs_csv(mcs_csv, job.left.graph, job.right.graph, left_map, right_map, pairs)
        saved_mcs_csv = str(mcs_csv)
    else:
        if mcs_csv.exists():
            mcs_csv.unlink()
        mapped_pairs = 0
        saved_mcs_csv = ""
    incumbents_summary = base.save_topk_incumbents(args, pair_stem, job.left, job.right, args.out_dir, blocks, left_map, right_map)
    mcis_nodes, left_mcis_edges, right_mcis_edges = mcis_edge_counts(
        job.left.csv_path,
        job.right.csv_path,
        left_map,
        right_map,
        pairs,
    )

    row.update(metrics)
    row.update(
        {
            "returncode": str(returncode),
            "mapped_pairs": str(mapped_pairs),
            "final_mcis_nodes": str(mcis_nodes),
            "final_mcis_left_edges": str(left_mcis_edges),
            "final_mcis_right_edges": str(right_mcis_edges),
            "final_mcis_edges": str(min(left_mcis_edges, right_mcis_edges)),
            "incumbents_summary": incumbents_summary,
            "mcs_csv": saved_mcs_csv,
        }
    )
    row.update({key: str(value) for key, value in validation.items()})
    row.setdefault("mcs_size", str(len(pairs)))
    for key in base.METRIC_KEYS:
        row.setdefault(key, "")
    return row


def main() -> int:
    args = parse_args()
    if args.n_jobs < 1:
        raise ValueError("--n-jobs must be >= 1")

    samples_by_size = sample_all(args)
    jobs = make_jobs(samples_by_size)
    print(f"Prepared {len(jobs)} triplet-pair jobs; running n_jobs={args.n_jobs}", flush=True)

    fields = [
        "triplet",
        "atomic_job_index",
        "left_graph",
        "right_graph",
        "heldout_graph",
        "sample_size",
        "sample_id",
        "sampling_strategy",
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
        "mapped_pairs",
        "final_mcis_nodes",
        "final_mcis_edges",
        "final_mcis_left_edges",
        "final_mcis_right_edges",
        "external_valid_solution",
        "out_of_range_pairs",
        "duplicate_left_nodes",
        "duplicate_right_nodes",
        "left_induced_edges",
        "right_induced_edges",
        "missing_left_edges_in_right",
        "extra_right_edges_not_in_left",
        "incumbents_summary",
        "mcs_csv",
        "stdout_log",
        "stderr_log",
    ]
    results_path = args.out_dir / "triplet_pair_mcs_summary.csv"
    final_rows: list[dict[str, str]] = []
    with results_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        with ThreadPoolExecutor(max_workers=args.n_jobs) as executor:
            future_to_job = {executor.submit(run_job, args, job): job for job in jobs}
            for future in as_completed(future_to_job):
                job = future_to_job[future]
                try:
                    row = future.result()
                except Exception as exc:
                    row = {
                        "triplet": "|".join(sample.graph for sample in job.triplet),
                        "atomic_job_index": str(job.atomic_job_index),
                        "left_graph": job.left.graph,
                        "right_graph": job.right.graph,
                        "heldout_graph": job.heldout.graph,
                        "sample_size": str(job.size),
                        "sample_id": job.left.sample_id,
                        "sampling_strategy": args.sampling_strategy,
                        "returncode": "wrapper_error",
                        "mcs_size": "",
                        "mapped_pairs": "",
                        "final_mcis_nodes": "",
                        "final_mcis_edges": "",
                        "final_mcis_left_edges": "",
                        "final_mcis_right_edges": "",
                        "incumbents_summary": "",
                        "mcs_csv": "",
                        "stdout_log": "",
                        "stderr_log": str(exc),
                    }
                writer.writerow(row)
                final_rows.append(row)
                handle.flush()
                print(
                    f"done {row['left_graph']} x {row['right_graph']} "
                    f"heldout={row['heldout_graph']} n={row['sample_size']} "
                    f"mcs={row.get('mcs_size', '')} rc={row.get('returncode', '')}",
                    flush=True,
                )

    print(f"Wrote {results_path}", flush=True)
    final_path = args.out_dir / "final_mcis_summary.csv"
    with final_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(sorted(
            final_rows,
            key=lambda row: (
                row.get("sample_size", ""),
                row.get("triplet", ""),
                row.get("atomic_job_index", ""),
            ),
        ))
    print(f"Wrote {final_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
