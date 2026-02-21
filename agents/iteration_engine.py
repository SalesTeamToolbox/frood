"""
Iteration engine — Primary -> Critic -> Revise loop.

The primary model generates output, the critic reviews it, and the
primary revises based on feedback. Repeats until the critic approves
or max iterations are reached.

Includes retry with exponential backoff on API failures and
convergence detection to avoid wasting tokens on stuck loops.
"""

import asyncio
import logging
from dataclasses import dataclass, field

from agents.model_router import ModelRouter

logger = logging.getLogger("agent42.iteration")


@dataclass
class IterationResult:
    """Result of a single iteration cycle."""
    iteration: int
    primary_output: str
    critic_feedback: str = ""
    approved: bool = False


@dataclass
class IterationHistory:
    """Full history of all iterations for a task."""
    iterations: list[IterationResult] = field(default_factory=list)
    final_output: str = ""
    total_iterations: int = 0

    def summary(self) -> str:
        lines = [f"Total iterations: {self.total_iterations}"]
        for it in self.iterations:
            status = "APPROVED" if it.approved else "NEEDS REVISION"
            lines.append(f"\n--- Iteration {it.iteration} [{status}] ---")
            lines.append(f"Output preview: {it.primary_output[:200]}...")
            if it.critic_feedback:
                lines.append(f"Critic: {it.critic_feedback[:200]}...")
        return "\n".join(lines)


FALLBACK_MODEL = "or-free-llama4-maverick"  # General-purpose fallback
MAX_RETRIES = 3
SIMILARITY_THRESHOLD = 0.85  # For convergence detection


class IterationEngine:
    """Run the primary -> critic -> revise loop."""

    def __init__(self, router: ModelRouter):
        self.router = router

    async def _complete_with_retry(
        self, model: str, messages: list[dict], retries: int = MAX_RETRIES,
    ) -> str:
        """Call router.complete with exponential backoff retry and model fallback."""
        last_error = None
        for attempt in range(retries):
            try:
                return await self.router.complete(model, messages)
            except Exception as e:
                last_error = e
                wait = 2 ** attempt  # 1s, 2s, 4s
                logger.warning(
                    f"API call failed (attempt {attempt + 1}/{retries}, "
                    f"model={model}): {e} — retrying in {wait}s"
                )
                await asyncio.sleep(wait)

        # All retries failed — try fallback model once
        if model != FALLBACK_MODEL:
            logger.warning(f"Falling back to {FALLBACK_MODEL} after {retries} failures")
            try:
                return await self.router.complete(FALLBACK_MODEL, messages)
            except Exception as e:
                logger.error(f"Fallback model also failed: {e}")

        raise RuntimeError(
            f"API call failed after {retries} retries + fallback: {last_error}"
        )

    @staticmethod
    def _feedback_similarity(a: str, b: str) -> float:
        """Simple word-overlap ratio to detect repeated critic feedback."""
        if not a or not b:
            return 0.0
        words_a = set(a.lower().split())
        words_b = set(b.lower().split())
        if not words_a or not words_b:
            return 0.0
        overlap = len(words_a & words_b)
        return overlap / max(len(words_a), len(words_b))

    async def run(
        self,
        task_description: str,
        primary_model: str,
        critic_model: str | None,
        max_iterations: int,
        system_prompt: str = "",
        on_iteration: callable = None,
    ) -> IterationHistory:
        """
        Execute the iteration loop.

        Args:
            task_description: What the agent should do.
            primary_model: Model key for the primary worker.
            critic_model: Model key for the critic (None to skip critic).
            max_iterations: Hard cap on iteration count.
            system_prompt: Optional system-level context.
            on_iteration: Optional async callback(IterationResult) for live updates.
        """
        history = IterationHistory()
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": task_description})

        prev_feedback = ""

        for i in range(1, max_iterations + 1):
            logger.info(f"Iteration {i}/{max_iterations} — primary: {primary_model}")

            # Primary pass (with retry + fallback)
            primary_output = await self._complete_with_retry(primary_model, messages)

            result = IterationResult(iteration=i, primary_output=primary_output)

            # Critic pass (if configured)
            if critic_model:
                critic_feedback = await self._critic_pass(
                    critic_model, task_description, primary_output
                )
                result.critic_feedback = critic_feedback
                result.approved = self._is_approved(critic_feedback)

                # Convergence detection: if critic keeps giving the same feedback,
                # accept the output to avoid burning tokens on a stuck loop
                if (
                    not result.approved
                    and prev_feedback
                    and self._feedback_similarity(critic_feedback, prev_feedback)
                    > SIMILARITY_THRESHOLD
                ):
                    logger.warning(
                        f"Convergence detected at iteration {i} — "
                        "critic feedback is repeating. Accepting output."
                    )
                    result.approved = True

                prev_feedback = critic_feedback
            else:
                result.approved = True

            history.iterations.append(result)

            if on_iteration:
                await on_iteration(result)

            if result.approved:
                logger.info(f"Critic approved at iteration {i}")
                history.final_output = primary_output
                history.total_iterations = i
                return history

            # Feed critic feedback back to primary for revision
            messages.append({"role": "assistant", "content": primary_output})
            messages.append({
                "role": "user",
                "content": (
                    f"The reviewer provided this feedback:\n\n{critic_feedback}\n\n"
                    "Please revise your output to address these concerns."
                ),
            })

        # Max iterations reached — use the last output
        history.final_output = primary_output
        history.total_iterations = max_iterations
        logger.warning(f"Max iterations ({max_iterations}) reached without full approval")
        return history

    async def _critic_pass(
        self, critic_model: str, original_task: str, output: str
    ) -> str:
        """Have the critic model review the primary's output."""
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a strict code/content reviewer. Evaluate the following output "
                    "for correctness, completeness, security issues, and quality. "
                    "If everything looks good, start your response with 'APPROVED'. "
                    "Otherwise, provide specific, actionable feedback for improvement."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Original task:\n{original_task}\n\n"
                    f"Output to review:\n{output}"
                ),
            },
        ]
        return await self._complete_with_retry(critic_model, messages)

    @staticmethod
    def _is_approved(critic_feedback: str) -> bool:
        """Check if the critic approved the output."""
        first_line = critic_feedback.strip().split("\n")[0].upper()
        return first_line.startswith("APPROVED")
