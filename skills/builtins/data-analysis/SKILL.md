---
name: data-analysis
description: Data processing workflows, visualization best practices, and insight extraction.
always: false
task_types: [data_analysis]
---

# Data Analysis Skill

Process data methodically, identify patterns, and deliver actionable insights.

## Analysis Workflow

1. **Understand the question.** What decision does this analysis inform?
2. **Load and inspect data.** Use the data tool to load CSV/JSON. Check row counts, column types, nulls.
3. **Clean and validate.** Filter bad data, handle missing values, verify ranges.
4. **Explore.** Compute stats (mean, median, distribution) for key columns.
5. **Analyze.** Group, filter, correlate. Look for patterns and outliers.
6. **Visualize.** Use charts to communicate findings. Choose the right chart type.
7. **Interpret.** Translate data patterns into business insights.
8. **Recommend.** Turn insights into actionable next steps.

## Using the Data Tool

The `data` tool supports:
- `load` — Read CSV/JSON data into memory
- `stats` — Get statistics for any column (mean, median, std dev, distribution)
- `query` — Filter with expressions like `column>value`, sort by columns
- `chart` — Generate ASCII bar charts and histograms
- `transform` — Group-by with aggregation (count, sum, avg, min, max)
- `export` — Output results as CSV or JSON

## Chart Selection Guide

| Data Type | Chart |
|-----------|-------|
| Comparing categories | Bar chart |
| Distribution of values | Histogram |
| Trends over time | Line chart (describe as table) |
| Part-to-whole | Pie chart (describe percentages) |
| Correlation between two variables | Scatter plot (describe relationship) |

When visual tools aren't available, use markdown tables with clear labels.

## Statistical Concepts

- **Mean vs. Median:** Use median when data is skewed (income, response times).
- **Standard deviation:** How spread out the data is. Low = consistent, high = variable.
- **Percentiles:** P50 = median, P95 = extreme cases, P99 = rare outliers.
- **Sample size:** Small samples have high variance. Be cautious with N < 30.
- **Correlation ≠ Causation:** Always note this when showing correlations.

## Presentation Guidelines

- **Lead with the insight, not the data.** "Sales dropped 15% in Q3" not "Here is the data."
- **Round numbers.** "About 2.3 million" not "2,347,892.41."
- **Compare to something.** "3x faster than last quarter" not "completion time: 4.2 seconds."
- **Highlight anomalies.** Unexpected patterns are often the most valuable findings.
- **Include methodology.** State what data you used, time range, and any exclusions.
