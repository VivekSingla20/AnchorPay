# FAILURES.md

Build Spec Part 10: "implement at least six [failure injections] and
document all... what broke, how it was detected, how the system degraded,
what the customer/merchant experienced." This project implements all eight
named in the spec. Every claim below is checkable by running:

```
python -m eval.scenarios
```

which writes `results/failure_injection.json` and exits non-zero if any
scenario fails to degrade gracefully. All eight currently pass.

---

## #1 — LLM returns malformed / schema-invalid output mid-batch

**What broke (injected):** `classify/llm_client.call_structured` returns
`ok=False` with a JSON-decode/schema-validation error — simulated by
monkeypatching the call boundary directly rather than fabricating an actual
malformed network response.

**How it was detected:** `call_structured` wraps `json.loads` +
`response_model.model_validate` in a single `try/except`, catching both
`json.JSONDecodeError` and pydantic's `ValidationError`.

**How it degraded:** `classify/reason_classifier.py`'s
`classify_unknown_reason` receives `ok=False`, returns its deterministic
fallback (`suggested_reason=None`, `actor=deterministic`) instead of
propagating an exception.

**What the customer/merchant experienced:** Nothing different — an
unrecognised reason still routes to `INVESTIGATE` regardless of whether the
classifier's suggestion resolved or not (see DECISIONS.md ADR-005). A human
reviewer loses the classifier's proposed taxonomy match for this one
record; no money decision is affected.

---

## #2 — LLM times out or rate-limits

**What broke (injected):** A simulated `TimeoutError` at the same call
boundary, surfaced as `LlmCallResult(ok=False, error="LLM call raised: ...")`.

**How it was detected:** `call_structured`'s `except Exception` clause
(deliberately broad — see its docstring) catches ANY SDK/network failure,
not just validation errors, and converts it to the same `ok=False` shape
every caller already knows how to handle.

**How it degraded:** `intervene/selector.py`'s `select()` falls back to its
deterministic rule table, still returning a valid, enumerated
`intervention_type` (never `None`, never a crash).

**What the customer/merchant experienced:** The scheduled pre-debit notice
still goes out, using the rule-table choice instead of an LLM-refined one.
No delay, no missing notification.

---

## #3 — NPCI stats file unavailable or stale

**What broke (injected):** `policy/bank_health.py` pointed at a
non-existent CSV path (simulating the reference file being deleted, moved,
or corrupted).

**How it was detected:** `_load_reference_table()`'s `try/except` around
the file read catches `OSError`/`ValueError`/`KeyError` and records the
exact error string via `reference_table_status()` — this was a REAL gap
found by deliberately breaking the path, not a hypothetical: the original
version of this function had no error handling at all and would have
raised `FileNotFoundError` straight into the eval harness.

**How it degraded:** Every bank falls through to the SAME "unknown bank
code" path that already existed for a bank not in the table — the
confirmed system-wide OC-149 targets (`SYSTEM_WIDE_TECHNICAL_DECLINE_TARGET_PCT`
/ `..._BUSINESS_DECLINE_TARGET_PCT`), tagged `confidence="system_wide_fallback"`.

**What the customer/merchant experienced:** Scheduling continues using a
neutral, system-wide bank-health assumption instead of a per-bank one — a
degraded but still legal and reasonable schedule, not a crashed batch.
`ingest/npci_stats.py`'s `load_all()`/`summary()` similarly degrade to an
empty list rather than raising, so an eval run's reporting step doesn't
fail even if this same file is unavailable at ingestion time.

---

## #4 — Downtime API unreachable

**What broke (injected):** `downtime_records=None` (Razorpay's Downtime API
being unreachable modelled as "no data available," its actual failure mode
for a real integration — see `SOURCES.md` §5 for the real API this stands
in for).

**How it was detected:** `bank_health_score()` already treats
`downtime_records` as `Optional`; this scenario confirms `run_mandate(...)`
runs to completion end-to-end with it set to `None`.

**How it degraded:** No bank-health penalty is applied at all (equivalent
to every bank being assumed healthy) — scheduling proceeds using only the
static reference table and the salary-cycle heuristic.

**What the customer/merchant experienced:** A schedule that's slightly less
finely tuned (no live downtime avoidance) but still fully legal and
functional.

---

## #5 — A failure reason arrives that is not in the taxonomy

**What broke (injected):** A raw webhook-shaped payload with
`"reason": "some_new_code_razorpay_invented_next_quarter"` — a string
Razorpay could plausibly ship in a future API version that this project's
closed 10-value `FailureReason` enum has never seen.

**How it was detected:** `ingest/normaliser.py`'s `normalise()` wraps the
`FailureReason(raw_reason)` enum construction in a `try/except ValueError`.

**How it degraded:** The event is normalised with `reason=FailureReason.UNKNOWN`
and the ORIGINAL string preserved verbatim in `raw_reason_text` — nothing is
silently dropped, and `policy/retryability.py` routes every `UNKNOWN` to
`INVESTIGATE`, never to an automatic retry (DECISIONS.md ADR-005).

**What the customer/merchant experienced:** The mandate is routed to
`escalate_to_support` with one notice sent; no money is auto-retried
against a reason this project has never validated.

---

## #6 — Clock/timezone edge cases (window boundary, midnight crossing; no DST in India)

**What was tested:** `earliest_legal_time` pinned to the exact instant the
13:00-17:00 permitted window opens, and to 23:59:50 IST (10 seconds before
midnight, inside the "after 21:30" window that runs to end-of-day).

**How it was detected:** `policy/allocator.py`'s candidate generation uses
half-open `[start, end)` interval arithmetic in minutes-of-day (never a
real `datetime.time(24, 0)`, which Python rejects) specifically so a
midnight rollover is ordinary arithmetic, not a special case.

**How it degraded:** Both boundary cases produce a legal, in-window
proposal at or after the requested time — no exception, no off-by-one slip
into an adjacent peak window.

**Honest finding:** India does not observe Daylight Saving Time, so there is
no DST transition to inject. Recorded here rather than fabricating one —
Build Spec §0.1 forbids treating an invented scenario as a verified fact.

---

## #7 — Duplicate webhook delivery (idempotency)

**What broke (injected):** The identical raw payload (same `payment_id`)
delivered to `ingest/normaliser.normalise()` twice in a row — the most
common real-world webhook failure mode (at-least-once delivery guarantees).

**How it was detected:** `normalise()` keeps a process-local
`_SEEN_PAYMENT_IDS` set and checks membership before doing anything else.

**How it degraded:** The first call normalises and processes normally; the
second call returns `(None, "duplicate webhook delivery ... ignored
(idempotent)")` — no second `FailureEvent`, no double-scheduled retry, no
double-counted violation or recovered amount.

**What the customer/merchant experienced:** Exactly one notice, one
schedule, one outcome per real failure — not two.

---

## #8 — Opt-out arriving between scheduling and execution

**This is the most interesting one** (Build Spec Part 10 calls it out by
name): it proves the guardrail layer is real rather than decorative,
because the schedule was ALREADY VALID when it was made.

**What broke (injected):** A mandate's customer opts out one hour after the
triggering failure — well before the next retry, which (per the 24h
pre-debit-notice rule) is scheduled at least a day later. At schedule-
proposal time, the customer was still opted in; by execution time, they
were not.

**How it was detected:** `guardrails/validator.py`'s `validate_execution`
and `validate_notification` both re-check `mandate.customer.opted_out_at`
against `now` AT THE MOMENT THEY'RE CALLED — which, for the executor, is
execution time, not the earlier moment the schedule was proposed. This is
the specific design property Build Spec Part 10 is testing for: a
guardrail that only checked once, when the schedule was created, would
have let this debit and its notice both through, because both were legal
at THAT moment.

**How it degraded:** `orchestrator.py`'s opt-out check (checked first, every
loop iteration — see DECISIONS.md ADR-007) stops the whole sequence the
next time it's evaluated. The already-proposed but not-yet-executed attempt
is never run.

**What the customer/merchant experienced:** No further debit, no further
message, after the exact moment they opted out — regardless of what had
already been scheduled in good faith before that moment. Verified directly
in `tests/test_invariants.py::test_engine_zero_violations_with_opt_out_mid_lifecycle`
and `eval/scenarios.py`'s scenario 8: zero post-opt-out executions, zero
compliance violations.

**A bug this exact scenario caught during development:** the first version
of `validate_execution` checked peak hours, terminal reasons, and the
attempt cap, but NOT opt-out — meaning a debit could still execute after
opt-out even though the resulting notice was (correctly) blocked, producing
a debit with no notice on either side of it (an INV-07 violation). Fixed by
adding the opt-out check to `validate_execution` itself, not only to
`validate_notification`. See AI_USAGE.md for how this was caught.
