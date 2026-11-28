---
description: Run terminal Claude Code on OpenCode Go or Nvidia through the Frood gateway (go, nvidia, cc, status)
argument-hint: "[mode]"  # go, nvidia, cc, status
---

Run terminal Claude Code through Frood's gateway at `http://127.0.0.1:8000/gw`.

**Modes:**
- `go` — Claude Code using OpenCode Go models (kimi-k3 / glm-5.3-flash / deepseek-v4.1-flash)
  through the gateway. Go spends the same allowance as the oc-workers.
- `nvidia` — Claude Code using Nvidia models (nemotron-3.5-super-vl / qwen3-coder)
  through the gateway.
- `cc` — Claude Code on the owner's normal Anthropic subscription (no gateway, no tier vars).
- `status` — Print one-line Frood health, gateway reachability/auth, the go and nvidia tier
  ids, and the current mode (`FROOD_CC_MODE`, or "subscription").

**Usage:**
```
/frood-cc go
/frood-cc nvidia
/frood-cc cc
/frood-cc status
```

This runs `python3 frood-cc-launcher.py $ARGUMENTS` from the Frood repo root, which:

1. Reads `FROOD_GATEWAY_TOKEN` from the repo `.env`, generating it there if missing (a
   one-time step: after generation, restart Frood with `python frood.py` so the gateway
   picks it up).
2. Checks Frood is running and that `/gw/v1/models` lists the mode's tier ids (unless
   `--no-check` is passed).
3. Builds a clean environment: the desktop app's `CLAUDE_CODE_*` host-auth and
   `ANTHROPIC_BASE_URL` are dropped, the gateway token is passed only through the child
   process environment (never in argv, never printed), and `claude` is launched against
   the gateway.
4. Opens a new terminal when `WAYLAND_DISPLAY` or `DISPLAY` is set (and
   `xdg-terminal-exec` is on PATH); otherwise prints the one-line command to run. Use
   `--here` to run in the current terminal, `--print-cmd` to print the command only,
   `--isolated` for an isolated `CLAUDE_CONFIG_DIR`.

**Switch back to the subscription:**
```
/frood-cc cc
```

`cc` clears the gateway and tier variables so Claude Code uses your normal Anthropic
subscription login.

**Note:** the Claude Desktop app itself cannot be switched — its `ANTHROPIC_BASE_URL` is
app-managed. This launcher only drives terminal Claude Code.

The previous provider-switching modes are retired; use `go`, `nvidia`, `cc` or `status`.
