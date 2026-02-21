---
name: research
description: Technical research — compare options, analyze trade-offs, provide recommendations.
always: false
task_types: [research]
---

# Research Skill

Conduct structured technical research that leads to clear, actionable recommendations.

## Research Methodology

### 1. Define the Question
- State the core question in one sentence. Be specific about scope and constraints.
- Identify decision criteria: performance, cost, maintainability, ecosystem, team expertise, timeline.
- Clarify non-negotiable requirements versus nice-to-haves.

### 2. Gather Sources
- **Official documentation** — authoritative, but may lack real-world nuance.
- **Benchmarks and case studies** — quantitative evidence; check methodology and relevance.
- **Community discussion** (GitHub issues, forums) — reveals common pain points.
- **Source code** — the ultimate truth for understanding behavior and quality.
- Prefer recent sources. Technology advice older than 2 years may be outdated.

### 3. Compare
- Build a **comparison matrix** covering all identified criteria.
- Be fair: represent each option's strengths and weaknesses honestly.
- Note where data is uncertain, missing, or self-reported by vendors.

### 4. Recommend
- Lead with a **clear recommendation** and a one-sentence justification.
- Acknowledge trade-offs and risks. Provide a fallback option.

## Source Evaluation

| Dimension | Strong | Weak |
|---|---|---|
| **Authority** | Official docs, core maintainer | Anonymous blog, undated forum post |
| **Recency** | Published within last 12 months | More than 3 years old |
| **Evidence** | Benchmarks, code samples, reproducible results | Anecdotal, opinion-only |
| **Relevance** | Matches your use case, scale, and stack | Different language, scale, or context |
| **Bias** | Independent or transparent affiliation | Vendor marketing, undisclosed sponsorship |

## Output Formats

### Comparison Table
```markdown
| Criteria       | Option A | Option B | Option C |
|----------------|----------|----------|----------|
| Performance    | ...      | ...      | ...      |
| Learning curve | ...      | ...      | ...      |
| Community size | ...      | ...      | ...      |
| Cost           | ...      | ...      | ...      |
```

### Pros and Cons
For each option list concrete **Pros** and **Cons** with supporting evidence.

## Deliverable Structure

1. **Question** — The specific question being answered.
2. **Context** — Relevant constraints and background.
3. **Options considered** — All candidates evaluated, including those rejected early.
4. **Comparison** — Table or structured analysis across decision criteria.
5. **Recommendation** — The chosen option with justification.
6. **Trade-offs and risks** — What you give up and what could go wrong.
7. **Next steps** — Concrete actions to move forward.
8. **Sources** — All references with links.

## Guidelines

- Separate facts from opinions. Label each clearly.
- Set a time box to avoid analysis paralysis. Commit to a recommendation with available information.
- When uncertain, quantify: "likely 2-3x faster based on benchmarks, but untested with our dataset."
