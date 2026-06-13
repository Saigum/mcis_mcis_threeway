#!/usr/bin/env python3
"""Build a biological narrative report for the FAFB largest-component recurrent core."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCC_SUMMARY = ROOT / "outputs" / "high_degree_bfs_20K" / "largest_component_source_hub_analysis" / "fafb_783_scc_summary.csv"
CLASSIFICATION = ROOT / "fafb" / "fafb_classification.csv"
CELL_TYPES = ROOT / "fafb" / "fafb_consolidated_cell_types.csv"
OUTPUT_DIR = ROOT / "outputs" / "high_degree_bfs_20K" / "fafb_recurrent_mesoscale_report"
PLOTS_DIR = OUTPUT_DIR / "plots"


def load_role_table() -> pd.DataFrame:
    scc = pd.read_csv(SCC_SUMMARY)
    core_id = int(scc.sort_values("size", ascending=False).iloc[0]["scc_id"])
    rows = []
    for row in scc[
        ["scc_id", "members", "is_source_like_hub", "dag_indegree", "dag_outdegree", "dag_level", "size"]
    ].itertuples(index=False):
        members = [int(node) for node in str(row.members).split() if node]
        for node in members:
            rows.append(
                {
                    "root_id": node,
                    "scc_id": int(row.scc_id),
                    "is_source_like_hub": bool(row.is_source_like_hub),
                    "dag_indegree": int(row.dag_indegree),
                    "dag_outdegree": int(row.dag_outdegree),
                    "dag_level": int(row.dag_level),
                    "scc_size": int(row.size),
                }
            )
    node_roles = pd.DataFrame(rows)
    node_roles["role"] = "intermediate"
    node_roles.loc[node_roles["scc_id"] == core_id, "role"] = "recurrent_core"
    node_roles.loc[
        (node_roles["role"] != "recurrent_core") & (node_roles["is_source_like_hub"]),
        "role",
    ] = "source_hub"
    node_roles.loc[
        (node_roles["role"] == "intermediate")
        & (node_roles["dag_outdegree"] == 0)
        & (node_roles["dag_indegree"] > 0),
        "role",
    ] = "sink"
    return node_roles


def normalize(series: pd.Series) -> pd.Series:
    return series.fillna("untyped").astype(str).replace({"nan": "untyped"})


def attach_annotations(node_roles: pd.DataFrame) -> pd.DataFrame:
    classification = pd.read_csv(CLASSIFICATION)
    cell_types = pd.read_csv(CELL_TYPES)
    df = node_roles.merge(classification, how="left", on="root_id").merge(cell_types, how="left", on="root_id")
    for col in ["primary_type", "super_class", "class", "sub_class", "flow", "side", "hemilineage", "nerve"]:
        if col in df.columns:
            df[col] = normalize(df[col])
    return df


def compute_enrichment(df: pd.DataFrame, role: str, column: str, min_role_count: int = 3) -> pd.DataFrame:
    baseline = df[column].value_counts()
    sub = df[df["role"] == role][column].value_counts()
    rows = []
    for label, role_count in sub.items():
        if int(role_count) < min_role_count:
            continue
        bg_count = int(baseline.get(label, 0))
        role_frac = float(role_count) / max(len(df[df["role"] == role]), 1)
        bg_frac = float(bg_count) / max(len(df), 1)
        fold = role_frac / bg_frac if bg_frac else float("inf")
        rows.append(
            {
                "role": role,
                "annotation": label,
                "role_count": int(role_count),
                "background_count": bg_count,
                "role_fraction": round(role_frac, 4),
                "background_fraction": round(bg_frac, 4),
                "fold_enrichment": round(fold, 4),
            }
        )
    return (
        pd.DataFrame(rows)
        .sort_values(["fold_enrichment", "role_count", "annotation"], ascending=[False, False, True])
        .reset_index(drop=True)
    )


def markdown_table(df: pd.DataFrame, columns: list[str], max_rows: int = 12) -> str:
    shown = df[columns].head(max_rows).copy()
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join(["---"] * len(columns)) + " |"
    lines = [header, sep]
    for row in shown.itertuples(index=False, name=None):
        vals = [str(v) for v in row]
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def top_counts(df: pd.DataFrame, role: str, column: str, top_n: int = 12) -> pd.DataFrame:
    sub = df[df["role"] == role][column].value_counts().reset_index()
    sub.columns = [column, "count"]
    return sub.head(top_n)


def role_order() -> list[str]:
    return ["source_hub", "recurrent_core", "intermediate", "sink"]


def role_colors() -> dict[str, str]:
    return {
        "source_hub": "#d95f02",
        "recurrent_core": "#1b9e77",
        "intermediate": "#7570b3",
        "sink": "#e7298a",
    }


def draw_role_counts(df: pd.DataFrame, out_path: Path) -> None:
    counts = df["role"].value_counts().reindex(role_order(), fill_value=0)
    colors = [role_colors()[role] for role in counts.index]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    bars = ax.bar(counts.index, counts.values, color=colors)
    ax.set_title("FAFB Largest Component Role Sizes")
    ax.set_ylabel("Cells")
    ax.set_xlabel("Role")
    ax.grid(axis="y", alpha=0.25)
    for bar, value in zip(bars, counts.values):
        ax.text(bar.get_x() + bar.get_width() / 2, value, f"{int(value)}", ha="center", va="bottom", fontsize=9)
    fig.tight_layout()
    fig.savefig(out_path, dpi=180)
    plt.close(fig)


def draw_role_superclass(df: pd.DataFrame, out_path: Path) -> None:
    counts = (
        df.groupby(["role", "super_class"]).size().reset_index(name="count")
        .pivot(index="role", columns="super_class", values="count")
        .fillna(0)
        .reindex(role_order())
    )
    major_cols = counts.sum(axis=0).sort_values(ascending=False).head(5).index.tolist()
    other = counts.drop(columns=major_cols, errors="ignore").sum(axis=1)
    plot_df = counts[major_cols].copy()
    if other.sum() > 0:
        plot_df["other"] = other
    fig, ax = plt.subplots(figsize=(9, 5))
    bottom = pd.Series(0, index=plot_df.index, dtype="float64")
    palette = ["#4daf4a", "#377eb8", "#984ea3", "#ff7f00", "#a65628", "#999999"]
    for color, column in zip(palette, plot_df.columns):
        ax.bar(plot_df.index, plot_df[column].values, bottom=bottom.values, label=column, color=color)
        bottom += plot_df[column]
    ax.set_title("Role Composition by FAFB Super Class")
    ax.set_ylabel("Cells")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(loc="upper right", fontsize=8, frameon=True)
    fig.tight_layout()
    fig.savefig(out_path, dpi=180)
    plt.close(fig)


def draw_role_primary_types(df: pd.DataFrame, out_path: Path) -> None:
    selected_types = ["T4b", "T5b", "T4d", "T5c", "Tm9", "T5d", "T2", "Tm3", "Li06", "Mi1"]
    counts = (
        df[df["primary_type"].isin(selected_types)]
        .groupby(["role", "primary_type"]).size().reset_index(name="count")
        .pivot(index="role", columns="primary_type", values="count")
        .fillna(0)
        .reindex(role_order(), fill_value=0)
    )
    fig, ax = plt.subplots(figsize=(10, 5.5))
    bottom = pd.Series(0, index=counts.index, dtype="float64")
    cmap = plt.get_cmap("tab10")
    for idx, column in enumerate(counts.columns):
        ax.bar(counts.index, counts[column].values, bottom=bottom.values, label=column, color=cmap(idx % 10))
        bottom += counts[column]
    ax.set_title("Role Composition Across Key FAFB Primary Types")
    ax.set_ylabel("Cells")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(loc="upper right", fontsize=8, ncol=2, frameon=True)
    fig.tight_layout()
    fig.savefig(out_path, dpi=180)
    plt.close(fig)


def draw_backbone_schematic(df: pd.DataFrame, out_path: Path) -> None:
    counts = df["role"].value_counts()
    core_top = ", ".join(top_counts(df, "recurrent_core", "primary_type", top_n=5)["primary_type"].tolist())
    source_top = ", ".join(top_counts(df, "source_hub", "primary_type", top_n=4)["primary_type"].tolist())
    sink_top = ", ".join(top_counts(df, "sink", "primary_type", top_n=5)["primary_type"].tolist())

    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    boxes = {
        "source_hub": (0.06, 0.28, 0.22, 0.44),
        "recurrent_core": (0.39, 0.18, 0.24, 0.64),
        "sink": (0.74, 0.28, 0.20, 0.44),
    }
    labels = {
        "source_hub": f"Source-Hub Feeders\n{int(counts.get('source_hub', 0))} cells\nTop: {source_top}\nEnriched: visual_projection,\nvisual_centrifugal",
        "recurrent_core": f"Recurrent Optic Core\n{int(counts.get('recurrent_core', 0))} cells\nTop: {core_top}\nEntirely optic super-class",
        "sink": f"Sink Readouts\n{int(counts.get('sink', 0))} cells\nTop: {sink_top}\nEnriched: T5d, T2, Li06,\nLC/LPLC-like readouts",
    }
    for role, (x, y, w, h) in boxes.items():
        rect = Rectangle((x, y), w, h, facecolor=role_colors()[role], alpha=0.18, edgecolor=role_colors()[role], linewidth=2)
        ax.add_patch(rect)
        ax.text(x + w / 2, y + h / 2, labels[role], ha="center", va="center", fontsize=10)

    arrows = [
        ((0.28, 0.5), (0.39, 0.5), "feed / modulation"),
        ((0.63, 0.5), (0.74, 0.5), "downstream readout"),
    ]
    for start, end, text in arrows:
        patch = FancyArrowPatch(start, end, arrowstyle="simple", mutation_scale=18, color="#444444", alpha=0.8)
        ax.add_patch(patch)
        ax.text((start[0] + end[0]) / 2, 0.57, text, ha="center", va="bottom", fontsize=10)

    ax.text(
        0.5,
        0.05,
        "Biological interpretation: a motion-vision dominated recurrent mesoscale core with small feeder hubs and multiple output branches.",
        ha="center",
        va="center",
        fontsize=11,
        weight="bold",
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=180)
    plt.close(fig)


def build_plots(df: pd.DataFrame, plots_dir: Path) -> None:
    plots_dir.mkdir(parents=True, exist_ok=True)
    draw_role_counts(df, plots_dir / "role_counts.png")
    draw_role_superclass(df, plots_dir / "role_super_class_stacked.png")
    draw_role_primary_types(df, plots_dir / "role_primary_types_stacked.png")
    draw_backbone_schematic(df, plots_dir / "backbone_schematic.png")


def build_report(df: pd.DataFrame, output_dir: Path) -> None:
    role_counts = df["role"].value_counts().rename_axis("role").reset_index(name="cells")
    role_counts.to_csv(output_dir / "role_counts.csv", index=False)

    enrichment_tables = {}
    for role in ["recurrent_core", "source_hub", "sink", "intermediate"]:
        for column in ["primary_type", "super_class", "sub_class"]:
            enr = compute_enrichment(df, role, column)
            enrichment_tables[(role, column)] = enr
            enr.to_csv(output_dir / f"enrichment_{role}_{column}.csv", index=False)

    # Save node-level roles for inspection.
    df.sort_values(["role", "scc_id", "root_id"]).to_csv(output_dir / "fafb_node_roles.csv", index=False)
    build_plots(df, PLOTS_DIR)

    lines = [
        "# FAFB Recurrent Mesoscale Network Report",
        "",
        "This report injects biological annotation into the FAFB largest weak-component structure by separating nodes into `recurrent_core`, `source_hub`, `sink`, and `intermediate` roles.",
        "",
        "Role definitions:",
        "- `recurrent_core`: the largest SCC after condensation.",
        "- `source_hub`: source-like SCCs outside the core with more outgoing than incoming DAG connectivity.",
        "- `sink`: non-core, non-source SCCs with zero DAG outdegree.",
        "- `intermediate`: everything else.",
        "",
        "## Role Counts",
        "",
        markdown_table(role_counts, ["role", "cells"], max_rows=10),
        "",
        "![Role counts](plots/role_counts.png)",
        "",
        "![Role composition by super class](plots/role_super_class_stacked.png)",
        "",
        "![Role composition across key primary types](plots/role_primary_types_stacked.png)",
        "",
        "![Backbone schematic](plots/backbone_schematic.png)",
        "",
        "## Biological Narrative",
        "",
        "The component is best interpreted as a recurrent optic-lobe mesoscale network rather than a feedforward hierarchy.",
        "",
        "Primary inference:",
        "- The recurrent core is entirely `optic` super-class and strongly dominated by `T4`/`T5` motion-channel neurons, with additional `Tm9` transmedullary participation.",
        "- Source-like hub SCCs are small, peripheral feeders rather than a second large control core; they are disproportionately enriched for `visual_projection` and `visual_centrifugal` identities relative to the full component.",
        "- Sink-side SCCs are enriched for `T5d`, `T2`, `Li06`, and some `LC` / `LPLC` output-associated types, which is consistent with downstream readout branches emerging from the recurrent optic core.",
        "",
        "In short: this looks like a motion-vision dominated recurrent processing core with a small set of feeder hubs and multiple output branches, not a deep command hierarchy.",
        "",
        "## Core Composition",
        "",
        "Top primary types in the recurrent core:",
        "",
        markdown_table(top_counts(df, "recurrent_core", "primary_type"), ["primary_type", "count"]),
        "",
        "Top sub-classes in the recurrent core:",
        "",
        markdown_table(top_counts(df, "recurrent_core", "sub_class"), ["sub_class", "count"]),
        "",
        "Core-enriched primary types:",
        "",
        markdown_table(
            enrichment_tables[("recurrent_core", "primary_type")],
            ["annotation", "role_count", "role_fraction", "background_fraction", "fold_enrichment"],
        ),
        "",
        "## Source-Hub Feeders",
        "",
        "Top source-hub primary types:",
        "",
        markdown_table(top_counts(df, "source_hub", "primary_type"), ["primary_type", "count"]),
        "",
        "Source-hub enriched super-classes:",
        "",
        markdown_table(
            enrichment_tables[("source_hub", "super_class")],
            ["annotation", "role_count", "role_fraction", "background_fraction", "fold_enrichment"],
        ),
        "",
        "Source-hub enriched primary types:",
        "",
        markdown_table(
            enrichment_tables[("source_hub", "primary_type")],
            ["annotation", "role_count", "role_fraction", "background_fraction", "fold_enrichment"],
        ),
        "",
        "Interpretation:",
        "- `Tm3` is the clearest source-hub-enriched primary type in this component.",
        "- `visual_projection` and `visual_centrifugal` classes are overrepresented among source hubs relative to the component baseline, suggesting feeder and modulatory entry points into the optic recurrent core.",
        "",
        "## Sink-Side Outputs",
        "",
        "Top sink primary types:",
        "",
        markdown_table(top_counts(df, "sink", "primary_type"), ["primary_type", "count"]),
        "",
        "Sink-enriched primary types:",
        "",
        markdown_table(
            enrichment_tables[("sink", "primary_type")],
            ["annotation", "role_count", "role_fraction", "background_fraction", "fold_enrichment"],
        ),
        "",
        "Sink-enriched super-classes:",
        "",
        markdown_table(
            enrichment_tables[("sink", "super_class")],
            ["annotation", "role_count", "role_fraction", "background_fraction", "fold_enrichment"],
        ),
        "",
        "Interpretation:",
        "- Sink-side SCCs are especially enriched for `T5d`, `T2`, `Li06`, and selected `LC`/`LPLC` identities.",
        "- That pattern is consistent with the recurrent optic core projecting into downstream visual readout branches rather than simply recirculating internally.",
        "",
        "## Intermediate Layer",
        "",
        "Top intermediate primary types:",
        "",
        markdown_table(top_counts(df, "intermediate", "primary_type"), ["primary_type", "count"]),
        "",
        "Top intermediate sub-classes:",
        "",
        markdown_table(top_counts(df, "intermediate", "sub_class"), ["sub_class", "count"]),
        "",
        "Interpretation:",
        "- Intermediates are strongly represented by `Mi1` and other medulla/transmedullary classes, which fits a bridge layer between optic feedforward pathways and the recurrent motion core.",
        "",
        "## Strong Claim You Can Defend",
        "",
        "A defensible biological claim from this component is:",
        "",
        "> The FAFB largest weak component in the `high_degree_bfs_20K` triplet is organized around a single large recurrent optic-lobe core, dominated by T4/T5 motion circuitry, with smaller projection-like and centrifugal feeder hubs and multiple downstream readout branches.",
        "",
        "That is stronger and more specific than saying the component merely contains high-degree hubs.",
        "",
    ]
    (output_dir / "REPORT.md").write_text("\n".join(lines))


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    role_df = load_role_table()
    annotated = attach_annotations(role_df)
    build_report(annotated, OUTPUT_DIR)
    print(f"Wrote {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
