# Data Analysis Checklist — Condensed Reference

> Condensed from `data-analysis` skill. Analysis pipeline structure.

## Standard Pipeline

```
Question → Data → Explore → Model → Visualize → Communicate
```

## Phase Checklists

### 1. Question Definition
- [ ] **Business question** clear and specific
- [ ] **Success metric** defined (accuracy, revenue, latency)
- [ ] **Constraints** known (time, data access, privacy)
- [ ] **Stakeholders** identified

### 2. Data Acquisition
- [ ] **Sources** documented (DB, API, files, logs)
- [ ] **Schema** understood (types, nulls, ranges)
- [ ] **Quality** assessed (completeness, consistency, accuracy)
- [ ] **Bias** considered (selection, survivor, temporal)
- [ ] **Privacy/PII** handled (anonymize, aggregate)

### 3. Exploration (EDA)
- [ ] **Descriptive stats** — mean, median, std, quartiles
- [ ] **Distributions** — histograms, box plots
- [ ] **Correlations** — heatmap, pair plots
- [ ] **Outliers** — identified, investigated, decision logged
- [ ] **Missing data** — pattern (MCAR/MAR/MNAR), strategy
- [ ] **Time series** — trend, seasonality, stationarity

### 4. Modeling
- [ ] **Baseline** established (mean, heuristic, simple model)
- [ ] **Train/val/test** split (temporal if time series)
- [ ] **Features** engineered, documented
- [ ] **Cross-validation** — appropriate for data type
- [ ] **Metrics** — match business objective
- [ ] **Overfitting** checked — train vs val gap

### 5. Visualization
- [ ] **Purpose-driven** — each chart answers a question
- [ ] **Audience-appropriate** — exec vs technical
- [ ] **Accessible** — colorblind-safe, labels, alt text
- [ ] **Interactive** where exploration needed

### 6. Communication
- [ ] **Executive summary** — 3 bullets max
- [ ] **Key finding** — one sentence, with evidence
- [ ] **Recommendation** — specific, actionable, owned
- [ ] **Limitations** — honesty about uncertainty
- [ ] **Reproducibility** — notebook/script + environment

## Common Pitfalls

| Pitfall | Prevention |
|---------|------------|
| P-hacking / data dredging | Pre-register hypotheses, holdout test set |
| Survivorship bias | Include failed/cancelled records |
| Leakage (target in features) | Strict temporal split, feature audit |
| Overfitting to validation | Nested CV, final test only once |
| Ignoring uncertainty | Confidence intervals, prediction intervals |
| Chart junk | Remove non-data ink, Tufte principles |

## Quick Commands

```bash
# Python EDA
python -c "import pandas as pd; df=pd.read_csv('data.csv'); print(df.describe()); print(df.info())"
python -m pandas_profiling data.csv  # Auto EDA report

# SQL exploration
SELECT COUNT(*), COUNT(DISTINCT col), MIN(col), MAX(col), AVG(col) FROM table;
SELECT col, COUNT(*) FROM table GROUP BY col ORDER BY 2 DESC LIMIT 20;

# Visualization
python -c "import seaborn as sns; sns.pairplot(df); plt.savefig('pairs.png')"
```

## Output Format

```
## Analysis: [Question]

### Data
- Source: [table/API/file]
- Rows: X, Cols: Y, Date range: [start] to [end]
- Quality: [missing %], [outliers handled how]

### Key Findings
1. **[Finding]** — [evidence: stat/chart]
2. **[Finding]** — [evidence: stat/chart]

### Model (if applicable)
- Baseline: [metric=X]
- Best: [model] — [metric=Y] — [improvement=Z%]
- CV: [mean±std]

### Recommendation
- **Do:** [specific action] — [expected impact] — [owner] — [timeline]
- **Don't:** [what to avoid based on data]

### Limitations
- [Assumption/uncertainty that could change conclusion]
```
