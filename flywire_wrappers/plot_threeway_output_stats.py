#!/usr/bin/env python3
"""Analyze three-way output stats across one or more output directories.

Expected per-directory inputs:
  - threeway_isomorphic_stats_ignore_self_loops.csv
  - threeway_all_rows_stats_ignore_self_loops.csv
  - threeway_isomorphic_stats_ignore_self_loops.summary.json

The script writes:
  - combined row-level CSVs
  - a per-run summary CSV
  - comparison plots
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib.pyplot as plt
import pandas as pd


REQUIRED_ISO_CSV = "threeway_isomorphic_stats_ignore_self_loops.csv"
REQUIRED_ALL_CSV = "threeway_all_rows_stats_ignore_self_loops.csv"
REQUIRED_SUMMARY_JSON = "threeway_isomorphic_stats_ignore_self_loops.summary.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output_dirs",
        nargs="+",
        type=Path,
        help="Output directories such as outputs/low_degree_bfs_seed1 outputs/high_degree_bfs_seed1",
    )
    parser.add_argument(
        "--outdir",
        type=Path,
        default=Path("outputs/threeway_analysis_plots"),
        help="Directory for combined tables and plots.",
    )
    return parser.parse_args()


def require_file(path: Path) -> Path:
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def load_run(output_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    iso_csv = require_file(output_dir / REQUIRED_ISO_CSV)
    all_csv = require_file(output_dir / REQUIRED_ALL_CSV)
    summary_json = require_file(output_dir / REQUIRED_SUMMARY_JSON)

    iso_df = pd.read_csv(iso_csv)
    all_df = pd.read_csv(all_csv)
    summary = json.loads(summary_json.read_text())

    run_name = output_dir.name
    for df in (iso_df, all_df):
        df["run_name"] = run_name
        df["output_dir"] = str(output_dir)

    return iso_df, all_df, summary


def build_summary_rows(output_dirs: list[Path]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    summary_rows: list[dict] = []
    iso_frames: list[pd.DataFrame] = []
    all_frames: list[pd.DataFrame] = []

    for output_dir in output_dirs:
        iso_df, all_df, summary = load_run(output_dir)
        iso_frames.append(iso_df)
        all_frames.append(all_df)

        row = {
            "run_name": output_dir.name,
            "output_dir": str(output_dir),
            "rows_analyzed": summary["rows_analyzed"],
            "threeway_isomorphic_rows_no_self_loops": summary["threeway_isomorphic_rows_no_self_loops"],
            "non_isomorphic_or_invalid_rows": summary["non_isomorphic_or_invalid_rows"],
        }
        for metric in [
            "threeway_nodes",
            "edges_no_self_loops",
            "weak_components",
            "largest_weak_component",
            "isolated_nodes_weak",
            "strong_components",
            "largest_strong_component",
        ]:
            stats = summary.get(metric, {})
            row[f"{metric}_min"] = stats.get("min")
            row[f"{metric}_median"] = stats.get("median")
            row[f"{metric}_mean"] = stats.get("mean")
            row[f"{metric}_max"] = stats.get("max")
        summary_rows.append(row)

    summary_df = pd.DataFrame(summary_rows)
    iso_combined = pd.concat(iso_frames, ignore_index=True)
    all_combined = pd.concat(all_frames, ignore_index=True)
    return summary_df, iso_combined, all_combined


def add_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    numeric_columns = [
        "threeway_nodes",
        "edges_no_self_loops",
        "weak_components",
        "largest_weak_component",
        "isolated_nodes_weak",
        "strong_components",
        "largest_strong_component",
    ]
    for col in numeric_columns:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    out["largest_weak_ratio"] = out["largest_weak_component"] / out["threeway_nodes"]
    out["largest_strong_ratio"] = out["largest_strong_component"] / out["threeway_nodes"]
    out["isolated_weak_ratio"] = out["isolated_nodes_weak"] / out["threeway_nodes"]
    return out


def write_tables(outdir: Path, summary_df: pd.DataFrame, iso_df: pd.DataFrame, all_df: pd.DataFrame) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    summary_df.to_csv(outdir / "run_summary.csv", index=False)
    iso_df.to_csv(outdir / "combined_isomorphic_rows.csv", index=False)
    all_df.to_csv(outdir / "combined_all_rows.csv", index=False)


def plot_boxplots(outdir: Path, iso_df: pd.DataFrame) -> None:
    metrics = [
        ("threeway_nodes", "Three-Way Nodes"),
        ("edges_no_self_loops", "Edges Ignoring Self-Loops"),
        ("weak_components", "Weak Components"),
        ("largest_weak_component", "Largest Weak Component"),
        ("strong_components", "Strong Components"),
        ("largest_strong_component", "Largest Strong Component"),
    ]

    fig, axes = plt.subplots(2, 3, figsize=(15, 9))
    axes = axes.flatten()
    run_names = list(iso_df["run_name"].drop_duplicates())

    for ax, (metric, title) in zip(axes, metrics):
        series = [
            iso_df.loc[iso_df["run_name"] == run_name, metric].dropna().to_numpy()
            for run_name in run_names
        ]
        ax.boxplot(series, tick_labels=run_names)
        ax.set_title(title)
        ax.tick_params(axis="x", rotation=20)

    fig.suptitle("Three-Way Isomorphic Graph Statistics by Run")
    fig.tight_layout()
    fig.savefig(outdir / "boxplots_isomorphic_stats.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def plot_summary_bars(outdir: Path, summary_df: pd.DataFrame) -> None:
    metrics = [
        "threeway_isomorphic_rows_no_self_loops",
        "threeway_nodes_median",
        "edges_no_self_loops_median",
        "largest_weak_component_median",
        "largest_strong_component_median",
    ]
    titles = [
        "Isomorphic Rows",
        "Median Nodes",
        "Median Edges",
        "Median Largest Weak Component",
        "Median Largest Strong Component",
    ]

    fig, axes = plt.subplots(1, len(metrics), figsize=(18, 4))
    for ax, metric, title in zip(axes, metrics, titles):
        ax.bar(summary_df["run_name"], summary_df[metric])
        ax.set_title(title)
        ax.tick_params(axis="x", rotation=20)
    fig.tight_layout()
    fig.savefig(outdir / "summary_bars.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def plot_scatter_grid(outdir: Path, iso_df: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for run_name, run_df in iso_df.groupby("run_name"):
        axes[0].scatter(
            run_df["threeway_nodes"],
            run_df["largest_weak_component"],
            label=run_name,
            alpha=0.75,
        )
        axes[1].scatter(
            run_df["threeway_nodes"],
            run_df["largest_strong_component"],
            label=run_name,
            alpha=0.75,
        )

    axes[0].set_xlabel("Three-Way Nodes")
    axes[0].set_ylabel("Largest Weak Component")
    axes[0].set_title("Weak Connectivity vs Size")

    axes[1].set_xlabel("Three-Way Nodes")
    axes[1].set_ylabel("Largest Strong Component")
    axes[1].set_title("Strong Connectivity vs Size")
    axes[1].legend()

    fig.tight_layout()
    fig.savefig(outdir / "connectivity_vs_size_scatter.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def plot_histograms(outdir: Path, iso_df: pd.DataFrame) -> None:
    metrics = [
        ("largest_weak_ratio", "Largest Weak Component / Nodes"),
        ("largest_strong_ratio", "Largest Strong Component / Nodes"),
        ("isolated_weak_ratio", "Isolated Weak Nodes / Nodes"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    for ax, (metric, title) in zip(axes, metrics):
        for run_name, run_df in iso_df.groupby("run_name"):
            ax.hist(run_df[metric], bins=12, alpha=0.5, label=run_name)
        ax.set_title(title)
    axes[-1].legend()
    fig.tight_layout()
    fig.savefig(outdir / "ratio_histograms.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    args = parse_args()
    summary_df, iso_df, all_df = build_summary_rows(args.output_dirs)
    iso_df = add_derived_columns(iso_df)
    all_df = add_derived_columns(all_df)

    write_tables(args.outdir, summary_df, iso_df, all_df)
    plot_boxplots(args.outdir, iso_df)
    plot_summary_bars(args.outdir, summary_df)
    plot_scatter_grid(args.outdir, iso_df)
    plot_histograms(args.outdir, iso_df)

    print(f"Wrote analysis outputs to {args.outdir}")
    print(f"Runs: {', '.join(summary_df['run_name'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
