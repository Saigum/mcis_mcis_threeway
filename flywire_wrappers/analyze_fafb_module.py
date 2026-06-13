#!/usr/bin/env python3
"""Analyze an FAFB module from a newline-separated node list."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib.pyplot as plt
import networkx as nx
import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("node_list", type=Path, help="Path to newline-separated FAFB node IDs")
    parser.add_argument("--fafb-dir", type=Path, default=Path("fafb"))
    parser.add_argument(
        "--outdir",
        type=Path,
        default=None,
        help="Output directory. Defaults to a sibling folder next to the node list.",
    )
    return parser.parse_args()


def default_outdir(node_list: Path) -> Path:
    return node_list.parent / "fafb_module_analysis"


def load_node_list(path: Path) -> list[int]:
    return [int(line.strip()) for line in path.read_text().splitlines() if line.strip()]


def load_metadata(fafb_dir: Path) -> pd.DataFrame:
    classification = pd.read_csv(fafb_dir / "fafb_classification.csv")
    cell_types = pd.read_csv(fafb_dir / "fafb_consolidated_cell_types.csv")
    cell_stats = pd.read_csv(fafb_dir / "cell_stats.csv")
    return classification.merge(cell_types, how="left", on="root_id").merge(cell_stats, how="left", on="root_id")


def top_counts(series: pd.Series, limit: int = 10) -> dict[str, int]:
    values = [
        str(value)
        for value in series.dropna()
        if str(value).strip() and str(value).strip().lower() != "nan"
    ]
    return {key: int(value) for key, value in pd.Series(values).value_counts().head(limit).items()}


def summarize_numeric(series: pd.Series) -> dict[str, float | int | None]:
    series = pd.to_numeric(series, errors="coerce").dropna()
    if series.empty:
        return {"min": None, "median": None, "mean": None, "max": None}
    return {
        "min": float(series.min()),
        "median": float(series.median()),
        "mean": float(series.mean()),
        "max": float(series.max()),
    }


def build_graph(edges: pd.DataFrame) -> nx.DiGraph:
    grouped = (
        edges.groupby(["pre_root_id", "post_root_id"], as_index=False)
        .agg(
            syn_count=("syn_count", "sum"),
            edge_rows=("syn_count", "size"),
            dominant_nt_type=("nt_type", lambda s: s.dropna().astype(str).mode().iloc[0] if not s.dropna().empty else ""),
            dominant_neuropil=("neuropil", lambda s: s.dropna().astype(str).mode().iloc[0] if not s.dropna().empty else ""),
        )
    )
    graph = nx.DiGraph()
    for row in grouped.itertuples(index=False):
        graph.add_edge(
            int(row.pre_root_id),
            int(row.post_root_id),
            syn_count=int(row.syn_count),
            edge_rows=int(row.edge_rows),
            nt_type=row.dominant_nt_type,
            neuropil=row.dominant_neuropil,
        )
    return graph


def color_map_for_nodes(node_annotations: pd.DataFrame) -> tuple[list[str], dict[str, str]]:
    palette = [
        "#1f77b4",
        "#ff7f0e",
        "#2ca02c",
        "#d62728",
        "#9467bd",
        "#8c564b",
        "#e377c2",
        "#7f7f7f",
        "#bcbd22",
        "#17becf",
    ]
    label_series = node_annotations["primary_type"].fillna(node_annotations["sub_class"]).fillna("untyped").astype(str)
    top_labels = list(label_series.value_counts().head(8).index)
    label_to_color: dict[str, str] = {"other": "#cccccc"}
    for idx, label in enumerate(top_labels):
        label_to_color[label] = palette[idx % len(palette)]
    colors = [label_to_color[label] if label in label_to_color else label_to_color["other"] for label in label_series]
    return colors, label_to_color


def save_graph_plot(
    graph: nx.DiGraph,
    node_annotations: pd.DataFrame,
    out_path: Path,
) -> None:
    undirected = graph.to_undirected()
    pos = nx.spring_layout(undirected, seed=7, k=0.22, iterations=200)

    weighted_degree = dict(graph.degree(weight="syn_count"))
    sizes = [16 + 4 * (weighted_degree.get(node, 0) ** 0.35) for node in graph.nodes()]

    annotations = node_annotations.set_index("root_id").reindex(list(graph.nodes())).reset_index()
    colors, label_to_color = color_map_for_nodes(annotations)

    fig, ax = plt.subplots(figsize=(24, 24))
    nx.draw_networkx_edges(
        graph,
        pos,
        ax=ax,
        alpha=0.08,
        arrows=False,
        width=[0.2 + 0.08 * (graph[u][v]["syn_count"] ** 0.35) for u, v in graph.edges()],
        edge_color="#444444",
    )
    nx.draw_networkx_nodes(
        graph,
        pos,
        ax=ax,
        node_size=sizes,
        node_color=colors,
        linewidths=0,
        alpha=0.9,
    )
    ax.set_title("FAFB Largest High-Degree MCIS Module", fontsize=24)
    ax.axis("off")

    handles = [
        plt.Line2D([0], [0], marker="o", color="w", label=label, markerfacecolor=color, markersize=10)
        for label, color in label_to_color.items()
    ]
    ax.legend(handles=handles, loc="upper right", frameon=True, title="Primary Type / Subclass")
    fig.tight_layout()
    fig.savefig(out_path, dpi=250, bbox_inches="tight")
    plt.close(fig)


def save_summary_plots(
    metadata_hits: pd.DataFrame,
    internal_edge_rows: pd.DataFrame,
    graph: nx.DiGraph,
    out_path: Path,
) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))

    top_primary = metadata_hits["primary_type"].fillna("untyped").astype(str).value_counts().head(12)
    axes[0, 0].barh(list(reversed(top_primary.index)), list(reversed(top_primary.values)))
    axes[0, 0].set_title("Top Primary Types")

    top_subclass = metadata_hits["sub_class"].fillna("untyped").astype(str).value_counts().head(12)
    axes[0, 1].barh(list(reversed(top_subclass.index)), list(reversed(top_subclass.values)))
    axes[0, 1].set_title("Top Subclasses")

    neuropil_syn = (
        internal_edge_rows.groupby("neuropil", dropna=False)["syn_count"].sum().sort_values(ascending=False).head(12)
    )
    axes[1, 0].barh(
        list(reversed([str(x) for x in neuropil_syn.index])),
        list(reversed(neuropil_syn.values)),
    )
    axes[1, 0].set_title("Internal Synapses by Neuropil")

    weighted_degree = pd.Series(dict(graph.degree(weight="syn_count"))).sort_values(ascending=False)
    axes[1, 1].hist(weighted_degree.values, bins=24, color="#4c78a8", alpha=0.8)
    axes[1, 1].set_title("Weighted Degree Distribution")
    axes[1, 1].set_xlabel("Weighted degree")

    fig.tight_layout()
    fig.savefig(out_path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    args = parse_args()
    node_list = args.node_list
    outdir = args.outdir or default_outdir(node_list)
    outdir.mkdir(parents=True, exist_ok=True)

    nodes = load_node_list(node_list)
    node_set = set(nodes)

    metadata = load_metadata(args.fafb_dir)
    metadata_hits = metadata[metadata["root_id"].isin(node_set)].copy()

    connections = pd.read_csv(args.fafb_dir / "connections_princeton.csv")
    internal_edge_rows = connections[
        connections["pre_root_id"].isin(node_set) & connections["post_root_id"].isin(node_set)
    ].copy()
    outgoing_edge_rows = connections[
        connections["pre_root_id"].isin(node_set) & ~connections["post_root_id"].isin(node_set)
    ].copy()
    incoming_edge_rows = connections[
        ~connections["pre_root_id"].isin(node_set) & connections["post_root_id"].isin(node_set)
    ].copy()

    graph = build_graph(internal_edge_rows)
    graph.add_nodes_from(nodes)

    weak_components = sorted((len(c) for c in nx.weakly_connected_components(graph)), reverse=True)
    strong_components = sorted((len(c) for c in nx.strongly_connected_components(graph)), reverse=True)
    undirected = graph.to_undirected()

    weighted_degree = pd.Series(dict(graph.degree(weight="syn_count")), name="weighted_degree")
    in_weighted = pd.Series(dict(graph.in_degree(weight="syn_count")), name="in_weighted_degree")
    out_weighted = pd.Series(dict(graph.out_degree(weight="syn_count")), name="out_weighted_degree")
    top_hubs = (
        pd.DataFrame({
            "root_id": weighted_degree.index.astype("int64"),
            "weighted_degree": weighted_degree.values,
            "in_weighted_degree": in_weighted.reindex(weighted_degree.index).values,
            "out_weighted_degree": out_weighted.reindex(weighted_degree.index).values,
        })
        .merge(metadata_hits[["root_id", "class", "sub_class", "primary_type", "side"]], how="left", on="root_id")
        .sort_values("weighted_degree", ascending=False)
        .head(25)
    )

    summary = {
        "node_list": str(node_list),
        "module_nodes": len(nodes),
        "metadata_rows_found": int(len(metadata_hits)),
        "metadata_coverage_ratio": len(metadata_hits) / max(1, len(nodes)),
        "internal_connection_rows": int(len(internal_edge_rows)),
        "internal_unique_directed_edges": int(graph.number_of_edges()),
        "internal_total_synapses": int(pd.to_numeric(internal_edge_rows["syn_count"], errors="coerce").fillna(0).sum()),
        "outgoing_connection_rows": int(len(outgoing_edge_rows)),
        "incoming_connection_rows": int(len(incoming_edge_rows)),
        "outgoing_total_synapses": int(pd.to_numeric(outgoing_edge_rows["syn_count"], errors="coerce").fillna(0).sum()),
        "incoming_total_synapses": int(pd.to_numeric(incoming_edge_rows["syn_count"], errors="coerce").fillna(0).sum()),
        "density_directed": float(nx.density(graph)),
        "weak_components": len(weak_components),
        "largest_weak_component": int(weak_components[0]) if weak_components else 0,
        "strong_components": len(strong_components),
        "largest_strong_component": int(strong_components[0]) if strong_components else 0,
        "reciprocity": None if graph.number_of_edges() == 0 else float(nx.reciprocity(graph)),
        "average_clustering_undirected": float(nx.average_clustering(undirected)) if undirected.number_of_edges() else 0.0,
        "top_flow": top_counts(metadata_hits["flow"]),
        "top_super_class": top_counts(metadata_hits["super_class"]),
        "top_class": top_counts(metadata_hits["class"]),
        "top_sub_class": top_counts(metadata_hits["sub_class"]),
        "top_primary_type": top_counts(metadata_hits["primary_type"]),
        "top_side": top_counts(metadata_hits["side"]),
        "top_internal_neuropils_by_synapses": (
            internal_edge_rows.groupby("neuropil", dropna=False)["syn_count"]
            .sum()
            .sort_values(ascending=False)
            .head(15)
            .to_dict()
        ),
        "top_internal_nt_types": top_counts(internal_edge_rows["nt_type"]),
        "length_nm": summarize_numeric(metadata_hits["length_nm"]),
        "area_nm": summarize_numeric(metadata_hits["area_nm"]),
        "size_nm": summarize_numeric(metadata_hits["size_nm"]),
    }

    summary_path = outdir / "fafb_module_summary.json"
    node_annotations_path = outdir / "fafb_module_node_annotations.csv"
    internal_edges_path = outdir / "fafb_module_internal_edges.csv"
    top_hubs_path = outdir / "fafb_module_top_hubs.csv"
    graph_plot_path = outdir / "fafb_module_graph.png"
    summary_plot_path = outdir / "fafb_module_summary_plots.png"

    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    metadata_hits.to_csv(node_annotations_path, index=False)
    internal_edge_rows.to_csv(internal_edges_path, index=False)
    top_hubs.to_csv(top_hubs_path, index=False)
    save_graph_plot(graph, metadata_hits, graph_plot_path)
    save_summary_plots(metadata_hits, internal_edge_rows, graph, summary_plot_path)

    print(f"Wrote {summary_path}")
    print(f"Wrote {node_annotations_path}")
    print(f"Wrote {internal_edges_path}")
    print(f"Wrote {top_hubs_path}")
    print(f"Wrote {graph_plot_path}")
    print(f"Wrote {summary_plot_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
