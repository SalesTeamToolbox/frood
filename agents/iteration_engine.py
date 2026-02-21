"""
Iteration engine — Primary -> Tool Execution -> Critic -> Revise loop.

The primary model generates output (which may include tool calls), tools
are executed and results fed back, then the critic reviews. If the critic
has feedback the primary revises. Repeats until approved or max iterations.

Includes retry with exponential backoff on API failures and
convergence detection to avoid wasting tokens on stuck loops.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field

from agents.model_router import ModelRouter

logger = logging.getLogger("agent42.iteration")


@dataclass
class ToolCallRecord:
    """Record of a single tool call during an iteration."""
    tool_name: str
    arguments: dict
    result: str
    success: bool


@dataclass
class IterationResult:
    """Result of a single iteration cycle."""
    iteration: int
    primary_output: str
    critic_feedback: str = ""
    approved: bool = False
    tool_calls: list[ToolCallRecord] = field(default_factory=list)


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
            if it.tool_calls:
                lines.append(f"Tool calls: {len(it.tool_calls)}")
                for tc in it.tool_calls:
                    status_str = "OK" if tc.success else "FAIL"
                    lines.append(f"  [{status_str}] {tc.tool_name}")
            if it.critic_feedback:
                lines.append(f"Critic: {it.critic_feedback[:200]}...")
        return "\n".join(lines)


FALLBACK_MODEL = "or-free-llama4-maverick"  # General-purpose fallback
MAX_RETRIES = 3
MAX_TOOL_ROUNDS = 10  # Max tool call rounds per iteration
SIMILARITY_THRESHOLD = 0.85  # For convergence detection

# Task-aware critic prompts — each task type gets a specialized reviewer
CRITIC_PROMPTS: dict[str, str] = {
    "coding": (
        "You are a strict code reviewer. Evaluate for correctness, security, "
        "test coverage, and adherence to project conventions. "
        "If everything looks good, start your response with 'APPROVED'. "
        "Otherwise, provide specific, actionable feedback for improvement."
    ),
    "debugging": (
        "You are a debugging expert reviewer. Verify the root cause is correctly "
        "identified, the fix is minimal and correct, and no regressions are introduced. "
        "If good, start your response with 'APPROVED'. "
        "Otherwise, provide specific feedback."
    ),
    "research": (
        "You are a research quality reviewer. Evaluate for thoroughness, source "
        "credibility, balanced analysis, and actionable recommendations. "
        "If good, start your response with 'APPROVED'. "
        "Otherwise, provide specific feedback on gaps or weaknesses."
    ),
    "refactoring": (
        "You are a refactoring reviewer. Verify behavior is preserved, code "
        "structure is improved, and tests still pass. "
        "If good, start your response with 'APPROVED'. "
        "Otherwise, provide specific feedback."
    ),
    "documentation": (
        "You are a technical writing reviewer. Evaluate for clarity, completeness, "
        "accuracy, and developer-friendliness. "
        "If good, start your response with 'APPROVED'. "
        "Otherwise, provide specific feedback."
    ),
    "marketing": (
        "You are a marketing strategist reviewer. Evaluate for audience fit, "
        "persuasive language, clear value proposition, and brand consistency. "
        "If good, start your response with 'APPROVED'. "
        "Otherwise, provide specific feedback on messaging and positioning."
    ),
    "email": (
        "You are a communications reviewer. Evaluate for tone, clarity, "
        "call-to-action effectiveness, and professionalism. "
        "If good, start your response with 'APPROVED'. "
        "Otherwise, provide specific feedback."
    ),
    "design": (
        "You are a design reviewer. Evaluate for visual consistency, accessibility, "
        "user experience, and brand alignment. Check hierarchy, spacing, color "
        "usage, and typography choices. "
        "If good, start your response with 'APPROVED'. "
        "Otherwise, provide specific, actionable design feedback."
    ),
    "content": (
        "You are an editorial reviewer. Evaluate for clarity, engagement, grammar, "
        "logical flow, and audience appropriateness. Check that the content delivers "
        "value and has a clear structure. "
        "If good, start your response with 'APPROVED'. "
        "Otherwise, provide specific editorial feedback."
    ),
    "strategy": (
        "You are a strategy reviewer. Evaluate for market insight depth, competitive "
        "awareness, feasibility, and actionable next steps. Check that frameworks "
        "are applied correctly and conclusions are evidence-based. "
        "If good, start your response with 'APPROVED'. "
        "Otherwise, provide specific strategic feedback."
    ),
    "data_analysis": (
        "You are a data analysis reviewer. Evaluate for statistical validity, clear "
        "visualizations, correct interpretations, and actionable insights. "
        "Check methodology and ensure conclusions are supported by the data. "
        "If good, start your response with 'APPROVED'. "
        "Otherwise, provide specific analytical feedback."
    ),
    "project_management": (
        "You are a project management reviewer. Evaluate for completeness, realistic "
        "timelines, risk identification, clear deliverables, and resource allocation. "
        "If good, start your response with 'APPROVED'. "
        "Otherwise, provide specific planning feedback."
    ),
}

# Default critic prompt for unknown task types
_DEFAULT_CRITIC_PROMPT = (
    "You are a strict content reviewer. Evaluate the following output "
    "for correctness, completeness, and quality. "
    "If everything looks good, start your response with 'APPROVED'. "
    "Otherwise, provide specific, actionable feedback for improvement."
)


class IterationEngine:
    """Run the primary -> tool exec -> critic -> revise loop."""

    def __init__(self, router: ModelRouter, tool_registry=None):
        self.router = router
        self.tool_registry = tool_registry

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

    async def _complete_with_tools_retry(
        self, model: str, messages: list[dict], tools: list[dict],
        retries: int = MAX_RETRIES,
    ):
        """Call router.complete_with_tools with retry logic."""
        last_error = None
        for attempt in range(retries):
            try:
                return await self.router.complete_with_tools(model, messages, tools)
            except Exception as e:
                last_error = e
                wait = 2 ** attempt
                logger.warning(
                    f"Tool API call failed (attempt {attempt + 1}/{retries}, "
                    f"model={model}): {e} — retrying in {wait}s"
                )
                await asyncio.sleep(wait)

        # Fallback without tools (degrade to text-only)
        logger.warning(f"Tool calling failed after {retries} retries, falling back to text-only")
        return await self.router.complete_with_tools(
            FALLBACK_MODEL, messages, []
        )

    async def _execute_tool_calls(self, tool_calls) -> list[ToolCallRecord]:
        """Execute tool calls from the LLM response and return records."""
        records = []
        if not self.tool_registry or not tool_calls:
            return records

        for tc in tool_calls:
            tool_name = tc.function.name
            try:
                arguments = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                records.append(ToolCallRecord(
                    tool_name=tool_name, arguments={},
                    result="Invalid JSON in tool arguments", success=False,
                ))
                continue

            logger.info(f"Executing tool: {tool_name}({list(arguments.keys())})")
            result = await self.tool_registry.execute(tool_name, **arguments)

            records.append(ToolCallRecord(
                tool_name=tool_name,
                arguments=arguments,
                result=result.content,
                success=result.success,
            ))

        return records

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
        task_type: str = "coding",
    ) -> IterationHistory:
        """
        Execute the iteration loop with tool calling support.

        If a tool_registry is configured, tool schemas are passed to the LLM
        and tool calls are executed automatically. The LLM receives tool results
        and can make additional tool calls before producing its final answer.

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

        # Get tool schemas if registry is available
        tool_schemas = []
        if self.tool_registry:
            tool_schemas = self.tool_registry.all_schemas()

        prev_feedback = ""

        for i in range(1, max_iterations + 1):
            logger.info(f"Iteration {i}/{max_iterations} — primary: {primary_model}")

            all_tool_records = []

            if tool_schemas:
                # Tool-calling loop: let the model make tool calls until it produces text
                primary_output = await self._run_tool_loop(
                    primary_model, messages, tool_schemas, all_tool_records
                )
            else:
                # Text-only mode (no tools or model doesn't support tools)
                primary_output = await self._complete_with_retry(primary_model, messages)

            result = IterationResult(
                iteration=i,
                primary_output=primary_output,
                tool_calls=all_tool_records,
            )

            # Critic pass (if configured)
            if critic_model:
                critic_feedback = await self._critic_pass(
                    critic_model, task_description, primary_output,
                    task_type=task_type,
                )
                result.critic_feedback = critic_feedback
                result.approved = self._is_approved(critic_feedback)

                # Convergence detection
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

    async def _run_tool_loop(
        self,
        model: str,
        messages: list[dict],
        tool_schemas: list[dict],
        all_tool_records: list[ToolCallRecord],
    ) -> str:
        """Run the tool-calling loop until the model produces a text response.

        The model can make multiple rounds of tool calls. After each round,
        tool results are appended to the conversation and the model is called
        again. Stops when the model produces a text response (no tool calls)
        or MAX_TOOL_ROUNDS is reached.
        """
        working_messages = list(messages)

        for round_num in range(MAX_TOOL_ROUNDS):
            response = await self._complete_with_tools_retry(
                model, working_messages, tool_schemas
            )

            choice = response.choices[0]
            message = choice.message

            # If no tool calls, return the text content
            if not message.tool_calls:
                text = message.content or ""
                # Append to parent conversation for context continuity
                messages.append({"role": "assistant", "content": text})
                return text

            # Process tool calls
            assistant_msg = {"role": "assistant", "content": message.content or ""}
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in message.tool_calls
            ]
            working_messages.append(assistant_msg)

            records = await self._execute_tool_calls(message.tool_calls)
            all_tool_records.extend(records)

            # Add tool results as tool response messages
            for tc, record in zip(message.tool_calls, records):
                working_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": record.result,
                })

            logger.info(
                f"Tool round {round_num + 1}: {len(records)} calls, "
                f"continuing..."
            )

        # Max tool rounds reached — ask model for final answer without tools
        working_messages.append({
            "role": "user",
            "content": "Please provide your final answer now based on the tool results above.",
        })
        final = await self._complete_with_retry(model, working_messages)
        messages.append({"role": "assistant", "content": final})
        return final

    async def _critic_pass(
        self, critic_model: str, original_task: str, output: str,
        task_type: str = "coding",
    ) -> str:
        """Have the critic model review the primary's output."""
        critic_prompt = CRITIC_PROMPTS.get(task_type, _DEFAULT_CRITIC_PROMPT)
        messages = [
            {
                "role": "system",
                "content": critic_prompt,
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
