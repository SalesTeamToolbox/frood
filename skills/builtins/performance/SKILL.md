---
name: performance
description: Profile, benchmark, and optimize code for speed and memory efficiency.
always: false
task_types: [coding, debugging, refactoring]
---

# Performance Profiling and Optimization

## Core Principle: Measure First, Optimize Second

Never optimize based on intuition. Always profile to identify actual bottlenecks before making changes. Record baseline metrics so you can quantify improvements.

## Profiling Tools

### Python
- **cProfile / profile**: Built-in deterministic profilers. Run with `python -m cProfile -s cumulative script.py` to sort by cumulative time.
- **py-spy**: Sampling profiler that attaches to running processes without code changes. Use `py-spy top --pid <PID>` for a live view or `py-spy record -o profile.svg --pid <PID>` for flame graphs.
- **memory_profiler**: Line-by-line memory usage with the `@profile` decorator.
- **tracemalloc**: Built-in module for tracking memory allocations and finding leaks.

### JavaScript / Web
- **Chrome DevTools Performance tab**: Record runtime performance, identify long tasks, layout thrashing, and forced reflows.
- **Lighthouse**: Automated auditing for page load performance, accessibility, and best practices. Run from DevTools or CLI with `npx lighthouse <url>`.
- **Node.js --prof**: Built-in V8 profiler. Process output with `node --prof-process isolate-*.log`.
- **clinic.js**: Diagnose Node.js performance issues with `clinic doctor`, `clinic flame`, and `clinic bubbleprof`.

## Optimization Strategies

### Algorithmic Improvements
- Review time complexity. Replacing O(n^2) with O(n log n) yields far greater gains than micro-optimizations.
- Use appropriate data structures: hash maps for lookups, heaps for priority queues, sets for membership tests.

### Caching
- **Memoization**: Cache function results for repeated calls with same arguments. Use `functools.lru_cache` in Python or custom Maps in JS.
- **Application-level caching**: Redis or Memcached for frequently accessed, rarely changing data.
- **HTTP caching**: Use `Cache-Control`, `ETag`, and `Last-Modified` headers appropriately.

### Lazy Loading and Deferred Execution
- Load resources only when needed: dynamic imports, lazy component loading in React (`React.lazy`), deferred database joins.
- Use generators/iterators instead of building large lists in memory.

### Connection Pooling
- Reuse database connections instead of opening/closing per request. Configure pool size based on workload.
- Use HTTP keep-alive and connection pools for outbound API calls.

### Database Indexing
- Add indexes on columns used in WHERE clauses, JOIN conditions, and ORDER BY.
- Use `EXPLAIN ANALYZE` to verify queries use indexes as expected.
- Avoid over-indexing: each index adds write overhead.

## Common Bottlenecks

| Bottleneck | Symptom | Fix |
|---|---|---|
| N+1 queries | Many small DB queries in a loop | Use eager loading / JOIN / batch queries |
| Unnecessary re-renders | Sluggish UI, high CPU in browser | Memoize components, use `React.memo`, `useMemo`, `useCallback` |
| Memory leaks | Growing memory over time, eventual OOM | Track allocations, close resources, remove event listeners |
| Blocking I/O | Slow response times, low throughput | Use async I/O, worker threads, or task queues |
| Large payloads | Slow network transfers | Paginate, compress, use sparse fieldsets |
| Missing indexes | Slow database queries, full table scans | Add targeted indexes, review query plans |

## Output Format

When reporting optimization results, always provide before/after benchmarks:

```
## Performance Optimization Report

### Bottleneck Identified
[Description of the issue and how it was found]

### Change Applied
[Description of the fix]

### Results
| Metric        | Before   | After    | Improvement |
|---------------|----------|----------|-------------|
| Response time | 1200ms   | 85ms     | 93% faster  |
| Memory usage  | 512MB    | 128MB    | 75% less    |
| Throughput    | 50 req/s | 800 req/s| 16x higher  |
```

Always test under realistic load conditions and verify no regressions in correctness.
