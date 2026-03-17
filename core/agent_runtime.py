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

logger = logging.getLogger("agent42.agent_runtime")


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
        self._logs_dir = self.workspace / ".agent42" / "agent-logs"
        self._logs_dir.mkdir(parents=True, exist_ok=True)

    def _build_env(self, agent_config):
        """Build environment variables for an agent process."""
        env = {**os.environ}
        provider = agent_config.get("provider", "anthropic")
        provider_url = agent_config.get("provider_url", "")
        model = agent_config.get("model", "")

        if provider == "synthetic":
            env["ANTHROPIC_API_KEY"] = ""
            env["ANTHROPIC_BASE_URL"] = provider_url or "https://api.synthetic.new/v1"
            env["SYNTHETIC_API_KEY"] = os.environ.get("SYNTHETIC_API_KEY", "")
            if model:
                env["ANTHROPIC_MODEL"] = model
        elif provider == "openrouter":
            env["ANTHROPIC_API_KEY"] = ""
            env["ANTHROPIC_BASE_URL"] = provider_url or "https://openrouter.ai/api/v1"
            env["OPENROUTER_API_KEY"] = os.environ.get("OPENROUTER_API_KEY", "")
            if model:
                env["ANTHROPIC_MODEL"] = model
        elif provider == "anthropic":
            if model:
                env["ANTHROPIC_MODEL"] = model

        # Prevent nested Claude Code sessions
        env.pop("CLAUDECODE", None)
        return env

    def _build_prompt(self, agent_config):
        """Build the task prompt for an agent."""
        parts = []
        name = agent_config.get("name", "Agent")
        desc = agent_config.get("description", "")
        parts.append(f"You are {name}. {desc}")

        tools = agent_config.get("tools", [])
        if tools:
            parts.append(f"\nYou have access to these Agent42 MCP tools: {', '.join(tools)}")
            parts.append("Use them as needed to complete your task.")

        skills = agent_config.get("skills", [])
        if skills:
            parts.append(f"\nApply these skill areas: {', '.join(skills)}")

        scope = agent_config.get("memory_scope", "global")
        parts.append(f"\nStore important findings in memory (scope: {scope}).")

        max_iter = agent_config.get("max_iterations", 10)
        parts.append(f"\nWork autonomously. Max iterations: {max_iter}.")
        parts.append("When your task is complete, summarize what you accomplished.")

        return "\n".join(parts)

    async def start_agent(self, agent_config):
        """Launch an agent as a background process."""
        agent_id = agent_config.get("id", "unknown")

        if agent_id in self._processes:
            existing = self._processes[agent_id]
            if existing.status == "running" and existing.process:
                if existing.process.returncode is None:
                    logger.warning(f"Agent {agent_id} already running (PID {existing.pid})")
                    return existing

        claude_bin = shutil.which("claude")
        if not claude_bin:
            logger.error("Claude Code CLI not found")
            return None

        env = self._build_env(agent_config)
        prompt = self._build_prompt(agent_config)

        timestamp = time.strftime("%Y%m%d-%H%M%S")
        log_path = self._logs_dir / f"{agent_id}-{timestamp}.log"

        logger.info(f"Starting agent {agent_id} provider={agent_config.get('provider')} "
                     f"model={agent_config.get('model', 'default')}")

        try:
            log_file = open(log_path, "w", encoding="utf-8")
            log_file.write(f"Agent: {agent_config.get('name', agent_id)}\n")
            log_file.write(f"Started: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            log_file.write(f"Provider: {agent_config.get('provider', 'anthropic')}\n")
            log_file.write(f"Model: {agent_config.get('model', 'default')}\n")
            log_file.write("=" * 60 + "\n\n")
            log_file.flush()

            proc = await asyncio.create_subprocess_exec(
                claude_bin, "-p", prompt, "--output-format", "text",
                stdout=log_file,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(self.workspace),
                env=env,
            )

            agent_proc = AgentProcess(
                agent_id=agent_id, pid=proc.pid, process=proc,
                started_at=time.time(), log_file=str(log_path), status="running",
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
                self._processes[agent_id].status = (
                    "completed" if proc.returncode == 0 else "error"
                )

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
            except asyncio.TimeoutError:
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
                with open(ap.log_file, "r", encoding="utf-8", errors="replace") as f:
                    last_output = "".join(f.readlines()[-10:])
            except Exception:
                pass

        return {
            "agent_id": ap.agent_id, "pid": ap.pid, "status": ap.status,
            "started_at": ap.started_at,
            "uptime": time.time() - ap.started_at if ap.status == "running" else 0,
            "log_file": ap.log_file, "last_output": last_output[-500:],
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
