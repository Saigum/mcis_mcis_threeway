#!/usr/bin/env python3
"""Characterize found modules using local BANC and FAFB annotation folders."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd


TARGET_GRAPHS = {"banc_626", "fafb_783"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output_dir",
        type=Path,
        help="Output directory such as outputs/high_degree_bfs_seed1",
    )
    parser.add_argument(
        "--banc-dir",
        type=Path,
        default=Path("banc"),
        help="Directory containing banc metadata files",
    )
    parser.add_argument(
        "--fafb-dir",
        type=Path,
        default=Path("fafb"),
        help="Directory containing fafb metadata files",
    )
    parser.add_argument(
        "--stats-csv",
        type=Path,
        default=None,
        help=(
            "Input stats CSV. Defaults to "
            "<output_dir>/threeway_isomorphic_stats_ignore_self_loops.csv"
        ),
    )
    parser.add_argument(
        "--output-prefix",
        type=Path,
        default=None,
        help=(
            "Prefix for outputs. Defaults to "
            "<output_dir>/banc_fafb_module_characterization"
        ),
    )
    return parser.parse_args()


def counter_to_string(counter: Counter, top_n: int = 8) -> str:
    items = [(str(key), int(value)) for key, value in counter.most_common(top_n)]
    return "; ".join(f"{key}:{value}" for key, value in items)


def safe_counter(series: pd.Series) -> Counter:
    values = [str(v) for v in series.dropna() if str(v).strip() and str(v).strip().lower() != "nan"]
    return Counter(values)


@dataclass
class GraphResources:
    metadata: pd.DataFrame
    id_col: str
    metadata_fields: list[str]
    connections: pd.DataFrame
    pre_col: str
    post_col: str
    graph_label: str


def load_fafb_resources(fafb_dir: Path) -> GraphResources:
    classification = pd.read_csv(fafb_dir / "fafb_classification.csv")
    cell_types = pd.read_csv(fafb_dir / "fafb_consolidated_cell_types.csv")
    cell_stats = pd.read_csv(fafb_dir / "cell_stats.csv")
    metadata = classification.merge(cell_types, how="left", on="root_id").merge(cell_stats, how="left", on="root_id")
    connections = pd.read_csv(fafb_dir / "connections_princeton.csv")
    return GraphResources(
        metadata=metadata,
        id_col="root_id",
        metadata_fields=[
            "flow",
            "super_class",
            "class",
            "sub_class",
            "hemilineage",
            "side",
            "nerve",
            "primary_type",
            "additional_type(s)",
        ],
        connections=connections,
        pre_col="pre_root_id",
        post_col="post_root_id",
        graph_label="fafb_783",
    )


def load_banc_resources(banc_dir: Path) -> GraphResources:
    metadata = pd.read_csv(banc_dir / "neurons.csv")
    connections = pd.read_csv(banc_dir / "connections_princeton.csv")
    return GraphResources(
        metadata=metadata,
        id_col="Root ID",
        metadata_fields=[
            "Top in/out region",
            "Community labels",
            "Predicted NT type",
            "Verified NT type",
            "Verified Neuropeptide",
            "Body Part",
            "Function",
            "Flow",
            "Super Class",
            "Class",
            "Sub Class",
            "Hemilineage",
            "Nerve",
            "Soma side",
            "Primary Cell Type",
            "Alternative Cell Type(s)",
        ],
        connections=connections,
        pre_col="pre_root_id",
        post_col="post_root_id",
        graph_label="banc_626",
    )


def read_threeway_nodes(threeway_csv: Path) -> tuple[list[str], list[dict[str, str]]]:
    with threeway_csv.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or len(reader.fieldnames) < 3:
            raise ValueError(f"unexpected header in {threeway_csv}")
        graphs = reader.fieldnames[:3]
        return graphs, list(reader)


def characterize_module(
    row: dict[str, str],
    graph_name: str,
    nodes: list[int],
    resources: GraphResources,
) -> dict[str, str]:
    node_set = set(nodes)
    metadata_hits = resources.metadata[resources.metadata[resources.id_col].isin(nodes)].copy()
    metadata_found = len(metadata_hits)

    internal_edges = resources.connections[
        resources.connections[resources.pre_col].isin(node_set)
        & resources.connections[resources.post_col].isin(node_set)
    ].copy()
    outgoing_edges = resources.connections[
        resources.connections[resources.pre_col].isin(node_set)
        & ~resources.connections[resources.post_col].isin(node_set)
    ].copy()
    incoming_edges = resources.connections[
        ~resources.connections[resources.pre_col].isin(node_set)
        & resources.connections[resources.post_col].isin(node_set)
    ].copy()

    result = {
        "run_name": Path(row.get("output_dir", "")).name if row.get("output_dir") else "",
        "triplet": row["triplet"],
        "row_index": str(row["row_index"]),
        "sample_size": str(row["sample_size"]),
        "graph_name": graph_name,
        "module_nodes": str(len(nodes)),
        "metadata_rows_found": str(metadata_found),
        "metadata_coverage_ratio": f"{(metadata_found / len(nodes)) if nodes else 0:.6f}",
        "internal_edge_rows": str(len(internal_edges)),
        "outgoing_edge_rows": str(len(outgoing_edges)),
        "incoming_edge_rows": str(len(incoming_edges)),
        "internal_syn_sum": str(int(pd.to_numeric(internal_edges.get("syn_count"), errors="coerce").fillna(0).sum())),
        "outgoing_syn_sum": str(int(pd.to_numeric(outgoing_edges.get("syn_count"), errors="coerce").fillna(0).sum())),
        "incoming_syn_sum": str(int(pd.to_numeric(incoming_edges.get("syn_count"), errors="coerce").fillna(0).sum())),
        "top_internal_neuropils": counter_to_string(safe_counter(internal_edges.get("neuropil", pd.Series(dtype=object)))),
        "top_internal_nt_types": counter_to_string(safe_counter(internal_edges.get("nt_type", pd.Series(dtype=object)))),
        "top_outgoing_neuropils": counter_to_string(safe_counter(outgoing_edges.get("neuropil", pd.Series(dtype=object)))),
        "top_incoming_neuropils": counter_to_string(safe_counter(incoming_edges.get("neuropil", pd.Series(dtype=object)))),
    }

    for field in resources.metadata_fields:
        if field in metadata_hits.columns:
            result[f"top_{field.lower().replace(' ', '_').replace('(', '').replace(')', '').replace('/', '_')}"] = counter_to_string(
                safe_counter(metadata_hits[field])
            )
        else:
            result[f"top_{field.lower().replace(' ', '_').replace('(', '').replace(')', '').replace('/', '_')}"] = ""
    return result


def build_rollup(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[(row["run_name"], row["graph_name"])].append(row)

    rollup: list[dict[str, str]] = []
    for (run_name, graph_name), items in grouped.items():
        module_nodes = [int(item["module_nodes"]) for item in items]
        internal_edge_rows = [int(item["internal_edge_rows"]) for item in items]
        internal_syn_sum = [int(item["internal_syn_sum"]) for item in items]
        rollup.append(
            {
                "run_name": run_name,
                "graph_name": graph_name,
                "modules": str(len(items)),
                "module_nodes_min": str(min(module_nodes)),
                "module_nodes_median": str(pd.Series(module_nodes).median()),
                "module_nodes_max": str(max(module_nodes)),
                "internal_edge_rows_median": str(pd.Series(internal_edge_rows).median()),
                "internal_syn_sum_median": str(pd.Series(internal_syn_sum).median()),
            }
        )
    return rollup


def main() -> int:
    args = parse_args()
    stats_csv = args.stats_csv or (args.output_dir / "threeway_isomorphic_stats_ignore_self_loops.csv")
    output_prefix = args.output_prefix or (args.output_dir / "banc_fafb_module_characterization")

    stats_df = pd.read_csv(stats_csv)
    stats_df["output_dir"] = str(args.output_dir)

    resources = {
        "fafb_783": load_fafb_resources(args.fafb_dir),
        "banc_626": load_banc_resources(args.banc_dir),
    }

    characterization_rows: list[dict[str, str]] = []

    for row in stats_df.to_dict(orient="records"):
        threeway_csv = Path(row["threeway_csv"])
        if not threeway_csv.exists():
            threeway_csv = args.output_dir / "threeway_node_triplets" / threeway_csv.name
        graphs, records = read_threeway_nodes(threeway_csv)
        for graph_name in graphs:
            if graph_name not in TARGET_GRAPHS:
                continue
            nodes = [int(record[graph_name]) for record in records]
            characterization_rows.append(
                characterize_module(row, graph_name, nodes, resources[graph_name])
            )

    if not characterization_rows:
        raise SystemExit("no banc/fafb modules found in the input stats CSV")

    detail_csv = output_prefix.with_suffix(".csv")
    rollup_csv = output_prefix.with_name(output_prefix.name + ".rollup.csv")
    summary_json = output_prefix.with_suffix(".json")

    detail_df = pd.DataFrame(characterization_rows)
    detail_df.to_csv(detail_csv, index=False)

    rollup_rows = build_rollup(characterization_rows)
    pd.DataFrame(rollup_rows).to_csv(rollup_csv, index=False)

    summary = {
        "rows_written": len(characterization_rows),
        "runs": sorted(set(detail_df["run_name"])),
        "graphs": sorted(set(detail_df["graph_name"])),
        "detail_csv": str(detail_csv),
        "rollup_csv": str(rollup_csv),
    }
    summary_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    print(f"Wrote {detail_csv}")
    print(f"Wrote {rollup_csv}")
    print(f"Wrote {summary_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
