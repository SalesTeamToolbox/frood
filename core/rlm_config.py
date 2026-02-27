"""
RLM (Recursive Language Model) configuration.

Loads RLM settings from environment variables and .agent42/settings.json.
All fields follow the existing Settings pattern: env var with sensible default.
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RLMConfig:
    """Immutable RLM configuration derived from environment variables."""

    enabled: bool = True
    threshold_tokens: int = 50_000
    environment: str = "local"
    max_depth: int = 3
    max_iterations: int = 20
    root_model: str | None = None
    sub_model: str | None = None
    log_dir: str = ".agent42/rlm_logs"
    verbose: bool = False
    cost_limit: float = 1.00
    timeout_seconds: int = 300
    docker_image: str = "python:3.11-slim"

    @classmethod
    def from_env(cls) -> "RLMConfig":
        """Load RLM configuration from environment variables."""
        return cls(
            enabled=os.getenv("RLM_ENABLED", "true").lower() in ("true", "1", "yes"),
            threshold_tokens=int(os.getenv("RLM_THRESHOLD_TOKENS", "50000")),
            environment=os.getenv("RLM_ENVIRONMENT", "local"),
            max_depth=int(os.getenv("RLM_MAX_DEPTH", "3")),
            max_iterations=int(os.getenv("RLM_MAX_ITERATIONS", "20")),
            root_model=os.getenv("RLM_ROOT_MODEL") or None,
            sub_model=os.getenv("RLM_SUB_MODEL") or None,
            log_dir=os.getenv("RLM_LOG_DIR", ".agent42/rlm_logs"),
            verbose=os.getenv("RLM_VERBOSE", "false").lower() in ("true", "1", "yes"),
            cost_limit=float(os.getenv("RLM_COST_LIMIT", "1.00")),
            timeout_seconds=int(os.getenv("RLM_TIMEOUT_SECONDS", "300")),
            docker_image=os.getenv("RLM_DOCKER_IMAGE", "python:3.11-slim"),
        )


# Singleton — import this everywhere
rlm_config = RLMConfig.from_env()
