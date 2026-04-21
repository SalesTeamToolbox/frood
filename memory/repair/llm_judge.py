"""LLM-judged repair decisions (Phase 2).

Thin wrapper over ``memory.consolidation.ConsolidationRouter`` that asks the
configured LLM tier to decide whether two memory entries are conflicting
(one supersedes the other) or should be merged into one.

All judgments are **flag-for-review** — the executor never auto-applies an
``decided_by="llm"`` op regardless of returned confidence. Graceful degrade:
returns ``LLMJudgment(verdict="none")`` when no API keys are configured or a
provider call fails.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Literal

from pydantic import ValidationError

from memory.repair.models import LLMJudgment

logger = logging.getLogger("frood.memory.repair.llm_judge")

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _default_model() -> str:
    return os.getenv("MEMORY_REPAIR_LLM_MODEL", "google/gemini-2.0-flash-001")


def _system_prompt(kind: Literal["supersede", "merge"]) -> str:
    if kind == "supersede":
        return (
            "You are a memory curator. Two memory entries may conflict — a newer one "
            "contradicting or replacing an older one. Output strict JSON with keys: "
            "verdict (one of supersede|none), rationale (1-2 sentences), confidence "
            "(0.0-1.0), keeper_target (the filename to keep when verdict=supersede, "
            "otherwise empty string). Output ONLY the JSON object, no prose."
        )
    return (
        "You are a memory curator. Two memory entries may overlap enough to be merged. "
        "Output strict JSON with keys: verdict (one of merge|none), rationale "
        "(1-2 sentences), confidence (0.0-1.0), keeper_target (filename of the entry "
        "to keep as merge destination when verdict=merge, otherwise empty string). "
        "Output ONLY the JSON object, no prose."
    )


def _user_payload(a_target: str, a_text: str, b_target: str, b_text: str) -> str:
    return (
        f"Entry A (filename: {a_target}):\n---\n{a_text.strip()[:1500]}\n---\n\n"
        f"Entry B (filename: {b_target}):\n---\n{b_text.strip()[:1500]}\n---"
    )


def _parse_judgment(raw: str, provider: str) -> LLMJudgment:
    """Extract the first JSON block from ``raw`` and validate into an LLMJudgment."""
    m = _JSON_BLOCK_RE.search(raw)
    if not m:
        logger.debug("llm-judge: no JSON block in response (provider=%s)", provider)
        return LLMJudgment(verdict="none", rationale="parse failed", provider=provider)
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        logger.debug("llm-judge: JSON decode failed: %s", exc)
        return LLMJudgment(verdict="none", rationale="parse failed", provider=provider)
    data["provider"] = provider
    try:
        return LLMJudgment(**data)
    except ValidationError as exc:
        logger.debug("llm-judge: pydantic validation failed: %s", exc)
        return LLMJudgment(verdict="none", rationale="parse failed", provider=provider)


async def judge(
    kind: Literal["supersede", "merge"],
    a_target: str,
    a_text: str,
    b_target: str,
    b_text: str,
    router=None,
) -> LLMJudgment:
    """Ask the LLM tier whether A supersedes B (or they should merge).

    ``router`` override is for tests — production callers leave it None so the
    default ``ConsolidationRouter`` is used. Returns ``verdict="none"`` on any
    failure so the caller can safely drop the op.
    """
    if router is None:
        try:
            from memory.consolidation import ConsolidationRouter

            router = ConsolidationRouter()
        except Exception as exc:  # pragma: no cover — defensive import guard
            logger.debug("llm-judge: ConsolidationRouter unavailable: %s", exc)
            return LLMJudgment(verdict="none", rationale="router unavailable")

    if not getattr(router, "has_providers", True):
        return LLMJudgment(verdict="none", rationale="no providers configured")

    messages = [
        {"role": "system", "content": _system_prompt(kind)},
        {"role": "user", "content": _user_payload(a_target, a_text, b_target, b_text)},
    ]
    try:
        text, provider = await router.complete(_default_model(), messages)
    except Exception as exc:
        logger.debug("llm-judge: provider call failed: %s", exc)
        return LLMJudgment(verdict="none", rationale=f"provider error: {exc}"[:200])

    return _parse_judgment(text, provider or "")
