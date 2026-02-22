"""
Dynamic agent capacity calculation based on real-time server load.

Uses CPU load averages and available memory to determine how many agents
can safely run concurrently, replacing a static configured limit.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger("agent42.capacity")

# Per-agent estimated memory cost in MB
_AGENT_MEMORY_MB = 256

# Minimum available memory before clamping to 1 agent
_MIN_MEMORY_MB = 512

# CPU load thresholds (per core)
_LOAD_SCALE_START = 0.80  # Begin scaling down
_LOAD_SCALE_CRITICAL = 0.95  # Clamp to 1 agent


def _read_meminfo() -> tuple[float, float]:
    """Read total and available memory from /proc/meminfo.

    Returns (total_mb, available_mb). Falls back to os.sysconf on
    platforms without /proc/meminfo.
    """
    meminfo_path = Path("/proc/meminfo")
    if meminfo_path.exists():
        try:
            text = meminfo_path.read_text()
            total_kb = 0
            available_kb = 0
            for line in text.splitlines():
                if line.startswith("MemTotal:"):
                    total_kb = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    available_kb = int(line.split()[1])
            if total_kb > 0:
                return total_kb / 1024, available_kb / 1024
        except (OSError, ValueError, IndexError):
            pass

    # Fallback: os.sysconf
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        total_pages = os.sysconf("SC_PHYS_PAGES")
        avail_pages = os.sysconf("SC_AVPHYS_PAGES")
        total_mb = (total_pages * page_size) / (1024 * 1024)
        avail_mb = (avail_pages * page_size) / (1024 * 1024)
        return total_mb, avail_mb
    except (ValueError, OSError):
        return 0.0, 0.0


def compute_effective_capacity(configured_max: int) -> dict:
    """Compute how many agents can run based on current system load.

    Args:
        configured_max: The operator-configured maximum (from settings).

    Returns a dict with:
        effective_max: int — actual number of agents allowed right now
        cpu_load_1m, cpu_load_5m, cpu_load_15m: float — load averages
        cpu_cores: int — number of logical CPU cores
        load_per_core: float — 1-min load / cores
        memory_total_mb, memory_available_mb: float
        reason: str — human-readable explanation of limiting factor
    """
    # --- CPU ---
    try:
        load_1m, load_5m, load_15m = os.getloadavg()
    except OSError:
        load_1m = load_5m = load_15m = 0.0

    cpu_cores = os.cpu_count() or 1
    load_per_core = load_1m / cpu_cores

    # CPU-based capacity
    if load_per_core >= _LOAD_SCALE_CRITICAL:
        cpu_cap = 1
        cpu_reason = f"CPU critically loaded ({load_per_core:.2f}/core)"
    elif load_per_core >= _LOAD_SCALE_START:
        # Linear interpolation: configured_max at 0.80 -> 1 at 0.95
        fraction = (load_per_core - _LOAD_SCALE_START) / (_LOAD_SCALE_CRITICAL - _LOAD_SCALE_START)
        cpu_cap = max(1, int(configured_max - fraction * (configured_max - 1)))
        cpu_reason = f"CPU load elevated ({load_per_core:.2f}/core), scaling down"
    else:
        cpu_cap = configured_max
        cpu_reason = ""

    # --- Memory ---
    memory_total_mb, memory_available_mb = _read_meminfo()

    if memory_available_mb > 0 and memory_available_mb < _MIN_MEMORY_MB:
        mem_cap = 1
        mem_reason = f"Low memory ({memory_available_mb:.0f}MB available)"
    elif memory_available_mb > 0:
        mem_cap = max(1, int(memory_available_mb / _AGENT_MEMORY_MB))
        mem_reason = (
            f"Memory allows ~{mem_cap} agents ({memory_available_mb:.0f}MB available)"
            if mem_cap < configured_max
            else ""
        )
    else:
        # Cannot read memory — don't constrain
        mem_cap = configured_max
        mem_reason = ""

    # --- Combine ---
    absolute_max = cpu_cores * 2
    effective = min(cpu_cap, mem_cap, configured_max, absolute_max)
    effective = max(1, effective)

    # Determine the reason string
    if effective == configured_max and not cpu_reason and not mem_reason:
        reason = "System load nominal — full capacity available"
    elif cpu_cap <= mem_cap:
        reason = cpu_reason or "CPU is the limiting factor"
    else:
        reason = mem_reason or "Memory is the limiting factor"

    return {
        "effective_max": effective,
        "cpu_load_1m": round(load_1m, 2),
        "cpu_load_5m": round(load_5m, 2),
        "cpu_load_15m": round(load_15m, 2),
        "cpu_cores": cpu_cores,
        "load_per_core": round(load_per_core, 2),
        "memory_total_mb": round(memory_total_mb, 1),
        "memory_available_mb": round(memory_available_mb, 1),
        "configured_max": configured_max,
        "reason": reason,
    }
