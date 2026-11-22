---
description: Switch Claude Code LLM provider via Frood proxy (zen, opencode, cmdcode, nvidia, openrouter, cc)
argument-hint: "[provider]"  # zen, opencode, cmdcode, nvidia, openrouter, cc, status
---

Launch or switch Claude Code's LLM provider via Frood's unified proxy.

**Providers:**
- `zen` / `z` — Zen API (free: Qwen, MiniMax, Nemotron-3-Super)
- `opencode` / `oc` — OpenCode Go ($10-40/mo: MiMo, Muse)
- `cmdcode` / `cmd` — CommandCode GOAT ($10/mo: Haiku, Sonnet, Opus)
- `nvidia` / `nv` — Nvidia (free: Nemotron, Qwen, DeepSeek)
- `openrouter` / `or` — OpenRouter (200+ models)
- `cc` / `c` — Claude Code subscription (default)
- `status` / `s` — Show current configuration

**Usage:**
```
/frood-cc zen
/frood-cc opencode
/frood-cc cmdcode
/frood-cc nvidia
/frood-cc openrouter
/frood-cc cc
/frood-cc status
```

This runs `python frood-cc-launcher.py $ARGUMENTS` in the background, which:
1. Checks Frood is running (starts on port 8000)
2. Fetches available models from Frood's `/llm/models`
3. Sets `ANTHROPIC_BASE_URL` and `ANTHROPIC_API_KEY` for the provider
4. Launches Claude Code with the provider's environment

**Switch back to CC subscription anytime:**
```
/frood-cc cc
```

This clears the custom `ANTHROPIC_BASE_URL` and uses your native Claude Code subscription.