# Configuration Reference

### Required Settings

| Variable | Purpose | Default |
|----------|---------|---------|
| `OPENROUTER_API_KEY` | OpenRouter API key (free tier available) | *(none)* |
| `DASHBOARD_PASSWORD` | Dashboard login password | *(none — login disabled)* |

### Security Settings

| Variable | Purpose | Default | Warning |
|----------|---------|---------|---------|
| `SANDBOX_ENABLED` | Enforce filesystem boundaries | `true` | Never disable in production |
| `COMMAND_FILTER_MODE` | Shell filtering mode | `deny` | `allowlist` for strict production |
| `JWT_SECRET` | JWT signing key | *(auto-generated)* | Set explicitly for persistent sessions |
| `DASHBOARD_HOST` | Dashboard bind address | `127.0.0.1` | Never use `0.0.0.0` without nginx |
| `DASHBOARD_PASSWORD_HASH` | Bcrypt password hash | *(none)* | Use instead of plaintext password |
| `MAX_DAILY_API_SPEND_USD` | Daily API spending cap | `0` (unlimited) | Set a cap for production |

### Tool Plugin Settings

| Variable | Purpose | Default |
|----------|---------|---------|
| `CUSTOM_TOOLS_DIR` | Directory for auto-discovered custom tool plugins | *(disabled)* |

### Dynamic Model Routing Settings

| Variable | Purpose | Default |
|----------|---------|---------|
| `MODEL_ROUTING_FILE` | Path to dynamic routing data | `data/dynamic_routing.json` |
| `MODEL_CATALOG_REFRESH_HOURS` | OpenRouter catalog sync interval | `24` |
| `MODEL_TRIAL_PERCENTAGE` | % of tasks assigned to unproven models | `10` |
| `MODEL_MIN_TRIALS` | Minimum completions before model is ranked | `5` |
| `MODEL_RESEARCH_ENABLED` | Enable web benchmark research | `true` |
| `MODEL_RESEARCH_INTERVAL_HOURS` | Research fetch interval | `168` (weekly) |

### Scope Detection Settings

| Variable | Purpose | Default |
|----------|---------|---------|
| `SCOPE_DETECTION_ENABLED` | Enable scope change detection between messages | `true` |
| `SCOPE_DETECTION_CONFIDENCE_THRESHOLD` | Below this confidence, ask user to confirm scope change | `0.5` |

### Optional Backends

| Variable | Purpose | Default |
|----------|---------|---------|
| `REDIS_URL` | Redis for session cache + queue | *(disabled)* |
| `QDRANT_URL` | Qdrant for vector semantic search | *(disabled)* |
| `QDRANT_ENABLED` | Enable Qdrant (auto if URL set) | `false` |

### SSH & Tunnel Settings

| Variable | Purpose | Default |
|----------|---------|---------|
| `SSH_ENABLED` | Enable SSH remote shell tool | `false` |
| `SSH_ALLOWED_HOSTS` | Comma-separated host patterns | *(empty — all blocked)* |
| `SSH_DEFAULT_KEY_PATH` | Default private key path | *(none)* |
| `SSH_MAX_UPLOAD_MB` | Max SFTP upload size | `50` |
| `SSH_COMMAND_TIMEOUT` | Per-command timeout (seconds) | `120` |
| `TUNNEL_ENABLED` | Enable tunnel manager tool | `false` |
| `TUNNEL_PROVIDER` | auto, cloudflared, serveo, localhost.run | `auto` |
| `TUNNEL_ALLOWED_PORTS` | Comma-separated allowed ports | *(empty — all allowed)* |
| `TUNNEL_TTL_MINUTES` | Auto-shutdown TTL | `60` |

### Knowledge & Vision Settings

| Variable | Purpose | Default |
|----------|---------|---------|
| `KNOWLEDGE_DIR` | Document storage directory | `.agent42/knowledge` |
| `KNOWLEDGE_CHUNK_SIZE` | Chunk size in tokens | `500` |
| `KNOWLEDGE_CHUNK_OVERLAP` | Overlap between chunks | `50` |
| `KNOWLEDGE_MAX_RESULTS` | Max results per query | `10` |
| `VISION_MAX_IMAGE_MB` | Max image file size | `10` |
| `VISION_MODEL` | Override model for vision tasks | *(auto-detect)* |

### Apps Platform Settings

| Variable | Purpose | Default |
|----------|---------|---------|
| `APPS_ENABLED` | Enable the apps platform | `true` |
| `APPS_DIR` | Base directory for all apps | `apps` |
| `APPS_PORT_RANGE_START` | Dynamic port allocation start | `9100` |
| `APPS_PORT_RANGE_END` | Dynamic port allocation end | `9199` |
| `APPS_MAX_RUNNING` | Max simultaneously running apps | `5` |
| `APPS_AUTO_RESTART` | Restart crashed apps | `true` |
| `APPS_MONITOR_INTERVAL` | Seconds between health-check polls | `15` |
| `APPS_DEFAULT_RUNTIME` | Default runtime for new apps | `python` |
| `APPS_GIT_ENABLED_DEFAULT` | Enable git for new apps by default | `false` |
| `APPS_GITHUB_TOKEN` | GitHub PAT for repo creation/push | *(disabled)* |
| `APPS_DEFAULT_MODE` | Default mode for new apps (`internal`/`external`) | `internal` |
| `APPS_REQUIRE_AUTH_DEFAULT` | Require dashboard auth by default for new apps | `false` |

### Chat Session Settings

| Variable | Purpose | Default |
|----------|---------|---------|
| `CHAT_SESSIONS_DIR` | Directory for session JSONL storage | `.agent42/chat_sessions` |

### Project Settings

| Variable | Purpose | Default |
|----------|---------|---------|
| `PROJECTS_DIR` | Directory for project data | `.agent42/projects` |

### GitHub OAuth Settings

| Variable | Purpose | Default |
|----------|---------|---------|
| `GITHUB_CLIENT_ID` | GitHub OAuth App Client ID (device flow) | *(disabled)* |
| `GITHUB_OAUTH_TOKEN` | Token stored after device flow auth | *(auto-populated)* |

### Project Interview Settings

| Variable | Purpose | Default |
|----------|---------|---------|
| `PROJECT_INTERVIEW_ENABLED` | Enable structured project discovery interviews | `true` |
| `PROJECT_INTERVIEW_MODE` | Gating mode: `auto` (complexity-based), `always`, `never` | `auto` |
| `PROJECT_INTERVIEW_MAX_ROUNDS` | Maximum interview rounds | `4` |
| `PROJECT_INTERVIEW_MIN_COMPLEXITY` | Minimum complexity to trigger: `moderate` or `complex` | `moderate` |

See `.env.example` for the complete list of 80+ configuration variables.
