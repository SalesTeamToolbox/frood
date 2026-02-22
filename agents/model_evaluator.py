"""
Model evaluator — tracks per-model per-task-type outcomes and ranks models.

Three responsibilities:
1. **Record outcomes**: after each task, record success/failure, iteration
   count, and critic scores per model per task type.
2. **Rank models**: compute composite scores and produce a dynamic routing
   table that the ModelRouter consults.
3. **Trial system**: new/unproven models are assigned to a small percentage
   of tasks for evaluation before being promoted.
"""

from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("agent42.model_evaluator")


@dataclass
class ModelOutcome:
    """A single recorded task outcome for a model."""

    model_key: str
    task_type: str
    success: bool
    iterations: int
    max_iterations: int
    critic_score: float | None = None  # 0-1 scale from last critic pass
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


@dataclass
class ModelStats:
    """Aggregated statistics for a model on a specific task type."""

    model_key: str
    task_type: str
    total_tasks: int = 0
    successes: int = 0
    total_iterations: int = 0
    total_max_iterations: int = 0
    critic_scores: list[float] = field(default_factory=list)
    research_score: float = 0.0  # External benchmark prior (0-1)

    @property
    def success_rate(self) -> float:
        if self.total_tasks == 0:
            return 0.0
        return self.successes / self.total_tasks

    @property
    def iteration_efficiency(self) -> float:
        """How efficiently the model uses iterations (fewer = better). Returns 0-1."""
        if self.total_max_iterations == 0:
            return 0.5
        ratio = self.total_iterations / self.total_max_iterations
        # Invert: lower ratio = higher efficiency
        return max(0.0, min(1.0, 1.0 - ratio))

    @property
    def critic_avg(self) -> float:
        if not self.critic_scores:
            return 0.5  # Neutral default
        return sum(self.critic_scores) / len(self.critic_scores)

    @property
    def composite_score(self) -> float:
        """Weighted composite score (higher = better).

        Weights:
          40% success rate
          30% iteration efficiency
          20% critic average
          10% research benchmark score
        """
        return (
            0.4 * self.success_rate
            + 0.3 * self.iteration_efficiency
            + 0.2 * self.critic_avg
            + 0.1 * self.research_score
        )

    def to_dict(self) -> dict:
        return {
            "model_key": self.model_key,
            "task_type": self.task_type,
            "total_tasks": self.total_tasks,
            "successes": self.successes,
            "success_rate": round(self.success_rate, 3),
            "iteration_efficiency": round(self.iteration_efficiency, 3),
            "critic_avg": round(self.critic_avg, 3),
            "research_score": round(self.research_score, 3),
            "composite_score": round(self.composite_score, 3),
        }


class ModelEvaluator:
    """Records task outcomes and ranks models dynamically."""

    def __init__(
        self,
        performance_path: Path | str = "data/model_performance.json",
        routing_path: Path | str = "data/dynamic_routing.json",
        research_path: Path | str = "data/model_research.json",
        trial_percentage: int = 10,
        min_trials: int = 5,
    ):
        self.performance_path = Path(performance_path)
        self.routing_path = Path(routing_path)
        self.research_path = Path(research_path)
        self.trial_percentage = trial_percentage
        self.min_trials = min_trials

        # {(model_key, task_type): ModelStats}
        self._stats: dict[tuple[str, str], ModelStats] = {}

        # Track which models are being trialed
        # {model_key: {"task_types_trialed": [...], "completions": int}}
        self._trials: dict[str, dict] = {}

        self._load_performance()

    # -- Recording outcomes ---------------------------------------------------

    def record_outcome(
        self,
        model_key: str,
        task_type: str,
        success: bool,
        iterations: int,
        max_iterations: int,
        critic_score: float | None = None,
    ):
        """Record a task outcome for a specific model and task type."""
        key = (model_key, task_type)
        if key not in self._stats:
            self._stats[key] = ModelStats(model_key=model_key, task_type=task_type)

        stats = self._stats[key]
        stats.total_tasks += 1
        if success:
            stats.successes += 1
        stats.total_iterations += iterations
        stats.total_max_iterations += max_iterations
        if critic_score is not None:
            stats.critic_scores.append(critic_score)
            # Keep only last 50 scores to avoid unbounded growth
            if len(stats.critic_scores) > 50:
                stats.critic_scores = stats.critic_scores[-50:]

        # Update trial tracking
        if model_key in self._trials:
            self._trials[model_key]["completions"] = (
                self._trials[model_key].get("completions", 0) + 1
            )
            if task_type not in self._trials[model_key].get("task_types_trialed", []):
                self._trials[model_key].setdefault("task_types_trialed", []).append(task_type)

        self._save_performance()

        logger.info(
            "Recorded outcome: %s on %s — %s (score=%.3f, %d tasks total)",
            model_key,
            task_type,
            "success" if success else "failure",
            stats.composite_score,
            stats.total_tasks,
        )

    # -- Ranking & routing ----------------------------------------------------

    def get_ranking(self, task_type: str) -> list[ModelStats]:
        """Get all models ranked by composite score for a task type (best first)."""
        stats = [s for (_, tt), s in self._stats.items() if tt == task_type]
        return sorted(stats, key=lambda s: s.composite_score, reverse=True)

    def get_best_model(self, task_type: str) -> str | None:
        """Return the best-performing model key for a task type.

        Only returns models with at least ``min_trials`` completions.
        """
        ranking = self.get_ranking(task_type)
        for stats in ranking:
            if stats.total_tasks >= self.min_trials:
                return stats.model_key
        return None

    def rerank_all(self) -> dict:
        """Recompute rankings for all task types and write dynamic routing file.

        Returns the dynamic routing dict.
        """
        # Inject research scores if available
        self._apply_research_scores()

        task_types = set(tt for _, tt in self._stats.keys())
        routing: dict[str, dict] = {}

        for task_type in task_types:
            best = self.get_best_model(task_type)
            if best:
                ranking = self.get_ranking(task_type)
                top = ranking[0] if ranking else None
                routing[task_type] = {
                    "primary": best,
                    "critic": self._pick_critic(task_type, best),
                    "confidence": round(top.composite_score, 3) if top else 0.0,
                    "sample_size": top.total_tasks if top else 0,
                    "max_iterations": 8,  # Default; could adapt based on efficiency
                }

        result = {
            "last_updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "routing": routing,
            "trials": self._trials,
        }

        self.routing_path.parent.mkdir(parents=True, exist_ok=True)
        self.routing_path.write_text(json.dumps(result, indent=2))
        logger.info("Dynamic routing updated for %d task types", len(routing))
        return result

    # -- Trial system ---------------------------------------------------------

    def select_trial_model(
        self,
        task_type: str,
        available_free_models: list[str],
    ) -> str | None:
        """Maybe return an unproven model to trial.

        Returns a model key with probability ``trial_percentage``%, or None.
        Only selects models that have fewer than ``min_trials`` completions
        for the given task type.
        """
        if random.randint(1, 100) > self.trial_percentage:
            return None

        # Find unproven models
        unproven = []
        for model_key in available_free_models:
            key = (model_key, task_type)
            stats = self._stats.get(key)
            if stats is None or stats.total_tasks < self.min_trials:
                unproven.append(model_key)

        if not unproven:
            return None

        selected = random.choice(unproven)

        # Track the trial
        if selected not in self._trials:
            self._trials[selected] = {"task_types_trialed": [], "completions": 0}
        if task_type not in self._trials[selected].get("task_types_trialed", []):
            self._trials[selected].setdefault("task_types_trialed", []).append(task_type)

        logger.info("Trial model selected: %s for task type %s", selected, task_type)
        return selected

    # -- Research score integration -------------------------------------------

    def _apply_research_scores(self):
        """Load research scores and apply as priors to model stats."""
        if not self.research_path.exists():
            return

        try:
            research = json.loads(self.research_path.read_text())
        except Exception:
            return

        # Map task types to research capability categories
        _task_to_cap = {
            "coding": "coding",
            "debugging": "coding",
            "refactoring": "coding",
            "research": "reasoning",
            "strategy": "reasoning",
            "data_analysis": "reasoning",
            "documentation": "writing",
            "marketing": "writing",
            "email": "writing",
            "content": "writing",
            "design": "general",
            "project_management": "general",
        }

        for (model_key, task_type), stats in self._stats.items():
            cap = _task_to_cap.get(task_type, "general")
            # Try matching by model_id (research data uses OpenRouter model IDs)
            for research_model_id, scores in research.items():
                if isinstance(scores, dict) and model_key in research_model_id:
                    stats.research_score = scores.get(cap, scores.get("general", 0.0))
                    break

    def _pick_critic(self, task_type: str, primary_model: str) -> str | None:
        """Pick the best critic model (different from primary) for a task type."""
        ranking = self.get_ranking(task_type)
        for stats in ranking:
            if stats.model_key != primary_model and stats.total_tasks >= self.min_trials:
                return stats.model_key
        return None

    # -- Persistence ----------------------------------------------------------

    def _save_performance(self):
        """Write performance data to disk."""
        self.performance_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "stats": {
                f"{mk}|{tt}": stats.to_dict() | {"critic_scores": stats.critic_scores}
                for (mk, tt), stats in self._stats.items()
            },
            "trials": self._trials,
        }
        self.performance_path.write_text(json.dumps(data, indent=2))

    def _load_performance(self):
        """Load performance data from disk."""
        if not self.performance_path.exists():
            return
        try:
            data = json.loads(self.performance_path.read_text())
        except Exception as e:
            logger.warning("Failed to load performance data: %s", e)
            return

        for key_str, sdata in data.get("stats", {}).items():
            parts = key_str.split("|", 1)
            if len(parts) != 2:
                continue
            mk, tt = parts
            stats = ModelStats(
                model_key=mk,
                task_type=tt,
                total_tasks=sdata.get("total_tasks", 0),
                successes=sdata.get("successes", 0),
                total_iterations=int(
                    sdata.get("total_tasks", 0)
                    * sdata.get("total_tasks", 0)
                    * (1 - sdata.get("iteration_efficiency", 0.5))
                )
                if "total_iterations" not in sdata
                else sdata.get("total_iterations", 0),
                total_max_iterations=sdata.get(
                    "total_max_iterations", sdata.get("total_tasks", 0) * 8
                ),
                critic_scores=sdata.get("critic_scores", []),
                research_score=sdata.get("research_score", 0.0),
            )
            self._stats[(mk, tt)] = stats

        self._trials = data.get("trials", {})
        logger.debug("Loaded performance data: %d model-task pairs", len(self._stats))
