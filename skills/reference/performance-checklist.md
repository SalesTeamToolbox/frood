# Performance Checklist — Condensed Reference

> Condensed from `performance` skill. Optimization patterns.

## Quick-Scan Categories

### 1. Database (Most Common)
- [ ] **N+1 queries** — Eager load / batch fetch
- [ ] **Missing indexes** — `EXPLAIN` slow queries
- [ ] **SELECT \*** — Select only needed columns
- [ ] **Pagination** — Keyset pagination, not OFFSET
- [ ] **Connection pooling** — Reuse, size tuned

### 2. Algorithmic
- [ ] **O(n²) loops** — Hash map / set for lookups
- [ ] **Redundant computation** — Memoize / cache
- [ ] **Large data in memory** — Stream / paginate / chunk
- [ ] **Unnecessary sorting** — Remove if order doesn't matter

### 3. Network/IO
- [ ] **Parallel requests** — `Promise.all` / `asyncio.gather`
- [ ] **Caching** — Redis / in-memory with TTL
- [ ] **Compression** — gzip/brotli for responses
- [ ] **CDN** — Static assets offloaded

### 4. Memory
- [ ] **Leaks** — Unclosed resources, growing caches
- [ ] **Object retention** — WeakMap / clear references
- [ ] **Large objects** — Stream processing, avoid full load

### 5. Frontend (if applicable)
- [ ] **Bundle size** — Code splitting, tree shaking
- [ ] **Render blocking** — Defer non-critical JS/CSS
- [ ] **Images** — WebP, lazy load, responsive
- [ ] **Re-renders** — Memo, virtual lists

## Profiling Commands

```bash
# Python
python -m cProfile -o profile.stats script.py
snakeviz profile.stats

# Node
node --inspect script.js
# Chrome DevTools → Performance

# Database
EXPLAIN ANALYZE SELECT ...
pg_stat_statements

# System
htop, iotop, netstat -i
```

## Optimization Priority

| Priority | Criteria | Action |
|----------|----------|--------|
| **P0** | User-facing latency >500ms | Profile, fix hot path |
| **P1** | Throughput bottleneck | Scale horizontally, cache |
| **P2** | Resource waste (CPU/Mem) | Tune, remove leaks |
| **P3** | Code quality | Refactor for maintainability |

## Anti-Patterns to Avoid

| Anti-Pattern | Fix |
|--------------|-----|
| Premature optimization | Profile first, optimize measured bottlenecks |
| Micro-optimizing hot path | Algorithm change > constant factor |
| Caching without invalidation | Add TTL, event-based invalidation |
| Premature parallelism | Measure contention, Amdahl's law |

## Output Format

```
## Performance — [component]

### Baseline
- Latency: p50=Xms, p95=Yms, p99=Zms
- Throughput: X req/s
- CPU: X%, Mem: YMB

### Findings
- [P0] N+1 query in UserService.getPosts — 50 queries/request
- [P1] Uncached API call to PaymentGateway — 200ms each

### Fixes Applied
- Added eager load → p95 400ms → 50ms
- Added Redis cache (TTL 5m) → 200ms → 5ms

### Post-Fix
- Latency: p50=20ms, p95=60ms
```
