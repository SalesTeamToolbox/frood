"""
Agent — per-task orchestration.

Each agent gets a git worktree, runs the iteration engine, generates
a REVIEW.md, and transitions the task to the review state.

Integrates skills (Phase 3), tools (Phase 4), memory (Phase 6),
and self-learning (post-task reflection + failure analysis).
"""

import asyncio
import logging
import textwrap
from collections.abc import Awaitable, Callable
from pathlib import Path

from agents.iteration_engine import IterationEngine, IterationResult, TokenAccumulator
from agents.learner import Learner
from agents.model_router import ModelRouter
from core.approval_gate import ApprovalGate
from core.task_queue import Task, TaskQueue, TaskType
from core.worktree_manager import WorktreeManager
from memory.project_memory import ProjectMemoryStore
from memory.store import MemoryStore
from providers.rlm_provider import RLMProvider
from skills.loader import SkillLoader
from tools.behaviour_tool import load_behaviour_rules

logger = logging.getLogger("agent42.agent")

# ---------------------------------------------------------------------------
# General assistant prompt — Agent42's user-facing persona for direct chat
# ---------------------------------------------------------------------------

GENERAL_ASSISTANT_PROMPT = """\
You are Agent42, a versatile AI assistant and project coordinator. You help users with \
a wide range of tasks — from quick questions and brainstorming to managing complex \
multi-step projects.

Your role:
- Answer questions directly when you can
- Help users clarify and refine their requests
- For substantial work (coding, research, content creation, design, data analysis, etc.), \
explain that you'll delegate to your specialized team and create a task
- Provide status updates on running tasks when asked
- Synthesize and present results from completed tasks

Communication style:
- Be helpful, clear, and concise
- Ask clarifying questions when a request is ambiguous
- Proactively suggest when a task would benefit from team collaboration
- When delegating work, briefly explain what will happen and set expectations

You have access to specialized teams of agents that can handle:
- Software development (coding, debugging, refactoring)
- Research and analysis
- Content creation and editing
- Marketing and strategy
- Design review
- Data analysis
- Project management
- App creation and deployment

When a user's request requires substantial work, let them know you're creating a task \
for your team and they'll see results when it's complete.\
"""

# ---------------------------------------------------------------------------
# L1 system prompts — Standard tier (free / admin-chosen models)
# These are detailed because free models benefit from more scaffolding.
# ---------------------------------------------------------------------------

L1_SYSTEM_PROMPTS = {
    "coding": (
        "You are a skilled software engineer on the development team. Your role is to "
        "write clean, well-tested, production-ready code that follows the project's "
        "existing conventions.\n\n"
        "Your work will be reviewed before deployment, so focus on:\n"
        "- Correct, working code with proper error handling\n"
        "- Following existing code style and patterns in the project\n"
        "- Including type hints and clear variable names\n"
        "- Writing or updating tests for your changes\n"
        "- Explaining your approach and any trade-offs in your output\n\n"
        "If anything is unclear about the requirements, document your assumptions."
    ),
    "debugging": (
        "You are a methodical debugger on the development team. Your role is to find "
        "and fix bugs systematically.\n\n"
        "Follow this process:\n"
        "1. Reproduce the issue — understand the expected vs. actual behavior\n"
        "2. Isolate the root cause — read relevant code, check logs, trace data flow\n"
        "3. Identify the minimal fix — change only what's necessary\n"
        "4. Verify the fix — ensure it resolves the issue without breaking other behavior\n"
        "5. Explain your reasoning — document what caused the bug and why your fix works\n\n"
        "Avoid shotgun debugging. Focus on understanding before changing code."
    ),
    "research": (
        "You are a thorough technical researcher. Your role is to investigate topics, "
        "gather reliable information, and present clear findings.\n\n"
        "Research standards:\n"
        "- Gather information from multiple perspectives\n"
        "- Compare options with specific pros/cons for each\n"
        "- Note any limitations, unknowns, or areas needing further investigation\n"
        "- Provide a clear recommendation supported by your findings\n"
        "- Use structured formatting (tables, bullet points) for easy scanning\n\n"
        "Focus on accuracy over breadth. If you're uncertain about something, say so."
    ),
    "refactoring": (
        "You are a refactoring specialist on the development team. Your role is to "
        "improve code structure and quality without changing external behavior.\n\n"
        "Refactoring rules:\n"
        "- Preserve all existing functionality — behavior must not change\n"
        "- Ensure all existing tests continue to pass\n"
        "- Make changes incrementally, not as a massive rewrite\n"
        "- Explain each change and the motivation behind it\n"
        "- Improve naming, reduce duplication, simplify complex logic\n"
        "- Add tests if coverage was previously lacking in the refactored area"
    ),
    "documentation": (
        "You are a technical writer. Your role is to write clear documentation that "
        "helps developers understand and use code effectively.\n\n"
        "Documentation standards:\n"
        "- Write for the audience — assume they're competent developers but new to this code\n"
        "- Lead with practical examples and usage patterns\n"
        "- Include parameter descriptions, return values, and error cases\n"
        "- Use consistent formatting and terminology throughout\n"
        "- Keep it concise — every sentence should earn its place"
    ),
    "marketing": (
        "You are a marketing specialist. Your role is to create compelling, targeted "
        "marketing content that drives action.\n\n"
        "Marketing guidelines:\n"
        "- Know your audience — tailor language, examples, and tone to their needs\n"
        "- Lead with benefits, not features — show how it solves their problem\n"
        "- Be specific — replace vague claims with concrete data points\n"
        "- Use proven frameworks (AIDA, PAS, BAB) for structured persuasion\n"
        "- Include clear calls to action\n"
        "- Avoid buzzwords and corporate jargon"
    ),
    "email": (
        "You are a professional communicator. Your role is to draft effective emails "
        "that achieve their purpose with clarity and appropriate tone.\n\n"
        "Email standards:\n"
        "- Start with the key point or request — don't bury the lead\n"
        "- Keep it concise — respect the reader's time\n"
        "- Match tone to context (formal, friendly, urgent as appropriate)\n"
        "- Include a clear call to action or next steps\n"
        "- Structure longer emails with bullet points or numbered lists"
    ),
    "design": (
        "You are a UI/UX design consultant. Your role is to provide detailed design "
        "guidance, feedback, and creative direction.\n\n"
        "Design principles:\n"
        "- Prioritize usability and accessibility (WCAG compliance)\n"
        "- Establish clear visual hierarchy to guide the user's eye\n"
        "- Maintain consistency in spacing, typography, and color usage\n"
        "- Describe layouts, color choices, and typography with precision\n"
        "- Consider responsive behavior and different screen sizes\n"
        "- Provide rationale for design decisions — not just what, but why"
    ),
    "content": (
        "You are a content creator. Your role is to write engaging, well-structured "
        "content tailored to the target audience.\n\n"
        "Content standards:\n"
        "- Open with a hook that captures attention\n"
        "- Structure content with clear sections and logical flow\n"
        "- Use active voice, concrete examples, and vivid language\n"
        "- Adapt tone and complexity to the target audience\n"
        "- Include a strong conclusion with a call to action\n"
        "- Proofread for grammar, clarity, and consistency"
    ),
    "strategy": (
        "You are a strategic business analyst. Your role is to analyze situations, "
        "identify opportunities, and deliver actionable recommendations.\n\n"
        "Strategy framework:\n"
        "- Start with clear problem definition and scope\n"
        "- Use structured frameworks (SWOT, Porter's Five Forces, etc.) where appropriate\n"
        "- Support insights with data, not assumptions\n"
        "- Identify risks and mitigation strategies\n"
        "- Deliver specific, actionable next steps — not vague advice\n"
        "- Present findings in a clear executive-friendly format"
    ),
    "data_analysis": (
        "You are a data analyst. Your role is to process data, identify patterns, "
        "and deliver actionable insights.\n\n"
        "Analysis standards:\n"
        "- Start by understanding the business question behind the data request\n"
        "- Clean and validate data before drawing conclusions\n"
        "- Present findings with clear visualizations (tables, charts as markdown/ASCII)\n"
        "- Distinguish between correlation and causation\n"
        "- Quantify uncertainty — provide confidence intervals where appropriate\n"
        "- Summarize key takeaways with recommended actions"
    ),
    "project_management": (
        "You are a project manager. Your role is to create clear plans and keep "
        "work organized and on track.\n\n"
        "PM standards:\n"
        "- Break work into specific, actionable tasks with clear ownership\n"
        "- Set realistic milestones and timelines\n"
        "- Identify dependencies, risks, and resource constraints\n"
        "- Use structured formats (tables, checklists, Gantt descriptions)\n"
        "- Define success criteria and acceptance standards for each deliverable\n"
        "- Include a communication plan and status tracking approach"
    ),
    "app_create": (
        "You are an expert full-stack developer building a complete, working web "
        "application. Use the 'app' tool to create the app, then write all source "
        "files using filesystem tools.\n\n"
        "App creation standards:\n"
        "- The app must be fully functional — no placeholders, no TODOs\n"
        "- Include proper error handling and input validation\n"
        "- Write clean, organized code with clear file structure\n"
        "- Include a README with setup instructions\n"
        "- After writing all code, mark the app as ready and start it\n"
        "- Report the access URL when done"
    ),
    "app_update": (
        "You are updating an existing web application. Your role is to make targeted "
        "improvements without breaking existing functionality.\n\n"
        "Update process:\n"
        "- Read the current app files first to understand the codebase\n"
        "- Make targeted changes — don't rewrite the entire app\n"
        "- Preserve existing functionality and code style\n"
        "- Test that existing features still work after your changes\n"
        "- After changes, restart the app and verify it works"
    ),
    "project_setup": (
        "You are a senior project manager conducting a discovery interview. "
        "Use the project_interview tool to guide the conversation. Ask questions "
        "in themed batches of 3-5. Listen carefully to answers, follow up on vague "
        "responses, and build toward a comprehensive PROJECT_SPEC.md. Be conversational "
        "but thorough — this spec will drive all subsequent development work."
    ),
}

# Backward compatibility alias
SYSTEM_PROMPTS = L1_SYSTEM_PROMPTS

# ---------------------------------------------------------------------------
# L2 system prompts — Premium tier (senior review and refinement)
# These are concise because premium models need less scaffolding.
# L2 agents review L1 output, not re-execute from scratch.
# ---------------------------------------------------------------------------

L2_SYSTEM_PROMPTS = {
    "coding": (
        "You are a senior staff engineer conducting a final review of code produced by "
        "your team. Your job is to:\n"
        "1. Assess correctness, security, and production-readiness\n"
        "2. Identify subtle bugs, edge cases, and architectural concerns\n"
        "3. Refine code quality — improve naming, structure, and patterns\n"
        "4. Ensure tests are comprehensive and meaningful\n"
        "5. Provide a concise quality assessment with specific improvements made\n\n"
        "Make direct improvements rather than just suggesting changes. "
        "Only flag issues you're confident about."
    ),
    "debugging": (
        "You are a senior engineer reviewing a bug fix produced by your team. Assess:\n"
        "1. Is the root cause correctly identified?\n"
        "2. Is the fix minimal and correct — no unnecessary changes?\n"
        "3. Are there related edge cases or similar bugs elsewhere?\n"
        "4. Is the explanation clear and the reasoning sound?\n\n"
        "Refine the fix if needed. Add any missed edge case handling."
    ),
    "research": (
        "You are a principal analyst reviewing a research deliverable. Assess for:\n"
        "- Accuracy and source quality\n"
        "- Completeness of analysis — any significant gaps?\n"
        "- Logical consistency of conclusions\n"
        "- Actionability of recommendations\n\n"
        "Refine and strengthen the output, filling gaps and correcting errors."
    ),
    "refactoring": (
        "You are a staff engineer reviewing a refactoring proposal. Verify:\n"
        "1. No behavioral changes — external behavior must be identical\n"
        "2. The refactoring actually improves the code (not just reshuffling)\n"
        "3. No subtle regressions in error handling or edge cases\n"
        "4. Consistency with overall architecture patterns\n\n"
        "Make targeted refinements where the refactoring fell short."
    ),
    "documentation": (
        "You are a documentation lead reviewing technical documentation. Assess:\n"
        "- Accuracy — does it match the actual code behavior?\n"
        "- Completeness — are all key scenarios covered?\n"
        "- Clarity — can a new developer follow this without confusion?\n"
        "- Consistency in terminology and formatting\n\n"
        "Refine for precision and readability."
    ),
    "marketing": (
        "You are a marketing director reviewing campaign materials. Assess:\n"
        "- Message clarity and persuasiveness\n"
        "- Audience targeting — does it speak to their needs?\n"
        "- Brand consistency and voice\n"
        "- Strength of calls to action\n\n"
        "Polish the copy for maximum impact. Tighten language, sharpen the hook."
    ),
    "email": (
        "You are reviewing a drafted email for a colleague. Check:\n"
        "- Is the purpose clear from the first sentence?\n"
        "- Is the tone appropriate for the audience and context?\n"
        "- Is it concise — no unnecessary filler?\n"
        "- Is the call to action clear?\n\n"
        "Refine for clarity and professionalism."
    ),
    "design": (
        "You are a design director reviewing a design proposal. Assess:\n"
        "- Usability and accessibility (WCAG compliance)\n"
        "- Visual hierarchy and information architecture\n"
        "- Consistency with design system and brand guidelines\n"
        "- Responsive behavior considerations\n\n"
        "Provide specific, actionable refinements. Not just what's wrong, but how to fix it."
    ),
    "content": (
        "You are an editorial director reviewing content. Assess:\n"
        "- Engagement — does it hook the reader and maintain interest?\n"
        "- Structure — logical flow, clear sections, strong conclusion\n"
        "- Voice — appropriate for the target audience\n"
        "- Accuracy of facts and claims\n\n"
        "Polish the content for publication quality."
    ),
    "strategy": (
        "You are a strategy VP reviewing a strategic analysis. Assess:\n"
        "- Rigor of analysis — are conclusions supported by evidence?\n"
        "- Completeness — are key factors and risks addressed?\n"
        "- Actionability — are recommendations specific enough to execute?\n"
        "- Presentation quality — clear enough for executive audience?\n\n"
        "Strengthen weak areas and challenge assumptions."
    ),
    "data_analysis": (
        "You are a senior data scientist reviewing an analysis. Assess:\n"
        "- Methodology — appropriate techniques for the question?\n"
        "- Data quality — are limitations and biases acknowledged?\n"
        "- Statistical validity — correct interpretation of results?\n"
        "- Actionability — do insights translate to clear recommendations?\n\n"
        "Refine the analysis for rigor and clarity."
    ),
    "project_management": (
        "You are a program director reviewing a project plan. Assess:\n"
        "- Completeness — all deliverables, milestones, and dependencies captured?\n"
        "- Feasibility — are timelines and resource allocations realistic?\n"
        "- Risk management — are key risks identified with mitigations?\n"
        "- Clarity — can the team execute from this plan without ambiguity?\n\n"
        "Refine the plan for executability."
    ),
    "app_create": (
        "You are a tech lead reviewing a newly built web application. Assess:\n"
        "1. Functionality — does everything work as intended?\n"
        "2. Code quality — clean structure, error handling, no hardcoded values\n"
        "3. Security — input validation, no exposed secrets, proper auth\n"
        "4. UX — intuitive interface, responsive, accessible\n\n"
        "Make targeted improvements. Report any critical issues found."
    ),
    "app_update": (
        "You are a tech lead reviewing changes to an existing web application. Verify:\n"
        "1. The update achieves its goal without breaking existing features\n"
        "2. Code changes are focused and minimal — no unnecessary rewrites\n"
        "3. Edge cases are handled\n"
        "4. The app still functions correctly after the update\n\n"
        "Refine the implementation for production readiness."
    ),
    "project_setup": (
        "You are a principal PM reviewing a project specification. Verify:\n"
        "- Requirements are clear, measurable, and complete\n"
        "- Scope is well-defined with explicit out-of-scope items\n"
        "- Technical approach is feasible\n"
        "- Success criteria are specific and testable\n\n"
        "Strengthen the spec for use as a development contract."
    ),
}

# Task types that require git worktrees — all others use output directories
_CODE_TASK_TYPES = {TaskType.CODING, TaskType.DEBUGGING, TaskType.REFACTORING}


class Agent:
    """Runs a single task through the full agent pipeline."""

    def __init__(
        self,
        task: Task,
        task_queue: TaskQueue,
        worktree_manager: WorktreeManager | None,
        approval_gate: ApprovalGate,
        emit: Callable[[str, dict], Awaitable[None]],
        skill_loader: SkillLoader | None = None,
        memory_store: MemoryStore | None = None,
        project_memory: ProjectMemoryStore | None = None,
        workspace_skills_dir: Path | None = None,
        tool_registry=None,
        profile_loader=None,
        extension_loader=None,
        intervention_queue: asyncio.Queue | None = None,
        state_manager=None,
    ):
        self.task = task
        self.task_queue = task_queue
        self.worktree_manager = worktree_manager
        self.approval_gate = approval_gate
        self.emit = emit
        self.router = ModelRouter()
        self.tool_registry = tool_registry
        self.profile_loader = profile_loader
        self.extension_loader = extension_loader
        self.intervention_queue = intervention_queue
        self.state_manager = state_manager
        self.engine = IterationEngine(
            self.router,
            tool_registry=tool_registry,
            approval_gate=approval_gate,
            agent_id=task.id,
            extension_loader=extension_loader,
        )
        self.skill_loader = skill_loader
        self.memory_store = memory_store
        self.project_memory = project_memory
        self.rlm_provider = RLMProvider()
        self.learner = (
            Learner(
                self.router,
                memory_store,
                project_memory=project_memory,
                skills_dir=workspace_skills_dir,
            )
            if memory_store
            else None
        )

    async def run(self):
        """Execute the full agent pipeline for this task."""
        task = self.task
        logger.info(f"Agent starting: {task.id} — {task.title}")
        needs_worktree = task.task_type in _CODE_TASK_TYPES

        try:
            # Set up workspace — worktree for code tasks, output dir for others
            if needs_worktree and self.worktree_manager:
                worktree_path = await self.worktree_manager.create(task.id)
            elif needs_worktree:
                logger.warning("No repo configured — running code task without worktree")
                needs_worktree = False
                from core.config import settings

                output_dir = Path(settings.outputs_dir) / task.id
                output_dir.mkdir(parents=True, exist_ok=True)
                worktree_path = output_dir
            else:
                from core.config import settings

                output_dir = Path(settings.outputs_dir) / task.id
                output_dir.mkdir(parents=True, exist_ok=True)
                worktree_path = output_dir

            task.worktree_path = str(worktree_path)

            await self.emit(
                "agent_start",
                {
                    "task_id": task.id,
                    "title": task.title,
                    "worktree": str(worktree_path),
                },
            )

            # Get model routing for this task type (tier-aware)
            if task.tier == "L2":
                routing = self.router.get_l2_routing(task.task_type)
                if not routing:
                    # L2 not available — fall back to L1
                    logger.warning("L2 routing unavailable for %s — falling back to L1", task.id)
                    task.tier = "L1"
                    routing = self.router.get_routing(
                        task.task_type, context_window=task.context_window
                    )
            else:
                routing = self.router.get_routing(
                    task.task_type, context_window=task.context_window
                )

            # Build system prompt (with skill overrides, profile, and behaviour rules)
            system_prompt = self._build_system_prompt(task)
            system_prompt = await self._apply_system_prompt_enhancements(system_prompt, task)

            # Build task context with file contents, skills, and memory
            task_context = await self._build_context(task, worktree_path)

            # RLM integration: if context exceeds the token threshold, use RLM
            # to pre-process and distill the large context before the iteration
            # engine.  The RLM decomposes the corpus via a REPL environment
            # and returns a focused summary — avoiding context window overflow.
            rlm_metadata = None
            if self.rlm_provider.should_use_rlm(task_context, task.task_type.value):
                rlm_query = (
                    f"Analyze the following task and its context thoroughly.\n\n"
                    f"Task: {task.title}\n\n"
                    f"Instructions: {task.description}\n\n"
                    f"Extract and organize the most relevant information needed "
                    f"to complete this task. Focus on key code sections, "
                    f"specifications, requirements, and constraints."
                )
                rlm_result = await self.rlm_provider.complete(
                    query=rlm_query,
                    context=task_context,
                    task_type=task.task_type.value,
                )
                if rlm_result is not None:
                    logger.info(
                        "RLM pre-processed context for task %s: %dk→%dk chars",
                        task.id,
                        len(task_context) // 1000,
                        len(rlm_result["response"]) // 1000,
                    )
                    # Wrap the RLM-distilled context with the original task details
                    task_context = (
                        f"# Task: {task.title}\n\n"
                        f"{task.description}\n\n"
                        f"Working directory: {worktree_path}\n\n"
                        f"## RLM-Processed Context\n\n"
                        f"The following context was extracted from a large corpus "
                        f"(~{rlm_result['estimated_context_tokens'] // 1000}k tokens) "
                        f"using recursive language model decomposition:\n\n"
                        f"{rlm_result['response']}"
                    )
                    rlm_metadata = rlm_result.get("metadata")
                    await self.emit(
                        "rlm_complete",
                        {
                            "task_id": task.id,
                            "elapsed": rlm_result.get("elapsed_seconds", 0),
                            "original_tokens": rlm_result.get("estimated_context_tokens", 0),
                        },
                    )

            # Run iteration engine with task-type-aware critic
            token_acc = TokenAccumulator()
            history = await self.engine.run(
                task_description=task_context,
                primary_model=routing["primary"],
                critic_model=routing["critic"],
                max_iterations=routing["max_iterations"],
                system_prompt=system_prompt,
                on_iteration=self._on_iteration,
                task_type=task.task_type.value,
                task_id=task.id,
                token_accumulator=token_acc,
                intervention_queue=self.intervention_queue,
                rlm_provider=self.rlm_provider,
            )

            # Store token usage on the task for persistence and dashboard display
            task.token_usage = history.token_usage
            if rlm_metadata:
                task.token_usage["rlm"] = {
                    "used": True,
                    "metadata": rlm_metadata,
                    "cost_usd": self.rlm_provider.total_cost_usd,
                }

            if needs_worktree:
                # Generate REVIEW.md and commit for code tasks
                diff = await self.worktree_manager.diff(task.id)
                review_md = self._generate_review(task, history, diff)
                review_path = worktree_path / "REVIEW.md"
                review_path.write_text(review_md)

                await self.worktree_manager.commit(
                    task.id, f"agent42: {task.title} — iteration complete"
                )
            else:
                # Save output as markdown for non-code tasks
                output_path = worktree_path / "output.md"
                review_md = self._generate_review(task, history, "")
                output_path.write_text(review_md)

            # Transition task to review
            await self.task_queue.complete(task.id, result=history.final_output)

            # Update project state for session recovery (GSD-inspired)
            if task.project_id and self.state_manager:
                try:
                    await self.state_manager.update_task_completion(task.project_id, task.id)
                except Exception as e:
                    logger.warning("Failed to update project state: %s", e)

            # Post-task learning: reflect on what worked + check for skill creation
            if self.learner:
                # Extract tool call records for tool effectiveness learning
                tool_calls_data = []
                for it_result in history.iterations:
                    for tc in it_result.tool_calls:
                        tool_calls_data.append(
                            {
                                "name": tc.tool_name,
                                "success": tc.success,
                            }
                        )

                await self.learner.reflect_on_task(
                    title=task.title,
                    task_type=task.task_type.value,
                    iterations=history.total_iterations,
                    max_iterations=routing["max_iterations"],
                    iteration_summary=history.summary(),
                    succeeded=True,
                    tool_calls=tool_calls_data,
                )
                # Check if this task's pattern should be saved as a reusable skill
                existing_names = (
                    [s.name for s in self.skill_loader.all_skills()] if self.skill_loader else []
                )
                await self.learner.check_for_skill_creation(
                    existing_skill_names=existing_names,
                )

            await self.emit(
                "agent_complete",
                {
                    "task_id": task.id,
                    "iterations": history.total_iterations,
                    "worktree": str(worktree_path),
                    "token_usage": task.token_usage,
                },
            )

            # Clean up worktree for code tasks to prevent disk space leaks
            if needs_worktree:
                try:
                    await self.worktree_manager.remove(task.id)
                except Exception as cleanup_err:
                    logger.warning(f"Worktree cleanup failed for {task.id}: {cleanup_err}")

            logger.info(f"Agent done: {task.id} — {history.total_iterations} iterations")

        except Exception as e:
            logger.error(f"Agent failed: {task.id} — {e}", exc_info=True)
            await self.task_queue.fail(task.id, str(e))
            await self.emit("agent_error", {"task_id": task.id, "error": str(e)})

            # Clean up orphaned worktree for code tasks to prevent disk bloat
            if needs_worktree:
                try:
                    await self.worktree_manager.remove(task.id)
                except Exception as cleanup_err:
                    logger.warning(f"Worktree cleanup failed for {task.id}: {cleanup_err}")

            # Post-task learning: analyze the failure
            if self.learner:
                await self.learner.reflect_on_task(
                    title=task.title,
                    task_type=task.task_type.value,
                    iterations=0,
                    max_iterations=routing.get("max_iterations", 8),
                    iteration_summary="(task failed before completing iterations)",
                    succeeded=False,
                    error=str(e),
                )

    async def _on_iteration(self, result: IterationResult):
        """Broadcast iteration progress to the dashboard."""
        await self.emit(
            "iteration",
            {
                "task_id": self.task.id,
                "iteration": result.iteration,
                "approved": result.approved,
                "preview": result.primary_output[:500],
            },
        )

    def _build_system_prompt(self, task: Task) -> str:
        """Build the system prompt, incorporating skill overrides and tier selection."""
        task_type_str = task.task_type.value

        # Check if any skill overrides the system prompt
        if self.skill_loader:
            skills = self.skill_loader.get_for_task_type(task_type_str)
            for skill in skills:
                if skill.system_prompt_override:
                    return skill.system_prompt_override

        # Select prompt by tier — L2 uses review-focused prompts
        if task.tier == "L2":
            return L2_SYSTEM_PROMPTS.get(task_type_str, L2_SYSTEM_PROMPTS["coding"])
        return L1_SYSTEM_PROMPTS.get(task_type_str, L1_SYSTEM_PROMPTS["coding"])

    async def _apply_system_prompt_enhancements(self, prompt: str, task: Task) -> str:
        """Apply profile overlay, behaviour rules, and extension hooks to the system prompt.

        Called after _build_system_prompt() to layer in Agent Zero-inspired features:
        1. Extension before_system_prompt hook
        2. Active agent profile overlay
        3. Persistent behaviour rules from memory/behaviour.md
        4. Extension after_system_prompt hook
        """
        task_type_str = task.task_type.value

        # Extension: before_system_prompt
        if self.extension_loader and self.extension_loader.has_extensions:
            prompt = self.extension_loader.call_before_system_prompt(prompt, task_type_str)

        # Agent profile overlay — apply profile for this task
        profile = self._resolve_profile(task)
        if profile and profile.prompt_overlay:
            prompt = f"{prompt}\n\n{profile.prompt_overlay}"

        # Behaviour rules — persistent rules from memory/behaviour.md
        if self.memory_store:
            try:
                from core.config import settings as _cfg

                behaviour = await load_behaviour_rules(_cfg.memory_dir)
                if behaviour:
                    prompt = prompt + behaviour
            except Exception as e:
                logger.debug(f"Could not load behaviour rules: {e}")

        # Extension: after_system_prompt
        if self.extension_loader and self.extension_loader.has_extensions:
            prompt = self.extension_loader.call_after_system_prompt(prompt)

        return prompt

    # L2 auto-profile mapping — code task types get l2-reviewer, others get l2-strategist
    _L2_CODE_TYPES = {"coding", "debugging", "refactoring", "app_create", "app_update"}

    def _resolve_profile(self, task: Task):
        """Return the active AgentProfile for this task, or None if unavailable."""
        if not self.profile_loader:
            return None
        # Task-specific profile takes precedence over default
        profile_name = task.profile if task.profile else None
        if profile_name:
            return self.profile_loader.get(profile_name)

        # L2 tasks use tier-specific profiles
        if task.tier == "L2":
            from core.config import settings

            l2_profile = settings.l2_default_profile
            if not l2_profile:
                # Auto-select based on task type
                if task.task_type.value in self._L2_CODE_TYPES:
                    l2_profile = "l2-reviewer"
                else:
                    l2_profile = "l2-strategist"
            profile = self.profile_loader.get(l2_profile)
            if profile:
                return profile

        return self.profile_loader.get_default()

    # Max bytes of file content to include in context
    _MAX_FILE_SIZE = 30_000  # ~30KB per file
    _MAX_CONTEXT_FILES = 15  # At most this many files read into context
    _MAX_TOTAL_CONTEXT = 200_000  # Total context budget in characters

    # File extensions for code tasks
    _CODE_EXTENSIONS = (".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".yaml", ".yml", ".md")
    # File extensions for non-code tasks (reference documents)
    _NONCODE_EXTENSIONS = (".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".html", ".xml")

    async def _build_context(self, task: Task, worktree_path: Path) -> str:
        """Build the full task context including file contents, skills, and memory.

        For code tasks: reads source files from the worktree.
        For non-code tasks: reads reference documents and prior outputs.
        Uses semantic memory search when available, falls back to recent history.
        """
        is_code_task = task.task_type in _CODE_TASK_TYPES
        parts = [
            f"# Task: {task.title}\n",
            task.description,
            f"\nWorking directory: {worktree_path}",
        ]
        if task.project_id:
            parts.append(f"\nProject ID: {task.project_id}")

        # L2 tasks include the L1 team output for review
        if task.tier == "L2" and task.l1_result:
            parts.append(f"\n## L1 Team Output (for your review)\n\n{task.l1_result}")

        extensions = self._CODE_EXTENSIONS if is_code_task else self._NONCODE_EXTENSIONS

        # Include project/reference file structure
        project_files = sorted(worktree_path.rglob("*"))
        relevant = [
            f
            for f in project_files
            if f.is_file()
            and f.suffix in extensions
            and ".git" not in f.parts
            and "node_modules" not in str(f)
            and "__pycache__" not in str(f)
        ]

        if relevant:
            label = "Project files" if is_code_task else "Reference documents"
            parts.append(f"\n## {label}:")
            for f in relevant[:50]:
                parts.append(f"- {f.relative_to(worktree_path)}")

        # Read file contents
        if relevant:
            label = "File Contents" if is_code_task else "Reference Contents"
            parts.append(f"\n## {label}:\n")
            total_chars = 0
            files_read = 0
            for f in relevant[: self._MAX_CONTEXT_FILES]:
                if total_chars >= self._MAX_TOTAL_CONTEXT:
                    parts.append(f"... ({len(relevant) - files_read} more files not shown)")
                    break
                try:
                    content = f.read_text(encoding="utf-8", errors="replace")
                    if len(content) > self._MAX_FILE_SIZE:
                        content = content[: self._MAX_FILE_SIZE] + "\n... (file truncated)"
                    rel_path = f.relative_to(worktree_path)
                    parts.append(f"### {rel_path}\n```\n{content}\n```\n")
                    total_chars += len(content)
                    files_read += 1
                except Exception:
                    continue

        # Include skill context (Phase 3)
        if self.skill_loader:
            skill_context = self.skill_loader.build_skill_context(task.task_type.value)
            if skill_context:
                parts.append(f"\n{skill_context}")

        # Include memory context (Phase 6) — project-scoped when available
        # Project memory merges project-specific + global context automatically.
        memory_source = self.project_memory or self.memory_store
        if memory_source:
            try:
                if memory_source.semantic_available:
                    memory_context = await memory_source.build_context_semantic(
                        query=task.description,
                    )
                else:
                    memory_context = memory_source.build_context()
            except Exception as e:
                logger.warning("Memory context failed, using basic fallback: %s", e)
                memory_context = memory_source.build_context()
            if memory_context.strip():
                parts.append(f"\n{memory_context}")

        # Include tool usage recommendations from prior learning (Phase 9)
        if self.learner:
            tool_recs = self.learner.get_tool_recommendations(task.task_type.value)
            if tool_recs:
                parts.append(f"\n{tool_recs}")

        # Include PROJECT_SPEC.md when task is linked to a project interview
        if task.project_spec_path:
            spec_path = Path(task.project_spec_path)
            if spec_path.exists():
                try:
                    spec_content = spec_path.read_text(encoding="utf-8", errors="replace")
                    parts.append(
                        f"\n## Project Specification\n\n"
                        f"This task is part of a larger project. Follow the spec below:\n\n"
                        f"{spec_content}"
                    )
                except Exception:
                    pass

        # Include project state for session recovery (GSD-inspired)
        if task.project_id and self.state_manager:
            try:
                state = await self.state_manager.load_state(task.project_id)
                if state:
                    parts.append(f"\n## Project State (session recovery)\n\n{state.to_markdown()}")
            except Exception as e:
                logger.debug("Could not load project state: %s", e)

        return "\n".join(parts)

    @staticmethod
    def _generate_review(task: Task, history, diff: str) -> str:
        """Generate REVIEW.md for human + Claude Code review."""
        token_section = ""
        usage = getattr(history, "token_usage", {})
        if usage and usage.get("total_tokens"):
            lines = [
                f"Total: {usage['total_tokens']:,} tokens "
                f"({usage.get('total_prompt_tokens', 0):,} prompt + "
                f"{usage.get('total_completion_tokens', 0):,} completion)",
            ]
            by_model = usage.get("by_model", {})
            if by_model:
                lines.append("\nBy model:")
                for model, data in by_model.items():
                    total = data.get("prompt_tokens", 0) + data.get("completion_tokens", 0)
                    lines.append(f"- {model}: {total:,} tokens ({data.get('calls', 0)} calls)")
            token_section = "\n## Token Usage\n\n" + "\n".join(lines) + "\n"

        return textwrap.dedent(f"""\
            # Review: {task.title}

            **Task ID:** {task.id}
            **Type:** {task.task_type.value}
            **Iterations:** {history.total_iterations}
            {token_section}
            ## Task Description

            {task.description}

            ## Iteration History

            {history.summary()}

            ## Final Output

            {history.final_output}

            ## Git Diff

            ```diff
            {diff}
            ```

            ## Claude Code Review Prompt

            Review the changes in this worktree. Check for:
            1. Correctness — does it do what the task asked?
            2. Security — any injection, XSS, or data exposure risks?
            3. Tests — are edge cases covered?
            4. Style — does it match the existing codebase?

            If approved, merge to dev. If not, explain what needs to change.
        """)
