"""
Model researcher — gathers benchmark data from authoritative sources.

Periodically fetches and analyzes LLM benchmark leaderboards to produce
capability scores that feed into the model evaluator's ranking algorithm.

Sources:
- LMSys Chatbot Arena leaderboard
- OpenRouter model statistics
- HuggingFace Open LLM Leaderboard
- Artificial Analysis quality/speed index

Results are stored as ``data/model_research.json`` and used as a "prior"
for models with limited task-outcome data.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import httpx

logger = logging.getLogger("agent42.model_researcher")

# Authoritative benchmark sources
BENCHMARK_SOURCES = [
    {
        "name": "LMSys Chatbot Arena",
        "url": "https://lmarena.ai/leaderboard",
        "type": "arena",
    },
    {
        "name": "OpenRouter Stats",
        "url": "https://openrouter.ai/rankings",
        "type": "stats",
    },
    {
        "name": "Artificial Analysis",
        "url": "https://artificialanalysis.ai/leaderboards/models",
        "type": "benchmark",
    },
]

RESEARCH_SYSTEM_PROMPT = """\
You are a model benchmarking analyst. Extract structured capability scores \
from the provided benchmark data.

For each model you can identify, produce a JSON object with scores \
normalized to 0.0-1.0 for these capabilities:
- coding: code generation, debugging, refactoring quality
- reasoning: logical reasoning, math, analysis
- writing: creative writing, documentation, communication
- general: overall capability and versatility

Output ONLY valid JSON in this format:
{
  "provider/model-name": {
    "coding": 0.85,
    "reasoning": 0.90,
    "writing": 0.75,
    "general": 0.82
  }
}

Focus on models available on OpenRouter. Include both free and paid models.
If you cannot determine a score for a capability, use 0.5 as neutral default.
Only include models you are reasonably confident about.
"""

RESEARCH_PROMPT_TEMPLATE = """\
Here is benchmark/leaderboard data from {source_name}:

{content}

Extract capability scores for all identifiable LLM models. Focus especially \
on models available via OpenRouter (free tier included).
"""


class ModelResearcher:
    """Researches model capabilities from authoritative benchmark sources."""

    def __init__(
        self,
        research_path: Path | str = "data/model_research.json",
        interval_hours: float = 168.0,  # Weekly
    ):
        self.research_path = Path(research_path)
        self.interval_seconds = interval_hours * 3600
        self._last_research: float = 0.0
        self._scores: dict[str, dict[str, float]] = {}

        self._load_cache()

    async def research(self, router=None) -> dict[str, dict[str, float]]:
        """Fetch benchmark data and extract model capability scores.

        Args:
            router: ModelRouter instance for making LLM calls to analyze
                    the fetched benchmark data. If None, only raw fetching
                    is done without LLM analysis.

        Returns:
            Dict mapping model IDs to capability scores.
        """
        all_content: list[tuple[str, str]] = []

        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            for source in BENCHMARK_SOURCES:
                try:
                    resp = await client.get(source["url"])
                    resp.raise_for_status()
                    # Take first 10k chars of text content
                    text = resp.text[:10000]
                    all_content.append((source["name"], text))
                    logger.info("Fetched benchmark data from %s", source["name"])
                except Exception as e:
                    logger.warning("Failed to fetch %s: %s", source["name"], e)

        if not all_content:
            logger.warning("No benchmark sources available; keeping cached data")
            return self._scores

        # Use LLM to analyze if router is available
        if router:
            combined_scores = await self._analyze_with_llm(router, all_content)
            if combined_scores:
                self._scores = combined_scores
        else:
            logger.info("No router available for LLM analysis; skipping score extraction")

        self._last_research = time.time()
        self._save_cache()
        logger.info("Research complete: %d models scored", len(self._scores))
        return self._scores

    def needs_research(self) -> bool:
        """Check whether research should be re-run."""
        if not self._scores:
            return True
        return (time.time() - self._last_research) > self.interval_seconds

    def get_scores(self) -> dict[str, dict[str, float]]:
        """Return the current research scores."""
        return self._scores.copy()

    def get_score(self, model_id: str, capability: str) -> float:
        """Get a specific model's score for a capability.

        Falls back to checking partial matches (e.g., 'llama-4' matches
        'meta-llama/llama-4-maverick').
        """
        # Exact match first
        if model_id in self._scores:
            return self._scores[model_id].get(capability, 0.5)

        # Partial match
        model_lower = model_id.lower()
        for key, scores in self._scores.items():
            if model_lower in key.lower() or key.lower() in model_lower:
                return scores.get(capability, 0.5)

        return 0.5  # Neutral default

    # -- LLM analysis ---------------------------------------------------------

    async def _analyze_with_llm(
        self,
        router,
        sources: list[tuple[str, str]],
    ) -> dict[str, dict[str, float]]:
        """Use an LLM to extract structured scores from benchmark data."""
        combined: dict[str, dict[str, float]] = {}

        for source_name, content in sources:
            prompt = RESEARCH_PROMPT_TEMPLATE.format(
                source_name=source_name,
                content=content,
            )

            try:
                response, _ = await router.complete(
                    "or-free-deepseek-chat",  # Use cheap model for analysis
                    [
                        {"role": "system", "content": RESEARCH_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                )

                scores = self._parse_scores(response)
                # Merge scores (average if model appears in multiple sources)
                for model_id, caps in scores.items():
                    if model_id not in combined:
                        combined[model_id] = {}
                    for cap, score in caps.items():
                        if cap in combined[model_id]:
                            combined[model_id][cap] = (combined[model_id][cap] + score) / 2
                        else:
                            combined[model_id][cap] = score

            except Exception as e:
                logger.warning("LLM analysis failed for %s: %s", source_name, e)

        return combined

    @staticmethod
    def _parse_scores(response: str) -> dict[str, dict[str, float]]:
        """Extract JSON scores from LLM response."""
        # Try to find JSON in the response
        text = response.strip()

        # Look for JSON block
        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start)
            text = text[start:end].strip()
        elif "```" in text:
            start = text.index("```") + 3
            end = text.index("```", start)
            text = text[start:end].strip()

        # Find the outermost { ... }
        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start >= 0 and brace_end > brace_start:
            text = text[brace_start : brace_end + 1]

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Failed to parse scores JSON from LLM response")
            return {}

        # Validate and clamp scores
        result: dict[str, dict[str, float]] = {}
        valid_caps = {"coding", "reasoning", "writing", "general"}

        for model_id, scores in data.items():
            if not isinstance(scores, dict):
                continue
            clean: dict[str, float] = {}
            for cap, val in scores.items():
                if cap in valid_caps:
                    try:
                        clean[cap] = max(0.0, min(1.0, float(val)))
                    except (ValueError, TypeError):
                        pass
            if clean:
                result[str(model_id)] = clean

        return result

    # -- Cache ----------------------------------------------------------------

    def _save_cache(self):
        """Persist research scores to disk."""
        self.research_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "last_research": self._last_research,
            "scores": self._scores,
        }
        self.research_path.write_text(json.dumps(payload, indent=2))

    def _load_cache(self):
        """Load research scores from disk."""
        if not self.research_path.exists():
            return
        try:
            data = json.loads(self.research_path.read_text())
            self._last_research = data.get("last_research", 0.0)
            self._scores = data.get("scores", {})
            logger.debug("Loaded research data: %d models", len(self._scores))
        except Exception as e:
            logger.warning("Failed to load research cache: %s", e)
