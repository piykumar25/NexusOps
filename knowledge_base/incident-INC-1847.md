# Incident Post-Mortem: INC-1847

**Date:** 2025-12-15
**Severity:** Critical
**Duration:** 45 minutes
**Service:** payment-service

## Summary
Payment processing was degraded for 45 minutes due to repeated pod crashes
caused by a memory leak in the database connection pool handler.

## Timeline
- 14:45 UTC — Deployment v2.3.1 rolled out
- 15:10 UTC — First OOM kill detected
- 15:15 UTC — PagerDuty alert triggered
- 15:20 UTC — On-call engineer begins investigation
- 15:35 UTC — Root cause identified as connection pool leak
- 15:40 UTC — Rollback to v2.2.0 initiated
- 15:55 UTC — All pods stable, error rate normalized

## Root Cause
The `ConnectionPoolHandler.release()` method was not called in the
exception path of `PaymentProcessor.process()`. Under normal conditions,
connections were properly returned. When timeout errors occurred (which
happen ~2% of the time), connections were leaked.

## Action Items
- [x] Hotfix: Add `finally` block to ensure connection release
- [x] Add integration test for connection pool under error conditions
- [ ] Add memory leak detection to CI pipeline
- [ ] Set up a growth rate alert for container memory
