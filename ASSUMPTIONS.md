# ASSUMPTIONS.md

Every `UNVERIFIED:`-tagged modelling choice in this codebase, in one place,
with its rationale and a sensitivity note — what changes if it's wrong.
Referenced by number (`#A1` etc.) from the exact constant/function that
encodes it. Per Build Spec §0.1: a Tier C fact is only ever used if it is
either asked about, marked here, or designed around — never silently
asserted as established.

---

### #A1 — Daily contact budget: 1 discretionary contact per mandate per day

`RC.UNVERIFIED_MAX_CONTACTS_PER_MANDATE_PER_DAY = 1`

**Why.** Domain Context §3.4 and Tier-2 idea #8 both point the same
direction: SIP investors "frequently ignore" automated notifications, and
"fewer, better-timed messages beat more messages." No source gives a
number, so `1` was chosen as the simplest expression of that principle.

**Does NOT apply to:** `pre_debit_notice`, `post_debit_confirmation`,
`source_aware_failure_notice` — these three are standing regulatory
obligations (§2.2) and INV-06/INV-07 requirements, never discretionary, and
are explicitly exempted in `guardrails/validator.py` (see DECISIONS.md, the
bug this exemption fixes).

**Sensitivity.** If this were `2` or `3` instead of `1`, the only measurable
effect in this codebase is on OTHER discretionary nudges — which, as
currently built, are rare (most retryable-path notices are the mandatory
pre-debit notice itself). The number matters more as a documented policy
lever for future intervention types than as a driver of today's headline
recovery number.

---

### #A2 — Intent-inference thresholds: 3+ consecutive same-reason failures, balance ratio ≤ 5%

`RC.UNVERIFIED_INTENT_MIN_CONSECUTIVE_SAME_REASON_FAILURES = 3`
`RC.UNVERIFIED_INTENT_MAX_BALANCE_TO_AMOUNT_RATIO = 0.05`

**Why.** Domain Context §3.2's TechnoFino finding describes the pattern
qualitatively ("very low balance, intentionally, so the mandate fails") but
gives no specific threshold. `3` consecutive failures was chosen because it
exceeds what a single unlucky salary-timing miss could plausibly explain
(Domain Context §4.4's payroll-cycle finding suggests ONE bad month is
common and NOT a signal of intent); `5%` was chosen as "clearly and
persistently near-empty," not "occasionally short."

**Generator calibration (data/generate.py).** ~12% of `insufficient_funds`
records are generated to match this exact pattern (also UNVERIFIED — a
guess at prevalence, not a sourced rate) — this is what
EVALUATION.md's intent-inference confusion matrix is measured against.

**Sensitivity.** Lowering the consecutive-failure threshold increases
recall but risks false-flagging a customer going through a genuinely hard
patch (a real cost — see ADR-003 on why the false-positive side of this
trade is not free either, since it triggers a cancellation-confirmation
message). EVALUATION.md's confusion matrix (81.2% precision / 100% recall,
n=160 held-out) is the honest, current measurement of where these two
thresholds land — re-run `python -m eval.run_eval` after changing them to
see the effect directly rather than guessing.

---

### #A3 — Salary-cycle high-liquidity days: 1, 2, 3, 28, 29, 30, 31

`RC.UNVERIFIED_SALARY_CYCLE_HIGH_LIQUIDITY_DAYS`

**Why.** Domain Context §4.4: Indian salary credit is "heavily concentrated
at month-end and the first few days of the month," combined with the
global finding that 26-30% of insufficient-funds soft declines resolve
within 2-5 business days of a payroll cycle completing. No source gives an
exact day-of-month list for India specifically — this project's own
operationalisation of "month-end and month-start."

**Explicitly does NOT hold for:** the self-employed, gig workers, or
agricultural income (stated as a caveat in the same Domain Context
section) — this heuristic is a population-level lift, not a per-customer
guarantee, and is never used to determine LEGALITY, only to break ties
among already-legal candidate times (see `policy/allocator.py`).

**Sensitivity — measured, not assumed.** `EVALUATION.md`'s ablation table
reports `engine_salary_cycle_only` vs. `engine_neither_heuristic_(=B3)` on
the actual synthetic batch. Re-run `python -m eval.run_eval` after editing
this set to see the real effect on this batch; if a future real dataset
were available, that comparison — not this list — should decide whether to
keep the heuristic at all (Build Spec §8: "if the engine doesn't beat B2 by
a meaningful margin, say so and analyse why").

---

### #A4 — Stopping rule: revoke after 21 days since the first failure

`RC.UNVERIFIED_STOPPING_RULE_MAX_DAYS_SINCE_FIRST_FAILURE = 21`

**Why.** Build Spec Part 4 demands an explicit stopping rule ("chasing
forever is a failure mode, not thoroughness") but gives no number. 21 days
was chosen as roughly one billing cycle's worth of slack beyond the 4
attempts across 3 daily windows — generous enough that a legitimately
slow-to-resolve `insufficient_funds` case (payday timing) isn't cut off
before the salary-cycle heuristic gets a fair chance, short enough that a
mandate genuinely cannot be chased indefinitely.

**Sensitivity.** In practice this rule almost never fires ahead of the
4-attempt cap in the current synthetic batch (see EVALUATION.md's stopping-
rule trigger counts) — the attempt-budget exhaustion nearly always arrives
first. It exists as a documented safety net for an edge case (very widely
spaced legal retries) rather than as an active lever in this batch's
numbers today.

---

### #A5 — Enhanced AFA threshold applied only to MCC 6211

`RC.ENHANCED_AFA_MCCS = frozenset({6211})`

**Why.** Build Spec §2.2 states the Rs 1,00,000 enhanced threshold applies
to "insurance premiums, mutual fund SIPs, credit card bills" in prose, but
only MCC 6211 (securities brokers and dealers, Domain Context §2.3) is
given as an explicit MCC number anywhere in the sourced material. Rather
than guess MCC numbers for "insurance" or "credit card bills" that were
never given, this project encodes only the one MCC it can point to a
source for.

**Consequence.** This is a conservative under-count: real insurance/credit-
card MCCs likely also qualify for the enhanced threshold, but are not
modelled as such here. Flagged so it is not mistaken for a complete mapping.

---

### #A6 — Z7 (velocity-limit) minimum retry spacing: 4 hours

`RC.Z7_MIN_SPACING_HOURS = 4`

**Why.** Build Spec §4.1 says Z7 is "retryable, with spacing" because
"retrying immediately re-triggers the same limit," but gives no number for
how much spacing. 4 hours was chosen as comfortably wider than any single
permitted execution window (the widest is the ~4.5h afternoon window), so a
Z7-flagged retry can never land in the SAME window it was originally
attempted in.

**Sensitivity.** A shorter spacing risks the exact failure mode this rule
exists to prevent (immediately re-triggering the velocity limit); a much
longer one simply delays recovery with no compliance benefit. 4 hours was
chosen as the smallest value that structurally guarantees a different
window, not tuned against any outcome data.

---

### #A7 — Grace-period allowlist: 1, 2, or 3 days; ceiling 3

`RC.MERCHANT_ALLOWED_GRACE_PERIOD_DAYS = (1, 2, 3)`
`RC.MERCHANT_GRACE_PERIOD_CEILING_DAYS = 3`

**Why.** Domain Context Tier-2 idea #7 / productgrowth.in's practitioner
notes: "grace periods of 2-3 days before termination recover ~15-20%"
(itself an unverified practitioner estimate, never cited as fact anywhere
in this codebase). This project's own choice is to offer a small,
merchant-configured allowlist rather than any free-form number, directly
implementing Razorpay Agent Studio principle 2 ("agents don't set prices or
invent discounts... selected from a merchant-configured allowlist with a
hard ceiling") applied to the one goodwill lever this engine has.

**Sensitivity.** The specific days (1/2/3) matter far less than the
STRUCTURE: INV-10 tests that this ceiling holds regardless of what number a
future LLM-assisted selector proposes (`tests/test_guardrails.py`,
`tests/test_invariants.py`). Changing the allowlist's contents is a
one-line, reviewable edit to `regulatory_constants.py`; nothing else in the
codebase needs to change.

---

### #A8 — Simulated outcome model: per-reason base success rates

`src/execute/simulator.py`'s `_BASE_SUCCESS_RATE` table, plus the
salary-cycle lift (+0.30) and bank-health penalties (-0.45/-0.20/0.0 for
high/medium/low downtime severity).

**Why.** This project has no real UPI AutoPay outcome dataset to calibrate
against (Domain Context §7: "no public labelled dataset... exists"). These
numbers were chosen only to be DIRECTIONALLY plausible — `insufficient_funds`
lowest, transient technical errors highest, matching the hard/soft-decline
doctrine (Domain Context §4.5) — and to leave clear, measurable headroom
for the salary-cycle and bank-health heuristics to move the needle at all.
They are calibration constants for a SIMULATION, never presented anywhere
in EVALUATION.md as an empirical recovery-rate figure.

**Also assumed:** within one mandate's retry episode, the underlying
failure reason is held constant across attempts (a mandate that starts as
`insufficient_funds` stays `insufficient_funds` until it succeeds or
exhausts its budget). A real mandate could in principle change failure mode
between attempts; modelling that transition would need a per-attempt causal
model this project has no data to calibrate, so it is out of scope
(LIMITATIONS.md).

**Sensitivity.** Every headline number in EVALUATION.md is downstream of
this table. This is the single most important number to re-calibrate first
if real UPI AutoPay outcome data ever becomes available — see
LIMITATIONS.md.

---

### #A9 — Synthetic mandate book distribution: MCC / reason / bank weights

`data/generate.py`'s `_MCC_WEIGHTS`, `_REASON_WEIGHTS`, `_BANK_WEIGHTS`.

**Why.** The underlying CODES are real (Domain Context §2.3's ranked MCC
list; the closed 10-reason Razorpay taxonomy; NPCI bank codes,
SOURCES.md §6) but the PROPORTIONS assigned to each are this project's own
choice — picked to (a) plausibly reflect recurring-billing use cases, (b)
guarantee both AFA-threshold branches and both notification carve-outs are
exercised in every generated batch, and (c) make `insufficient_funds`
dominate, consistent with the ~74% average business-decline figure and the
20 million/month revocation figure (Domain Context §2.1) — while
acknowledging that article's own caveat that its 20M figure conflates
execution failures with deliberate cancellations.

**Sensitivity.** Changing these weights changes which branches get more or
less exercise in a given batch, but does not change any LEGALITY logic —
the compliance invariants hold identically regardless of the mix (see
`tests/test_invariants.py`'s per-reason-branch sweep, which checks every
branch individually rather than relying on the generator's proportions).

---

### #A10 — Synthetic recurring downtime pattern for the bank-health ablation

`eval/run_eval.py`'s `build_synthetic_downtime_records()`: PYTM down every
afternoon, INDB down every night, for the whole generation-plus-scheduling
window.

**Why.** See DECISIONS.md ADR-010: a scattered, realistic one-off downtime
pattern almost never intersects the allocator's deliberately short
candidate search horizon, making the bank-health heuristic's effect
statistically invisible in a batch this size. This pattern is deliberately
UNREALISTIC (a 2-4 hour outage EVERY SINGLE DAY for a whole bank is far
more severe than any real Razorpay Downtime API record would typically
show) — it exists to make the heuristic's effect provably non-zero and
auditable, not to model realistic outage frequency.

**A real deployment would consume Razorpay's live Downtime API**
(`GET /v1/payments/downtimes`, schema confirmed in SOURCES.md §5) instead of
this synthetic generator. `policy/bank_health.py`'s `DowntimeRecord` already
matches that live schema field-for-field, so swapping the data source is
the only change a real integration would need.

**Sensitivity.** EVALUATION.md's ablation table's `engine_bank_health_only`
row reflects THIS demonstrative pattern's effect, not a real bank's typical
downtime frequency. Reported with this caveat directly in EVALUATION.md's
own ablation section, not just here.
