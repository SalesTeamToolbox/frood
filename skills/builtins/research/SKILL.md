---
name: research
description: Technical research — compare options, analyze trade-offs, provide recommendations.
always: false
task_types: [research]
---

# Research Skill

Conduct structured technical research that leads to clear, actionable recommendations.

## Research Methodology

Follow these four phases to produce reliable, well-supported analysis.

### 1. Define the Question

- State the core question in one sentence. Be specific about scope and constraints.
- Identify decision criteria: performance, cost, maintainability, ecosystem, team expertise, timeline.
- Clarify non-negotiable requirements versus nice-to-haves.
- Confirm the audience and the decision that will be made based on this research.

### 2. Gather Sources

- Use a mix of source types:
  - **Official documentation** — authoritative, but may lack real-world nuance.
  - **Benchmarks and case studies** — quantitative evidence; check methodology and relevance.
  - **Community discussion** (GitHub issues, Stack Overflow, forums) — reveals common pain points.
  - **Source code** — the ultimate truth for understanding behavior and quality.
- Record each source with its URL, date, and a brief relevance note.
- Prefer recent sources. Technology advice older than 2 years may be outdated.

### 3. Compare

- Build a **comparison matrix** covering all identified criteria.
- Be fair: represent each option's strengths and weaknesses honestly.
- Note where data is uncertain, missing, or self-reported by vendors.
- Test claims when feasible — run a quick proof of concept rather than relying solely on documentation.

### 4. Recommend

- Lead with a **clear recommendation** and a one-sentence justification.
- Support the recommendation with evidence from the comparison.
- Acknowledge trade-offs and risks of the recommended option.
- Provide a fallback option if the primary choice does not work out.

## Source Evaluation

Rate sources on these dimensions:

| Dimension | Strong | Weak |
|---|---|---|
| **Authority** | Official docs, peer-reviewed, core maintainer | Anonymous blog, undated forum post |
| **Recency** | Published within last 12 months | More than 3 years old |
| **Evidence** | Includes benchmarks, code samples, reproducible results | Anecdotal, opinion-only, no examples |
| **Relevance** | Matches your exact use case, scale, and stack | Different language, scale, or context |
| **Bias** | Independent or transparent about affiliation | Vendor marketing, undisclosed sponsorship |

Disclose source quality when presenting findings. Flag weak sources explicitly.

## Output Format — Comparison Table

```markdown
| Criteria       | Option A       | Option B       | Option C       |
|----------------|----------------|----------------|----------------|
| Performance    | ...            | ...            | ...            |
| Learning curve | ...            | ...            | ...            |
| Community size | ...            | ...            | ...            |
| Maintenance    | ...            | ...            | ...            |
| Cost           | ...            | ...            | ...            |
```

## Output Format — Pros and Cons

For each option, list:

```markdown
### Option A

**Pros:**
- [Pro 1 with supporting evidence]
- [Pro 2 with supporting evidence]

**Cons:**
- [Con 1 with supporting evidence]
- [Con 2 with supporting evidence]
```

## Deliverable Structure

A complete research deliverable includes:

1. **Question** — The specific question being answered.
2. **Context** — Relevant constraints, requirements, and background.
3. **Options considered** — List of all options evaluated, including those rejected early (with reasons).
4. **Comparison** — Table or structured comparison across decision criteria.
5. **Recommendation** — The chosen option with justification.
6. **Trade-offs and risks** — What you give up and what could go wrong.
7. **Next steps** — Concrete actions to move forward with the recommendation.
8. **Sources** — All references with links and access dates.

## Guidelines

- Separate facts from opinions. Label each clearly.
- Avoid analysis paralysis: set a time box for research and commit to a recommendation with the information available.
- If two options are genuinely equivalent, say so and recommend the one with lower switching cost.
- Update research findings when new information emerges or requirements change.
- When uncertain, quantify the uncertainty: "Option A is likely 2-3x faster based on benchmarks, but we have not tested it with our dataset."
