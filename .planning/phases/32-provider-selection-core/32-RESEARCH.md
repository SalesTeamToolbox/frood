# Phase 32: Provider Selection Core - Research

## Claude Code Subscription Integration

### Current State
Agent42 currently uses the Claude Code CLI to execute agents:
- Agents are launched as subprocesses using `shutil.which("claude")`
- The Claude Code CLI is called with a prompt and output format
- Environment variables are set to configure different providers

### Claude Code Subscription
Based on the existing codebase, Claude Code Subscription appears to be integrated as:
1. The primary execution mechanism for agents via the Claude Code CLI
2. A subscription service that provides access to Claude models
3. Integrated with Agent42's memory system via CC memory files

### Provider Hierarchy Analysis

#### Current Implementation (from tiered_routing_bridge.py)
```python
# Provider selection chain (ROUTE-03, D-06, D-07, D-08)
if preferred_provider:
    provider = preferred_provider  # (1) explicit override
elif os.environ.get("SYNTHETIC_API_KEY"):
    provider = "synthetic"  # (2) L1 workhorse default
else:
    provider = "anthropic"  # (3) fallback when synthetic key missing
```

#### Proposed New Implementation
```python
# New provider selection chain for v5.0
if preferred_provider:
    provider = preferred_provider  # (1) explicit override
elif claude_code_subscription_available():
    provider = "claude_code"  # (2) CC Subscription primary
elif os.environ.get("SYNTHETIC_API_KEY"):
    provider = "synthetic"  # (3) Synthetic.new fallback
else:
    provider = "anthropic"  # (4) other providers fallback
```

### Claude Code CLI Usage (from agent_runtime.py)
```python
claude_bin = shutil.which("claude")
proc = await asyncio.create_subprocess_exec(
    claude_bin,
    "-p",
    prompt,
    "--output-format",
    "text",
    stdout=log_file,
    stderr=asyncio.subprocess.STDOUT,
    cwd=str(self.workspace),
    env=env,
)
```

### Environment Configuration
The current environment building logic supports:
- Synthetic.new with `SYNTHETIC_API_KEY` and custom base URL
- OpenRouter with `OPENROUTER_API_KEY` and custom base URL
- Anthropic with `ANTHROPIC_API_KEY`

### StrongWall Analysis
StrongWall is currently referenced as:
- Configuration in `core/config.py` with `strongwall_api_key` and `strongwall_monthly_cost`
- Environment variable `STRONGWALL_API_KEY` in `.env.example`
- Provider mapping in `PROVIDER_MODELS` in `core/agent_manager.py`
- Base URL configuration with `STRONGWALL_BASE_URL`

### Integration Requirements

#### Claude Code Subscription Integration
1. Determine how to check if Claude Code Subscription is available
2. Configure environment variables for Claude Code CLI to use Subscription
3. Update provider model mappings
4. Add health check mechanism

#### Provider Selection Logic
1. Add function to check Claude Code Subscription availability
2. Update provider selection chain in TieredRoutingBridge
3. Update environment configuration in AgentRuntime
4. Add logging for provider selection decisions

### Technical Considerations

#### Backward Compatibility
- Existing configurations should continue to work
- Graceful degradation when new providers are unavailable
- Maintain existing provider configuration options

#### Environment Variables
- Need to determine what environment variables Claude Code Subscription requires
- How to configure the Claude Code CLI to use Subscription
- Whether special configuration is needed for the CLI itself

#### Health Checks
- How to verify Claude Code Subscription is active and working
- What to check for availability
- How to handle subscription expiration or issues

### Implementation Approach

#### Step 1: Research Claude Code Subscription
1. Determine how to check if Claude Code Subscription is available
2. Identify required environment variables
3. Understand how the Claude Code CLI uses Subscription

#### Step 2: Implement Provider Selection Logic
1. Add function to check Claude Code Subscription availability
2. Update TieredRoutingBridge.resolve() method
3. Add Claude Code Subscription to provider model mappings

#### Step 3: Update Environment Configuration
1. Modify AgentRuntime._build_env() method
2. Add Claude Code Subscription environment configuration
3. Update provider URL mappings

#### Step 4: Remove StrongWall References
1. Remove StrongWall from PROVIDER_MODELS
2. Remove StrongWall configuration from Settings
3. Remove StrongWall environment variables
4. Clean up any remaining references

### Unknowns

1. How to programmatically check if Claude Code Subscription is active
2. What environment variables are required for Claude Code CLI to use Subscription
3. Whether the Claude Code CLI needs special configuration to access Subscription models
4. How to handle cases where Subscription is active but specific models are not available

### Next Steps

1. Create a test to verify Claude Code CLI behavior with Subscription
2. Implement the provider selection logic changes
3. Test the new provider hierarchy
4. Remove StrongWall references
5. Update documentation and configuration files