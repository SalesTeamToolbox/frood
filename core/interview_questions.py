"""
Question banks for project discovery interviews.

Organized by project type (new_project, new_feature) and interview theme.
Each round presents a themed batch of 3-5 questions. The adaptive system
can skip rounds when enough info is already provided, or generate follow-up
questions when answers are vague.
"""

import logging

logger = logging.getLogger("agent42.interview_questions")


# Interview round themes in order — used to drive the interview flow.
# For "moderate" complexity, skip the last round unless red flags detected.
ROUND_THEMES = ["overview", "requirements", "technical", "constraints"]

# Display-friendly names for each round theme
ROUND_DISPLAY_NAMES = {
    "overview": "Overview & Goals",
    "requirements": "Requirements & Scope",
    "technical": "Technical Approach",
    "constraints": "Constraints & Risks",
}


# Question banks keyed by (project_type, theme)
QUESTION_BANKS: dict[tuple[str, str], list[str]] = {
    # ── New Project ─────────────────────────────────────────────────────
    ("new_project", "overview"): [
        "What problem are you trying to solve, and who is it for?",
        "What does success look like? Are there specific metrics or outcomes you're targeting?",
        "Are there existing solutions you've looked at? What do you like or dislike about them?",
    ],
    ("new_project", "requirements"): [
        "Walk me through the core features — what should a user be able to do?",
        "Which features are must-haves for the first version vs. nice-to-haves for later?",
        "Are there any specific data types, integrations, or external services involved?",
    ],
    ("new_project", "technical"): [
        "Do you have preferences for the tech stack, or should I recommend one based on the requirements?",
        "Where will this be deployed — local, cloud, Docker, static hosting?",
        "Any existing code, APIs, or systems this needs to integrate with?",
    ],
    ("new_project", "constraints"): [
        "Are there hard constraints — timeline, budget, team size, specific technologies to use or avoid?",
        "What are the biggest risks you see? What could go wrong?",
        "Are there compliance, security, or accessibility requirements?",
    ],
    # ── New Feature on Existing Project ─────────────────────────────────
    ("new_feature", "overview"): [
        "Describe the feature you want to add — what should it do from the user's perspective?",
        "Why is this feature needed now? What problem does it solve for users?",
        "How does this feature relate to what already exists in the codebase?",
    ],
    ("new_feature", "requirements"): [
        "What are the acceptance criteria — how will you know the feature works correctly?",
        "Are there edge cases or error scenarios to handle specifically?",
        "Should this feature be behind a feature flag or available immediately?",
    ],
    ("new_feature", "technical"): [
        "Which parts of the codebase does this touch? Are there specific files or modules involved?",
        "Are there existing patterns in the code we should follow for consistency?",
        "What test coverage is expected — unit tests, integration tests, E2E?",
    ],
    ("new_feature", "constraints"): [
        "Are there backward-compatibility requirements or migration concerns?",
        "What's the timeline for this feature?",
        "Are there performance, security, or accessibility considerations?",
    ],
}


# LLM prompt for extracting structured answers from a user's natural-language response
ANSWER_EXTRACTION_PROMPT = """\
You are analyzing a user's response to project discovery questions.

The interview round theme is: {theme}
The questions asked were:
{questions}

The user responded with:
{response}

Extract structured answers from their response. For each question, determine
what the user said (or if they didn't address it). Also assess the quality
of the answers.

Respond with ONLY a JSON object (no markdown, no extra text):

{{
  "answers": {{
    "q1": "<extracted answer for question 1, or 'not addressed'>",
    "q2": "<extracted answer for question 2, or 'not addressed'>",
    "q3": "<extracted answer for question 3, or 'not addressed'>"
  }},
  "vague_questions": [<list of question numbers (1-indexed) with vague/incomplete answers>],
  "follow_up_needed": <true or false>,
  "follow_up_questions": [<specific follow-up questions for vague answers, or empty list>],
  "key_insights": [<important facts or decisions extracted from the response>]
}}
"""


# LLM prompt for evaluating whether to skip a round
ROUND_SKIP_PROMPT = """\
You are evaluating whether a project discovery interview round can be skipped.

The upcoming round theme is: {next_theme}
The project description is: {description}
Information already gathered from previous rounds:
{gathered_info}

Based on what's already known, determine if the next round's questions have
already been substantially answered.

Respond with ONLY a JSON object:

{{
  "skip": <true or false>,
  "reason": "<why the round can or cannot be skipped>",
  "already_covered": [<list of topics from this round that are already answered>],
  "still_needed": [<list of topics from this round that still need answers>]
}}
"""


def get_questions(project_type: str, theme: str) -> list[str]:
    """Get the question list for a given project type and theme.

    Args:
        project_type: "new_project" or "new_feature"
        theme: One of ROUND_THEMES values

    Returns:
        List of question strings, or empty list if not found.
    """
    return list(QUESTION_BANKS.get((project_type, theme), []))


def get_round_sequence(complexity: str) -> list[str]:
    """Return the sequence of round themes for a given complexity level.

    - complex: all 4 rounds
    - moderate: first 3 rounds (skip constraints unless needed)
    - simple: should not reach here, but returns first 2 rounds as safety

    Args:
        complexity: "simple", "moderate", or "complex"

    Returns:
        List of theme strings in order.
    """
    if complexity == "complex":
        return list(ROUND_THEMES)
    elif complexity == "moderate":
        return ROUND_THEMES[:3]
    else:
        return ROUND_THEMES[:2]


def format_question_batch(questions: list[str], theme: str) -> str:
    """Format a batch of questions into a user-friendly message.

    Args:
        questions: List of question strings.
        theme: The theme name for the header.

    Returns:
        Formatted markdown string with numbered questions.
    """
    display_name = ROUND_DISPLAY_NAMES.get(theme, theme.replace("_", " ").title())
    lines = [f"**{display_name}:**"]
    for i, q in enumerate(questions, 1):
        lines.append(f"{i}. {q}")
    return "\n".join(lines)
