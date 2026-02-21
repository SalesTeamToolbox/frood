---
name: project-planning
description: WBS, Gantt charts, risk matrices, RACI charts, and sprint planning.
always: false
task_types: [project_management]
---

# Project Planning Skill

Create clear, actionable project plans that keep teams aligned and projects on track.

## Planning Frameworks

### Work Breakdown Structure (WBS)
Decompose the project into manageable pieces:
1. **Level 1:** Project name
2. **Level 2:** Major workstreams / phases
3. **Level 3:** Deliverables within each workstream
4. **Level 4:** Tasks to produce each deliverable

**Rule:** Every task should be completable in 1-5 days. If it's bigger, break it down further.

### RACI Matrix
For each major deliverable, define:
- **R** (Responsible): Who does the work?
- **A** (Accountable): Who makes the final decision?
- **C** (Consulted): Who provides input?
- **I** (Informed): Who needs to know?

**Rule:** Every row has exactly one A. Multiple Rs are OK.

### Risk Register
For each identified risk:

| Risk | Likelihood (1-5) | Impact (1-5) | Score | Mitigation | Owner |
|------|-------------------|--------------|-------|------------|-------|

**Focus on:** Risks with score >= 9 (high likelihood × high impact).

### Sprint Planning
When breaking work into sprints:
- **Sprint length:** 1-2 weeks.
- **Capacity:** Account for meetings, reviews, and context switching (use 70% capacity).
- **Priorities:** Must-have, should-have, nice-to-have for each sprint.
- **Dependencies:** Identify blockers before the sprint starts.
- **Demo:** What will be demonstrable at the end?

## Gantt / Timeline Description

When tools for visual Gantt charts aren't available, use markdown tables:

```
| Phase       | Week 1 | Week 2 | Week 3 | Week 4 | Week 5 |
|-------------|--------|--------|--------|--------|--------|
| Research    | ██████ | ███    |        |        |        |
| Design      |        | ███    | ██████ |        |        |
| Development |        |        | ███    | ██████ | ███    |
| Testing     |        |        |        | ███    | ██████ |
| Launch      |        |        |        |        | ███    |
```

## Status Reports

Structure weekly status as:
1. **Summary** — One sentence on overall health (green/yellow/red).
2. **Completed this week** — What was delivered.
3. **Planned next week** — What will be done.
4. **Blockers** — What's preventing progress.
5. **Risks** — Emerging concerns with mitigation plans.
6. **Decisions needed** — What requires stakeholder input.

## Quality Standards

- **Dates, not durations.** "Due March 15" not "takes 2 weeks."
- **Named owners.** Every task has a person (not a team).
- **Exit criteria.** Define what "done" means for each deliverable.
- **Dependencies explicit.** "Task B cannot start until Task A completes."
- **Buffers included.** Add 20-30% buffer for unknowns.
