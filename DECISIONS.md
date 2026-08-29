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

