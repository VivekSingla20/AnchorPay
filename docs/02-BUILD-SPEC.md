# BUILD PROMPT — UPI AutoPay Mandate Recovery Engine

**How to use this file:** paste it whole into your coding agent as the first message
of a fresh session. Keep it in the repo root as `SPEC.md` and re-reference it
whenever the agent drifts. Do not summarise it — the precision is the point.

---

# PART 0 — YOUR ROLE AND THE ANTI-HALLUCINATION CONTRACT

You are building a production-grade demonstration system for a competitive
hiring evaluation at a payments company. The evaluator is a senior payments
engineer who knows this domain better than you do. **A confident wrong fact is
worse than an admitted gap.** One invented regulation destroys the credibility
of the entire submission.

## 0.1 The three-tier fact system — obey this absolutely

Every factual claim in this project belongs to exactly one tier. You must tag
which tier you are operating in whenever you introduce a fact.

**TIER A — VERIFIED.** Listed in Part 2 of this document with a source. You may
use these directly. You may not modify, extend, round, or "improve" them.

**TIER B — MUST VERIFY BEFORE USE.** Listed in Part 3. You must fetch the
primary source and confirm before writing a single line that depends on it. If
you cannot fetch it, you must stop and tell the operator, not proceed on
assumption.

**TIER C — UNKNOWN.** Everything else. If a fact is not in Tier A or Tier B and
you need it, you have exactly three permitted moves:
1. Ask the operator.
2. Mark it as a modelling assumption in `ASSUMPTIONS.md` with an explicit
   `UNVERIFIED:` prefix, a rationale, and a sensitivity note on what breaks if
   it's wrong.
3. Design so the fact isn't needed.

You may **never** state a Tier C fact as though it were established. In
particular you may not invent: regulation numbers, circular dates, API field
names, error codes, statutory thresholds, industry benchmark percentages, or
citations of any kind.

## 0.2 Forbidden behaviours

- Do not invent API endpoints, request/response fields, enum values, or webhook
  event names. If it is not in Part 2, fetch the docs or ask.
- Do not invent NPCI or bank error codes. The authoritative list is in §2.5.
- Do not invent statistics. No "typically around 15%", no "industry standard",
  no "studies show". If you want a number in the README, it comes from Part 2
  or it comes out.
- Do not fabricate citations, URLs, circular numbers, or document titles.
- Do not silently widen scope. Every new module needs operator sign-off.
- Do not write placeholder logic that looks finished. If something is stubbed,
  it says `NOT_IMPLEMENTED` and appears in `LIMITATIONS.md`.
- Do not use an LLM for anything deterministic. See §5.4.
- Do not generate customer-facing copy containing urgency, scarcity, guilt, or
  escalating pressure. See §6.6.

## 0.3 The uncertainty protocol

When you are unsure, emit exactly this and stop:

```
UNCERTAIN: <the specific question>
TIER: <B or C>
BLOCKING: <yes/no — can you proceed on other work meanwhile?>
OPTIONS: <the 2-3 ways this could resolve, and what each implies>
NEED: <primary source to fetch, or decision from operator>
```

Do not guess and continue. Do not "assume reasonable defaults" on anything
touching regulation, money, or customer contact.

## 0.4 The defensibility test

Before adding any component, ask: *can the operator explain why this exists, in
90 seconds, from memory, under hostile questioning?* If no, do not add it. A
smaller system fully understood beats a larger system partially understood.
This rule outranks every other instruction in this document except §0.1.

---

# PART 1 — WHAT WE ARE BUILDING AND WHY

## 1.1 One-sentence statement

A recovery engine for failed UPI AutoPay mandate executions that allocates a
**hard-capped, regulator-constrained retry budget** across **restricted
execution windows**, chooses out-of-band interventions between attempts, and
proves — on a batch — how much money it recovers and how many compliance
violations it commits (target: zero).

## 1.2 Why this problem

Recurring UPI collections fail structurally, not occasionally, and the retry
budget is set by the regulator rather than by the engineer. That converts
"retry the payment" from a loop into a constrained allocation problem with a
real objective function and hard feasibility constraints. See Part 2 for the
verified scale and constraint figures.

## 1.3 What makes this defensible

The scheduler is **deterministic and testable**. The LLM is confined to
classification, intervention selection, and copy drafting. No LLM output ever
directly triggers a money movement. This split is the thesis of the project and
must be visible in the architecture, not just claimed in the README.

## 1.4 Explicit non-goals

- Not a real payment integration. Test mode / simulation only.
- Not a fraud or risk system.
- Not a voice or telephony agent.
- Not a general subscription-management platform.
- Not a UI-first product. The interface exists to make the batch legible.

---

# PART 2 — TIER A: VERIFIED GROUND TRUTH

Everything in this part is sourced. Use it verbatim. Encode each item as a named
constant in `src/domain/regulatory_constants.py` with the source string attached
— never as a bare number in logic.

## 2.1 NPCI operational constraints on AutoPay execution

Source: NPCI *Guidelines on usage of Unified Payments Interface (UPI) and
Application Programming Interface (API)*, circular dated **21 May 2025**,
effective **1 August 2025**.

| Constraint | Value |
|---|---|
| Peak hours (execution prohibited) | 10:00–13:00 and 17:00–21:30 IST |
| Permitted execution windows | before 10:00, 13:00–17:00, after 21:30 |
| Retry budget per mandate | **maximum 1 attempt + 3 retries** |
| Execution rate | moderated TPS |
| Status check — first call | not before **90 seconds** after authentication |
| Status check — frequency cap | maximum **3 calls in any 2-hour window** |
| Terminal error codes | certain codes must be treated as failed; no further calls |
| Balance enquiry cap | 50 per app per customer per 24h |
| Linked-account listing cap | 25 per app per customer per 24h |
| Non-compliance consequence | penalties, API restrictions, or customer-onboarding embargo |

**This is the core constraint of the entire system.** Four attempts total,
inside three disjoint daily windows. Model it exactly.

## 2.2 RBI e-mandate framework

Source: RBI **Digital Payments – E-Mandate Framework, 2026**, Circular No.
**RBI/DPSS/2026-27/396**, dated **21 April 2026**. Issued under Sections 10(2)
read with Section 18, Payment and Settlement Systems Act, 2007. Consolidates
eight circulars issued 2019–2024. Covers cards, PPIs and UPI.

| Obligation | Value |
|---|---|
| Pre-debit notification | 24 hours before debit |
| Post-debit confirmation | after **every** collection |
| Opt-out facility | must be provided |
| Grievance redressal details | must be communicated before and after every debit |
| No-AFA threshold, general | ₹15,000 per transaction |
| No-AFA threshold, enhanced | ₹1,00,000 for insurance premiums, mutual fund SIPs, credit card bills |
| Responsibility | merchant **and** payment aggregator equally responsible |

**Known carve-out:** pre-debit notification is not required for auto-replenishment
of NETC FASTag (**MCC 4784**) and RuPay NCMC (**MCC 7412**) under UPI AutoPay.
Source: NPCI notification dated 23 September 2024, following RBI's Statement on
Developmental and Regulatory Policies of 7 June 2024. Implement this as an
exception path — it is a detail almost nobody encodes and it demonstrates you
read the actual notifications.

## 2.3 Scale and failure-rate figures

| Figure | Value | Source |
|---|---|---|
| AutoPay mandates revoked monthly | ~20 million, primarily insufficient balance | Business Standard, Sept 2025, citing NPCI data |
| New AutoPay mandates, July 2025 | 50m+ (vs 26m July 2024) | NPCI figures via Business Standard |
| Mandate executions, July 2025 | 808m (vs 392m July 2024) | NPCI figures via Business Standard |
| UPI AutoPay failure rate | 8–15% | productgrowth.in fintech analysis, 2026 |
| Card e-mandate failure rate | 2–3% | same |
| Structural cause | UPI flows are stateless; card mandates are bank-managed | same |
| NPCI Technical Decline target | <1% | NPCI Circular OC-149, June 2022 |
| NPCI Business Decline target | <5% | NPCI Circular OC-149, June 2022 |
| System-wide TD trend | 8–10% (2016) → ~0.7–0.8% (2025) | NPCI ecosystem data |

Cite the source inline wherever you use these. Never round or restate them.

## 2.4 Razorpay subscription state machine

Source: Razorpay Docs — *Subscriptions States*, *Test Subscriptions*,
*Subscriptions Webhook Events*.

**Statuses:** `created`, `authenticated`, `active`, `pending`, `halted`,
`cancelled`, `completed`, `expired`, `paused`

**Verified transition rules:**
- An unsuccessful auto-charge moves a subscription `active → pending`. Retries
  continue while pending.
- **Four consecutive failed charges exhaust all retries → `halted`**, and
  `subscription.halted` fires. (Note this independently matches NPCI's 1+3.)
- In `halted`, invoices continue to be generated per billing cycle but **no
  auto-charge is attempted**.
- A subscription can remain `halted` across more than one billing cycle.
- **Returning to `active` does not re-attempt previous charges.** Only future
  billing cycles auto-charge. This is a critical business rule — recovered
  arrears must be collected explicitly, not assumed.
- To return to `active`, the customer authenticates another instrument, or the
  merchant/customer manually charges an older unpaid invoice.

**Webhook events:** `subscription.authenticated`, `subscription.activated`,
`subscription.charged`, `subscription.pending`, `subscription.halted`,
`subscription.completed`, `subscription.updated`, `subscription.cancelled`,
`subscription.paused`, `subscription.resumed`, plus `invoice.paid`,
`invoice.partially_paid`, `invoice.expired`, `payment.failed`,
`payment.captured`, `payment.authorized`.

**Subscription entity fields (verified from real payloads):**
`id`, `entity`, `plan_id`, `customer_id`, `status`, `current_start`,
`current_end`, `ended_at`, `quantity`, `notes`, `charge_at`, `start_at`,
`end_at`, `auth_attempts`, `total_count`, `paid_count`, `remaining_count`,
`customer_notify`, `created_at`, `expire_by`, `short_url`,
`has_scheduled_changes`, `change_scheduled_at`, `source`, `offer_id`

Timestamps are Unix epoch integers. IDs are prefixed (`sub_`, `plan_`, `cust_`,
`pay_`, `inv_`, `order_`). Amounts are integers in paise.

Mirror these field names exactly in your synthetic data. An evaluator will spot
a wrong field name instantly.

## 2.5 Failure taxonomy — the authoritative codes

**Razorpay UPI error reasons.** Source: Razorpay Docs, *UPI Error Codes*. This
is the complete published set. Do not add to it.

| `reason` | Meaning |
|---|---|
| `insufficient_funds` | Account lacked funds |
| `bank_technical_error` | Downtime on the UPI provider |
| `gateway_technical_error` | Gateway-side technical failure |
| `credit_failed` | Credit leg failed |
| `invalid_vpa` | Customer not a valid user on the UPI app |
| `vpa_resolution_failed` | Could not process using customer's UPI ID |
| `payment_declined` | Funds could not be debited |
| `payment_cancelled` | Customer cancelled or pressed back |
| `payment_timed_out` | Timed out |
| `payment_collect_request_expired` | Customer exceeded the time limit (typically 10 minutes) |

Two published descriptions map to bank-side causes: *Partner Bank Downtime* and
*Partner Bank Technical Issues*. *Customer Bank Account Mismatch* covers the
customer selecting a different account than the one registered.

**NPCI response codes.** Source: Razorpay blog, *Tackling UPI Payment Failures*.

| Code | Meaning |
|---|---|
| `Z9` | Insufficient funds |
| `U28` | Customer's bank is down |
| `U30` | Debit failed — bank down or debit issue |
| `U69` | Collect request expired |
| `Z7` | Too many transactions in an interval, as set by customer's bank |
| `Z8` | Per-transaction limit exceeded, as set by customer's bank |

**Razorpay error object shape:** `code`, `description`, `field`, `source`,
`step`, `reason`, `metadata`. The `source` field identifies whether the failure
came from customer action or an external factor (Razorpay, gateway, bank,
network). The `step` field identifies the stage of the transaction.

Use `source` as a first-class routing signal — it is the difference between
"retry later" and "the customer must act."

## 2.6 Razorpay Downtime API

A Downtime API exists at `/docs/api/payments/downtime/` and Razorpay
recommends integrating it to surface downtime at checkout. **Treat this as the
canonical justification for downtime-aware scheduling** — you are not inventing
the concept, you are applying a documented signal to a scheduling decision.
Verify its response shape before depending on specific fields (Tier B).

## 2.7 Razorpay's published agent principles

Source: *Razorpay Agent Studio: Principles, Guardrails, and Merchant Control*,
30 March 2026. Agent Studio launched at FTX'26 on 12 March 2026, built on
Anthropic's Claude Agent SDK.

The nine principles, in their vocabulary — implement and name these:
1. The merchant is always in control (review-first mode; no irreversible action
   without explicit approval; double confirmation for large transfers; one-tap
   kill switch)
2. Agents don't set prices or invent discounts (offers come from a
   merchant-configured allowlist with a ceiling)
3. Agents work with verified first-party data (no scraping, no external
   inference)
4. Every action is validated before it executes (independent layer: compliance
   boundaries, amount validation, PII handling, scope checks, out-of-scope
   behaviour detection)
5. Customer communication follows consent rules (consent verified before
   contact; opt-outs permanently suppressed, no exceptions, no escalation loop)
6. No false urgency, no manufactured pressure (must not employ dark patterns as
   defined under India's Guidelines for Prevention and Regulation of Dark
   Patterns, 2023 — including false urgency, confirm shaming, bait and switch,
   drip pricing, subscription traps)
7. Transparent pricing (cost per action visible)
8. Certification and accountability (continuous evaluation of metrics, outcome
   rates and error patterns)
9. Data privacy and compliance (DPDPA; per-merchant scoping; no cross-tenant
   exposure)

**The timing argument.** Agent Studio shipped 12 March 2026. The RBI E-Mandate
Framework 2026 was issued 21 April 2026. A recovery agent built before that date
cannot structurally encode obligations that did not yet exist. This is the
project's positioning and it belongs in the README's opening paragraph.

---

# PART 3 — TIER B: FETCH BEFORE YOU BUILD

Do not write dependent code until each is confirmed. Record what you found in
`SOURCES.md` with the retrieval date.

1. **NPCI circular of 21 May 2025** — primary text. Confirm the window
   boundaries and the retry budget verbatim. Secondary sources agree but you
   are encoding a regulatory constant.
2. **RBI Circular RBI/DPSS/2026-27/396** — primary text. Confirm which
   obligations apply to UPI AutoPay specifically versus cards and PPIs. Do not
   assume uniformity across rails.
3. **Razorpay Downtime API** — response schema and field names.
4. **Razorpay Subscriptions API** — create/fetch/cancel/pause shapes and the
   exact retry cadence Razorpay itself applies. Confirm whether the documented
   card retry schedule applies identically to UPI mandates. If unclear, say so
   in `LIMITATIONS.md` rather than assuming.
5. **NPCI UPI Ecosystem Statistics** — per-bank Technical Decline, Business
   Decline and uptime. Confirm the actual published columns and cadence before
   designing the ingestion schema.
6. **Any figure you want in the README that is not in Part 2.**

**If a fetch fails, that is a finding, not a blocker.** Record it and design a
fallback. Do not silently substitute a guess.

---

# PART 4 — THE CORE PROBLEM, STATED FORMALLY

State this in `ARCHITECTURE.md` in these terms. It is what elevates the project
above "a retry script."

**Given:** a mandate `m` whose scheduled execution has failed, with
- remaining retry budget `r ∈ {3, 2, 1, 0}` (from a total of 1 + 3)
- a failure reason `f` from the taxonomy in §2.5
- a failure source `s ∈ {customer, bank, gateway, network, razorpay}`
- payer bank identifier `b`, with a health signal `h(b, t)`
- mandate amount `a`, MCC, and billing-cycle position
- consent state, opt-out state, and last-contacted timestamp
- the customer's arrears (note §2.4: returning to active does not collect them)

**Choose:** for each remaining retry, an execution time `t` such that
- `t` falls inside a permitted window (§2.1)
- total attempts never exceed 4
- `f` is not in the terminal set
- the 24h pre-debit notification obligation is satisfiable before `t` (§2.2),
  unless the MCC carve-out applies
- inter-attempt out-of-band interventions respect consent and contact-frequency
  limits

**Maximising:** expected rupees recovered.
**Subject to:** zero compliance violations. This is a hard constraint, not a
penalty term. A schedule that violates it is infeasible, not merely worse.

**Stopping rule:** define explicitly when to stop and revoke rather than
continue. Chasing forever is a failure mode, not thoroughness.

## 4.1 Reason → strategy mapping

Derive this from the taxonomy. It must be a data table, not code branches, so it
can be reviewed by a non-engineer.

| Reason | Source | Retryable? | Rationale |
|---|---|---|---|
| `insufficient_funds` / `Z9` | customer | Yes, but timing-sensitive | Balance is time-varying. Salary-cycle timing is the lever. |
| `bank_technical_error` / `U28` / `U30` | bank | Yes | Transient. Bank health signal should drive window choice. |
| `gateway_technical_error` | gateway | Yes | Transient. |
| `Z7` (velocity limit) | customer's bank | Yes, with spacing | Retrying immediately re-triggers the same limit. |
| `Z8` (per-txn limit exceeded) | customer's bank | **No, not unchanged** | Limit is structural. Retrying the same amount cannot succeed. |
| `invalid_vpa` | customer | **No** | Requires customer action. Retry is waste. |
| `vpa_resolution_failed` | — | Investigate | Razorpay docs direct this to technical support. |
| `payment_cancelled` | customer | Judgment | Customer chose to cancel. Consider intent. |
| `payment_collect_request_expired` / `U69` | customer | Yes | Timing/attention problem, not a funds problem. |
| `payment_declined` | bank | Yes | Debit failed; cause may be transient. |
| `credit_failed` | — | Investigate | Distinguish from debit failure. |

**Do not treat this table as final.** Verify each mapping against the Razorpay
docs in §2.5 and record any you had to reason about rather than read.

The single highest-value insight to encode: **`Z8` and `invalid_vpa` are
structurally unretryable.** Spending a retry on them is pure waste, and
retrying against a terminal code may itself violate §2.1. Your baseline will
burn retries here; your engine will not. That delta is a headline number.

---

# PART 5 — ARCHITECTURE

## 5.1 Pipeline

```
  Failure event  (webhook payload, §2.4 shape)
        │
        ▼
  [1] Normaliser        deterministic  → canonical FailureEvent
        │
        ▼
  [2] Classifier        LLM-assisted   → reason class + confidence + evidence
        │
        ▼
  [3] Retryability gate deterministic  → RETRYABLE | TERMINAL | NEEDS_CUSTOMER
        │
        ▼
  [4] Bank health       deterministic  → h(b,t) from NPCI TD/BD + Downtime API
        │
        ▼
  [5] Allocator         deterministic  → schedule: [(t₁,…), …] within budget
        │
        ▼
  [6] Intervention      LLM-assisted   → which out-of-band action, if any
        │
        ▼
  [7] Copy generator    LLM            → notification text (then screened)
        │
        ▼
  [8] Guardrail layer   deterministic  → INDEPENDENT validation; can veto
        │
        ▼
  [9] Executor          simulated      → attempt, record outcome
        │
        ▼
  [10] Audit log        deterministic  → append-only, every decision, reasoned
```

## 5.2 Non-negotiable structural rules

- **Stage 8 is independent of stages 2, 6 and 7.** It re-derives legality from
  the raw event and the constants, and can veto. It must not import from the
  agent modules. This is Razorpay's principle 4 and it must be architecturally
  true, not decorative.
- **Stages 3, 4, 5, 8 contain no LLM calls.** Ever. Assert this in a test that
  greps the modules for the client import.
- **Stage 9 executes only what stage 8 approved.** Approval is a signed token,
  not a boolean flag someone can flip.
- **Every stage emits to the audit log**, including refusals and vetoes.

## 5.3 Directory layout

```
src/
  domain/
    entities.py             # Subscription, Mandate, FailureEvent, Attempt
    enums.py                # statuses & reasons — EXACTLY §2.4/§2.5
    regulatory_constants.py # every constant + its source string
  ingest/
    normaliser.py
    npci_stats.py           # bank TD/BD ingestion
  classify/
    reason_classifier.py    # LLM
    prompts/
  policy/
    retryability.py         # deterministic gate
    bank_health.py
    allocator.py            # THE CORE ALGORITHM
    stopping_rules.py
  intervene/
    selector.py             # LLM
    copy_generator.py       # LLM
    consent.py
  guardrails/
    validator.py            # INDEPENDENT. no agent imports.
    dark_pattern_screen.py
    invariants.py
  execute/
    simulator.py
  audit/
    log.py
data/
  generate.py               # seeded synthetic mandate book
  npci/                     # real NPCI stats, with retrieval date
eval/
  run_eval.py
  baselines.py
  scenarios.py              # failure injection
tests/
  test_invariants.py        # the compliance assertions
  test_allocator.py
  test_no_llm_in_policy.py
```

## 5.4 Where the LLM is allowed

**Permitted:** classifying free-text failure descriptions into the taxonomy;
choosing intervention type from an enumerated set given context; drafting
notification copy; summarising the batch for a human reader.

**Forbidden:** deciding whether a retry is legal; computing a schedule; deciding
an amount; deciding whether consent exists; deciding whether to stop. All
deterministic.

Every LLM call must use **structured output with a strict schema**, log its
prompt hash, model, latency and token cost, and have a defined behaviour when
output fails validation — which is to fall back to the deterministic default and
log the failure, never to retry indefinitely.

---

# PART 6 — COMPLIANCE INVARIANTS

Write these **first**, as executable tests, before the code they constrain. They
are the spine of the submission.

```python
# tests/test_invariants.py — every one must hold on every run

INV-01  No execution attempt is scheduled inside peak hours
        (10:00–13:00 or 17:00–21:30 IST).                          [§2.1]
INV-02  No mandate ever exceeds 4 total attempts (1 + 3 retries).  [§2.1]
INV-03  No retry is scheduled against a terminal error code.       [§2.1/§4.1]
INV-04  No status check occurs within 90s of authentication.       [§2.1]
INV-05  No more than 3 status checks in any rolling 2-hour window. [§2.1]
INV-06  Every scheduled debit has a pre-debit notification at
        least 24h prior — unless MCC ∈ {4784, 7412}.               [§2.2]
INV-07  A post-debit confirmation is emitted after every
        collection attempt outcome.                                [§2.2]
INV-08  No contact of any kind after an opt-out timestamp.         [§2.7 P5]
INV-09  No generated copy contains a dark pattern.                 [§2.7 P6]
INV-10  No offer outside the merchant-configured allowlist, and
        none above the configured ceiling.                         [§2.7 P2]
INV-11  Every state change has a corresponding audit entry with a
        stated reason.                                             [§2.7 P4]
INV-12  No PII appears in any log at any level.                    [§2.7 P9]
INV-13  No policy or guardrail module imports an LLM client.       [§5.2]
INV-14  Every executed action carries a guardrail approval token.  [§5.2]
INV-15  Arrears are never assumed collected on reactivation.       [§2.4]
```

The eval harness reports `violations: 0` for the engine and the actual count for
each baseline. **That comparison is the single most persuasive artifact in the
submission.**

## 6.6 Dark-pattern screen — specifics

Screen generated copy against India's Guidelines for Prevention and Regulation
of Dark Patterns, 2023, as referenced by Razorpay: false urgency, confirm
shaming, bait and switch, drip pricing, subscription traps.

Concretely, reject copy containing: countdown or expiry language not backed by a
real merchant-configured deadline; scarcity claims; guilt or shame framing;
offers that escalate across contacts; obscured cancellation paths; any implied
consequence that is not factually true.

Permitted: the actual amount, the actual due date, the actual consequence of
non-payment where genuinely applicable, and a clear opt-out.

Implement as a deterministic screen that runs **after** generation and can veto.
Log every rejection with the offending span. Rejections are a feature — report
the count.

---

# PART 7 — DATA

## 7.1 Synthetic mandate book

Generate 500–1,000 mandates, seeded and reproducible via `data/generate.py`.
Commit the generator, not just the output.

Use the exact field names from §2.4. Model:
- a plausible amount distribution (many small, few large), with mass around the
  ₹15,000 and ₹1,00,000 AFA thresholds so those branches are exercised
- MCC assignment including some 4784 and 7412 so the carve-out path is tested
- failure reasons distributed across the §2.5 taxonomy, weighted so
  `insufficient_funds` dominates (consistent with §2.3's finding on revocation
  causes)
- payer banks drawn from the real NPCI bank list, so real TD data joins
- consent and opt-out states, including some pre-existing opt-outs
- billing-cycle position and existing arrears

**Every distributional choice goes in `ASSUMPTIONS.md` marked `UNVERIFIED:`,
with a note on what changes if it's wrong.** Do not present the mix as
empirical. Say plainly in the README: the mandate book is synthetic; the bank
health signal is real; here is exactly how each was constructed.

## 7.2 Real bank health data

Ingest NPCI per-bank Technical Decline, Business Decline and uptime figures.
Record the retrieval date and the exact source page in `SOURCES.md`. Join on
payer bank.

This hybrid — synthetic events, real bank signal — is a deliberate, defensible
modelling choice. Be ready to defend why it's more honest than fully synthetic
data *and* why it doesn't make the results empirical.

## 7.3 Held-out split

Hold out 20% before any tuning. Never look at it until the final run. Tune on
train; report on held-out; report both.

---

# PART 8 — BASELINES

Implement all four. Without them your number has no denominator.

- **B0 — No recovery.** Fail and halt. The floor.
- **B1 — Naive retry.** Retry immediately, up to budget, ignoring windows,
  terminal codes, and notification obligations. *This is what most systems
  actually do and it will rack up violations. That contrast is the point.*
- **B2 — Fixed schedule.** Retry at fixed offsets (e.g. +24h, +48h, +72h),
  window-aware but not reason-aware or bank-aware.
- **B3 — Reason-aware, not bank-aware.** Isolates the marginal value of the
  bank health signal.

Report B0–B3 and the engine side by side. If the engine doesn't beat B2 by a
meaningful margin, **say so in the README and analyse why.** An honest negative
result, well-analysed, outperforms an inflated positive one. The evaluator has
seen a hundred inflated positives.

---

# PART 9 — EVALUATION HARNESS

Build before the agent. One command regenerates every number:
`make eval` → `EVALUATION.md` + `results/`.

Required table, per strategy:

| Metric | Note |
|---|---|
| Mandates processed | N |
| ₹ at risk | Total |
| ₹ recovered | The headline, **always with its denominator** |
| Recovery rate | Never reported alone |
| Mandates saved from halt | Count |
| **Compliance violations** | **Per invariant. Target 0.** |
| Retries consumed | Total and mean |
| Retries wasted on terminal codes | The efficiency argument |
| Time-to-recovery | Median and p90 |
| Interventions sent | By type |
| Dark-pattern rejections | Count, with examples |
| LLM cost | ₹ per mandate, tokens, p99 latency |
| Unresolved exceptions | **Full list with reasons** |
| Classifier accuracy | On held-out, with confusion matrix |

Plus: a sensitivity analysis over the two or three assumptions that most affect
the headline. If the result only holds under one distributional guess, the
evaluator will find that. Find it first.

---

# PART 10 — FAILURE INJECTION

Track 01's bar demands "one failure handled gracefully." Implement at least six
and document all in `FAILURES.md`: what broke, how it was detected, how the
system degraded, what the customer/merchant experienced.

1. LLM returns malformed or schema-invalid output mid-batch
2. LLM times out or rate-limits
3. NPCI stats file unavailable or stale
4. Downtime API unreachable
5. A failure reason arrives that is not in the taxonomy
6. Clock/timezone edge: a schedule computed near a window boundary, and a DST-
   or midnight-crossing case
7. Duplicate webhook delivery (idempotency)
8. Opt-out arriving *between* scheduling and execution

**Number 8 is the most interesting one.** Handle it correctly and say so out
loud — it's the case that proves the guardrail layer is real rather than
decorative, because the schedule was already valid when it was made.

---

# PART 11 — DELIVERABLES

```
README.md          problem in money → headline number with denominator →
                   30-second quickstart → architecture diagram → limitations
ARCHITECTURE.md    formal problem statement (Part 4), diagram, every major
                   decision with rationale AND rejected alternatives
EVALUATION.md      generated. all baselines. full exception list.
DECISIONS.md       ADR log, written as you go, not retrofitted
ASSUMPTIONS.md     every UNVERIFIED: item with sensitivity notes
SOURCES.md         every Tier A/B fact, its source, retrieval date
LIMITATIONS.md     what doesn't work, what's stubbed, what you'd fix
FAILURES.md        Part 10
AI_USAGE.md        which agent, how context was structured, what was delegated
                   vs written by hand, where the agent was wrong and how it
                   was caught
CLAUDE.md          committed. the working agreement.
Makefile           make setup && make eval && make demo
```

**Commit hygiene:** real incremental commits with meaningful messages across the
whole build period. Never squash the project into one commit.

**Reproducibility:** seed everything, pin dependencies, and test the clean-clone
path on a fresh machine before submitting.

---

# PART 12 — BUILD ORDER, WITH GATES

Stop at each gate and report. Do not proceed unprompted.

| Phase | Work | Gate |
|---|---|---|
| 0 | Fetch all Tier B sources. Write `SOURCES.md`. | Operator confirms constants |
| 1 | `regulatory_constants.py` + `tests/test_invariants.py`, all failing | Tests exist and fail correctly |
| 2 | Domain entities and enums from §2.4/§2.5 | Field names match docs exactly |
| 3 | `data/generate.py` + held-out split + `ASSUMPTIONS.md` | Distribution reviewed |
| 4 | NPCI stats ingestion | Real data joined |
| 5 | Baselines B0–B3 + eval harness | Baseline numbers exist |
| 6 | Retryability gate + allocator (deterministic core) | Invariant tests pass |
| 7 | Guardrail layer, independent | INV-13/14 pass |
| 8 | LLM classifier + intervention selector | Structured output validated |
| 9 | Copy generator + dark-pattern screen | INV-09 passes |
| 10 | Failure injection (Part 10) | All six documented |
| 11 | Minimal interface, ≤15% of effort | Audit trail viewable |
| 12 | Final eval, docs, sensitivity analysis | Every number reproducible |

**Phases 1 and 5 come before any agent code.** Tests and baselines first. This
ordering is the difference between a measured system and a demo.

---

# PART 13 — WHAT WOULD MAKE THIS FAIL

Recognise and refuse these:

- A chatbot wrapper with no measurement
- A percentage with no denominator
- A demo that works on one hand-picked mandate
- A polished UI over an unmeasured backend
- An architecture diagram with a box nobody can explain
- Vector DB / RAG / a multi-agent framework used because it's fashionable
  rather than because the problem needs it
- Invented regulations, invented codes, invented statistics
- Hidden failures
- One squashed commit
- A README describing intentions rather than results

---

# PART 14 — HOW TO WORK WITH THE OPERATOR

- Report at every gate. Short: what you did, what you verified, what you
  assumed, what's next, what you need.
- Surface uncertainty immediately using the §0.3 format. Never bury it.
- When you write a non-obvious line, add a one-line comment explaining *why* —
  those comments become the operator's interview answers.
- Keep `DECISIONS.md` current as you go. Retrofitting it produces a document
  nobody can defend.
- If asked to add scope, restate §0.4 and ask what should come out in exchange.
- If you notice the operator has misunderstood something in this spec, say so
  directly.

**Final instruction:** the operator will stand in a room and defend every line
of this. Build accordingly. When in doubt, build less and understand it
completely.
