"""
Data tool — CSV/JSON processing, statistics, and visualization.

Uses Python standard library only (csv, json, statistics).
Agents can load, query, transform, and visualize structured data.
"""

import csv
import io
import json
import logging
import math
import statistics
from collections import Counter, defaultdict

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.data")


class DataTool(Tool):
    """Process structured data: load, query, stats, chart, transform, export."""

    def __init__(self):
        self._datasets: dict[str, list[dict]] = {}

    @property
    def name(self) -> str:
        return "data"

    @property
    def description(self) -> str:
        return (
            "Work with structured data (CSV/JSON). "
            "Actions: load (read CSV/JSON string into memory), query (filter/sort), "
            "stats (basic statistics on a column), chart (ASCII bar chart or markdown table), "
            "transform (group-by/pivot), export (output as CSV/JSON), list (show loaded datasets)."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["load", "query", "stats", "chart", "transform", "export", "list"],
                    "description": "Data action",
                },
                "dataset": {
                    "type": "string",
                    "description": "Dataset name (for load/query/stats/chart/transform/export)",
                    "default": "default",
                },
                "data": {
                    "type": "string",
                    "description": "CSV or JSON string to load",
                    "default": "",
                },
                "format": {
                    "type": "string",
                    "enum": ["csv", "json"],
                    "description": "Data format (for load/export)",
                    "default": "csv",
                },
                "column": {
                    "type": "string",
                    "description": "Column name (for stats/chart/transform)",
                    "default": "",
                },
                "filter": {
                    "type": "string",
                    "description": "Filter expression for query: 'column=value' or 'column>value'",
                    "default": "",
                },
                "sort_by": {
                    "type": "string",
                    "description": "Column to sort by (for query)",
                    "default": "",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max rows to return (for query)",
                    "default": 50,
                },
                "group_by": {
                    "type": "string",
                    "description": "Column to group by (for transform)",
                    "default": "",
                },
                "agg": {
                    "type": "string",
                    "enum": ["count", "sum", "avg", "min", "max"],
                    "description": "Aggregation function (for transform)",
                    "default": "count",
                },
                "value_column": {
                    "type": "string",
                    "description": "Column to aggregate (for transform with sum/avg/min/max)",
                    "default": "",
                },
            },
            "required": ["action"],
        }

    async def execute(self, action: str = "", **kwargs) -> ToolResult:
        if not action:
            return ToolResult(error="action is required", success=False)

        try:
            if action == "load":
                return self._load(kwargs)
            elif action == "query":
                return self._query(kwargs)
            elif action == "stats":
                return self._stats(kwargs)
            elif action == "chart":
                return self._chart(kwargs)
            elif action == "transform":
                return self._transform(kwargs)
            elif action == "export":
                return self._export(kwargs)
            elif action == "list":
                return self._list_datasets()
            else:
                return ToolResult(error=f"Unknown action: {action}", success=False)
        except Exception as e:
            return ToolResult(error=str(e), success=False)

    def _load(self, kwargs: dict) -> ToolResult:
        name = kwargs.get("dataset", "default")
        data_str = kwargs.get("data", "")
        fmt = kwargs.get("format", "csv")

        if not data_str:
            return ToolResult(error="data is required for load", success=False)

        if fmt == "json":
            parsed = json.loads(data_str)
            if isinstance(parsed, list):
                rows = parsed
            elif isinstance(parsed, dict):
                rows = [parsed]
            else:
                return ToolResult(error="JSON must be an array or object", success=False)
        else:
            reader = csv.DictReader(io.StringIO(data_str))
            rows = list(reader)

        self._datasets[name] = rows
        columns = list(rows[0].keys()) if rows else []

        return ToolResult(
            output=(
                f"Dataset '{name}' loaded: {len(rows)} rows, "
                f"{len(columns)} columns\n"
                f"Columns: {', '.join(columns)}"
            )
        )

    def _get_dataset(self, kwargs: dict) -> tuple[str, list[dict]]:
        name = kwargs.get("dataset", "default")
        if name not in self._datasets:
            raise ValueError(
                f"Dataset '{name}' not loaded. "
                f"Available: {', '.join(self._datasets.keys()) or '(none)'}"
            )
        return name, self._datasets[name]

    def _query(self, kwargs: dict) -> ToolResult:
        name, rows = self._get_dataset(kwargs)
        filter_expr = kwargs.get("filter", "")
        sort_by = kwargs.get("sort_by", "")
        limit = kwargs.get("limit", 50)

        result = list(rows)

        # Apply filter
        if filter_expr:
            result = self._apply_filter(result, filter_expr)

        # Sort
        if sort_by:
            desc = sort_by.startswith("-")
            col = sort_by.lstrip("-")
            result.sort(key=lambda r: self._sort_key(r.get(col, "")), reverse=desc)

        # Limit
        result = result[:limit]

        if not result:
            return ToolResult(output=f"Query on '{name}': 0 rows matched.")

        return ToolResult(output=self._rows_to_table(result, name, len(rows)))

    def _stats(self, kwargs: dict) -> ToolResult:
        name, rows = self._get_dataset(kwargs)
        column = kwargs.get("column", "")

        if not column:
            return ToolResult(error="column is required for stats", success=False)

        values = [r.get(column, "") for r in rows]
        numeric = []
        for v in values:
            try:
                numeric.append(float(v))
            except (ValueError, TypeError):
                pass

        non_empty = [v for v in values if v]
        unique = len(set(values))

        output = f"# Statistics: {name}.{column}\n\n"
        output += f"| Metric | Value |\n|--------|-------|\n"
        output += f"| Total rows | {len(values)} |\n"
        output += f"| Non-empty | {len(non_empty)} |\n"
        output += f"| Unique values | {unique} |\n"

        if numeric:
            output += f"| Numeric values | {len(numeric)} |\n"
            output += f"| Min | {min(numeric):.4g} |\n"
            output += f"| Max | {max(numeric):.4g} |\n"
            output += f"| Mean | {statistics.mean(numeric):.4g} |\n"
            output += f"| Median | {statistics.median(numeric):.4g} |\n"
            if len(numeric) >= 2:
                output += f"| Std Dev | {statistics.stdev(numeric):.4g} |\n"
            output += f"| Sum | {sum(numeric):.4g} |\n"
        else:
            # For non-numeric, show top values
            freq = Counter(values).most_common(10)
            output += "\n## Top Values\n\n"
            output += "| Value | Count |\n|-------|-------|\n"
            for val, count in freq:
                output += f"| {val} | {count} |\n"

        return ToolResult(output=output)

    def _chart(self, kwargs: dict) -> ToolResult:
        name, rows = self._get_dataset(kwargs)
        column = kwargs.get("column", "")

        if not column:
            return ToolResult(error="column is required for chart", success=False)

        values = [r.get(column, "") for r in rows]

        # Try numeric chart first
        numeric = []
        for v in values:
            try:
                numeric.append(float(v))
            except (ValueError, TypeError):
                pass

        if len(numeric) > len(values) * 0.5:
            # Numeric histogram
            return ToolResult(output=self._ascii_histogram(numeric, column))
        else:
            # Category bar chart
            freq = Counter(values).most_common(20)
            return ToolResult(output=self._ascii_bar_chart(freq, column))

    def _transform(self, kwargs: dict) -> ToolResult:
        name, rows = self._get_dataset(kwargs)
        group_by = kwargs.get("group_by", "")
        agg = kwargs.get("agg", "count")
        value_column = kwargs.get("value_column", "")

        if not group_by:
            return ToolResult(error="group_by is required for transform", success=False)
        if agg in ("sum", "avg", "min", "max") and not value_column:
            return ToolResult(
                error=f"value_column is required for {agg} aggregation",
                success=False,
            )

        groups: dict[str, list] = defaultdict(list)
        for row in rows:
            key = row.get(group_by, "(empty)")
            if value_column:
                try:
                    groups[key].append(float(row.get(value_column, 0)))
                except (ValueError, TypeError):
                    pass
            else:
                groups[key].append(1)

        result_rows = []
        for key, vals in sorted(groups.items()):
            if agg == "count":
                result = len(vals)
            elif agg == "sum":
                result = sum(vals)
            elif agg == "avg":
                result = statistics.mean(vals) if vals else 0
            elif agg == "min":
                result = min(vals) if vals else 0
            elif agg == "max":
                result = max(vals) if vals else 0
            else:
                result = len(vals)

            result_rows.append({
                group_by: key,
                f"{agg}({value_column or '*'})": f"{result:.4g}" if isinstance(result, float) else str(result),
            })

        return ToolResult(output=self._rows_to_table(result_rows, f"{name} grouped", len(rows)))

    def _export(self, kwargs: dict) -> ToolResult:
        name, rows = self._get_dataset(kwargs)
        fmt = kwargs.get("format", "csv")

        if not rows:
            return ToolResult(output="(empty dataset)")

        if fmt == "json":
            return ToolResult(output=json.dumps(rows, indent=2))
        else:
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
            return ToolResult(output=output.getvalue())

    def _list_datasets(self) -> ToolResult:
        if not self._datasets:
            return ToolResult(output="No datasets loaded.")

        lines = ["# Loaded Datasets\n"]
        for name, rows in self._datasets.items():
            cols = list(rows[0].keys()) if rows else []
            lines.append(
                f"- **{name}**: {len(rows)} rows, {len(cols)} columns "
                f"({', '.join(cols[:5])}{'...' if len(cols) > 5 else ''})"
            )
        return ToolResult(output="\n".join(lines))

    # -- Helpers ---------------------------------------------------------------

    @staticmethod
    def _apply_filter(rows: list[dict], expr: str) -> list[dict]:
        """Simple filter: 'col=val', 'col>val', 'col<val', 'col!=val'."""
        for op in ("!=", ">=", "<=", ">", "<", "="):
            if op in expr:
                parts = expr.split(op, 1)
                col, val = parts[0].strip(), parts[1].strip()
                break
        else:
            return rows

        result = []
        for row in rows:
            cell = row.get(col, "")
            try:
                cell_num = float(cell)
                val_num = float(val)
                numeric = True
            except (ValueError, TypeError):
                cell_num = val_num = 0
                numeric = False

            if op == "=" and cell == val:
                result.append(row)
            elif op == "!=" and cell != val:
                result.append(row)
            elif op == ">" and numeric and cell_num > val_num:
                result.append(row)
            elif op == "<" and numeric and cell_num < val_num:
                result.append(row)
            elif op == ">=" and numeric and cell_num >= val_num:
                result.append(row)
            elif op == "<=" and numeric and cell_num <= val_num:
                result.append(row)

        return result

    @staticmethod
    def _sort_key(val: str):
        try:
            return (0, float(val))
        except (ValueError, TypeError):
            return (1, val)

    @staticmethod
    def _rows_to_table(rows: list[dict], title: str, total: int) -> str:
        if not rows:
            return f"(no data in {title})"

        cols = list(rows[0].keys())
        lines = [f"# {title} ({len(rows)}/{total} rows)\n"]

        # Header
        lines.append("| " + " | ".join(cols) + " |")
        lines.append("|" + "|".join("---" for _ in cols) + "|")

        for row in rows:
            cells = [str(row.get(c, ""))[:50] for c in cols]
            lines.append("| " + " | ".join(cells) + " |")

        return "\n".join(lines)

    @staticmethod
    def _ascii_bar_chart(freq: list[tuple], label: str) -> str:
        if not freq:
            return "(no data)"

        max_count = max(c for _, c in freq)
        bar_width = 30

        lines = [f"# Bar Chart: {label}\n"]
        for val, count in freq:
            bar_len = round(count / max_count * bar_width) if max_count else 0
            bar = "█" * bar_len
            lines.append(f"  {str(val)[:20]:>20} | {bar} {count}")

        return "\n".join(lines)

    @staticmethod
    def _ascii_histogram(values: list[float], label: str, bins: int = 10) -> str:
        if not values:
            return "(no data)"

        lo, hi = min(values), max(values)
        if lo == hi:
            return f"All {len(values)} values = {lo}"

        bin_width = (hi - lo) / bins
        counts = [0] * bins
        for v in values:
            idx = min(int((v - lo) / bin_width), bins - 1)
            counts[idx] += 1

        max_count = max(counts)
        bar_width = 30

        lines = [f"# Histogram: {label}\n"]
        for i, count in enumerate(counts):
            lo_edge = lo + i * bin_width
            hi_edge = lo_edge + bin_width
            bar_len = round(count / max_count * bar_width) if max_count else 0
            bar = "█" * bar_len
            lines.append(f"  {lo_edge:>8.2f}-{hi_edge:<8.2f} | {bar} {count}")

        return "\n".join(lines)
