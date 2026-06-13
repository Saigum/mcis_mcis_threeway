#!/usr/bin/env python3
"""Compute average induced outdegree by cell type for the saved largest component."""

from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
COMPONENT_DIR = ROOT / "outputs" / "high_degree_bfs_20K" / "largest_weak_component_triplet" / "banc_626__fafb_783__mcns_0.9"
OUTPUT_DIR = ROOT / "outputs" / "high_degree_bfs_20K"

BANC_EDGES = Path("/home/saigum/Desktop/flywire_codex/data/raw_graphs/banc_626_edge_list.csv")
FAFB_EDGES = Path("/home/saigum/Desktop/flywire_codex/data/raw_graphs/fafb_783_edge_list.csv")
MCNS_EDGES = ROOT / "raw_graphs" / "mcns_0.9_edge_list.csv"

BANC_TYPES = ROOT / "banc" / "neurons.csv"
FAFB_TYPES = ROOT / "fafb" / "fafb_consolidated_cell_types.csv"


def load_metadata() -> dict:
    return json.loads((COMPONENT_DIR / "metadata.json").read_text())


def load_component_nodes(graph_name: str) -> list[int]:
    path = COMPONENT_DIR / f"{graph_name}_nodes.txt"
    return [int(line.strip()) for line in path.read_text().splitlines() if line.strip()]


def load_triplets(path: Path) -> pd.DataFrame:
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    df = pd.DataFrame(rows)
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    return df


def compute_induced_outdegree(edge_csv: Path, node_ids: list[int], chunksize: int = 500_000) -> pd.Series:
    node_set = set(node_ids)
    counts: dict[int, int] = {node_id: 0 for node_id in node_ids}
    for chunk in pd.read_csv(edge_csv, usecols=[0, 1], chunksize=chunksize):
        src = chunk.iloc[:, 0].astype("int64")
        dst = chunk.iloc[:, 1].astype("int64")
        mask = src.isin(node_set) & dst.isin(node_set)
        if not mask.any():
            continue
        vc = src[mask].value_counts()
        for node_id, value in vc.items():
            counts[int(node_id)] = counts.get(int(node_id), 0) + int(value)
    return pd.Series(counts, name="outdegree", dtype="int64")


def load_banc_types() -> pd.DataFrame:
    df = pd.read_csv(BANC_TYPES, usecols=["Root ID", "Primary Cell Type"])
    return df.rename(columns={"Root ID": "banc_626", "Primary Cell Type": "banc_primary_type"})


def load_fafb_types() -> pd.DataFrame:
    df = pd.read_csv(FAFB_TYPES, usecols=["root_id", "primary_type"])
    return df.rename(columns={"root_id": "fafb_783", "primary_type": "fafb_primary_type"})


def normalize_type(value: object) -> str:
    if value is None:
        return "untyped"
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return "untyped"
    return text


def summarize_by_type(df: pd.DataFrame, type_col: str, degree_col: str) -> pd.DataFrame:
    work = df[[type_col, degree_col]].copy()
    work[type_col] = work[type_col].map(normalize_type)
    grouped = (
        work.groupby(type_col, dropna=False)[degree_col]
        .agg(["count", "mean", "median", "max", "sum"])
        .reset_index()
        .rename(
            columns={
                type_col: "cell_type",
                "count": "cells",
                "mean": "avg_outdegree",
                "median": "median_outdegree",
                "max": "max_outdegree",
                "sum": "total_outdegree",
            }
        )
        .sort_values(["avg_outdegree", "cells", "cell_type"], ascending=[False, False, True])
        .reset_index(drop=True)
    )
    grouped["avg_outdegree"] = grouped["avg_outdegree"].round(4)
    grouped["median_outdegree"] = grouped["median_outdegree"].round(4)
    return grouped


def markdown_table(df: pd.DataFrame, max_rows: int = 20) -> str:
    shown = df.head(max_rows).copy()
    header = "| cell_type | cells | avg_outdegree | median_outdegree | max_outdegree | total_outdegree |"
    sep = "| --- | ---: | ---: | ---: | ---: | ---: |"
    lines = [header, sep]
    for row in shown.itertuples(index=False):
        lines.append(
            f"| {row.cell_type} | {int(row.cells)} | {row.avg_outdegree:.4f} | {row.median_outdegree:.4f} | {int(row.max_outdegree)} | {int(row.total_outdegree)} |"
        )
    return "\n".join(lines)


def filtered_markdown_table(df: pd.DataFrame, min_cells: int, max_rows: int = 15) -> str:
    filtered = df[df["cells"] >= min_cells].copy()
    if filtered.empty:
        return "_No rows matched this filter._"
    return markdown_table(filtered, max_rows=max_rows)


def write_report(
    banc_direct: pd.DataFrame,
    fafb_direct: pd.DataFrame,
    mcns_proxy: pd.DataFrame,
    path: Path,
) -> None:
    lines = [
        "# Largest Component Average Outdegree By Cell Type",
        "",
        "Outdegree here is the induced outdegree inside the 1,540-node largest weak-component triplet node set, computed separately from each dataset's raw edge list.",
        "",
        "MCNS caveat: this workspace does not contain a local MCNS root-id to primary-type table, so the MCNS table is grouped by the paired FAFB `primary_type` from the triplet mapping.",
        "",
        f"Full CSVs: `{OUTPUT_DIR / 'avg_outdegree_by_cell_type_banc.csv'}`, `{OUTPUT_DIR / 'avg_outdegree_by_cell_type_fafb.csv'}`, `{OUTPUT_DIR / 'avg_outdegree_by_cell_type_mcns_by_mapped_fafb_type.csv'}`.",
        "",
        "## BANC",
        "",
        markdown_table(banc_direct),
        "",
        "### BANC Types With At Least 5 Cells",
        "",
        filtered_markdown_table(banc_direct, min_cells=5),
        "",
        "## FAFB",
        "",
        markdown_table(fafb_direct),
        "",
        "### FAFB Types With At Least 5 Cells",
        "",
        filtered_markdown_table(fafb_direct, min_cells=5),
        "",
        "## MCNS (Grouped By Paired FAFB Type)",
        "",
        markdown_table(mcns_proxy),
        "",
        "### MCNS Proxy Types With At Least 5 Cells",
        "",
        filtered_markdown_table(mcns_proxy, min_cells=5),
        "",
    ]
    path.write_text("\n".join(lines))


def main() -> int:
    metadata = load_metadata()
    triplets = load_triplets(ROOT / metadata["threeway_csv"])

    banc_nodes = load_component_nodes("banc_626")
    fafb_nodes = load_component_nodes("fafb_783")
    mcns_nodes = load_component_nodes("mcns_0.9")

    banc_out = compute_induced_outdegree(BANC_EDGES, banc_nodes)
    fafb_out = compute_induced_outdegree(FAFB_EDGES, fafb_nodes)
    mcns_out = compute_induced_outdegree(MCNS_EDGES, mcns_nodes)

    triplets = triplets[
        triplets["banc_626"].isin(banc_nodes)
        & triplets["fafb_783"].isin(fafb_nodes)
        & triplets["mcns_0.9"].isin(mcns_nodes)
    ].copy()

    triplets["banc_outdegree"] = triplets["banc_626"].map(banc_out).fillna(0).astype(int)
    triplets["fafb_outdegree"] = triplets["fafb_783"].map(fafb_out).fillna(0).astype(int)
    triplets["mcns_outdegree"] = triplets["mcns_0.9"].map(mcns_out).fillna(0).astype(int)

    triplets = triplets.merge(load_banc_types(), how="left", on="banc_626")
    triplets = triplets.merge(load_fafb_types(), how="left", on="fafb_783")

    banc_direct = summarize_by_type(triplets, "banc_primary_type", "banc_outdegree")
    fafb_direct = summarize_by_type(triplets, "fafb_primary_type", "fafb_outdegree")
    mcns_proxy = summarize_by_type(triplets, "fafb_primary_type", "mcns_outdegree")

    banc_csv = OUTPUT_DIR / "avg_outdegree_by_cell_type_banc.csv"
    fafb_csv = OUTPUT_DIR / "avg_outdegree_by_cell_type_fafb.csv"
    mcns_csv = OUTPUT_DIR / "avg_outdegree_by_cell_type_mcns_by_mapped_fafb_type.csv"
    report_md = OUTPUT_DIR / "largest_component_outdegree_by_cell_type.md"

    banc_direct.to_csv(banc_csv, index=False)
    fafb_direct.to_csv(fafb_csv, index=False)
    mcns_proxy.to_csv(mcns_csv, index=False)
    write_report(banc_direct, fafb_direct, mcns_proxy, report_md)

    print(f"Wrote {banc_csv}")
    print(f"Wrote {fafb_csv}")
    print(f"Wrote {mcns_csv}")
    print(f"Wrote {report_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
