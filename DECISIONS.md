# DECISIONS.md

ADR-style log: what was chosen, what was rejected, why. Written as the build
happened, not retrofitted — every ADR below is referenced by number from a
code comment at the exact place it applies, so this file is the answer key
for "why does this line exist," not a summary written afterward.

---

### ADR-001 — Intent inference is deterministic, never an LLM judgment call

**Context.** Domain Context §3.2 documents a real pattern (TechnoFino): some
customers keep an AutoPay-linked account intentionally empty as a
de facto cancellation mechanism, because they don't trust the official
cancel flow. Distinguishing "can't pay" from "won't pay" is this project's
signature feature.

**Decision.** Detect the pattern with a plain threshold rule over the
mandate's own recorded history — `consecutive_same_reason_failures >= 3`
AND `account_balance_paise_hint / amount_paise <= 0.05` (ASSUMPTIONS.md #A2)
— in `src/policy/retryability.py`, not an LLM call.

**Rejected alternative.** Ask an LLM to read the mandate's history and
"decide" if this looks intentional. Rejected because Build Spec §0.1/§5.4
forbid an LLM from deciding anything that changes whether/when money moves,
and intent inference directly changes the retry verdict. A threshold over
two numbers is also strictly more auditable in an interview: "why did you
flag this one" has a one-line, arithmetic answer instead of "the model
thought so."

**Consequence.** The mechanism's accuracy is bounded by how good two
thresholds are, not by a model's judgment — measured honestly in
EVALUATION.md's confusion matrix (81.2% precision / 100% recall on the
held-out split, Domain Context §3.2's proportions being themselves
UNVERIFIED, ASSUMPTIONS.md #A2).

---

### ADR-002 — The 4-attempt cap is asserted once, from two independent sources

**Context.** NPCI's circular (SOURCES.md §1) says "1 attempt + 3 retries."
Razorpay's own subscription state machine (SOURCES.md §4) independently
halts after 4 consecutive failed charges.

**Decision.** `RC.MAX_EXECUTION_ATTEMPTS_TOTAL = 4` and
`RC.CONSECUTIVE_FAILURES_TO_HALT = 4` are two separately-named constants
(not one reused for both purposes) even though they're numerically
identical, because they come from two different sources and could in
principle diverge if either regulator/platform changed its number
independently. Naming them separately means a future edit to one doesn't
silently also change the other's meaning.

**Consequence.** The convergence of NPCI's and Razorpay's independent
numbers is used as a defensibility point in the README/pitch: "the model's
central constraint is corroborated by two unrelated sources, not asserted
once and hoped."

---

### ADR-003 — `payment_cancelled` is treated as an intent signal by default

**Context.** Build Spec §4.1 explicitly calls this row a "judgment" case: a
customer affirmatively backing out of a UPI collect request could mean
"wrong moment" or "I don't want this."

**Decision.** Default to `RetryabilityVerdict.LIKELY_INTENTIONAL_NONPAYMENT`
— route to `cancellation_confirmation`, not a blind retry — because Build
Spec §2.7 principle 5 says a "no" ends the sequence with no escalation loop,
and a cancelled collect request is the most direct "no" a customer can give
in this flow (more direct than silence/timeout).

**Rejected alternative.** Treat it as `RETRYABLE` like most other reasons,
on the theory that a cancel might be an accident (wrong app switch,
interruption). Rejected because the cost of the two error types is
asymmetric: wrongly treating a genuine cancel as retryable means chasing a
customer who said no (a consent violation); wrongly treating an accidental
cancel as intentional only costs one cancellation-confirmation message,
which the customer can simply reply KEEP to (see the template in
`intervene/copy_generator.py`). The safer failure mode was chosen.

---

### ADR-004 — `payment_timed_out` is mapped identically to `payment_collect_request_expired`

**Context.** Build Spec §4.1's table does not include `payment_timed_out`
as a row at all.

**Decision.** Map it to `RETRYABLE`, same as `payment_collect_request_expired`,
because Razorpay's own UPI Error Codes page (SOURCES.md §3) gives both the
identical secondary label "Customer Exceeded Payment Time Limit" and
identical next-step guidance.

**This is an inference this project made, not a mapping given by any
source table.** Flagged explicitly in `regulatory_constants.py`'s
`REASON_STRATEGY_TABLE` rather than presented as equally sourced to the
other nine rows.

---

### ADR-005 — The taxonomy classifier's scope is deliberately narrow

**Context.** Stage 2 ("Classifier") in the Build Spec's pipeline sounds like
it should classify every failure event. In practice, nine of the ten known
`FailureReason` values arrive as an already-structured enum from Razorpay —
there's nothing to classify.

**Decision.** `classify/reason_classifier.py` only does real work when
`reason == FailureReason.UNKNOWN` (Failure Injection #5), and even then its
suggestion is advisory-only: `policy/retryability.py` ALWAYS routes an
unresolved UNKNOWN to `INVESTIGATE`, regardless of what the classifier
proposes. The classifier can shorten a human reviewer's triage time; it
never gets to make the retry decision itself.

**Rejected alternative.** Call an LLM to "confirm" every already-known
reason (e.g., to catch a hypothetical Razorpay bug where the wrong enum
value was sent). Rejected as pure cost with no compliance benefit — Build
Spec §0.4's defensibility test ("can the operator explain why this exists
in 90 seconds") fails for "we re-classify data we already trust."

---

### ADR-006 — The pre-existing seed attempt carries a sentinel approval token

**Context.** Every mandate arrives at this engine already having failed
once — that's the webhook that triggers the whole pipeline. INV-14 requires
every EXECUTED attempt to carry an approval token, but this engine's
guardrail didn't exist yet at the moment attempt #1 happened; it cannot
retroactively mint a real one.

**Decision.** Attempt #1 is given the literal sentinel string
`"tok_preexisting_attempt_1"` rather than `None`, so it doesn't trip
INV-14's "every executed attempt has a token" check as a false positive
purely due to a scoping artifact, and rather than a real
`guardrails.validator`-minted token, which would misrepresent that this
engine approved an action that happened before it ran.

**Consequence.** ADR-009 (below) goes further and excludes attempt #1 from
grading entirely — this sentinel is a belt-and-braces second safeguard, not
the primary fix.

---

### ADR-007 — An opt-out stops the WHOLE sequence, not just future messages

**Context.** Razorpay Agent Studio principle 5 says opt-outs are
"permanently suppressed, no exceptions." A naive reading suppresses only
outbound MESSAGES while leaving the underlying debit schedule untouched.

**Decision.** Under the RBI E-Mandate Framework's standing pre-debit/
post-debit notification obligation (§2.2), a debit that cannot be
legally notified around cannot legally happen either. So
`src/orchestrator.py` checks opt-out FIRST, ahead of retryability, and
`guardrails/validator.py`'s `validate_execution` independently re-checks it
too — an opt-out halts scheduling AND execution, not only notification.

**Rejected alternative.** Suppress only the message, keep attempting the
debit silently. Rejected for two reasons: (1) it produces a debit with no
notice on either side of it, which is a bare compliance violation, not a
judgment call; (2) it is hard to defend in an interview — "we kept charging
them after they said stop, we just stopped emailing them about it" is not a
sentence Razorpay's principle 5 survives.

**Found via the engine's own test suite**, not by inspection — see
AI_USAGE.md and FAILURES.md #8.

---

### ADR-008 — B3 is the engine with both ranking heuristics disabled, not a separate implementation

**Context.** Build Spec Part 8 defines B3 as "reason-aware, not bank-aware."
Domain Context Part 5 idea #2 separately asks for a salary-cycle/bank-health
ablation study.

**Decision.** Implement B3 as literally
`orchestrator.run_mandate(..., use_salary_cycle_heuristic=False,
use_bank_health_heuristic=False)` (see `eval/run_eval.py`), rather than a
hand-rolled fourth scheduler in `eval/baselines.py`.

**Rationale.** These are the same mechanism wearing two names. B3 disabled
both heuristics; the ablation study disables them one at a time. Writing a
second, parallel scheduling implementation for B3 would risk it silently
drifting from the engine's actual retryability/guardrail behaviour over
time, defeating the purpose of a controlled ablation (it should differ from
the engine in EXACTLY the two heuristics, nothing else).

---

### ADR-009 — Attempt #1 is excluded from all invariant grading, for every strategy

**Context.** Every strategy (baselines and engine alike) starts from the
same pre-existing failed attempt — the webhook payload that triggers this
whole pipeline. That attempt happened before ANY strategy had a chance to
act on it (see ADR-006).

**Decision.** Every place this project counts violations
(`eval/run_eval.py`, `tests/test_invariants.py`, `src/cli.py`) grades
`result.attempts[1:]`, never `result.attempts[0]`.

**Why this matters.** Without this exclusion, INV-06 ("pre-debit notice
24h before") and INV-07 ("post-debit confirmation after every outcome")
would flag EVERY SINGLE MANDATE, for every strategy including the engine —
not because anything is actually non-compliant, but because nobody, ever,
in this simulation, was in a position to have sent a notice for an event
that predates the whole system. This was found empirically (369 spurious
violations on a 200-mandate smoke test, 200 of which were INV-07 on 100%
of mandates — an unmissable signal once looked at row-by-row) rather than
reasoned out in advance. See AI_USAGE.md.

---

### ADR-010 — The bank-health ablation needed a recurring, not scattered, downtime pattern

**Context.** The first version of `eval/run_eval.py`'s synthetic downtime
data was a handful of scattered one-off windows. The salary-cycle vs.
bank-health ablation showed a real, if modest, lift for the salary-cycle
heuristic but a byte-identical result for bank-health on/off — a strong
sign of a measurement problem, not evidence the heuristic does nothing.

**Root cause.** `policy/allocator.py`'s candidate search deliberately
bounds itself to roughly the next 2 days across 3 windows/day (~6
candidates) — a scattered one-off downtime window almost never intersects
that narrow horizon for any given mandate.

**Decision.** `build_synthetic_downtime_records()` in `eval/run_eval.py`
generates a clearly-labelled, deliberately pronounced RECURRING daily
pattern for two specific banks (PYTM afternoons, INDB nights) spanning the
whole generation-plus-scheduling window, so every affected mandate's
allocator search actually encounters the pattern. Documented as
demonstrative, not realistic, in ASSUMPTIONS.md #A10 — a real deployment
would consume Razorpay's live Downtime API (SOURCES.md §5) instead.

**Consequence.** Report this honestly: the ablation study's numbers say
what THIS demonstrative downtime pattern's effect is, not what a real
bank's typical outage frequency would do to recovery. See EVALUATION.md's
ablation table and its own caveat line.

---

### ADR-011 — Narration (escalation briefs, batch summary) added as LLM-assisted, never decision-assisted

**Context.** Mid-build, the operator directly questioned whether the
project under-used AI — the pipeline's three original LLM touch points
(classifier, intervention selector, copy generator) are all deliberately
narrow, which can look, from outside, like "not enough AI" rather than
"AI kept away from money decisions on purpose." Build Spec §5.4 lists a
fourth permitted LLM use case this project had never built: "summarising
the batch for a human reader."

**Decision.** Add exactly two new modules, both read-only narrators over
an ALREADY-FINAL result:
- `intervene/escalation_brief.py` — turns one escalated mandate's audit
  trail into a 1-2 sentence note for the human who investigates it next.
- `eval/batch_summary.py` — turns `eval/run_eval.py`'s already-computed
  metrics dict into one narrative paragraph atop `EVALUATION.md`.

Both follow the exact contract every existing LLM-assisted stage already
uses (structured Pydantic schema, deterministic templated fallback,
`actor` field naming which path ran) — no new pattern was invented for
this.

**Rejected alternative.** Add a "Planner" stage mirroring Bumblebee's
shape (Domain Context §1.3) that decides which data sources to fetch.
Rejected: Bumblebee's planner exists because it has multiple INDEPENDENT
data sources to fetch in parallel; this pipeline's stages are sequential
dependencies (you cannot bank-health-score before you know the reason is
retryable), so a planner stage would have nothing genuine to plan — it
would be complexity added to look more "agentic" rather than because the
problem needs it, which is explicitly named as an anti-pattern (Build Spec
§13 / evaluation criteria §11).

**Why this is the correct response to "make it more advanced,"
specifically:** every other way to add more LLM usage here (having it
re-confirm an already-correct classification, having it choose the
schedule, having it decide whether to stop) would mean moving a money
decision INTO the model — forbidden outright by Build Spec §0.1/§5.4.
Narration is the one direction growth was still available in: augmenting
the human who reads the output, never touching the decision itself. See
`AI_USAGE.md`'s "Where 'why isn't this more agentic' led to two real
additions" for the fuller account, and `ARCHITECTURE.md` §3a for where
these sit relative to the core pipeline.

---

### ADR-012 — Likely-intentional-nonpayment now offers a pause, alongside — never instead of — cancellation

**Context.** The operator pushed back on `LIKELY_INTENTIONAL_NONPAYMENT`
routing to a bare cancellation-confirmation: "even a customer who doesn't
want to pay is still a customer" from a business standpoint, and asked
for research — both on industry practice and on regulation — before
changing anything.

**Research done before deciding (not asserted from memory):**
- Chargebee's own dunning-practice writeup, live-fetched: *"Instead of
  cancelling the subscription due to non-payment, create a flexible
  payment plan to ease some burdens on your customers."*
- Multiple independent 2026 SaaS-churn playbooks (klyzed.com and others),
  live-fetched, converge on the same reframe: *"replace the delete button
  with pause, downgrade, and discount options."*
- Industry framing (enterpret.com) that voluntary and involuntary churn
  "require different interventions" — read as SUPPORTING, not undermining,
  keeping intent-inference: the value is in correctly identifying which
  bucket a mandate is in, then choosing the right intervention for that
  bucket, not in collapsing the distinction.
- The regulatory question checked directly rather than assumed: the US
  FTC's "click-to-cancel" rule was **vacated by a court in 2025**, and the
  FTC reopened rulemaking via a March 2026 ANPRM — this space is
  contested and unsettled in the US, not a stable rule to cite as
  precedent either way.
- Cross-checked against India's own Dark Patterns Guidelines 2023
  (already governing this project, Build Spec §1 principle 6, §6.6):
  "subscription traps" specifically means hiding or obstructing
  cancellation. It does not prohibit offering an equally-easy alternative
  ALONGSIDE an equally-easy cancel option — that is the legal daylight
  this design relies on.

**Decision.** `CANCELLATION_CONFIRMATION` (kept as the existing enum
name — see "rejected alternative" below) now always offers a
merchant-allowlisted pause (`RC.MERCHANT_ALLOWED_PAUSE_CYCLES`,
ASSUMPTIONS.md #A11) in the SAME single message as the cancel option,
governed by the identical allowlist-with-ceiling mechanism already built
for grace periods (INV-10) — `guardrails/validator.py::validate_pause_offer`
and an extended `guardrails/invariants.py::check_inv10_grace_period_ceiling`
independently re-check it, exactly like a grace period.

**What deliberately did NOT change:** the retryability verdict and
stopping-rule logic. This engine still never re-attempts the SAME charge
against a mandate flagged as likely-intentional — a pause is something the
CUSTOMER must reply to accept, not this engine unilaterally trying again.
Confirmed via `python -m eval.run_eval` before and after: recovered
rupees, at-risk rupees, and violation counts are byte-identical, because
nothing about the money-moving logic changed, only what the one
stop-and-ask message offers.

**Rejected alternative — a new InterventionType / renaming the enum.**
Considered adding `RETENTION_OFFER` as a new, better-named enum value, or
renaming `CANCELLATION_CONFIRMATION`. Rejected to keep the change surgical:
the verdict this intervention responds to is unchanged
(`LIKELY_INTENTIONAL_NONPAYMENT`), and a rename would touch the enum,
every template, every test, and every generated-artifact string
(`results/escalations.json`, `EVALUATION.md`'s stopping-reason counts) for
a naming improvement alone. Noted here explicitly rather than silently
accepting a slightly-stale name: the enum is called
`CANCELLATION_CONFIRMATION`; its behaviour is "offer a pause or a cancel,
never assume the answer."

**Rejected alternative — escalating multi-touch win-back campaign.**
Some dunning playbooks researched recommend a SEQUENCE of increasingly
generous offers across multiple messages. Rejected outright: that is
exactly the "escalating-offer pressure" Razorpay Agent Studio principle 6
and India's Dark Patterns Guidelines prohibit. This engine sends exactly
ONE message with all options presented together, then stops — consistent
with principle 5's "a no ends the sequence, no escalation loop."

### ADR-013 — Review-first mode and a kill switch, as a preview-and-re-invoke pattern rather than a stateful approval queue

**Context.** Razorpay Agent Studio principle 1 ("merchant always in
control") names two specific mechanisms this project had not yet built:
a review-first mode that holds actions for human approval before
anything irreversible happens, and a one-tap kill switch that stops all
future action for a specific mandate. A completeness audit against the
principles table (triggered by the operator asking "is it now fully
completed?") found this gap directly — it wasn't inferred, it was
checked by grepping this project's own docs for "review-first" and
"kill switch" and finding nothing.

**Decision — review-first.** `run_mandate()` takes a `review_first: bool`
flag. When set, the loop runs the full deterministic pipeline (ingest,
retryability gate, allocator, intervention selection, guardrail check)
exactly as normal, but stops one step BEFORE the side-effecting action
(`simulator.execute_with_guardrail()` for a debit, or the notification
send) and returns a `PendingApproval` object instead — carrying the
human-readable description of what would happen, and an `irreversible`
flag (`True` for a debit attempt, `False` for a notification-only step).
Nothing is scheduled, executed, or sent. The CLI's `explain --review-first`
prints this and suggests the exact `approve` command to run next.
`approve` re-invokes the SAME pipeline from scratch with `review_first`
now `False` — recomputation, not resumption from stored state — and, for
an irreversible action, refuses outright unless `--confirm-irreversible`
is also passed (verified manually: refuses with a clear message without
it, executes and prints the full decision trail with it). This is a
literal double confirmation, not a slogan: two separate CLI invocations,
the second requiring an explicit extra flag, standing between "reviewed"
and "money moves."

**Decision — kill switch.** `src/audit/kill_switch.py` persists a flat
JSON list of killed mandate ids at `results/killed_mandates.json`
(`kill_mandate()`, `revive_mandate()`, `load_killed_mandate_ids()`).
`run_mandate()` checks membership in this set at the very TOP of its
loop — before even the opt-out check, which was previously the
earliest possible stop — and if present, records an audit entry
attributed to `ActorType.HUMAN_OPERATOR` and halts with no further
action of any kind. Verified manually: `kill` followed by `explain` on
the same mandate shows exactly one audit line
(`[stopping_rule] stop - kill switch activated...`) and zero attempts,
notifications, or rupees recovered; `revive` restores normal processing.
Wired into `eval/run_eval.py` too (`_run_strategy` loads the kill set
once per run and passes it to both the engine and B3 strategies) so the
mechanism is exercised by the same code path the batch evaluation uses,
not a CLI-only side path — confirmed via `git diff` on `results/metrics.json`
after re-running the harness that only the non-deterministic
`wall_clock_seconds`/`throughput_records_per_min` fields changed; every
financial and violation figure was byte-identical, meaning the wiring
introduced zero behavioural change when the kill list is empty (the
default and committed state).

**What this deliberately is NOT.** Neither mechanism is a persistent,
multi-user approval workflow with its own database, queue, or UI. This
project's whole shape is a batch simulator plus a read-only CLI over a
static ledger of synthetic mandates — there is no running service for a
human to click "approve" against in real time. The honest implementation
of the PRINCIPLE (nothing irreversible happens without an explicit,
separately-confirmed human step; any single mandate can be stopped
outright and later resumed) is a preview-then-re-invoke pattern over the
same deterministic pipeline, not a workflow engine. Building the latter
was rejected as scope that doesn't match what a synthetic-data batch
evaluation project can honestly claim to demonstrate — see
`LIMITATIONS.md`.

**Rejected alternative — fail-closed kill switch on a corrupt/unreadable
state file.** `load_killed_mandate_ids()` returns an empty set (fails
OPEN, meaning "nothing is killed") if `results/killed_mandates.json` is
missing, unreadable, or contains invalid JSON, rather than raising and
halting everything. This looks backwards for a safety control at first
glance, but the alternative — a malformed file silently freezing ALL
mandate processing — is a worse failure mode for a file this project
does not treat as security-critical (it holds no money-moving
authority itself; it only ever REMOVES actions, never grants them). A
production system would likely want the opposite (fail closed, alert an
operator) for a real distributed kill switch; that tradeoff is noted
here rather than silently chosen.


