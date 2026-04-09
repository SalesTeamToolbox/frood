"""Agent Runtime — Launches and manages autonomous agent processes.

Spawns agents as background processes using Claude Code CLI with
provider-specific environment variables. Each agent runs in its own
subprocess with isolated environment. Multiple agents can run
concurrently using different models/providers.
"""

import asyncio
import logging
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("frood.agent_runtime")


@dataclass
class AgentProcess:
    """Tracks a running agent process."""

    agent_id: str
    pid: int
    process: object = None
    started_at: float = 0.0
    log_file: str = ""
    status: str = "running"


class AgentRuntime:
    """Manages agent process lifecycle."""

    def __init__(self, workspace, mcp_config=""):
        self.workspace = Path(workspace)
        self.mcp_config = mcp_config or str(self.workspace / ".mcp.json")
        self._processes = {}
        self._logs_dir = self.workspace / ".frood" / "agent-logs"
        self._logs_dir.mkdir(parents=True, exist_ok=True)

    def _build_env(self, agent_config):
        """Build environment variables for an agent process."""
        env = {**os.environ}
        provider = agent_config.get("provider", "anthropic")
        provider_url = agent_config.get("provider_url", "")
        model = agent_config.get("model", "")

        if provider == "zen":
            zen_key = os.environ.get("ZEN_API_KEY", "")
            env["ANTHROPIC_API_KEY"] = zen_key
            env["ANTHROPIC_BASE_URL"] = provider_url or "https://opencode.ai/zen/v1"
            if model:
                env["ANTHROPIC_MODEL"] = model
        elif provider == "openrouter":
            or_key = os.environ.get("OPENROUTER_API_KEY", "")
            env["ANTHROPIC_API_KEY"] = or_key
            env["ANTHROPIC_BASE_URL"] = provider_url or "https://openrouter.ai/api/v1"
            if model:
                env["ANTHROPIC_MODEL"] = model
        elif provider == "anthropic":
            if model:
                env["ANTHROPIC_MODEL"] = model
        elif provider == "openai":
            env["OPENAI_API_KEY"] = os.environ.get("OPENAI_API_KEY", "")
            env["OPENAI_BASE_URL"] = provider_url or "https://api.openai.com/v1"
            if model:
                env["OPENAI_MODEL"] = model

        return env

    async def _build_prompt(self, agent_config):
        """Build the task prompt for an agent."""
        parts = []
        name = agent_config.get("name", "Agent")
        desc = agent_config.get("description", "")
        parts.append(f"You are {name}. {desc}")

        tools = agent_config.get("tools", [])
        if tools:
            parts.append(f"\nYou have access to these Frood MCP tools: {', '.join(tools)}")
            parts.append("Use them as needed to complete your task.")

        skills = agent_config.get("skills", [])
        if skills:
            parts.append(f"\nApply these skill areas: {', '.join(skills)}")

        scope = agent_config.get("memory_scope", "global")
        parts.append(f"\nStore important findings in memory (scope: {scope}).")

        # N8N workflow automation guidance
        if "n8n_workflow" in tools or "n8n_create_workflow" in tools:
            parts.append(
                "\nN8N AUTOMATION: Before repeating multi-step deterministic work "
                "(bulk API calls, data transforms, notifications, integration glue), "
                "check if an N8N workflow exists (n8n_workflow list) or create one "
                "(n8n_create_workflow). Workflows run for free — no tokens per execution. "
                "Only use LLM reasoning for tasks requiring judgment or creativity."
            )

        # Phase 43: Inject automation suggestions from effectiveness pattern detection
        try:
            import json as _json

            from memory.effectiveness import get_shared_store

            store = get_shared_store()
            if store:
                agent_id = agent_config.get("id", "")
                suggestions = await store.get_pending_suggestions(agent_id)
                for s in suggestions:
                    tools_str = " -> ".join(_json.loads(s["tool_sequence"]))
                    savings = s["tokens_saved_estimate"]
                    count = s["execution_count"]
                    parts.append(
                        f"\nAUTOMATION SUGGESTION: Pattern '{tools_str}' has repeated "
                        f"{count} times. Estimated savings: ~{savings} tokens. "
                        "Use n8n_create_workflow to automate this."
                    )
                    await store.mark_suggestion_status(s["fingerprint"], agent_id, "suggested")
        except Exception:
            pass  # Non-critical — never block agent startup for suggestions

        max_iter = agent_config.get("max_iterations", 10)
        parts.append(f"\nWork autonomously. Max iterations: {max_iter}.")
        parts.append("When your task is complete, summarize what you accomplished.")

        return "\n".join(parts)

    def _uses_openai_protocol(self, provider: str) -> bool:
        """Check if a provider uses OpenAI Chat Completions protocol."""
        return provider in ("zen", "openrouter", "openai")

    async def start_agent(self, agent_config):
        """Launch an agent — routes to Claude CLI or OpenAI runner based on provider."""
        agent_id = agent_config.get("id", "unknown")

        if agent_id in self._processes:
            existing = self._processes[agent_id]
            if existing.status == "running" and existing.process:
                if existing.process.returncode is None:
                    logger.warning(f"Agent {agent_id} already running (PID {existing.pid})")
                    return existing

        provider = agent_config.get("provider", "anthropic")
        if self._uses_openai_protocol(provider):
            return await self._start_openai_agent(agent_config)
        return await self._start_claude_agent(agent_config)

    async def _start_openai_agent(self, agent_config):
        """Run agent using OpenAI Chat Completions protocol (Zen, OpenRouter, OpenAI)."""
        agent_id = agent_config.get("id", "unknown")
        provider = agent_config.get("provider", "zen")
        model = agent_config.get("model", "")
        prompt = await self._build_prompt(agent_config)

        timestamp = time.strftime("%Y%m%d-%H%M%S")
        log_path = self._logs_dir / f"{agent_id}-{timestamp}.log"

        # Resolve API key and base URL
        if provider == "zen":
            api_key = os.environ.get("ZEN_API_KEY", "")
            base_url = agent_config.get("provider_url") or "https://opencode.ai/zen/v1"
        elif provider == "openrouter":
            api_key = os.environ.get("OPENROUTER_API_KEY", "")
            base_url = agent_config.get("provider_url") or "https://openrouter.ai/api/v1"
        elif provider == "openai":
            api_key = os.environ.get("OPENAI_API_KEY", "")
            base_url = agent_config.get("provider_url") or "https://api.openai.com/v1"
        else:
            api_key = ""
            base_url = ""

        if not api_key:
            logger.error(f"No API key for provider {provider}")
            return None

        logger.info(
            f"Starting OpenAI-protocol agent {agent_id} provider={provider} "
            f"model={model} base_url={base_url}"
        )

        agent_proc = AgentProcess(
            agent_id=agent_id,
            pid=os.getpid(),
            process=None,
            started_at=time.time(),
            log_file=str(log_path),
            status="running",
        )
        self._processes[agent_id] = agent_proc

        asyncio.create_task(
            self._run_openai_loop(
                agent_id, agent_proc, log_path, prompt, api_key, base_url, model, agent_config
            )
        )
        logger.info(f"Agent {agent_id} started (OpenAI protocol, in-process)")
        return agent_proc

    async def _run_openai_loop(
        self, agent_id, agent_proc, log_path, prompt, api_key, base_url, model, agent_config
    ):
        """Agentic loop using OpenAI Chat Completions."""
        import httpx as _httpx

        max_iter = agent_config.get("max_iterations", 10)
        messages = [
            {
                "role": "system",
                "content": "You are a helpful autonomous agent. Complete the task, then summarize.",
            },
            {"role": "user", "content": prompt},
        ]

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        url = f"{base_url}/chat/completions"

        try:
            with open(log_path, "w", encoding="utf-8") as log:
                log.write(f"Agent: {agent_config.get('name', agent_id)}\n")
                log.write(f"Started: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                log.write(f"Provider: {agent_config.get('provider', 'unknown')}\n")
                log.write(f"Model: {model}\n")
                log.write("Runner: OpenAI Chat Completions\n")
                log.write("=" * 60 + "\n\n")
                log.flush()

                total_tokens = 0
                async with _httpx.AsyncClient(timeout=120.0) as client:
                    for iteration in range(1, max_iter + 1):
                        log.write(f"--- Iteration {iteration}/{max_iter} ---\n")
                        log.flush()

                        payload = {
                            "model": model,
                            "messages": messages,
                            "max_tokens": 2048,
                        }

                        try:
                            resp = await client.post(url, json=payload, headers=headers)
                            if resp.status_code != 200:
                                error_text = resp.text[:500]
                                log.write(f"API error ({resp.status_code}): {error_text}\n")
                                logger.warning(f"Agent {agent_id} API error: {resp.status_code}")
                                break

                            data = resp.json()
                            usage = data.get("usage", {})
                            total_tokens += usage.get("total_tokens", 0)

                            choice = data.get("choices", [{}])[0]
                            msg = choice.get("message", {})
                            content = msg.get("content", "")
                            finish_reason = choice.get("finish_reason", "")

                            log.write(f"\n{content}\n\n")
                            log.flush()

                            messages.append({"role": "assistant", "content": content})

                            if finish_reason == "stop":
                                break

                        except _httpx.TimeoutException:
                            log.write("Request timed out\n")
                            break
                        except Exception as e:
                            log.write(f"Error: {e}\n")
                            break

                log.write(f"\n{'=' * 60}\n")
                log.write(f"Finished: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                log.write(f"Total tokens: {total_tokens}\n")
                log.write("Exit: success\n")

                # Fire learning extraction if memory bridge is available
                try:
                    from core.memory_bridge import MemoryBridge

                    memory_store = getattr(self, "_memory_store", None)
                    if memory_store:
                        mb = MemoryBridge(memory_store=memory_store)
                        summary = messages[-1].get("content", "") if messages else ""
                        await mb.learn_async(summary, agent_id)
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"OpenAI agent loop failed for {agent_id}: {e}")
            try:
                with open(log_path, "a", encoding="utf-8") as log:
                    log.write(f"\nFATAL: {e}\n")
            except Exception:
                pass

        agent_proc.status = "completed"

    async def _start_claude_agent(self, agent_config):
        """Launch agent via Claude Code CLI (Anthropic protocol)."""
        agent_id = agent_config.get("id", "unknown")

        claude_bin = shutil.which("claude")
        if not claude_bin:
            logger.error("Claude Code CLI not found")
            return None

        env = self._build_env(agent_config)
        prompt = await self._build_prompt(agent_config)

        timestamp = time.strftime("%Y%m%d-%H%M%S")
        log_path = self._logs_dir / f"{agent_id}-{timestamp}.log"

        logger.info(
            f"Starting agent {agent_id} provider={agent_config.get('provider')} "
            f"model={agent_config.get('model', 'default')}"
        )

        try:
            log_file = open(log_path, "w", encoding="utf-8")
            log_file.write(f"Agent: {agent_config.get('name', agent_id)}\n")
            log_file.write(f"Started: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            log_file.write(f"Provider: {agent_config.get('provider', 'anthropic')}\n")
            log_file.write(f"Model: {agent_config.get('model', 'default')}\n")
            log_file.write("Runner: Claude Code CLI\n")
            log_file.write("=" * 60 + "\n\n")
            log_file.flush()

            cmd_args = [
                claude_bin,
                "-p",
                prompt,
                "--output-format",
                "text",
            ]
            model = agent_config.get("model", "")
            if model:
                cmd_args.extend(["--model", model])

            proc = await asyncio.create_subprocess_exec(
                *cmd_args,
                stdout=log_file,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(self.workspace),
                env=env,
            )

            agent_proc = AgentProcess(
                agent_id=agent_id,
                pid=proc.pid,
                process=proc,
                started_at=time.time(),
                log_file=str(log_path),
                status="running",
            )
            self._processes[agent_id] = agent_proc
            asyncio.create_task(self._monitor(agent_id, proc, log_file))

            logger.info(f"Agent {agent_id} started (PID {proc.pid})")
            return agent_proc
        except Exception as e:
            logger.error(f"Failed to start agent {agent_id}: {e}")
            return None

    async def _monitor(self, agent_id, proc, log_file):
        """Monitor agent process until completion."""
        try:
            await proc.wait()
        except Exception:
            pass
        finally:
            try:
                log_file.write(f"\n{'=' * 60}\n")
                log_file.write(f"Finished: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                log_file.write(f"Exit code: {proc.returncode}\n")
                log_file.close()
            except Exception:
                pass
            if agent_id in self._processes:
                self._processes[agent_id].status = "completed" if proc.returncode == 0 else "error"

    async def stop_agent(self, agent_id):
        """Stop a running agent."""
        ap = self._processes.get(agent_id)
        if not ap or not ap.process:
            return False
        if ap.process.returncode is not None:
            ap.status = "stopped"
            return True
        try:
            ap.process.terminate()
            try:
                await asyncio.wait_for(ap.process.wait(), timeout=5.0)
            except TimeoutError:
                ap.process.kill()
            ap.status = "stopped"
            return True
        except Exception:
            return False

    def get_status(self, agent_id):
        """Get agent process status with last log output."""
        ap = self._processes.get(agent_id)
        if not ap:
            return None
        if ap.process and ap.process.returncode is not None and ap.status == "running":
            ap.status = "completed" if ap.process.returncode == 0 else "error"

        last_output = ""
        if ap.log_file and Path(ap.log_file).exists():
            try:
                with open(ap.log_file, encoding="utf-8", errors="replace") as f:
                    last_output = "".join(f.readlines()[-10:])
            except Exception:
                pass

        return {
            "agent_id": ap.agent_id,
            "pid": ap.pid,
            "status": ap.status,
            "started_at": ap.started_at,
            "uptime": time.time() - ap.started_at if ap.status == "running" else 0,
            "log_file": ap.log_file,
            "last_output": last_output[-500:],
        }

    def list_running(self):
        """List all agent processes."""
        return [self.get_status(aid) for aid in self._processes if self.get_status(aid)]

    def get_log(self, agent_id):
        """Get full log for an agent run."""
        ap = self._processes.get(agent_id)
        if not ap or not ap.log_file:
            return ""
        try:
            return Path(ap.log_file).read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""
