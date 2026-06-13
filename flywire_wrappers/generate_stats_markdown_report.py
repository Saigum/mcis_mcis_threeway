#!/usr/bin/env python3

import json
import os
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib.pyplot as plt


TABLE_LABELS_BY_COUNT = {
    14: [
        "Summary",
        "Top Primary Cell Types",
        "Top Input Types (Synapses / Partners)",
        "Top Output Types (Synapses / Partners)",
        "Top Input Regions",
        "Top Output Regions",
        "Neurotransmitter Types",
        "Side",
        "Flow",
        "Super Class",
        "Class",
        "Sub Class",
        "Nerve",
        "Hemilineage",
    ],
    9: [
        "Summary",
        "Top Primary Cell Types",
        "Top Input Types (Synapses / Partners)",
        "Top Output Types (Synapses / Partners)",
        "Neurotransmitter Types",
        "Side",
        "Super Class",
        "Class",
        "Sub Class",
    ],
}


@dataclass
class ParsedTable:
    label: str
    rows: list[list[str]]


@dataclass
class ParsedChart:
    title: str
    chart_type: str
    data: list[list[Any]] | None
    color: str | None
    label: str | None
    value: str | None


@dataclass
class DatasetReport:
    name: str
    html_path: Path
    tables: list[ParsedTable]
    charts: list[ParsedChart]


def sanitize_slug(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text or "plot"


def extract_tables(html_text: str) -> list[ParsedTable]:
    soup = BeautifulSoup(html_text, "html.parser")
    tables = soup.find_all("table")
    labels = TABLE_LABELS_BY_COUNT.get(len(tables), [f"Table {i + 1}" for i in range(len(tables))])
    parsed: list[ParsedTable] = []
    for i, table in enumerate(tables):
        rows: list[list[str]] = []
        for tr in table.find_all("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in tr.find_all(["th", "td"])]
            if cells:
                rows.append(cells)
        parsed.append(ParsedTable(label=labels[i], rows=rows))
    return parsed


def extract_charts(html_text: str) -> list[ParsedChart]:
    pattern = re.compile(r'chart_json = (\{.*?\});\s*elem = document\.createElement', re.S)
    raw_matches = pattern.findall(html_text)
    charts: list[ParsedChart] = []
    for raw in raw_matches:
        obj = json.loads(raw)
        if obj["type"] == "big_number":
            charts.append(
                ParsedChart(
                    title=obj["label"],
                    chart_type=obj["type"],
                    data=None,
                    color=obj.get("color"),
                    label=obj.get("label"),
                    value=obj.get("value"),
                )
            )
        else:
            title = str(obj["data"][0][0])
            charts.append(
                ParsedChart(
                    title=title,
                    chart_type=obj["type"],
                    data=obj["data"],
                    color=None,
                    label=None,
                    value=None,
                )
            )
    return charts


def markdown_table(rows: list[list[str]], max_rows: int | None = None) -> str:
    trimmed = rows[:max_rows] if max_rows is not None else rows
    width = max(len(row) for row in trimmed)
    normalized = [row + [""] * (width - len(row)) for row in trimmed]
    if width == 2 and normalized and normalized[0][0] != normalized[0][1]:
        header = ["Metric", "Value"]
        body = normalized
    else:
        header = normalized[0]
        body = normalized[1:]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * len(header)) + " |",
    ]
    for row in body:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def maybe_number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def draw_chart_image(chart: ParsedChart, dataset_name: str, plots_dir: Path) -> Path | None:
    if chart.chart_type == "big_number":
        return None
    assert chart.data is not None
    header = chart.data[0]
    rows = chart.data[1:]
    if len(rows) == 0:
        return None

    labels = [str(row[0]) for row in rows]
    values = [maybe_number(row[1]) for row in rows]
    if any(v is None for v in values):
        return None
    numbers = [float(v) for v in values if v is not None]

    filename = f"{dataset_name}_{sanitize_slug(chart.title)}.png"
    out_path = plots_dir / filename

    if chart.chart_type == "bar":
        n = len(labels)
        fig_h = max(3.0, min(8.0, 0.45 * n + 1.6))
        fig, ax = plt.subplots(figsize=(9, fig_h))
        y = list(range(n))
        colors = []
        for row in rows:
            if len(row) > 2 and isinstance(row[2], str) and row[2].startswith("#"):
                colors.append(row[2])
            else:
                colors.append("#4C78A8")
        ax.barh(y, numbers, color=colors)
        ax.set_yticks(y)
        ax.set_yticklabels(labels, fontsize=9)
        ax.invert_yaxis()
        ax.set_title(f"{dataset_name.upper()}: {chart.title}")
        ax.grid(axis="x", alpha=0.25)
        for idx, value in enumerate(numbers):
            ax.text(value, idx, f" {int(value):,}" if value.is_integer() else f" {value:,.2f}", va="center", fontsize=8)
        fig.tight_layout()
        fig.savefig(out_path, dpi=160)
        plt.close(fig)
        return out_path

    if chart.chart_type == "donut":
        colors = []
        for row in rows:
            if len(row) > 2 and isinstance(row[2], str) and row[2].startswith("#"):
                colors.append(row[2])
            else:
                colors.append(None)
        fig, ax = plt.subplots(figsize=(6.5, 5.5))
        wedges, texts, autotexts = ax.pie(
            numbers,
            labels=labels,
            colors=colors,
            startangle=90,
            autopct=lambda pct: f"{pct:.1f}%" if pct >= 3 else "",
            wedgeprops={"width": 0.42, "edgecolor": "white"},
        )
        ax.set_title(f"{dataset_name.upper()}: {chart.title}")
        fig.tight_layout()
        fig.savefig(out_path, dpi=160)
        plt.close(fig)
        return out_path

    return None


def extract_summary_metrics(table: ParsedTable) -> dict[str, str]:
    metrics: dict[str, str] = {}
    for row in table.rows:
        if len(row) >= 2:
            key = re.sub(r"^\-\s*", "", row[0]).strip()
            metrics[key] = row[1].strip()
    return metrics


def parse_numeric_prefix(value: str) -> float | None:
    match = re.search(r"[-+]?[0-9][0-9,]*\.?[0-9]*", value)
    if not match:
        return None
    return float(match.group(0).replace(",", ""))


def draw_comparison_plots(reports: list[DatasetReport], plots_dir: Path) -> list[Path]:
    summary_maps = {report.name: extract_summary_metrics(report.tables[0]) for report in reports}
    output_paths: list[Path] = []

    metrics_to_plot = [
        "Cells",
        "Typed cells",
        "Combined length",
        "Combined volume",
    ]

    parsed_series: dict[str, list[float]] = {}
    for metric in metrics_to_plot:
        vals = []
        ok = True
        for report in reports:
            value = summary_maps[report.name].get(metric)
            parsed = parse_numeric_prefix(value or "")
            if parsed is None:
                ok = False
                break
            vals.append(parsed)
        if ok:
            parsed_series[metric] = vals

    for metric, values in parsed_series.items():
        fig, ax = plt.subplots(figsize=(7.5, 4.5))
        names = [r.name.upper() for r in reports]
        ax.bar(names, values, color=["#4C78A8", "#F58518", "#54A24B"][: len(values)])
        ax.set_title(f"Comparison: {metric}")
        ax.grid(axis="y", alpha=0.25)
        for idx, value in enumerate(values):
            label = f"{int(value):,}" if float(value).is_integer() else f"{value:,.2f}"
            ax.text(idx, value, label, ha="center", va="bottom", fontsize=9)
        fig.tight_layout()
        out_path = plots_dir / f"comparison_{sanitize_slug(metric)}.png"
        fig.savefig(out_path, dpi=160)
        plt.close(fig)
        output_paths.append(out_path)

    return output_paths


def build_report(reports: list[DatasetReport], output_md: Path, plots_dir: Path) -> None:
    lines: list[str] = []
    lines.append("# Largest Component Stats Report")
    lines.append("")
    lines.append("Generated from `banc_stats.html`, `fafb_stats.html`, and `mcns_stats.html` in `outputs/high_degree_bfs_20K/`.")
    lines.append("")

    lines.append("## Cross-Dataset Summary")
    lines.append("")
    summary_header = ["Dataset"]
    summary_metric_names = [
        "Cells",
        "Typed cells",
        "Unique Primary Cell Types (1 per cell)",
        "Unique Cell Types (all assigned types)",
        "Combined length",
        "Combined area",
        "Combined volume",
    ]
    summary_header.extend(summary_metric_names)
    summary_rows = [summary_header]
    for report in reports:
        metrics = extract_summary_metrics(report.tables[0])
        row = [report.name.upper()] + [metrics.get(metric, "") for metric in summary_metric_names]
        summary_rows.append(row)
    lines.append(markdown_table(summary_rows))
    lines.append("")

    comparison_paths = draw_comparison_plots(reports, plots_dir)
    for path in comparison_paths:
        rel = path.relative_to(output_md.parent)
        title = path.stem.replace("_", " ").title()
        lines.append(f"### {title}")
        lines.append("")
        lines.append(f"![{title}]({rel.as_posix()})")
        lines.append("")

    for report in reports:
        lines.append(f"## {report.name.upper()}")
        lines.append("")
        lines.append(f"Source: `{report.html_path.relative_to(output_md.parent.parent).as_posix()}`")
        lines.append("")

        for table in report.tables:
            lines.append(f"### {table.label}")
            lines.append("")
            lines.append(markdown_table(table.rows, max_rows=15))
            if len(table.rows) > 15:
                lines.append("")
                lines.append(f"_Showing first 15 rows out of {len(table.rows)}._")
            lines.append("")

        lines.append("### Plots")
        lines.append("")
        plot_count = 0
        for chart in report.charts:
            if chart.chart_type == "big_number":
                lines.append(f"- `{chart.label}`: `{chart.value}`")
                continue
            plot_path = draw_chart_image(chart, report.name, plots_dir)
            if plot_path is None:
                continue
            plot_count += 1
            rel = plot_path.relative_to(output_md.parent)
            lines.append(f"#### {chart.title}")
            lines.append("")
            lines.append(f"![{report.name} {chart.title}]({rel.as_posix()})")
            lines.append("")
        if plot_count == 0:
            lines.append("_No plottable chart data found._")
            lines.append("")

    output_md.write_text("\n".join(lines))


def main() -> None:
    base = Path("outputs/high_degree_bfs_20K")
    output_md = base / "largest_component_stats_report.md"
    plots_dir = base / "largest_component_stats_report_plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    reports: list[DatasetReport] = []
    for name in ["banc", "fafb", "mcns"]:
        html_path = base / f"{name}_stats.html"
        html_text = html_path.read_text()
        reports.append(
            DatasetReport(
                name=name,
                html_path=html_path,
                tables=extract_tables(html_text),
                charts=extract_charts(html_text),
            )
        )

    build_report(reports, output_md, plots_dir)
    print(output_md)


if __name__ == "__main__":
    main()
