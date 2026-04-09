#!/usr/bin/env python3
"""
frood-cc-launcher.py - Unified launcher for Claude Code with provider switching

Usage:
    python frood-cc-launcher.py          # Interactive menu
    python frood-cc-launcher.py zen      # Direct launch with Zen
    python frood-cc-launcher.py cc        # Direct launch with CC subscription
    python frood-cc-launcher.py status    # Show current status

Providers:
    zen  - Zen API via Frood proxy (free models: Qwen, MiniMax, Nemotron)
    cc   - Anthropic Claude Code subscription (default)
"""

import os
import sys
import subprocess
import json
import shutil
import urllib.request
import urllib.error
from pathlib import Path

# Configuration
FROOD_URL = "http://localhost:8000"
FROOD_HEALTH = f"{FROOD_URL}/health"
FROOD_MODELS = f"{FROOD_URL}/llm/models"


def check_frood_status():
    """Check if Frood is running and available."""
    try:
        req = urllib.request.Request(FROOD_HEALTH, method="GET")
        with urllib.request.urlopen(req, timeout=3) as response:
            return response.status == 200
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        return False


def get_frood_models():
    """Fetch available models from Frood."""
    try:
        req = urllib.request.Request(FROOD_MODELS, method="GET")
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            return data.get("data", [])
    except Exception:
        return []


def get_env_for_provider(provider):
    """Get environment variables for the selected provider - dynamically from Frood."""
    env = os.environ.copy()

    # Fetch live models from Frood
    models = get_frood_models()

    # Extract models by provider
    zen_models = [m["id"] for m in models if m.get("provider") == "zen"]
    cc_models = [m["id"] for m in models if m.get("provider") == "anthropic"]
    or_models = [m["id"] for m in models if m.get("provider") == "openrouter"]

    # Use first available model from each category, or fall back to sensible defaults
    def get_model(model_list, fallback):
        return model_list[0] if model_list else fallback

    zen_fast = get_model([m for m in zen_models if "qwen" in m.lower()], "qwen3.6-plus-free")
    zen_general = get_model([m for m in zen_models if "minimax" in m.lower()], "minimax-m2.5-free")
    zen_reasoning = get_model(
        [m for m in zen_models if "nemotron" in m.lower()], "nemotron-3-super-free"
    )
    zen_content = get_model([m for m in zen_models if "pickle" in m.lower()], "big-pickle")

    cc_fast = get_model([m for m in cc_models if "haiku" in m.lower()], "claude-haiku-4-5-20251001")
    cc_general = get_model(
        [m for m in cc_models if "sonnet" in m.lower()], "claude-sonnet-4-6-20260217"
    )
    cc_reasoning = get_model(
        [m for m in cc_models if "opus" in m.lower()], "claude-opus-4-6-20260205"
    )

    # OpenRouter models
    or_fast = get_model(
        [m for m in or_models if "gemini" in m.lower()], "google/gemini-2.0-flash-001"
    )
    or_general = get_model(
        [m for m in or_models if "sonnet" in m.lower()], "anthropic/claude-sonnet-4-6"
    )
    or_reasoning = get_model(
        [m for m in or_models if "opus" in m.lower()], "anthropic/claude-opus-4-6"
    )

    if provider == "zen":
        env["ANTHROPIC_BASE_URL"] = f"{FROOD_URL}/llm/v1"
        env["ANTHROPIC_API_KEY"] = os.environ.get("ZEN_API_KEY", "")
        env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = zen_general
        env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = zen_reasoning
        env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = zen_fast
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"

        # Log which models we're using
        print(
            f"   [ZEN] Using models: sonnet={zen_general}, opus={zen_reasoning}, haiku={zen_fast}"
        )

    elif provider == "cc":
        # Clear any custom settings - use default CC
        env.pop("ANTHROPIC_BASE_URL", None)
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("ANTHROPIC_DEFAULT_SONNET_MODEL", None)
        env.pop("ANTHROPIC_DEFAULT_OPUS_MODEL", None)
        env.pop("ANTHROPIC_DEFAULT_HAIKU_MODEL", None)
        env.pop("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", None)

        # Log which models we're using
        print(f"   [CC] Using models: sonnet={cc_general}, opus={cc_reasoning}, haiku={cc_fast}")

    elif provider == "openrouter":
        # OpenRouter via Frood proxy
        env["ANTHROPIC_BASE_URL"] = f"{FROOD_URL}/llm/v1"
        env["ANTHROPIC_API_KEY"] = os.environ.get("OPENROUTER_API_KEY", "")
        env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = or_general
        env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = or_reasoning
        env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = or_fast
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"

        print(f"   [OR] Using models: sonnet={or_general}, opus={or_reasoning}, haiku={or_fast}")

    return env


def find_claude_exe():
    """Find Claude Code executable."""
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Claude" / "claude.exe",
        Path.home() / ".local" / "bin" / "claude.exe",
        Path.home() / "AppData" / "Roaming" / "Claude" / "claude-code" / "2.1.92" / "claude.exe",
        Path("C:/Users/rickw/AppData/Roaming/Claude/claude-code/2.1.92/claude.exe"),
    ]

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    # Try PATH
    for exe in ["claude.exe", "claude"]:
        path = shutil.which(exe)
        if path:
            return path

    return "claude"  # Fallback to PATH


def launch_claude(provider, args=None):
    """Launch Claude Code with the selected provider."""
    claude_exe = find_claude_exe()
    env = get_env_for_provider(provider)

    provider_label = "Zen API" if provider == "zen" else "CC Subscription"
    print(f"\n[ROCKET] Launching Claude Code with {provider_label}...")
    print(f"   Executable: {claude_exe}")

    cmd_args = args if args else []

    try:
        subprocess.run([claude_exe] + cmd_args, env=env, check=False)
    except FileNotFoundError:
        print(f"\n❌ Claude Code not found at: {claude_exe}")
        print("   Please ensure Claude Code is installed.")
        sys.exit(1)


def show_status():
    """Show current provider status."""
    frood_running = check_frood_status()

    print("\n" + "=" * 60)
    print("[BOT] Claude Code Provider Status")
    print("=" * 60)

    print("\n[FROOD] Frood Proxy:")
    if frood_running:
        print("   [OK] Running at http://localhost:8000")
        models = get_frood_models()
        if models:
            zen_count = sum(1 for m in models if m.get("provider") == "zen")
            cc_count = sum(1 for m in models if m.get("provider") == "anthropic")
            or_count = sum(1 for m in models if m.get("provider") == "openrouter")
            print(
                f"   [STATS] Models: {len(models)} total ({zen_count} Zen, {cc_count} CC, {or_count} OpenRouter)"
            )
    else:
        print("   [ERROR] Not running")
        print("   [HINT] Start with: python frood.py")

    print("\n[ENV] Environment:")
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "(not set)")
    print(f"   ANTHROPIC_BASE_URL: {base_url}")

    default_model = os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "(not set)")
    print(f"   Default Model: {default_model}")

    print("\n" + "=" * 60)
    print("[BOT] Claude Code Provider Status")
    print("=" * 60)

    print("\n[FROOD] Frood Proxy:")
    if frood_running:
        print("   [OK] Running at http://localhost:8000")
        models = get_frood_models()
        if models:
            zen_count = sum(1 for m in models if m.get("provider") == "zen")
            cc_count = sum(1 for m in models if m.get("provider") == "anthropic")
            or_count = sum(1 for m in models if m.get("provider") == "openrouter")
            print(
                f"   [STATS] Models: {len(models)} total ({zen_count} Zen, {cc_count} CC, {or_count} OpenRouter)"
            )
    else:
        print("   [ERROR] Not running")
        print("   [HINT] Start with: python frood.py")

    print("\n[ENV] Environment:")
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "(not set)")
    print(f"   ANTHROPIC_BASE_URL: {base_url}")

    default_model = os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "(not set)")
    print(f"   Default Model: {default_model}")

    print("\n" + "=" * 60)


def show_menu():
    """Show interactive menu with all available models."""
    frood_running = check_frood_status()
    models = get_frood_models() if frood_running else []

    # Group models by provider
    zen_models = sorted(set(m["id"] for m in models if m.get("provider") == "zen"))
    cc_models = sorted(set(m["id"] for m in models if m.get("provider") == "anthropic"))
    or_models = sorted(set(m["id"] for m in models if m.get("provider") == "openrouter"))

    print("\n" + "=" * 60)
    print("[TARGET] Claude Code Launcher")
    print("=" * 60)
    print("\nAvailable models:")

    # CC Subscription models
    print("\n  [1] Claude Code Subscription (Anthropic)")
    for m in cc_models:
        print(f"       - {m}")

    # Frood providers
    if frood_running:
        print("\n  [2] Frood - Zen API (Free)")
        for m in zen_models:
            print(f"       - {m}")

        print("\n  [3] Frood - OpenRouter (Paid)")
        for m in or_models:
            print(f"       - {m}")
    else:
        print("\n  [2] Frood - NOT RUNNING")
        print("  [3] Frood - NOT RUNNING")

    print("\n  [4] Status      - Show current configuration")
    print("  [5] Exit        - Quit")

    print("=" * 60)

    while True:
        choice = input("\n> ").strip()

        if choice == "1":
            # CC Subscription
            launch_claude("cc")
            break
        elif choice == "2":
            if frood_running:
                launch_claude("zen")
            else:
                print("[ERROR] Frood is not running. Start it first with: python frood.py")
        elif choice == "3":
            if frood_running:
                launch_claude("openrouter")
            else:
                print("[ERROR] Frood is not running. Start it first with: python frood.py")
        elif choice == "4":
            show_status()
            show_menu()
            break
        elif choice == "5":
            print("Bye!")
            break
        else:
            print("Invalid choice. Please enter 1-5.")


def main():
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()

        if arg in ["zen", "z"]:
            if check_frood_status():
                launch_claude("zen", sys.argv[2:])
            else:
                print("[ERROR] Frood is not running. Start it first with: python frood.py")
                sys.exit(1)

        elif arg in ["cc", "claude", "c"]:
            launch_claude("cc", sys.argv[2:])

        elif arg in ["status", "s"]:
            show_status()

        elif arg in ["help", "h", "-h", "--help"]:
            print(__doc__)

        else:
            print(f"Unknown argument: {arg}")
            print(__doc__)
            sys.exit(1)
    else:
        show_menu()


if __name__ == "__main__":
    main()
