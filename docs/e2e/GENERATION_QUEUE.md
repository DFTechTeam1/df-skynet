# Generation Pipeline — Reliability Design

This document describes the end-to-end flow for AI generation requests (image/video),
from API validation through Openrouter generation and Udin file upload, with the
reliability guarantees that make external-API calls survive retries, worker crashes,
and provider outages without data loss or duplicate side effects.

See `generation_pipeline_bulletproof.mermaid` for the full diagram this document walks through.

## Table of contents

- [Goal](#goal)
- [Request lifecycle overview](#request-lifecycle-overview)
- [1. Synchronous validation](#1-synchronous-validation)
- [2. Record creation & response](#2-record-creation--response)
- [3. Enqueue](#3-enqueue)
- [4. Worker pickup & `before_start`](#4-worker-pickup--before_start)
- [5. Idempotency guard](#5-idempotency-guard)
- [6. Stage 1 — Openrouter](#6-stage-1--openrouter)
- [7. Stage 2 — Udin](#7-stage-2--udin)
- [8. Task handlers](#8-task-handlers)
- [9. Watchdog / reaper](#9-watchdog--reaper)
- [Error classification reference](#error-classification-reference)
- [State model](#state-model)
- [Celery configuration reference](#celery-configuration-reference)
- [Operational notes / troubleshooting](#operational-notes--troubleshooting)

## Goal

Every request that reaches Openrouter (generate) and Udin (upload result) must
eventually resolve to a terminal, correctly-recorded state — `Success` or `Failed` —
with **no silently stuck records**, **no duplicate Openrouter charges**, and
**no orphaned files on Udin with no matching database row**.

## Request lifecycle overview

```
Client → Validation → Insert record (queued) → Return response → Enqueue
                                                                      │
                                                                      ▼
                                                    Worker: before_start()
                                                                      │
                                                                      ▼
                                                      Idempotency guard (resume point)
                                                          │        │         │
                                                   already done  Udin left  nothing done
                                                          │        │         │
                                                          ▼        ▼         ▼
                                                      on_success  Udin    Openrouter → Udin
                                                                      │
                                                          success ──► commit (upload flag → results row) → on_success
                                                          failure ──► classify → retry / on_failure
```

A watchdog runs independently on a schedule and re-drives anything that gets
stuck between `started` and a terminal event.

## 1. Synchronous validation

Runs inline on the request, before anything is persisted:

| Check | Failure |
|---|---|
| Project status is `Ongoing` | validation error |
| Requesting user is assigned to a task in the project | validation error |
| User is not resigned | validation error |
| Main API key is valid | validation error |
| Payload matches the chosen model's schema | validation error |

Any failure short-circuits to `RaiseValidationError` and the request ends — no
record is created, nothing is queued.

## 2. Record creation & response

- `InsertInitRecord` writes `df_engine_generations` with `status=queued`. This row
  is the durability anchor everything downstream depends on.
- The API builds and returns its response immediately (`queued` / `processing` /
  `success` / `failed` per generation, per the existing response contract) and
  seeds Redis so polling doesn't have to hit the DB.
- The HTTP request ends here. Everything from this point on is asynchronous.

## 3. Enqueue

`LogEnqueued` inserts `df_engine_queues: event=enqueued, attempt=1` **before** the
Celery message is published (producer-side, `before_task_publish`). This is the
ground-truth record that a generation was supposed to start, independent of
whether a worker ever actually picks it up — it's what the watchdog cross-checks
against later.

## 4. Worker pickup & `before_start`

A worker in the `ImageGeneration` or `VideoGeneration` queue (routed by `kind`)
picks up the task. `before_start()` — part of the shared `GenerationTask` base
class, not per-task code — fires automatically on **every** delivery, including
retries and watchdog requeues:

- `df_engine_queues: event=started, attempt=request.retries+1`
- Redis cache → `On Process`
- Pusher notify (`processing`) — wrapped in its own try/except; a Pusher outage
  never blocks the two writes above

## 5. Idempotency guard

Before touching any external API, `run()` checks how far this generation has
already progressed:

| Existing state | Action |
|---|---|
| `status == success` | Replay `retval` from the stored `generation_results` row; return immediately (no-op into `on_success`) |
| Openrouter response already stored, Udin not yet uploaded | Skip Stage 1, resume at Stage 2 |
| Nothing completed yet | `SetProcessing`, run Stage 1 from the top |

This is the load-bearing safety mechanism: it's what makes retries, Celery
redeliveries after a crashed worker (`acks_late`), and watchdog requeues all
**safe** rather than dangerous. Without it, a retry after a Udin failure would
re-call Openrouter and re-bill it; a redelivered message after a lost ack could
re-upload a file that already succeeded.

## 6. Stage 1 — Openrouter

Calls the Openrouter API with a timer and a hard cap at `soft_time_limit`.

**On success:** persists `response`, `status_code`, `token_usage`, `cost` to
`df_engine_generations`; creates a `df_engine_generation_uploads` row
(`upload_status=pending`); logs the full request/response to
`df_engine_openrouter_logs`. Falls through directly into Stage 2 — the task has
not returned yet, so no handler fires here.

**On any exception** — HTTP error, timeout, connection error, JSON decode error,
or a tripped `soft_time_limit` — everything is normalized into a single typed
`GenerationStageError(source, status_code, retryable)` before it can escape
un-typed, and run through the shared classifier (see below).

## 7. Stage 2 — Udin

Same shape and same shared classifier as Stage 1.

**On success**, the commit is deliberately split into two steps to avoid
orphaning an uploaded file:

1. `MarkUploadSuccessFirst` — a small local write (up to 3 attempts, short
   backoff; a plain DB update, not a Celery-level retry) sets
   `upload_status=success`. This is written **first**, so the fact that the file
   exists on Udin is durable before anything else happens.
2. `InsertGenerationResult` — upserts `df_engine_generation_results` (idempotent
   on `generation_id`) and returns the final payload, triggering `on_success`.
3. If step 1 can't be written after 3 local attempts, a distinct
   `GenerationStageError(source='db_commit', final=True,
   needs_reconciliation=True)` is raised instead of a normal failure — the file
   genuinely exists on Udin, so blindly retrying here would create a duplicate
   upload rather than fix anything.

**On any exception** from the Udin call itself: same retryable/final split as
Stage 1. A retry re-enters at worker pickup, and the idempotency guard resumes
at Udin (Openrouter's response is already saved) — Openrouter is never called
again.

## 8. Task handlers

Four handlers on the shared `GenerationTask` base class are the single place
that write `df_engine_queues`, the Redis cache, and Pusher notifications — both
stages funnel into the same four, so state-of-record logic isn't duplicated per
provider.

| Handler | Writes | Notes |
|---|---|---|
| `on_retry` | `event=retried`; computes backoff (honors `Retry-After` on 429) | No cache write — externally still `On Process` |
| `on_failure` | `event=failed`; cache → `Failed` | `db_commit` failures set `needs_reconciliation=true, can_retry=false` instead of the normal `can_retry=true` |
| `on_success` | `event=succeeded`; cache → `Success` with name/size/md5/path | |
| `before_start` | `event=started`; cache → `On Process` | Covered above |

Every handler's Pusher call is wrapped in its own try/except — a notification
outage is logged and swallowed, never allowed to block the DB/cache write next
to it.

## 9. Watchdog / reaper

Runs independently on a schedule (every 60s), outside the task chain:

1. Scans `df_engine_queues` for `event=started` rows with no matching
   `succeeded`/`failed`/`retried` within `soft_time_limit + grace`. This is the
   signature of a worker that died mid-task or a message lost even with
   `acks_late`.
2. If reaped fewer than 2 times, requeues through the same
   idempotency-guarded `run()` — safe, per §5.
3. After 2 failed reap attempts, force-fails the record (`can_retry=true`) so
   it's visible to ops instead of silently stuck forever.

## Error classification reference

Shared by both the Openrouter and Udin call sites:

| Condition | Classification | Behavior |
|---|---|---|
| 5xx | Retryable | Exponential backoff + jitter |
| Timeout / connection / network error | Retryable | Exponential backoff + jitter |
| `SoftTimeLimitExceeded` | Retryable | Exponential backoff + jitter |
| 429 | Retryable | Honors `Retry-After` if present |
| Any other 4xx | Final | No retry — bad request/auth/payload won't fix itself |
| Retries exhausted (5 attempts) while retryable | Final | Same failure handling as a non-retryable error |
| Local DB write after successful Udin upload fails 3x | Final, `needs_reconciliation` | Not auto-retried — avoids duplicate upload |

Backoff: exponential with jitter, base 2s, capped at 60s, `max_retries=5`.

## State model

```
queued → processing → success
                    → failed (can_retry=true, can_archieve=true)
                    → failed (needs_reconciliation=true, can_retry=false)   [db_commit only]
```

`On Process` covers both `queued`/`processing` externally — the API response
contract doesn't distinguish them, only the internal `df_engine_generations`
row does.

## Celery configuration reference

```
acks_late = True
reject_on_worker_lost = True
retry_backoff = True
retry_jitter = True
max_retries = 5
soft_time_limit = 280   # seconds
time_limit = 300        # seconds
autoscale = (10, 1)
rate_limit = "10/s"
```

`acks_late` + `reject_on_worker_lost` mean a crashed worker's task is
redelivered rather than lost — this is only safe because of the idempotency
guard in §5.

## Operational notes / troubleshooting

- **A generation is stuck at "On Process" for a long time**: check
  `df_engine_queues` for the last event. If it's `started` with nothing after
  it past the grace window, the watchdog should pick it up within 60s — if it
  hasn't, check the reaper job is actually running.
- **`needs_reconciliation=true` on a failed generation**: the file exists on
  Udin but the local commit didn't land. Don't retry the generation normally —
  verify the file on Udin, then manually re-run the commit step (upsert
  `generation_results`) rather than re-uploading.
- **Repeated 429s from one provider**: check whether `rate_limit` /
  `autoscale` are set too aggressively relative to the provider's actual
  limit — synchronized retries across many workers can create a thundering
  herd even with jitter.
- **Pusher notifications missing but state looks correct in the DB/cache**:
  expected behavior per §8 — Pusher failures are logged and swallowed, not
  surfaced as generation failures. Check the `pusher_failures` metric/log
  separately.
