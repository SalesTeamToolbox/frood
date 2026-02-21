---
name: monitoring
description: Set up logging, metrics, alerting, and observability for applications.
always: false
task_types: [coding, debugging]
---

# Monitoring and Observability

## Three Pillars of Observability

### 1. Logs
Discrete events that describe what happened at a specific point in time.
- Use **structured logging** (JSON format) so logs are machine-parseable.
- Include context: timestamp, log level, service name, request ID, user ID.
- Example (JSON):
```json
{
  "timestamp": "2025-01-15T10:23:45Z",
  "level": "ERROR",
  "service": "payment-api",
  "request_id": "abc-123",
  "message": "Payment processing failed",
  "error": "CardDeclined",
  "user_id": "user-456"
}
```

### 2. Metrics
Numerical measurements aggregated over time. Cheaper to store and query than logs.
- **Counter**: Monotonically increasing value (e.g., total requests served, errors count).
- **Gauge**: Value that goes up and down (e.g., current memory usage, active connections).
- **Histogram**: Distribution of values (e.g., request latency percentiles).
- Follow the **RED method** for services: Rate (requests/sec), Errors (error rate), Duration (latency).
- Follow the **USE method** for resources: Utilization, Saturation, Errors.

### 3. Traces
End-to-end path of a request across services.
- Each trace contains multiple **spans** representing individual operations.
- Use a **correlation ID / trace ID** propagated across service boundaries.
- Essential for debugging latency in microservice architectures.
- Implement with OpenTelemetry for vendor-neutral instrumentation.

## Log Levels

Use log levels consistently across your application:

| Level    | When to Use                                                    |
|----------|----------------------------------------------------------------|
| DEBUG    | Detailed diagnostic information. Disabled in production.       |
| INFO     | Routine operational events (server started, request handled).  |
| WARNING  | Something unexpected but not an error (deprecated API called). |
| ERROR    | An operation failed but the application can continue.          |
| CRITICAL | The application cannot continue (database unreachable).        |

Set the production log level to **INFO** or **WARNING**. Use DEBUG only during active investigation.

## Alerting Best Practices

- **Alert on symptoms, not causes**: Alert when users are affected (high error rate, slow response time), not on internal details (CPU at 80%).
- **Set meaningful thresholds**: Use percentiles (p99 latency > 500ms) rather than averages, which hide outliers.
- **Include runbooks**: Every alert should link to a document explaining what it means and how to respond.
- **Avoid alert fatigue**: Too many noisy alerts cause people to ignore them. Review and tune alerts regularly.
- **Use severity levels**: Critical (pages on-call immediately), Warning (review next business day), Info (no action needed).
- **Set up escalation policies**: If the primary on-call does not acknowledge within a time window, escalate to the next responder.

## Common Tools

### Metrics and Dashboards
- **Prometheus**: Open-source metrics collection using a pull model. Pairs with Grafana for visualization.
- **Grafana**: Dashboard and visualization tool. Supports Prometheus, CloudWatch, DataDog, and many other data sources.
- **DataDog**: Commercial SaaS for metrics, logs, and traces in one platform.

### Error Tracking
- **Sentry**: Captures exceptions with full stack traces, context, and release tracking. SDKs for most languages.

### Log Aggregation
- **ELK Stack** (Elasticsearch, Logstash, Kibana): Self-hosted log aggregation and search.
- **Loki**: Lightweight log aggregation by Grafana Labs; indexes labels, not full text.

### Tracing
- **Jaeger**: Open-source distributed tracing. Compatible with OpenTelemetry.
- **Zipkin**: Another open-source tracing tool, lighter weight.

## Health Check Endpoints

Every service should expose a health check endpoint:

```
GET /health
```

Response (healthy):
```json
{
  "status": "healthy",
  "version": "1.4.2",
  "uptime_seconds": 86400,
  "checks": {
    "database": "connected",
    "redis": "connected",
    "disk_space": "ok"
  }
}
```

Response (degraded):
```json
{
  "status": "degraded",
  "checks": {
    "database": "connected",
    "redis": "timeout",
    "disk_space": "ok"
  }
}
```

Use health checks for:
- Load balancer routing (remove unhealthy instances).
- Kubernetes liveness and readiness probes.
- Uptime monitoring services.
- Deployment verification (verify new instances are healthy before routing traffic).
