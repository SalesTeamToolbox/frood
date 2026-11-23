#!/usr/bin/env python3
"""
frood-cc-launcher.py - Unified launcher for Claude Code with provider switching

Usage:
    python frood-cc-launcher.py          # Interactive menu
    python frood-cc-launcher.py zen      # Direct launch with Zen (free)
    python frood-cc-launcher.py opencode # Direct launch with OpenCode Go
    python frood-cc-launcher.py cmdcode  # Direct launch with CommandCode GOAT
    python frood-cc-launcher.py nvidia   # Direct launch with Nvidia
    python frood-cc-launcher.py openrouter # Direct launch with OpenRouter
    python frood-cc-launcher.py cc       # Direct launch with CC subscription
    python frood-cc-launcher.py status   # Show current status

Providers:
    zen        - Zen API via Frood proxy (free: Qwen, MiniMax, Nemotron)
    opencode   - OpenCode Go API ($10/mo Pro, $40/mo Max)
    cmdcode    - CommandCode GOAT ($10/mo flat)
    nvidia     - Nvidia build.nvidia.com (free tier: Nemotron, Qwen, DeepSeek)
    openrouter - OpenRouter via Frood (200+ models)
    cc         - Anthropic Claude Code subscription (default)
"""

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
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
    oc_models = [m["id"] for m in models if m.get("provider") == "opencode"]
    cmd_models = [m["id"] for m in models if m.get("provider") == "commandcode"]
    nv_models = [m["id"] for m in models if m.get("provider") == "nvidia"]

    def get_model(model_list, fallback):
        return model_list[0] if model_list else fallback

    # Zen models
    zen_fast = get_model([m for m in zen_models if "qwen" in m.lower()], "qwen3.6-plus-free")
    zen_general = get_model([m for m in zen_models if "minimax" in m.lower()], "minimax-m2.5-free")
    zen_reasoning = get_model(
        [m for m in zen_models if "nemotron" in m.lower()], "nemotron-3-super-free"
    )
    get_model([m for m in zen_models if "pickle" in m.lower()], "big-pickle")

    # CC models
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

    # OpenCode models
    oc_fast = get_model(
        [m for m in oc_models if "haiku" in m.lower()], "opencode-go/mimo-v2.6-flash"
    )
    oc_general = get_model(
        [m for m in oc_models if "sonnet" in m.lower()], "opencode-go/muse-spark-1.3-contributor"
    )
    oc_reasoning = get_model(
        [m for m in oc_models if "opus" in m.lower()], "commandcode/meta/muse-spark-1.3-contributor"
    )

    # CommandCode models
    cmd_fast = get_model(
        [m for m in cmd_models if "haiku" in m.lower()], "commandcode/claude-haiku-5-5"
    )
    cmd_general = get_model(
        [m for m in cmd_models if "sonnet" in m.lower()], "commandcode/claude-sonnet-5-5"
    )
    cmd_reasoning = get_model(
        [m for m in cmd_models if "opus" in m.lower()], "commandcode/claude-opus-5-5"
    )

    # Nvidia models
    nv_fast = get_model([m for m in nv_models if "qwen" in m.lower()], "qwen/qwen3.5-397b-a17b")
    nv_general = get_model(
        [m for m in nv_models if "nemotron" in m.lower()], "nvidia/llama-3.1-nemotron-ultra-253b-v1"
    )
    nv_reasoning = get_model(
        [m for m in nv_models if "deepseek" in m.lower()], "deepseek-ai/deepseek-v3.2"
    )

    if provider == "zen":
        env["ANTHROPIC_BASE_URL"] = f"{FROOD_URL}/llm/v1"
        env["ANTHROPIC_API_KEY"] = os.environ.get("ZEN_API_KEY", "")
        env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = zen_general
        env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = zen_reasoning
        env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = zen_fast
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
        print(f"   [ZEN] Models: sonnet={zen_general}, opus={zen_reasoning}, haiku={zen_fast}")

    elif provider == "opencode":
        env["ANTHROPIC_BASE_URL"] = f"{FROOD_URL}/llm/v1"
        env["ANTHROPIC_API_KEY"] = os.environ.get("OPENCODE_API_KEY", "")
        env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = oc_general
        env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = oc_reasoning
        env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = oc_fast
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
        print(f"   [OPENCODE] Models: sonnet={oc_general}, opus={oc_reasoning}, haiku={oc_fast}")

    elif provider == "cmdcode":
        env["ANTHROPIC_BASE_URL"] = f"{FROOD_URL}/llm/v1"
        env["ANTHROPIC_API_KEY"] = os.environ.get("COMMANDCODE_API_KEY", "")
        env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = cmd_general
        env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = cmd_reasoning
        env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = cmd_fast
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
        print(f"   [CMDCODE] Models: sonnet={cmd_general}, opus={cmd_reasoning}, haiku={cmd_fast}")

    elif provider == "nvidia":
        env["ANTHROPIC_BASE_URL"] = f"{FROOD_URL}/llm/v1"
        env["ANTHROPIC_API_KEY"] = os.environ.get("NVIDIA_API_KEY", "")
        env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = nv_general
        env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = nv_reasoning
        env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = nv_fast
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
        print(f"   [NVIDIA] Models: sonnet={nv_general}, opus={nv_reasoning}, haiku={nv_fast}")

    elif provider == "openrouter":
        env["ANTHROPIC_BASE_URL"] = f"{FROOD_URL}/llm/v1"
        env["ANTHROPIC_API_KEY"] = os.environ.get("OPENROUTER_API_KEY", "")
        env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = or_general
        env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = or_reasoning
        env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = or_fast
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
        print(f"   [OPENROUTER] Models: sonnet={or_general}, opus={or_reasoning}, haiku={or_fast}")

    elif provider == "cc":
        # Clear any custom settings - use default CC
        env.pop("ANTHROPIC_BASE_URL", None)
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("ANTHROPIC_DEFAULT_SONNET_MODEL", None)
        env.pop("ANTHROPIC_DEFAULT_OPUS_MODEL", None)
        env.pop("ANTHROPIC_DEFAULT_HAIKU_MODEL", None)
        env.pop("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", None)
        print(f"   [CC] Models: sonnet={cc_general}, opus={cc_reasoning}, haiku={cc_fast}")

    return env


def find_claude_exe():
    """Find Claude Code executable."""
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Claude" / "claude.exe",
        Path.home() / ".local" / "bin" / "claude.exe",
        Path.home() / "AppData" / "Roaming" / "Claude" / "claude-code" / "2.1.92" / "claude.exe",
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

    provider_labels = {
        "zen": "Zen API (Free)",
        "opencode": "OpenCode Go",
        "cmdcode": "CommandCode GOAT",
        "nvidia": "Nvidia (Free)",
        "openrouter": "OpenRouter",
        "cc": "CC Subscription",
    }
    provider_label = provider_labels.get(provider, provider)

    print(f"\n🚀 Launching Claude Code with {provider_label}...")
    print(f"   Executable: {claude_exe}")

    cmd_args = args if args else []

    try:
        subprocess.run([claude_exe, *cmd_args], env=env, check=False)
    except FileNotFoundError:
        print(f"\n❌ Claude Code not found at: {claude_exe}")
        print("   Please ensure Claude Code is installed.")
        sys.exit(1)


def show_status():
    """Show current provider status."""
    frood_running = check_frood_status()

    print("\n" + "=" * 60)
    print("🤖 Claude Code Provider Status")
    print("=" * 60)

    print("\n🐛 Frood Proxy:")
    if frood_running:
        print("   ✅ Running at http://localhost:8000")
        models = get_frood_models()
        if models:
            providers = {}
            for m in models:
                p = m.get("provider", "unknown")
                providers[p] = providers.get(p, 0) + 1
            for p, count in sorted(providers.items()):
                print(f"   📊 {p}: {count} models")
    else:
        print("   ❌ Not running")
        print("   💡 Start with: python frood.py")

    print("\n🌍 Environment:")
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
    providers = {
        "cc": {"label": "Claude Code Subscription", "models": []},
        "zen": {"label": "Zen API (Free)", "models": []},
        "opencode": {"label": "OpenCode Go ($10-40/mo)", "models": []},
        "cmdcode": {"label": "CommandCode GOAT ($10/mo)", "models": []},
        "nvidia": {"label": "Nvidia (Free)", "models": []},
        "openrouter": {"label": "OpenRouter (200+ models)", "models": []},
    }

    for m in models:
        p = m.get("provider", "unknown")
        if p in providers:
            providers[p]["models"].append(m["id"])

    print("\n" + "=" * 60)
    print("🎯 Claude Code Launcher")
    print("=" * 60)
    print("\nAvailable providers:")

    # CC Subscription
    print("\n  [1] Claude Code Subscription (Anthropic)")
    for m in providers["cc"]["models"]:
        print(f"       - {m}")

    # Frood providers
    if frood_running:
        print("\n  [2] Frood - Zen API (Free)")
        for m in providers["zen"]["models"]:
            print(f"       - {m}")

        print("\n  [3] Frood - OpenCode Go ($10-40/mo)")
        for m in providers["opencode"]["models"]:
            print(f"       - {m}")

        print("\n  [4] Frood - CommandCode GOAT ($10/mo)")
        for m in providers["cmdcode"]["models"]:
            print(f"       - {m}")

        print("\n  [5] Frood - Nvidia (Free)")
        for m in providers["nvidia"]["models"]:
            print(f"       - {m}")

        print("\n  [6] Frood - OpenRouter (200+ models)")
        for m in providers["openrouter"]["models"]:
            print(f"       - {m}")
    else:
        print("\n  [2-6] Frood - NOT RUNNING")

    print("\n  [s] Status      - Show current configuration")
    print("  [q] Exit        - Quit")

    print("=" * 60)

    while True:
        choice = input("\n> ").strip().lower()

        if choice in ["1", "cc"]:
            launch_claude("cc")
            break
        elif choice in ["2", "zen"]:
            if frood_running:
                launch_claude("zen")
            else:
                print("❌ Frood is not running. Start it first with: python frood.py")
        elif choice in ["3", "opencode", "oc"]:
            if frood_running:
                launch_claude("opencode")
            else:
                print("❌ Frood is not running. Start it first with: python frood.py")
        elif choice in ["4", "cmdcode", "cmd"]:
            if frood_running:
                launch_claude("cmdcode")
            else:
                print("❌ Frood is not running. Start it first with: python frood.py")
        elif choice in ["5", "nvidia", "nv"]:
            if frood_running:
                launch_claude("nvidia")
            else:
                print("❌ Frood is not running. Start it first with: python frood.py")
        elif choice in ["6", "openrouter", "or"]:
            if frood_running:
                launch_claude("openrouter")
            else:
                print("❌ Frood is not running. Start it first with: python frood.py")
        elif choice in ["s", "status"]:
            show_status()
            show_menu()
            break
        elif choice in ["q", "quit", "exit", "5"]:
            print("Bye!")
            break
        else:
            print("Invalid choice. Please enter 1-6, s, or q.")


def main():
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()

        if arg in ["zen", "z"]:
            if check_frood_status():
                launch_claude("zen", sys.argv[2:])
            else:
                print("❌ Frood is not running. Start it first with: python frood.py")
                sys.exit(1)

        elif arg in ["opencode", "oc"]:
            if check_frood_status():
                launch_claude("opencode", sys.argv[2:])
            else:
                print("❌ Frood is not running. Start it first with: python frood.py")
                sys.exit(1)

        elif arg in ["cmdcode", "cmd"]:
            if check_frood_status():
                launch_claude("cmdcode", sys.argv[2:])
            else:
                print("❌ Frood is not running. Start it first with: python frood.py")
                sys.exit(1)

        elif arg in ["nvidia", "nv"]:
            if check_frood_status():
                launch_claude("nvidia", sys.argv[2:])
            else:
                print("❌ Frood is not running. Start it first with: python frood.py")
                sys.exit(1)

        elif arg in ["openrouter", "or"]:
            if check_frood_status():
                launch_claude("openrouter", sys.argv[2:])
            else:
                print("❌ Frood is not running. Start it first with: python frood.py")
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
