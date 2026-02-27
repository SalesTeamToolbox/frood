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
import os
from dataclasses import dataclass, field

from agents.model_router import ModelRouter
from core.approval_gate import ProtectedAction
from providers.registry import PROVIDERS, ProviderType, SpendingLimitExceeded

logger = logging.getLogger("agent42.iteration")


# Tools that require human approval before execution.
# Maps tool name to the ProtectedAction type.
_TOOL_TO_ACTION: dict[str, ProtectedAction] = {
    "http_request": ProtectedAction.EXTERNAL_API,
}

# Actions within tools that need approval (checked via arguments)
_GIT_PUSH_KEYWORDS = {"push"}
_FILE_DELETE_KEYWORDS = {"delete", "remove"}


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
class TokenAccumulator:
    """Accumulates token usage across LLM calls within a task."""

    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    by_model: dict = field(default_factory=dict)

    def record(self, model_key: str, prompt_tokens: int, completion_tokens: int):
        """Record token usage from a single LLM call."""
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        if model_key not in self.by_model:
            self.by_model[model_key] = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}
        self.by_model[model_key]["prompt_tokens"] += prompt_tokens
        self.by_model[model_key]["completion_tokens"] += completion_tokens
        self.by_model[model_key]["calls"] += 1

    def to_dict(self) -> dict:
        return {
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_prompt_tokens + self.total_completion_tokens,
            "by_model": dict(self.by_model),
        }


@dataclass
class IterationHistory:
    """Full history of all iterations for a task."""

    iterations: list[IterationResult] = field(default_factory=list)
    final_output: str = ""
    total_iterations: int = 0
    token_usage: dict = field(default_factory=dict)

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

    def __init__(
        self,
        router: ModelRouter,
        tool_registry=None,
        approval_gate=None,
        agent_id: str = "default",
        extension_loader=None,
    ):
        self.router = router
        self.tool_registry = tool_registry
        self.approval_gate = approval_gate
        self.agent_id = agent_id
        self.extension_loader = extension_loader
        # Models that failed during the current task — excluded from fallback attempts.
        # Reset at the start of each run(). Prevents wasting time retrying models
        # that are known-broken (e.g. Gemini daily quota exhausted, OR model 404'd).
        self._failed_models: set[str] = set()

    def _is_model_unavailable(self, error: Exception) -> bool:
        """Return True for 404/endpoint-not-found errors that should not be retried."""
        msg = str(error).lower()
        return "404" in msg or "no endpoints found" in msg or "endpoint not found" in msg

    def _is_auth_error(self, error: Exception) -> bool:
        """Return True for 401/auth errors that should not be retried (key is wrong/missing)."""
        msg = str(error).lower()
        return (
            "401" in msg
            or "unauthorized" in msg
            or "invalid api key" in msg
            or "authentication" in msg
            or ("forbidden" in msg and "403" in msg)
        )

    def _is_rate_limited(self, error: Exception) -> bool:
        """Return True for 429 rate-limit / quota-exhausted errors.

        Covers both OpenRouter RPM limits and Gemini daily quota exhaustion
        (RESOURCE_EXHAUSTED with limit: 0). Retrying the *same* model wastes
        time — the caller should switch to a fallback model immediately.
        """
        msg = str(error).lower()
        return (
            "429" in msg
            or "rate limit" in msg
            or "rate_limit" in msg
            or "resource_exhausted" in msg
            or "quota" in msg
        )

    def _is_payment_error(self, error: Exception) -> bool:
        """Return True for 402 Payment Required / spending-limit errors.

        OpenRouter returns 402 when a backend provider (e.g. Venice) rejects
        because the API key's USD spending limit was exceeded. The key belongs
        to OpenRouter (is_byok=False), so this is an infrastructure issue on
        the OR side — retrying the same model is pointless.
        """
        msg = str(error).lower()
        return (
            "402" in msg
            or "spend limit" in msg
            or "spending limit" in msg
            or "payment required" in msg
        )

    def _get_fallback_models(self, exclude: set[str]) -> list[str]:
        """Return an ordered list of fallback models for cross-provider failover.

        Priority order:
        1. Configured native providers (Gemini first — generous free tier)
        2. OpenRouter free models (diverse but rate-limited)

        Native providers are listed first because they use independent API keys
        and typically have higher rate limits than OpenRouter's free tier.

        Models marked unhealthy by the health check system are skipped.
        """
        # Get unhealthy models from catalog health checks (if available)
        unhealthy = self._get_unhealthy_models()

        # Native providers — tried first (independent keys, better rate limits)
        native_fallbacks: list[tuple[ProviderType, str]] = [
            (ProviderType.GEMINI, "gemini-2-flash"),
            (ProviderType.OPENAI, "gpt-4o-mini"),
            (ProviderType.ANTHROPIC, "claude-haiku"),
            (ProviderType.DEEPSEEK, "deepseek-chat"),
        ]
        native_candidates: list[str] = []
        for provider_type, model_key in native_fallbacks:
            if model_key in exclude or model_key in unhealthy:
                continue
            spec = PROVIDERS.get(provider_type)
            if spec and os.getenv(spec.api_key_env):
                native_candidates.append(model_key)

        # OpenRouter free models — tried second
        static = [
            "or-free-auto",
            "or-free-llama-70b",
            "or-free-gemma-27b",
            "or-free-mistral-small",
            "or-free-gemini-flash",
        ]
        openrouter_candidates: list[str] = []
        try:
            all_free = self.router.free_models()
            keys = [m["key"] for m in all_free if isinstance(m, dict) and m.get("key")]
            openrouter_candidates = [k for k in keys if k not in exclude and k not in unhealthy]
        except Exception:
            pass

        if not openrouter_candidates:
            openrouter_candidates = [m for m in static if m not in exclude and m not in unhealthy]

        return native_candidates + openrouter_candidates[:8]

    def _get_unhealthy_models(self) -> set[str]:
        """Get the set of unhealthy model keys from the catalog health check."""
        try:
            catalog = getattr(self.router, "_catalog", None)
            if catalog:
                return catalog.unhealthy_model_keys()
        except Exception:
            pass
        return set()

    async def _complete_with_retry(
        self,
        model: str,
        messages: list[dict],
        retries: int = MAX_RETRIES,
    ) -> str:
        """Call router.complete with exponential backoff retry and dynamic model fallback.

        Errors that skip retries immediately (go straight to fallback):
        - 404 / endpoint-not-found — model doesn't exist
        - 401 / auth errors — key is wrong (retrying wastes quota)
        - 402 / payment error — provider spending limit hit (OR infrastructure issue)
        - 429 / rate-limited — model at RPM cap (retrying the *same* model wastes time)

        Models that fail are tracked in ``_failed_models`` for the lifetime of the
        task so they are excluded from fallback lists in subsequent iterations.
        """
        # If this model already failed in a previous iteration, skip straight to fallback
        if model in self._failed_models:
            logger.info(f"Model {model} failed earlier this task, skipping to fallback")
            return await self._complete_from_fallbacks(model, messages)

        last_error = None
        for attempt in range(retries):
            try:
                text, usage = await self.router.complete(model, messages)
                if usage and self._token_acc:
                    self._token_acc.record(
                        usage["model_key"], usage["prompt_tokens"], usage["completion_tokens"]
                    )
                return text
            except SpendingLimitExceeded:
                raise  # Don't retry spending limits
            except Exception as e:
                last_error = e
                if self._is_model_unavailable(e):
                    logger.warning(f"Model {model} unavailable (404), skipping retries: {e}")
                    self._failed_models.add(model)
                    break
                if self._is_auth_error(e):
                    logger.warning(f"Auth error for {model} (401), skipping retries: {e}")
                    self._failed_models.add(model)
                    break
                if self._is_rate_limited(e):
                    logger.warning(f"Model {model} rate-limited (429), switching to fallback: {e}")
                    self._failed_models.add(model)
                    break
                if self._is_payment_error(e):
                    logger.warning(f"Model {model} payment error (402), switching to fallback: {e}")
                    self._failed_models.add(model)
                    break
                wait = 2**attempt  # 1s, 2s, 4s
                logger.warning(
                    f"API call failed (attempt {attempt + 1}/{retries}, "
                    f"model={model}): {e} — retrying in {wait}s"
                )
                await asyncio.sleep(wait)

        return await self._complete_from_fallbacks(model, messages, last_error)

    async def _complete_from_fallbacks(
        self,
        failed_model: str,
        messages: list[dict],
        last_error: Exception | None = None,
    ) -> str:
        """Try fallback models after the primary model failed.

        Skips models already known to be broken (tracked in _failed_models).
        When auth fails, all OpenRouter models are skipped (provider-wide key).
        """
        primary_auth_failed = last_error is not None and self._is_auth_error(last_error)
        tried: set[str] = self._failed_models | {failed_model}
        for fallback in self._get_fallback_models(exclude=tried):
            # Skip OpenRouter models when the OR key is known to be invalid
            if primary_auth_failed and fallback.startswith("or-"):
                logger.debug(f"Skipping OR fallback {fallback} — provider auth failure")
                tried.add(fallback)
                continue
            try:
                logger.warning(f"Primary model failed; trying fallback: {fallback}")
                text, usage = await self.router.complete(fallback, messages)
                if usage and self._token_acc:
                    self._token_acc.record(
                        usage["model_key"], usage["prompt_tokens"], usage["completion_tokens"]
                    )
                return text
            except SpendingLimitExceeded:
                raise
            except Exception as e:
                logger.warning(f"Fallback {fallback} also failed: {e}")
                tried.add(fallback)
                self._failed_models.add(fallback)
                # If a fallback OR model also gets 401, skip remaining OR models too
                if self._is_auth_error(e) and fallback.startswith("or-"):
                    primary_auth_failed = True
                # Continue trying remaining fallbacks — a different provider may succeed

        raise RuntimeError(f"API call failed — all models exhausted (tried: {tried}): {last_error}")

    async def _complete_with_tools_retry(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict],
        retries: int = MAX_RETRIES,
    ):
        """Call router.complete_with_tools with retry logic and dynamic fallback.

        Skips retries immediately for 404, 401, 402, and 429 errors.
        On full failure, degrades to text-only mode using the first available
        fallback model. When auth fails, OpenRouter fallbacks are skipped
        (invalid key is provider-wide) and native providers are tried directly.
        Failed models are tracked in ``_failed_models`` across iterations.
        """
        # If this model already failed earlier in this task, skip straight to fallback
        if model in self._failed_models:
            logger.info(f"Tool model {model} failed earlier this task, using fallback")
            tried = self._failed_models | {model}
            fallbacks = self._get_fallback_models(exclude=tried)
            fallback = fallbacks[0] if fallbacks else "or-free-auto"
            logger.warning(f"Degrading to text-only with {fallback}")
            return await self.router.complete_with_tools(fallback, messages, [])

        last_error = None
        attempts_made = 0
        for attempt in range(retries):
            attempts_made = attempt + 1
            try:
                return await self.router.complete_with_tools(model, messages, tools)
            except SpendingLimitExceeded:
                raise  # Don't retry spending limits
            except Exception as e:
                last_error = e
                if self._is_model_unavailable(e):
                    logger.warning(f"Tool model {model} unavailable (404), skipping retries: {e}")
                    self._failed_models.add(model)
                    break
                if self._is_auth_error(e):
                    logger.warning(
                        f"Auth error for tool model {model} (401), skipping retries: {e}"
                    )
                    self._failed_models.add(model)
                    break
                if self._is_rate_limited(e):
                    logger.warning(
                        f"Tool model {model} rate-limited (429), switching to fallback: {e}"
                    )
                    self._failed_models.add(model)
                    break
                if self._is_payment_error(e):
                    logger.warning(
                        f"Tool model {model} payment error (402), switching to fallback: {e}"
                    )
                    self._failed_models.add(model)
                    break
                wait = 2**attempt
                logger.warning(
                    f"Tool API call failed (attempt {attempt + 1}/{retries}, "
                    f"model={model}): {e} — retrying in {wait}s"
                )
                await asyncio.sleep(wait)

        # Fallback: try available models in text-only mode (degrade gracefully).
        # If primary auth failed, skip OpenRouter fallbacks — the invalid key is
        # provider-wide, so they will all fail too. Jump straight to native providers.
        primary_auth_failed = last_error is not None and self._is_auth_error(last_error)
        tried: set[str] = self._failed_models | {model}
        fallbacks = self._get_fallback_models(exclude=tried)
        if primary_auth_failed:
            fallbacks = [f for f in fallbacks if not f.startswith("or-")]
        fallback = fallbacks[0] if fallbacks else "or-free-auto"
        logger.warning(
            f"Tool calling failed after {attempts_made} attempt(s) (model={model}), "
            f"degrading to text-only with {fallback}"
        )
        return await self.router.complete_with_tools(fallback, messages, [])

    async def _execute_tool_calls(self, tool_calls, task_id: str = "") -> list[ToolCallRecord]:
        """Execute tool calls from the LLM response and return records."""
        records = []
        if not self.tool_registry or not tool_calls:
            return records

        for tc in tool_calls:
            tool_name = tc.function.name
            try:
                arguments = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                records.append(
                    ToolCallRecord(
                        tool_name=tool_name,
                        arguments={},
                        result="Invalid JSON in tool arguments",
                        success=False,
                    )
                )
                continue

            # Check if this tool call needs human approval
            if self.approval_gate:
                action = self._resolve_protected_action(tool_name, arguments)
                if action:
                    desc = f"Tool '{tool_name}' called with: {list(arguments.keys())}"
                    approved = await self.approval_gate.request(
                        task_id or self.agent_id,
                        action,
                        desc,
                        details=arguments,
                    )
                    if not approved:
                        records.append(
                            ToolCallRecord(
                                tool_name=tool_name,
                                arguments=arguments,
                                result="Action denied — human approval not granted",
                                success=False,
                            )
                        )
                        continue

            # Call before_tool_call extension hooks
            if self.extension_loader and self.extension_loader.has_extensions:
                arguments = self.extension_loader.call_before_tool_call(tool_name, arguments)

            logger.info(f"Executing tool: {tool_name}({list(arguments.keys())})")
            result = await self.tool_registry.execute(
                tool_name,
                agent_id=self.agent_id,
                **arguments,
            )

            # Call after_tool_call extension hooks
            if self.extension_loader and self.extension_loader.has_extensions:
                result = self.extension_loader.call_after_tool_call(tool_name, result)

            records.append(
                ToolCallRecord(
                    tool_name=tool_name,
                    arguments=arguments,
                    result=result.content,
                    success=result.success,
                )
            )

        return records

    @staticmethod
    def _resolve_protected_action(tool_name: str, arguments: dict) -> ProtectedAction | None:
        """Determine if a tool call requires approval based on tool name and args."""
        # Direct tool-level protection
        action = _TOOL_TO_ACTION.get(tool_name)
        if action:
            return action

        # Git tool: only push operations need approval
        if tool_name == "git":
            git_action = arguments.get("action", "")
            if git_action in _GIT_PUSH_KEYWORDS:
                return ProtectedAction.GIT_PUSH

        return None

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
        task_id: str = "",
        token_accumulator: TokenAccumulator | None = None,
        intervention_queue: asyncio.Queue | None = None,
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
            token_accumulator: Optional accumulator for per-task token tracking.
            intervention_queue: Optional queue for mid-task user feedback messages.
        """
        self._token_acc = token_accumulator or TokenAccumulator()
        self._failed_models = set()  # Reset per-task failed model tracking
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
        primary_output = ""

        for i in range(1, max_iterations + 1):
            logger.info(f"Iteration {i}/{max_iterations} — primary: {primary_model}")

            # Drain any pending user interventions and inject as user messages
            if intervention_queue:
                while True:
                    try:
                        feedback = intervention_queue.get_nowait()
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    f"[USER INTERVENTION] The user has provided the following "
                                    f"feedback. Incorporate it into your work:\n\n{feedback}"
                                ),
                            }
                        )
                        logger.info(f"Intervention injected for task {task_id}: {feedback[:80]}")
                    except asyncio.QueueEmpty:
                        break

            # Call before_iteration extension hooks
            if self.extension_loader and self.extension_loader.has_extensions:
                messages = self.extension_loader.call_before_iteration(messages, i)

            # Context window overflow guard (OpenClaw feature)
            try:
                from core.config import settings as _cfg

                max_ctx = _cfg.max_context_tokens
                strategy = _cfg.context_overflow_strategy
                # Rough token estimation: chars / 4
                est_tokens = sum(len(str(m.get("content", ""))) for m in messages) // 4
                if est_tokens > int(max_ctx * 0.8):
                    logger.warning(
                        f"Context approaching limit: ~{est_tokens} tokens "
                        f"(limit: {max_ctx}, strategy: {strategy})"
                    )
                    if strategy == "error":
                        history.final_output = primary_output
                        history.total_iterations = i
                        history.token_usage = self._token_acc.to_dict()
                        return history
                    elif strategy == "truncate_oldest" and len(messages) > 3:
                        # Keep system prompt + first user msg + latest 2 messages
                        kept = messages[:2] + messages[-2:]
                        messages.clear()
                        messages.extend(kept)
                        logger.info(f"Truncated context: kept {len(messages)} messages")
            except ImportError:
                pass

            all_tool_records = []

            if tool_schemas:
                # Tool-calling loop: let the model make tool calls until it produces text
                primary_output = await self._run_tool_loop(
                    primary_model,
                    messages,
                    tool_schemas,
                    all_tool_records,
                    task_id=task_id,
                )
            else:
                # Text-only mode (no tools or model doesn't support tools)
                primary_output = await self._complete_with_retry(primary_model, messages)

            # Call after_iteration extension hooks
            if self.extension_loader and self.extension_loader.has_extensions:
                primary_output = self.extension_loader.call_after_iteration(primary_output, i)

            result = IterationResult(
                iteration=i,
                primary_output=primary_output,
                tool_calls=all_tool_records,
            )

            # Critic pass (if configured)
            if critic_model:
                critic_feedback = await self._critic_pass(
                    critic_model,
                    task_description,
                    primary_output,
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
                history.token_usage = self._token_acc.to_dict()
                return history

            # Feed critic feedback back to primary for revision
            messages.append({"role": "assistant", "content": primary_output})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"The reviewer provided this feedback:\n\n{critic_feedback}\n\n"
                        "Please revise your output to address these concerns."
                    ),
                }
            )

        # Max iterations reached — use the last output
        history.final_output = primary_output
        history.total_iterations = max_iterations
        history.token_usage = self._token_acc.to_dict()
        logger.warning(f"Max iterations ({max_iterations}) reached without full approval")
        return history

    async def _run_tool_loop(
        self,
        model: str,
        messages: list[dict],
        tool_schemas: list[dict],
        all_tool_records: list[ToolCallRecord],
        task_id: str = "",
    ) -> str:
        """Run the tool-calling loop until the model produces a text response.

        The model can make multiple rounds of tool calls. After each round,
        tool results are appended to the conversation and the model is called
        again. Stops when the model produces a text response (no tool calls)
        or MAX_TOOL_ROUNDS is reached.
        """
        working_messages = list(messages)

        for round_num in range(MAX_TOOL_ROUNDS):
            # Re-fetch schemas each round so dynamically created tools are visible
            current_schemas = (
                self.tool_registry.all_schemas() if self.tool_registry else tool_schemas
            )
            response = await self._complete_with_tools_retry(
                model, working_messages, current_schemas
            )

            # Record token usage from tool-calling response
            if response.usage and self._token_acc:
                self._token_acc.record(
                    model, response.usage.prompt_tokens, response.usage.completion_tokens
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

            records = await self._execute_tool_calls(message.tool_calls, task_id=task_id)
            all_tool_records.extend(records)

            # Add tool results as tool response messages
            for tc, record in zip(message.tool_calls, records):
                working_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": record.result,
                    }
                )

            logger.info(f"Tool round {round_num + 1}: {len(records)} calls, continuing...")

        # Max tool rounds reached — ask model for final answer without tools
        working_messages.append(
            {
                "role": "user",
                "content": "Please provide your final answer now based on the tool results above.",
            }
        )
        final = await self._complete_with_retry(model, working_messages)
        messages.append({"role": "assistant", "content": final})
        return final

    async def _critic_pass(
        self,
        critic_model: str,
        original_task: str,
        output: str,
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
                "content": (f"Original task:\n{original_task}\n\nOutput to review:\n{output}"),
            },
        ]
        return await self._complete_with_retry(critic_model, messages)

    @staticmethod
    def _is_approved(critic_feedback: str) -> bool:
        """Check if the critic approved the output."""
        first_line = critic_feedback.strip().split("\n")[0].upper()
        return first_line.startswith("APPROVED")
