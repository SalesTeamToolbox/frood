"""
Template tool — render templates for marketing, reports, and business documents.

Templates use simple {variable} substitution. Stored in-memory with built-in
templates for common document types.
"""

import logging
import re

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.template")


# Built-in templates
BUILTIN_TEMPLATES: dict[str, dict] = {
    "email-campaign": {
        "name": "email-campaign",
        "description": "Marketing email campaign template (AIDA framework)",
        "variables": [
            "subject",
            "preview_text",
            "recipient_name",
            "hook",
            "problem",
            "solution",
            "benefit_1",
            "benefit_2",
            "benefit_3",
            "cta_text",
            "cta_url",
            "sender_name",
            "company",
        ],
        "content": """Subject: {subject}
Preview: {preview_text}

Hi {recipient_name},

{hook}

{problem}

{solution}

Here's what you get:
- {benefit_1}
- {benefit_2}
- {benefit_3}

[{cta_text}]({cta_url})

Best,
{sender_name}
{company}

P.S. Don't miss out — this offer is available for a limited time.""",
    },
    "landing-page-outline": {
        "name": "landing-page-outline",
        "description": "Landing page content outline",
        "variables": [
            "headline",
            "subheadline",
            "hero_description",
            "benefit_1",
            "benefit_2",
            "benefit_3",
            "social_proof",
            "objection_1",
            "answer_1",
            "objection_2",
            "answer_2",
            "cta_text",
            "product_name",
        ],
        "content": """# {headline}

## {subheadline}

{hero_description}

[{cta_text}]

---

## Why {product_name}?

### {benefit_1}

### {benefit_2}

### {benefit_3}

---

## What people are saying

> {social_proof}

---

## FAQ

**{objection_1}**
{answer_1}

**{objection_2}**
{answer_2}

---

## Ready to get started?

[{cta_text}]""",
    },
    "press-release": {
        "name": "press-release",
        "description": "Standard press release format",
        "variables": [
            "headline",
            "subheadline",
            "city",
            "date",
            "company",
            "body_paragraph_1",
            "quote_person",
            "quote_title",
            "quote_text",
            "body_paragraph_2",
            "boilerplate",
            "contact_name",
            "contact_email",
        ],
        "content": """# {headline}

## {subheadline}

**{city}, {date}** — {company} today announced {body_paragraph_1}

"{quote_text}" said {quote_person}, {quote_title} at {company}.

{body_paragraph_2}

### About {company}

{boilerplate}

### Media Contact

{contact_name}
{contact_email}""",
    },
    "executive-summary": {
        "name": "executive-summary",
        "description": "Executive summary for reports and proposals",
        "variables": [
            "title",
            "date",
            "author",
            "objective",
            "key_finding_1",
            "key_finding_2",
            "key_finding_3",
            "recommendation",
            "next_steps",
            "timeline",
        ],
        "content": """# Executive Summary: {title}

**Date:** {date}
**Author:** {author}

## Objective

{objective}

## Key Findings

1. {key_finding_1}
2. {key_finding_2}
3. {key_finding_3}

## Recommendation

{recommendation}

## Next Steps

{next_steps}

**Timeline:** {timeline}""",
    },
    "project-brief": {
        "name": "project-brief",
        "description": "Project brief for kicking off new initiatives",
        "variables": [
            "project_name",
            "owner",
            "date",
            "background",
            "objective",
            "scope",
            "out_of_scope",
            "success_criteria",
            "stakeholders",
            "timeline",
            "risks",
            "budget",
        ],
        "content": """# Project Brief: {project_name}

**Owner:** {owner}
**Date:** {date}

## Background

{background}

## Objective

{objective}

## Scope

### In Scope
{scope}

### Out of Scope
{out_of_scope}

## Success Criteria

{success_criteria}

## Stakeholders

{stakeholders}

## Timeline

{timeline}

## Risks

{risks}

## Budget

{budget}""",
    },
}


class TemplateTool(Tool):
    """Render templates for marketing emails, landing pages, reports, and more."""

    def __init__(self):
        self._templates: dict[str, dict] = dict(BUILTIN_TEMPLATES)

    @property
    def name(self) -> str:
        return "template"

    @property
    def description(self) -> str:
        return (
            "Render document templates with variable substitution. "
            "Actions: list (show templates), show (view a template), "
            "render (fill template with values), create (save new template), "
            "delete (remove custom template), preview (show with placeholder hints). "
            "Built-in: email-campaign, landing-page-outline, press-release, "
            "executive-summary, project-brief."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "show", "render", "create", "delete", "preview"],
                    "description": "Template action",
                },
                "name": {
                    "type": "string",
                    "description": "Template name",
                    "default": "",
                },
                "variables": {
                    "type": "object",
                    "description": "Variables to fill in the template (for render)",
                    "default": {},
                },
                "content": {
                    "type": "string",
                    "description": "Template content with {variable} placeholders (for create)",
                    "default": "",
                },
                "description": {
                    "type": "string",
                    "description": "Template description (for create)",
                    "default": "",
                },
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str = "",
        name: str = "",
        variables: dict = None,
        content: str = "",
        description: str = "",
        **kwargs,
    ) -> ToolResult:
        if not action:
            return ToolResult(error="action is required", success=False)

        if action == "list":
            return self._list()
        elif action == "show":
            return self._show(name)
        elif action == "render":
            return self._render(name, variables or {})
        elif action == "create":
            return self._create(name, content, description)
        elif action == "delete":
            return self._delete(name)
        elif action == "preview":
            return self._preview(name)
        else:
            return ToolResult(error=f"Unknown action: {action}", success=False)

    def _list(self) -> ToolResult:
        if not self._templates:
            return ToolResult(output="No templates available.")

        lines = ["# Available Templates\n"]
        for name, tmpl in sorted(self._templates.items()):
            builtin = " (built-in)" if name in BUILTIN_TEMPLATES else ""
            var_count = len(tmpl.get("variables", []))
            lines.append(
                f"- **{name}**{builtin} — {tmpl.get('description', '')}\n  Variables: {var_count}"
            )
        return ToolResult(output="\n".join(lines))

    def _show(self, name: str) -> ToolResult:
        if not name:
            return ToolResult(error="name is required for show", success=False)
        tmpl = self._templates.get(name)
        if not tmpl:
            return ToolResult(error=f"Template '{name}' not found", success=False)

        variables = tmpl.get("variables", [])
        output = (
            f"# Template: {name}\n\n"
            f"**Description:** {tmpl.get('description', '')}\n"
            f"**Variables:** {', '.join(variables)}\n\n"
            f"## Content\n\n```\n{tmpl['content']}\n```"
        )
        return ToolResult(output=output)

    def _render(self, name: str, variables: dict) -> ToolResult:
        if not name:
            return ToolResult(error="name is required for render", success=False)
        tmpl = self._templates.get(name)
        if not tmpl:
            return ToolResult(error=f"Template '{name}' not found", success=False)

        content = tmpl["content"]

        # Find required variables
        required = set(re.findall(r"\{(\w+)\}", content))
        provided = set(variables.keys())
        missing = required - provided

        if missing:
            return ToolResult(
                error=(
                    f"Missing variables: {', '.join(sorted(missing))}. "
                    f"Required: {', '.join(sorted(required))}"
                ),
                success=False,
            )

        try:
            rendered = content.format_map(variables)
        except KeyError as e:
            return ToolResult(error=f"Variable error: {e}", success=False)

        return ToolResult(output=rendered)

    def _create(self, name: str, content: str, description: str) -> ToolResult:
        if not name:
            return ToolResult(error="name is required for create", success=False)
        if not content:
            return ToolResult(error="content is required for create", success=False)

        variables = list(set(re.findall(r"\{(\w+)\}", content)))

        self._templates[name] = {
            "name": name,
            "description": description or f"Custom template: {name}",
            "variables": sorted(variables),
            "content": content,
        }

        return ToolResult(
            output=(
                f"Template '{name}' created with {len(variables)} variables: "
                f"{', '.join(sorted(variables))}"
            )
        )

    def _delete(self, name: str) -> ToolResult:
        if not name:
            return ToolResult(error="name is required for delete", success=False)
        if name not in self._templates:
            return ToolResult(error=f"Template '{name}' not found", success=False)
        if name in BUILTIN_TEMPLATES:
            return ToolResult(error=f"Cannot delete built-in template '{name}'", success=False)
        del self._templates[name]
        return ToolResult(output=f"Template '{name}' deleted.")

    def _preview(self, name: str) -> ToolResult:
        """Show a template with placeholder hints instead of requiring all variables."""
        if not name:
            return ToolResult(error="name is required for preview", success=False)
        tmpl = self._templates.get(name)
        if not tmpl:
            return ToolResult(error=f"Template '{name}' not found", success=False)

        content = tmpl["content"]
        # Replace {variable} with [VARIABLE: hint]
        hints = {
            "subject": "Email subject line",
            "preview_text": "Preview text shown in inbox",
            "recipient_name": "Recipient's first name",
            "hook": "Opening hook to grab attention",
            "problem": "Pain point you're addressing",
            "solution": "Your product/service as the solution",
            "cta_text": "Call-to-action button text",
            "cta_url": "Link URL for the CTA",
            "headline": "Main headline (H1)",
            "subheadline": "Supporting subheadline",
            "hero_description": "Hero section description",
            "social_proof": "Customer testimonial or stat",
            "product_name": "Your product/service name",
            "company": "Company name",
            "city": "City for press release dateline",
            "date": "Publication date",
            "title": "Document title",
            "author": "Author name",
            "objective": "Primary objective",
            "project_name": "Project name",
            "owner": "Project owner",
            "background": "Background context",
            "scope": "What's included",
            "out_of_scope": "What's excluded",
        }

        preview_content = content
        for var in tmpl.get("variables", []):
            hint = hints.get(var, var.replace("_", " ").title())
            preview_content = preview_content.replace(f"{{{var}}}", f"[{var.upper()}: {hint}]")

        output = (
            f"# Preview: {name}\n\n"
            f"**Description:** {tmpl.get('description', '')}\n\n"
            f"---\n\n{preview_content}\n\n---\n\n"
            f"**Variables to fill:** {', '.join(tmpl.get('variables', []))}"
        )
        return ToolResult(output=output)
