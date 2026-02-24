"""
Project specification generator and manager.

Produces PROJECT_SPEC.md documents from interview round data, validates
completeness, and decomposes specs into ordered subtasks.
"""

import json
import logging
import time

logger = logging.getLogger("agent42.project_spec")

# Template for PROJECT_SPEC.md
SPEC_TEMPLATE = """\
# Project Specification: {project_name}

**Version:** {version} | **Status:** {status} | **Created:** {created}
**Type:** {project_type_display} | **Complexity:** {complexity}

---

## 1. Overview

**Problem Statement:** {problem_statement}

**Goals:** {goals}

**Target Users:** {target_users}

## 2. Scope

### In Scope
{in_scope}

### Out of Scope
{out_of_scope}

### MVP Definition
{mvp_definition}

## 3. Requirements

### Functional Requirements

| ID | Requirement | Priority | Notes |
|----|------------|----------|-------|
{functional_requirements}

### Non-Functional Requirements
{non_functional_requirements}

## 4. Technical Approach

**Architecture:** {architecture}

**Tech Stack:** {tech_stack}

**Data Model:** {data_model}

**File Structure:**
```
{file_structure}
```

## 5. Milestones

| # | Milestone | Deliverables | Dependencies |
|---|-----------|-------------|--------------|
{milestones}

## 6. Risks & Assumptions

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
{risks}

**Assumptions:**
{assumptions}

## 7. Acceptance Criteria

{acceptance_criteria}

---

## Change Log

| Date | Change | Reason |
|------|--------|--------|
| {created} | Initial spec created | Project kickoff |
"""

# LLM prompt for synthesizing interview data into a spec
SPEC_GENERATION_PROMPT = """\
You are a senior project manager synthesizing interview data into a formal
project specification document.

Project type: {project_type}
Complexity: {complexity}
Original description: {description}

Interview data collected:
{interview_data}

Generate a complete project specification by filling in ALL sections below.
Be specific and actionable — no vague placeholders. If information is missing,
make reasonable assumptions and note them in the Assumptions section.

Respond with ONLY a JSON object (no markdown, no extra text):

{{
  "project_name": "<clear, concise project name>",
  "problem_statement": "<1-2 sentence problem statement>",
  "goals": "<bulleted list of project goals>",
  "target_users": "<who will use this>",
  "in_scope": "<bulleted list of in-scope items>",
  "out_of_scope": "<bulleted list of explicitly excluded items>",
  "mvp_definition": "<bulleted list of minimum viable features>",
  "functional_requirements": [
    {{"id": "FR-1", "requirement": "...", "priority": "Must", "notes": "..."}},
    {{"id": "FR-2", "requirement": "...", "priority": "Should", "notes": "..."}}
  ],
  "non_functional_requirements": "<bulleted list (performance, security, etc.)>",
  "architecture": "<high-level architecture description>",
  "tech_stack": "<languages, frameworks, tools>",
  "data_model": "<key entities and relationships>",
  "file_structure": "<planned directory layout>",
  "milestones": [
    {{"number": 1, "name": "...", "deliverables": "...", "dependencies": "..."}}
  ],
  "risks": [
    {{"risk": "...", "likelihood": "Medium", "impact": "High", "mitigation": "..."}}
  ],
  "assumptions": "<bulleted list of assumptions>",
  "acceptance_criteria": "<checkbox list of acceptance criteria>"
}}
"""

# LLM prompt for decomposing a spec into subtasks
SUBTASK_DECOMPOSITION_PROMPT = """\
You are a senior project manager breaking down a project specification into
ordered, executable subtasks.

Project specification:
{spec_content}

Create a list of subtasks that, when completed in order, will deliver the
project. Each subtask should be:
- Small enough for a single agent to complete in one session
- Clearly scoped with specific deliverables
- Properly ordered with dependencies

Respond with ONLY a JSON array:

[
  {{
    "title": "<short descriptive title>",
    "description": "<detailed description of what to build/do>",
    "task_type": "<coding | debugging | documentation | testing>",
    "depends_on": [<indices of tasks this depends on, 0-indexed>],
    "estimated_iterations": <3-12>,
    "acceptance_criteria": ["<criterion 1>", "<criterion 2>"]
  }}
]

Rules:
- First task should be project setup/scaffolding
- Last task should be integration testing and polish
- Each task should reference specific parts of the spec
- Include 4-10 subtasks depending on project complexity
- Use "coding" for implementation tasks, "debugging" for testing/fix tasks
"""


class ProjectSpecGenerator:
    """Generates, validates, and manages PROJECT_SPEC.md documents."""

    def __init__(self, router=None, model: str = "or-free-llama4-maverick"):
        self.router = router
        self.model = model

    async def generate(self, project_data: dict) -> str:
        """Generate PROJECT_SPEC.md content from interview round data.

        Args:
            project_data: Dict with keys: project_type, complexity, description,
                         rounds (list of round dicts with theme, extracted_answers,
                         key_insights).

        Returns:
            Complete PROJECT_SPEC.md content as a string.
        """
        # Format interview data for the LLM
        interview_summary = self._format_interview_data(project_data)

        if self.router:
            try:
                return await self._llm_generate(project_data, interview_summary)
            except Exception as e:
                logger.warning(f"LLM spec generation failed, using template fallback: {e}")

        return self._template_generate(project_data, interview_summary)

    async def _llm_generate(self, project_data: dict, interview_summary: str) -> str:
        """Use LLM to synthesize interview data into a spec."""
        prompt = SPEC_GENERATION_PROMPT.format(
            project_type=project_data.get("project_type", "new_project"),
            complexity=project_data.get("complexity", "moderate"),
            description=project_data.get("description", ""),
            interview_data=interview_summary,
        )

        messages = [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": "Generate the project specification from the interview data above.",
            },
        ]

        response, _ = await self.router.complete(
            self.model, messages, temperature=0.3, max_tokens=3000
        )

        spec_data = self._parse_json_response(response)
        if not spec_data:
            return self._template_generate(project_data, interview_summary)

        return self._render_spec(spec_data, project_data)

    def _template_generate(self, project_data: dict, interview_summary: str) -> str:
        """Fallback: generate spec from template without LLM."""
        project_type = project_data.get("project_type", "new_project")
        type_display = "New Project" if project_type == "new_project" else "New Feature"
        today = time.strftime("%Y-%m-%d")

        # Extract what we can from round data
        rounds = project_data.get("rounds", [])
        answers_text = ""
        for r in rounds:
            extracted = r.get("extracted_answers", {})
            for key, val in extracted.items():
                if val and val != "not addressed":
                    answers_text += f"- {val}\n"

        return SPEC_TEMPLATE.format(
            project_name=project_data.get("description", "Untitled Project")[:60],
            version="1.0-draft",
            status="Draft — Awaiting Approval",
            created=today,
            project_type_display=type_display,
            complexity=project_data.get("complexity", "moderate"),
            problem_statement=self._extract_answer(
                rounds, "overview", "q1", "See interview data below"
            ),
            goals=self._extract_answer(rounds, "overview", "q2", "To be defined after approval"),
            target_users=self._extract_answer(rounds, "overview", "q1", "To be defined"),
            in_scope=answers_text or "- To be defined based on interview data\n",
            out_of_scope="- To be determined during implementation\n",
            mvp_definition="- Core features identified during interview\n",
            functional_requirements="| FR-1 | Core functionality | Must | From interview |\n",
            non_functional_requirements="- To be defined\n",
            architecture="To be determined based on requirements",
            tech_stack="To be recommended based on project needs",
            data_model="To be designed during implementation",
            file_structure="To be determined",
            milestones="| 1 | MVP | Core features | None |\n",
            risks="| Scope creep | Medium | High | Clear spec + change log |\n",
            assumptions="- Requirements as captured during interview are accurate\n",
            acceptance_criteria="- [ ] All functional requirements met\n- [ ] Tests pass\n",
        )

    def _render_spec(self, spec_data: dict, project_data: dict) -> str:
        """Render the LLM-generated spec data into the markdown template."""
        project_type = project_data.get("project_type", "new_project")
        type_display = "New Project" if project_type == "new_project" else "New Feature"
        today = time.strftime("%Y-%m-%d")

        # Format functional requirements table
        fr_rows = []
        for fr in spec_data.get("functional_requirements", []):
            if isinstance(fr, dict):
                fr_rows.append(
                    f"| {fr.get('id', '')} | {fr.get('requirement', '')} "
                    f"| {fr.get('priority', '')} | {fr.get('notes', '')} |"
                )
        fr_table = "\n".join(fr_rows) if fr_rows else "| FR-1 | TBD | Must | — |\n"

        # Format milestones table
        ms_rows = []
        for ms in spec_data.get("milestones", []):
            if isinstance(ms, dict):
                ms_rows.append(
                    f"| {ms.get('number', '')} | {ms.get('name', '')} "
                    f"| {ms.get('deliverables', '')} | {ms.get('dependencies', '')} |"
                )
        ms_table = "\n".join(ms_rows) if ms_rows else "| 1 | MVP | Core features | None |\n"

        # Format risks table
        risk_rows = []
        for risk in spec_data.get("risks", []):
            if isinstance(risk, dict):
                risk_rows.append(
                    f"| {risk.get('risk', '')} | {risk.get('likelihood', '')} "
                    f"| {risk.get('impact', '')} | {risk.get('mitigation', '')} |"
                )
        risk_table = (
            "\n".join(risk_rows)
            if risk_rows
            else "| Scope creep | Medium | High | Clear spec + change log |\n"
        )

        return SPEC_TEMPLATE.format(
            project_name=spec_data.get("project_name", "Untitled Project"),
            version="1.0-draft",
            status="Draft — Awaiting Approval",
            created=today,
            project_type_display=type_display,
            complexity=project_data.get("complexity", "moderate"),
            problem_statement=spec_data.get("problem_statement", "TBD"),
            goals=spec_data.get("goals", "TBD"),
            target_users=spec_data.get("target_users", "TBD"),
            in_scope=spec_data.get("in_scope", "- TBD\n"),
            out_of_scope=spec_data.get("out_of_scope", "- TBD\n"),
            mvp_definition=spec_data.get("mvp_definition", "- TBD\n"),
            functional_requirements=fr_table,
            non_functional_requirements=spec_data.get("non_functional_requirements", "- TBD\n"),
            architecture=spec_data.get("architecture", "TBD"),
            tech_stack=spec_data.get("tech_stack", "TBD"),
            data_model=spec_data.get("data_model", "TBD"),
            file_structure=spec_data.get("file_structure", "TBD"),
            milestones=ms_table,
            risks=risk_table,
            assumptions=spec_data.get("assumptions", "- TBD\n"),
            acceptance_criteria=spec_data.get("acceptance_criteria", "- [ ] TBD\n"),
        )

    async def generate_subtasks(self, spec_content: str, project_type: str) -> list[dict]:
        """Break a spec into ordered subtasks with dependencies.

        Args:
            spec_content: The full PROJECT_SPEC.md content.
            project_type: "new_project" or "new_feature".

        Returns:
            List of subtask dicts with title, description, task_type,
            depends_on, estimated_iterations, and acceptance_criteria.
        """
        if not self.router:
            return self._fallback_subtasks(project_type)

        try:
            prompt = SUBTASK_DECOMPOSITION_PROMPT.format(spec_content=spec_content)
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": "Decompose this specification into subtasks."},
            ]
            response, _ = await self.router.complete(
                self.model, messages, temperature=0.2, max_tokens=2000
            )
            subtasks = self._parse_json_response(response)
            if isinstance(subtasks, list) and len(subtasks) > 0:
                return subtasks
        except Exception as e:
            logger.warning(f"LLM subtask decomposition failed: {e}")

        return self._fallback_subtasks(project_type)

    def validate_completeness(self, project_data: dict) -> dict:
        """Check if enough data has been collected from the interview.

        Args:
            project_data: Dict with rounds and their extracted answers.

        Returns:
            Dict with {complete: bool, missing: list[str], coverage: float}.
        """
        rounds = project_data.get("rounds", [])
        total_questions = 0
        answered_questions = 0
        missing = []

        for r in rounds:
            answers = r.get("extracted_answers", {})
            for key, val in answers.items():
                total_questions += 1
                if val and val != "not addressed":
                    answered_questions += 1
                else:
                    theme = r.get("theme", "unknown")
                    missing.append(f"{theme}: {key}")

        coverage = answered_questions / max(total_questions, 1)
        # Consider complete if 70%+ of questions are answered
        return {
            "complete": coverage >= 0.7,
            "missing": missing,
            "coverage": round(coverage, 2),
            "total_questions": total_questions,
            "answered_questions": answered_questions,
        }

    def _format_interview_data(self, project_data: dict) -> str:
        """Format interview rounds into a readable summary for LLM consumption."""
        rounds = project_data.get("rounds", [])
        parts = []
        for r in rounds:
            theme = r.get("theme", "Unknown")
            parts.append(f"\n### {theme}")
            # Include raw response if available
            raw = r.get("raw_response", "")
            if raw:
                parts.append(f"User response: {raw}")
            # Include extracted answers
            answers = r.get("extracted_answers", {})
            for key, val in answers.items():
                if val and val != "not addressed":
                    parts.append(f"- {key}: {val}")
            # Include key insights
            insights = r.get("key_insights", [])
            for insight in insights:
                parts.append(f"- Insight: {insight}")
        return "\n".join(parts)

    @staticmethod
    def _extract_answer(rounds: list, theme: str, key: str, default: str) -> str:
        """Extract a specific answer from interview rounds."""
        for r in rounds:
            if r.get("theme", "").lower().startswith(theme):
                answers = r.get("extracted_answers", {})
                val = answers.get(key, "")
                if val and val != "not addressed":
                    return val
        return default

    @staticmethod
    def _parse_json_response(response: str):
        """Parse a JSON response from an LLM, stripping markdown fences."""
        text = response.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse spec generation response: {text[:200]}")
            return None

    @staticmethod
    def _fallback_subtasks(project_type: str) -> list[dict]:
        """Generate basic subtask structure when LLM is unavailable."""
        if project_type == "new_feature":
            return [
                {
                    "title": "Analyze existing codebase and plan changes",
                    "description": "Read the relevant code, understand patterns, plan the implementation.",
                    "task_type": "coding",
                    "depends_on": [],
                    "estimated_iterations": 4,
                    "acceptance_criteria": ["Implementation plan documented"],
                },
                {
                    "title": "Implement the feature",
                    "description": "Write the code changes as specified in the project spec.",
                    "task_type": "coding",
                    "depends_on": [0],
                    "estimated_iterations": 8,
                    "acceptance_criteria": ["Feature works as specified"],
                },
                {
                    "title": "Write tests and verify",
                    "description": "Add test coverage and verify the feature works end-to-end.",
                    "task_type": "debugging",
                    "depends_on": [1],
                    "estimated_iterations": 4,
                    "acceptance_criteria": ["Tests pass", "No regressions"],
                },
            ]
        else:
            return [
                {
                    "title": "Set up project structure and boilerplate",
                    "description": "Create the project directory structure, configuration files, and base dependencies.",
                    "task_type": "coding",
                    "depends_on": [],
                    "estimated_iterations": 4,
                    "acceptance_criteria": ["Project scaffolding complete"],
                },
                {
                    "title": "Implement core features",
                    "description": "Build the primary functionality as defined in the project spec.",
                    "task_type": "coding",
                    "depends_on": [0],
                    "estimated_iterations": 10,
                    "acceptance_criteria": ["Core features functional"],
                },
                {
                    "title": "Add supporting features and polish",
                    "description": "Implement secondary features, error handling, and UI polish.",
                    "task_type": "coding",
                    "depends_on": [1],
                    "estimated_iterations": 6,
                    "acceptance_criteria": ["All specified features working"],
                },
                {
                    "title": "Testing and integration verification",
                    "description": "Run full test suite, fix bugs, verify all acceptance criteria.",
                    "task_type": "debugging",
                    "depends_on": [2],
                    "estimated_iterations": 4,
                    "acceptance_criteria": ["All tests pass", "Acceptance criteria met"],
                },
            ]
