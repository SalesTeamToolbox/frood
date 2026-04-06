# Phase 33: Synthetic.new Integration - Research

## Current Synthetic.new Integration

### Existing Implementation
Agent42 already has Synthetic.new integration:
- Configuration in `core/config.py` with `synthetic_api_key`
- Provider mapping in `PROVIDER_MODELS` in `core/agent_manager.py`
- Environment configuration in `AgentRuntime._build_env()`

### Current Provider Models for Synthetic.new
```python
"synthetic": {
    "fast": "hf:zai-org/GLM-4.7-Flash",
    "general": "hf:zai-org/GLM-4.7",
    "reasoning": "hf:moonshotai/Kimi-K2-Thinking",
    "coding": "hf:Qwen/Qwen3-Coder-480B-A35B-Instruct",
    "content": "hf:Qwen/Qwen3.5-397B-A17B",
    "research": "hf:moonshotai/Kimi-K2.5",
    "monitoring": "hf:zai-org/GLM-4.7-Flash",
    "marketing": "hf:MiniMaxAI/MiniMax-M2.5",
    "analysis": "hf:deepseek-ai/DeepSeek-R1-0528",
    "lightweight": "hf:meta-llama/Llama-3.3-70B-Instruct",
},
```

### Current Environment Configuration
```python
elif provider == "synthetic":
    env["ANTHROPIC_API_KEY"] = ""
    env["ANTHROPIC_BASE_URL"] = provider_url or "https://api.synthetic.new/v1"
    env["SYNTHETIC_API_KEY"] = os.environ.get("SYNTHETIC_API_KEY", "")
    if model:
        env["ANTHROPIC_MODEL"] = model
```

## Synthetic.new API Analysis

### Required Research
1. What endpoints does Synthetic.new provide for model discovery?
2. What authentication mechanism is used?
3. What is the response format for model information?
4. How often can the API be called?
5. What rate limiting applies?

### Assumptions
Based on the existing integration:
- Synthetic.new uses an Anthropic-compatible API
- Base URL is `https://api.synthetic.new/v1`
- Authentication is via `SYNTHETIC_API_KEY` header
- Models are identified by HuggingFace-style identifiers

## Dynamic Model Discovery Requirements

### API Endpoint
Need to determine if Synthetic.new provides:
1. A model listing endpoint (e.g., `/models` or `/v1/models`)
2. Model details endpoint (e.g., `/models/{model_id}`)
3. Health check endpoint (e.g., `/health` or `/v1/health`)

### Response Format
Expected information from model discovery:
- Model ID/name
- Model capabilities
- Context window size
- Pricing information (if available)
- Availability status
- Performance metrics (if available)

### Caching Strategy
Requirements for caching:
- In-memory cache with TTL (24 hours default)
- File-based persistence for restart resilience
- Cache invalidation on demand
- Thread-safe access patterns

### Refresh Mechanism
Requirements for refresh:
- Automatic refresh every 24 hours
- Manual refresh via admin endpoint
- Background refresh without blocking
- Failure handling and retry logic

## Health Check Integration

### Startup Validation
Requirements:
- Validate API key on startup
- Check API availability
- Log validation results
- Graceful degradation on failure

### Runtime Monitoring
Requirements:
- Periodic health checks
- Status reporting via admin endpoints
- Alerting on failures
- Automatic fallback behavior

## Agent Configuration Updates

### UI Requirements
- Model selection dropdown in agent configuration
- Real-time model availability status
- Model details display
- Search/filter capabilities

### Backend Requirements
- Extended agent configuration schema
- Model selection persistence
- Backward compatibility
- Migration for existing agents

## Technical Considerations

### Rate Limiting
- Determine Synthetic.new API rate limits
- Implement appropriate throttling
- Handle rate limit errors gracefully
- Queue requests if necessary

### Error Handling
- Network errors
- Authentication errors
- API errors
- Parsing errors
- Timeout errors

### Security
- Secure storage of API key
- Sanitization of API responses
- Protection against injection attacks
- Secure communication (HTTPS)

### Performance
- Cache performance
- API response times
- Memory usage
- Concurrent access handling

## Implementation Approach

### Step 1: API Discovery
1. Research Synthetic.new API documentation
2. Identify model discovery endpoints
3. Determine authentication requirements
4. Test API endpoints with existing key

### Step 2: Client Development
1. Create SyntheticNewAPIClient class
2. Implement model discovery
3. Add health check functionality
4. Implement error handling

### Step 3: Caching Implementation
1. Design cache data structure
2. Implement in-memory cache
3. Add file-based persistence
4. Implement cache invalidation

### Step 4: Refresh Mechanism
1. Create refresh scheduler
2. Implement automatic refresh
3. Add manual refresh endpoint
4. Handle refresh failures

### Step 5: Health Check Integration
1. Implement startup validation
2. Add runtime monitoring
3. Create status reporting
4. Implement alerting

### Step 6: Configuration Updates
1. Extend agent configuration schema
2. Update UI components
3. Implement persistence
4. Add backward compatibility

## Unknowns

1. What endpoints Synthetic.new provides for model discovery
2. Rate limits and usage restrictions
3. Response format for model information
4. Health check endpoint availability
5. Authentication mechanism details
6. Model update frequency and notification mechanisms

## Next Steps

1. Research Synthetic.new API documentation
2. Test existing API key with potential endpoints
3. Implement API client based on findings
4. Design and implement caching system
5. Create refresh mechanism
6. Integrate health checks
7. Update agent configuration
8. Test and verify implementation