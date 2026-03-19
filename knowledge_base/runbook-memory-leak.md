# RB-0042: Memory Leak in Payment Service

## Symptoms
- Pod memory usage grows linearly over time
- Pods eventually hit OOM (Out of Memory) limits and are killed
- CrashLoopBackOff state observed
- Error rate spikes during pod restarts
- P99 latency degrades as memory pressure increases

## Root Cause
The payment-service connection pool handler in v2.3.x has a known memory leak.
Database connections are not properly returned to the pool after timeout errors,
causing the pool to grow unboundedly.

## Immediate Actions
1. **Rollback** to the previous stable version (v2.2.x)
2. **Increase** memory limits temporarily (from 1Gi to 2Gi)
3. **Monitor** `container_memory_working_set_bytes` metric

## Long-term Fix
- PR #847 fixes the connection pool cleanup
- Add memory profiling to CI/CD pipeline
- Set up alerting for memory growth rate > 10% per hour

## Related Incidents
- INC-1847 (2025-12-15): Identical symptoms, resolved by rollback
- INC-1623 (2025-10-03): Similar pattern in auth-service
