# RCA: Generations stuck in "processing" with no retry or error

- **Date of incident:** 2026-10-29 (first seen 2026-10-28 23:56 WIB)
- **Environment:** production (`erp_workspace_prod`)
- **Impact:** image/video generations hung in `processing` indefinitely. The UI timer kept counting (5375s ≈ 90 min) and the user got no failure, no retry and no refund path.
- **Status:** root cause identified; fixes not yet deployed.
- All times WIB (UTC+7) unless marked UTC.

## Summary

The kernel OOM-killed celery worker child processes because the worker containers are limited to 256 MB while each child uses about 125–145 MB and the pool autoscales to 10 children. An OOM kill is a SIGKILL, so no Python code runs: `on_failure` never fires, no retry is scheduled, and the row stays `processing`. Nothing else in the system moves a stuck `processing` row to a terminal state.

## Evidence

| Source | Finding |
|---|---|
| `compose.prod.yaml` (`engine-worker-generation`, `engine-worker-udin`) | `memory: 256M` each. `compose.yaml` runs both with `--autoscale=10,1`. |
| `dmesg` / `journalctl -k` | Many `Memory cgroup out of memory: Killed process (celery)` entries, `anon-rss` 123–145 MB per child, in the two worker containers' cgroups. A burst of about 1 kill/second at 02:21–02:23 UTC (09:21–09:23 WIB), plus kills at 03:05:36, 03:15:28, 03:35:34 UTC. |
| `df_engine_queues` for gen 18, 19, 20 | `started` attempt 1, then the same `celery_task_id` `started` again about 31 min later. No `succeeded` / `failed` / `retried`. |
| Correlation | Gen 20 restarted at 10:05:12 and gen 19 at 10:15:12 WIB; OOM kills logged at 10:05:36 and 10:15:28 WIB (03:05:36 / 03:15:28 UTC). |
| `df_engine_queues` for gen 4 | The udin task `2437cbdc` logged `started` 11 times in 15 s: a crash loop from `task_reject_on_worker_lost`. |
| `docker inspect` | Containers started 2026-10-29 11:00 WIB (a redeploy), so `oom=false restarts=0` describes the new containers and the old logs are gone. |
| `inspect active` | Empty on both workers: the stuck rows are dead, not slow. |

## Timeline

| Time | Event |
|---|---|
| 10-28 23:56 | Gen 4: OpenRouter stage succeeds, udin upload task crash-loops (11 starts in 15 s) and never finishes. |
| 10-29 09:21–09:23 | OOM kill storm in the worker cgroups (autoscale forking children for a burst). |
| 09:24 | User submits 5 image requests; gen 18, 19, 20 never get `status_code` or a terminal event. |
| 09:24 / 09:34 / 09:44 | First `started` for gen 18 / 20 / 19, about 10 min apart. |
| 09:55 / 10:05 / 10:15 | Same task ids redelivered (`acks_late` + `visibility_timeout=600`); kills logged at 10:05 and 10:15. |
| 10:53 | Screenshot: three tiles at "5375s", no error. |
| 11:00 | Workers redeployed, old containers and logs removed. |

## Root cause

1. **Memory limit too low for the pool size.** 256 MB per worker container vs. ~130 MB per child and `--autoscale=10,1`. Two children exceed the limit.
2. **No failure path for a SIGKILLed child.** `GenerationTask.on_failure` ([services/tasks/base.py](../../services/tasks/base.py)) is the only place that marks a generation `failed`, and it cannot run when the process is killed.
3. **Redelivery does not count as a retry.** `acks_late` + `reject_on_worker_lost` requeue the message, but `request.retries` is not incremented, so `max_retries=5` never applies. The result is an unbounded loop (gen 4) or a slow loop gated by `visibility_timeout` (gen 18–20).

## Contributing factors

- **The watchdog described in [docs/e2e/GENERATION_QUEUE.md](../e2e/GENERATION_QUEUE.md) §9 was never implemented.** `beat_schedule` in [services/celery_app.py](../../services/celery_app.py) only has `udin_sweep` and `search_backfill`; `udin_sweep` ignores `processing` rows.
- **No alert on worker OOM or on rows stuck in `processing`.**
- **Logs are lost on redeploy**, which made the investigation depend on kernel logs.

## Not confirmed

- **Gen 4 (10-28 23:56):** the kernel logs we pulled cover only 10-29 02:00–03:30 UTC, so OOM is the most likely cause of that crash loop but is not directly verified. Check `journalctl -k --since "2026-10-28 16:30" --until "2026-10-28 17:30"` (UTC).
- Why the first starts of gen 18/20/19 were 10 min apart is not fully explained; it is consistent with children being killed and the visibility timeout expiring, not proven.

## Corrective actions

| # | Action | Type | Status |
|---|---|---|---|
| 1 | Raise worker memory limits to ≥ 1 GB and cap the pool (e.g. `--autoscale=3,1`) in `compose.prod.yaml` / `compose.yaml` | Fix | Open |
| 2 | Add `--max-memory-per-child` so growing children are recycled cleanly | Fix | Open |
| 3 | Implement the §9 reaper as a beat job: fail `processing` rows older than ~6 min with no terminal queue event (force-fail only; no auto-requeue, to avoid double OpenRouter charges) | Prevent | Open |
| 4 | Poison guard in `before_start`: if ≥ 3 `started` rows exist for the same `celery_task_id`, mark failed and `Reject(requeue=False)` | Prevent | Open |
| 5 | Manually mark gen 4, 18, 19, 20 `failed` (needs developer approval; not yet run) | Cleanup | Open |
| 6 | Alert on kernel OOM for the worker containers and on `processing` rows older than 10 min | Detect | Open |
| 7 | Persist container logs (log driver / shipping) so a redeploy does not erase evidence | Detect | Open |
| 8 | Sync [docs/e2e/GENERATION_QUEUE.md](../e2e/GENERATION_QUEUE.md) with reality (reaper, memory sizing) | Docs | Open |
