#!/usr/bin/env python3
"""Analyze source-like hierarchical structure in the saved largest weak component."""

from __future__ import annotations

import json
from pathlib import Path

import networkx as nx
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
COMPONENT_DIR = ROOT / "outputs" / "high_degree_bfs_20K" / "largest_weak_component_triplet" / "banc_626__fafb_783__mcns_0.9"
OUTPUT_DIR = ROOT / "outputs" / "high_degree_bfs_20K" / "largest_component_source_hub_analysis"

EDGE_PATHS = {
    "banc_626": Path("/home/saigum/Desktop/flywire_codex/data/raw_graphs/banc_626_edge_list.csv"),
    "fafb_783": Path("/home/saigum/Desktop/flywire_codex/data/raw_graphs/fafb_783_edge_list.csv"),
    "mcns_0.9": ROOT / "raw_graphs" / "mcns_0.9_edge_list.csv",
}


def load_metadata() -> dict:
    return json.loads((COMPONENT_DIR / "metadata.json").read_text())


def load_component_nodes(graph_name: str) -> list[int]:
    path = COMPONENT_DIR / f"{graph_name}_nodes.txt"
    return [int(line.strip()) for line in path.read_text().splitlines() if line.strip()]


def load_induced_edges(edge_csv: Path, node_ids: list[int], chunksize: int = 500_000) -> pd.DataFrame:
    node_set = set(node_ids)
    kept: list[pd.DataFrame] = []
    for chunk in pd.read_csv(edge_csv, usecols=[0, 1], chunksize=chunksize):
        src = chunk.iloc[:, 0].astype("int64")
        dst = chunk.iloc[:, 1].astype("int64")
        mask = src.isin(node_set) & dst.isin(node_set)
        if not mask.any():
            continue
        kept.append(
            pd.DataFrame(
                {
                    "source": src[mask].to_numpy(),
                    "target": dst[mask].to_numpy(),
                }
            )
        )
    if not kept:
        return pd.DataFrame(columns=["source", "target"])
    return pd.concat(kept, ignore_index=True)


def dag_levels(condensation: nx.DiGraph) -> dict[int, int]:
    order = list(nx.topological_sort(condensation))
    level: dict[int, int] = {}
    for node in order:
        preds = list(condensation.predecessors(node))
        level[node] = 0 if not preds else 1 + max(level[pred] for pred in preds)
    return level


def analyze_graph(graph_name: str, node_ids: list[int]) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    edges = load_induced_edges(EDGE_PATHS[graph_name], node_ids)

    graph = nx.DiGraph()
    graph.add_nodes_from(node_ids)
    graph.add_edges_from(edges[["source", "target"]].itertuples(index=False, name=None))

    sccs = list(nx.strongly_connected_components(graph))
    node_to_scc: dict[int, int] = {}
    for scc_id, members in enumerate(sccs):
        for node in members:
            node_to_scc[node] = scc_id

    edges = edges.copy()
    edges["source_scc"] = edges["source"].map(node_to_scc)
    edges["target_scc"] = edges["target"].map(node_to_scc)

    internal_edges = int((edges["source_scc"] == edges["target_scc"]).sum())
    external_edges = edges[edges["source_scc"] != edges["target_scc"]].copy()
    condensed_edge_df = (
        external_edges[["source_scc", "target_scc"]]
        .drop_duplicates()
        .rename(columns={"source_scc": "source", "target_scc": "target"})
        .sort_values(["source", "target"])
        .reset_index(drop=True)
    )
    collapsed_parallel_edges = len(external_edges) - len(condensed_edge_df)

    condensation = nx.DiGraph()
    condensation.add_nodes_from(range(len(sccs)))
    condensation.add_edges_from(condensed_edge_df.itertuples(index=False, name=None))

    levels = dag_levels(condensation)
    scc_rows = []
    for scc_id, members in enumerate(sccs):
        member_list = sorted(int(node) for node in members)
        scc_rows.append(
            {
                "scc_id": scc_id,
                "size": len(member_list),
                "members": " ".join(str(node) for node in member_list),
                "dag_indegree": int(condensation.in_degree(scc_id)),
                "dag_outdegree": int(condensation.out_degree(scc_id)),
                "dag_level": levels[scc_id],
            }
        )
    scc_df = pd.DataFrame(scc_rows)

    if not external_edges.empty:
        source_external = external_edges.groupby("source_scc").size()
        target_external = external_edges.groupby("target_scc").size()
    else:
        source_external = pd.Series(dtype="int64")
        target_external = pd.Series(dtype="int64")

    internal_by_scc = (
        edges[edges["source_scc"] == edges["target_scc"]]
        .groupby("source_scc")
        .size()
        if internal_edges
        else pd.Series(dtype="int64")
    )

    scc_df["external_out_edges"] = scc_df["scc_id"].map(source_external).fillna(0).astype(int)
    scc_df["external_in_edges"] = scc_df["scc_id"].map(target_external).fillna(0).astype(int)
    scc_df["internal_edges"] = scc_df["scc_id"].map(internal_by_scc).fillna(0).astype(int)
    scc_df["source_like_score"] = (
        scc_df["dag_outdegree"] - scc_df["dag_indegree"]
    ) + (
        scc_df["external_out_edges"] - scc_df["external_in_edges"]
    )
    scc_df["is_source_scc"] = scc_df["dag_indegree"] == 0
    scc_df["is_source_like_hub"] = (
        (scc_df["dag_outdegree"] >= 2)
        & (scc_df["dag_outdegree"] > scc_df["dag_indegree"])
        & (scc_df["external_out_edges"] >= scc_df["external_in_edges"])
    )
    scc_df = scc_df.sort_values(
        ["is_source_like_hub", "source_like_score", "dag_outdegree", "external_out_edges", "size"],
        ascending=[False, False, False, False, False],
    ).reset_index(drop=True)

    summary = {
        "graph_name": graph_name,
        "component_nodes": graph.number_of_nodes(),
        "component_edges": graph.number_of_edges(),
        "scc_count": len(sccs),
        "condensation_nodes": condensation.number_of_nodes(),
        "condensation_edges": condensation.number_of_edges(),
        "internal_edges_removed": internal_edges,
        "parallel_cross_scc_edges_removed": int(collapsed_parallel_edges),
        "total_edges_removed": int(graph.number_of_edges() - condensation.number_of_edges()),
        "dag_sources": sum(1 for node in condensation.nodes if condensation.in_degree(node) == 0),
        "dag_sinks": sum(1 for node in condensation.nodes if condensation.out_degree(node) == 0),
        "dag_longest_path_length": int(nx.dag_longest_path_length(condensation)) if condensation.number_of_nodes() else 0,
        "source_like_hub_sccs": int(scc_df["is_source_like_hub"].sum()),
        "largest_scc_size": int(max((len(scc) for scc in sccs), default=0)),
    }
    return summary, scc_df, condensed_edge_df


def format_summary_table(rows: list[dict]) -> str:
    header = "| graph | nodes | edges | sccs | dag_edges | edges_removed | internal_removed | parallel_removed | dag_sources | longest_path | source_like_hub_sccs |"
    sep = "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
    lines = [header, sep]
    for row in rows:
        lines.append(
            "| {graph_name} | {component_nodes} | {component_edges} | {scc_count} | {condensation_edges} | {total_edges_removed} | {internal_edges_removed} | {parallel_cross_scc_edges_removed} | {dag_sources} | {dag_longest_path_length} | {source_like_hub_sccs} |".format(
                **row
            )
        )
    return "\n".join(lines)


def format_top_hubs(summary: dict, scc_df: pd.DataFrame, top_n: int = 10) -> list[str]:
    cols = [
        "scc_id",
        "size",
        "dag_level",
        "dag_indegree",
        "dag_outdegree",
        "external_in_edges",
        "external_out_edges",
        "internal_edges",
        "source_like_score",
        "members",
    ]
    top = scc_df[scc_df["is_source_like_hub"]].head(top_n)
    lines = [f"### {summary['graph_name']}", ""]
    if top.empty:
        lines.append("No SCCs met the source-like hub rule.")
        lines.append("")
        return lines
    header = "| scc_id | size | level | dag_in | dag_out | ext_in | ext_out | internal | score | members |"
    sep = "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |"
    lines.extend([header, sep])
    for row in top[cols].itertuples(index=False):
        lines.append(
            f"| {row.scc_id} | {row.size} | {row.dag_level} | {row.dag_indegree} | {row.dag_outdegree} | {row.external_in_edges} | {row.external_out_edges} | {row.internal_edges} | {int(row.source_like_score)} | {row.members} |"
        )
    lines.append("")
    return lines


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=False)
    metadata = load_metadata()

    summary_rows: list[dict] = []
    md_lines = [
        "# Largest Component Source-Hub Condensation Analysis",
        "",
        "This analysis uses the saved 1,540-node largest weak-component triplet and computes a directed SCC condensation DAG separately for `banc_626`, `fafb_783`, and `mcns_0.9`.",
        "",
        "Edge-removal accounting:",
        "- `internal_edges_removed`: edges whose endpoints fell inside the same SCC and therefore disappear after SCC collapse.",
        "- `parallel_cross_scc_edges_removed`: repeated cross-SCC edges that collapse into a single DAG edge.",
        "- `total_edges_removed = original_component_edges - condensation_dag_edges`.",
        "",
    ]

    for graph_name in metadata["graphs"]:
        node_ids = load_component_nodes(graph_name)
        summary, scc_df, condensed_edge_df = analyze_graph(graph_name, node_ids)
        summary_rows.append(summary)

        scc_df.to_csv(OUTPUT_DIR / f"{graph_name}_scc_summary.csv", index=False)
        condensed_edge_df.to_csv(OUTPUT_DIR / f"{graph_name}_condensation_edges.csv", index=False)
        with (OUTPUT_DIR / f"{graph_name}_summary.json").open("w") as handle:
            json.dump(summary, handle, indent=2)

        md_lines.extend(format_top_hubs(summary, scc_df))

    (OUTPUT_DIR / "condensation_summary.json").write_text(json.dumps(summary_rows, indent=2))
    md_lines.insert(8, format_summary_table(summary_rows))
    (OUTPUT_DIR / "README.md").write_text("\n".join(md_lines))

    print(f"Wrote analysis to {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
