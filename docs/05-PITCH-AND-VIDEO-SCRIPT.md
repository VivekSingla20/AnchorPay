# The UPI AutoPay Mandate Recovery Engine — Full Explainer & Hackathon Script

One reference document: the idea, the problem, the solution (twice — once
in plain language, once technical), the measured impact, who it's for,
what it's made of, and a ready-to-use video script. Read top to bottom
once before the panel interview; use the last two sections directly for
the video.

---

## 1. The idea, in one sentence

When a recurring UPI payment (Netflix, a SIP, an insurance premium, an
EMI) fails to auto-collect, this engine decides **whether it's even worth
retrying, exactly when to retry it, and what to honestly tell the
customer** — inside a legal budget of just 4 attempts across 3 fixed daily
windows — and proves on 800 real-shaped test records that it recovers
real money with **zero compliance violations**, unlike the naive approach
most systems actually use.

---

## 2. The problem

**What UPI AutoPay is:** a "standing instruction" — you tell your bank
once, "auto-charge me ₹500 every month for X," and it happens without you
tapping approve each time.

**What breaks:** sometimes the auto-charge fails. Not enough balance that
day, a bank server hiccup, a broken UPI ID, or — a subtler case — the
customer deliberately keeps the account empty because they don't trust
the app's "cancel" button and this is their workaround.

**Why this is a genuinely hard engineering problem, not a trivial one:**
the payments regulator (NPCI) enforces two hard rules on every retry:

1. **You get exactly 4 attempts, total** — 1 original + 3 retries. Not 5.
   Not "3 more if you're careful." Four, ever, per failed cycle.
2. **You can only attempt during 3 specific daily windows** — before
   10:00 AM, 1:00–5:00 PM, or after 9:30 PM (IST). Two "peak" windows in
   between are completely off-limits, because NPCI reserves them to keep
   the national payment network from overloading.

Get either rule wrong and the *merchant* — not just this one payment —
risks penalties, API restrictions, or losing the ability to onboard new
customers. So "just retry until it works" is not a safe strategy; it's a
compliance liability wearing the costume of a bug fix.

---

## 3. The problem's impact (real-world scale)

These figures are independently reported, not this project's own numbers
— see `SOURCES.md` and `docs/03-DOMAIN-CONTEXT.md` for exact citations:

- **~20 million** UPI AutoPay mandates are revoked every month in India,
  primarily due to insufficient balance (Business Standard, citing NPCI
  data, Sept 2025).
- Business declines — non-technical failures, mostly low balance — average
  **~74%** of AutoPay transaction failures across the top 50 banks.
- UPI AutoPay's overall failure rate (8–15%) runs several times higher
  than card-based auto-debit (2–3%), because UPI is a stateless,
  real-time-approval rail — the bank never "reserves" funds the way a
  card network does at mandate setup.
- Globally, failed recurring payments cost businesses an estimated
  **$118.5 billion a year** (PYMNTS/Checkout.com) — UPI AutoPay is India's
  local, sharper version of a problem every subscription business has.

Put simply: a small percentage improvement in how well these retries are
handled is a very large absolute number of rupees, at this volume.

---

## 4. The solution — in simple language

Think of it as a careful specialist handling each failed payment through a
checklist, instead of a machine blindly hammering "retry" every hour:

1. **What exactly went wrong?** ("no money" vs. "bank was down" vs. "this
   UPI ID doesn't exist" are very different situations.)
2. **Is retrying even worth it?** Some failures are dead ends — no amount
   of retrying fixes a broken UPI ID. Wasting one of only 4 attempts on a
   guaranteed failure is the single most avoidable mistake a naive system
   makes.
3. **If it's worth retrying, pick a smart moment.** For "no balance"
   failures, lean toward the 1st–3rd of the month (payday season), not a
   random hour later.
4. **Tell the customer honestly**, before and after, with no fake urgency,
   countdown timers, or guilt — an automatic screen actively blocks any
   generated message that tries.
5. **Recognise when someone has already said no.** If the same account
   keeps failing the same way, near-empty every time, that's very likely
   someone using "insufficient funds" as a quiet cancel button — chasing
   them isn't recovery, it's harassment. Stop and ask instead of retrying.
6. **Double-check the rules again right before acting**, not just when the
   plan was first made — because a customer can opt out *after* a retry
   was scheduled but *before* it runs, and the system needs to catch that.
7. **Write down every decision in plain English**, so any single payment's
   story can be pulled up and explained in seconds.

---

## 5. The solution — in technical language

**Architecture:** a 10-stage linear pipeline (`src/orchestrator.py`
wires it together), not one giant LLM prompt and not a dynamic
multi-agent framework:

```
ingest → classify → retryability gate → bank-health score → allocator
  → intervention selector → copy generator → guardrail → executor → audit log
```

**The hard architectural rule:** stages 3, 4, 5, and 8 (retryability
gate, bank health, allocator, guardrail) are **100% deterministic Python —
structurally incapable of calling an LLM.** This isn't a comment promising
good behaviour; it's mechanically enforced by
`tests/test_no_llm_in_policy.py`, which parses every file in those folders
with Python's `ast` module and fails the build if any of them import an
LLM client. No LLM ever decides legality, timing, amounts, or consent.

**The core algorithm (`src/policy/allocator.py`):** constraint-satisfaction
plus greedy scoring.
- *Phase 1:* generate only candidate times that are already inside a legal
  window and past the 24-hour pre-debit-notice deadline — illegal times are
  never even constructed, not generated-then-filtered.
- *Phase 2:* score each legal candidate — `+3.0` if it's a high-liquidity
  day-of-month for a balance-related failure, `-5.0`/`-2.0` for
  known bank downtime severity, a small "sooner is better" tiebreaker — and
  greedily pick the best.

**The double-check pattern (defense in depth):** stage 5 (allocator)
*proposes* a schedule; stage 8 (`src/guardrails/validator.py`)
independently *re-derives* the same legality facts from the raw
regulatory constants — without importing the allocator's code at all —
and re-checks them **at the literal moment of execution**, not just when
the schedule was made. That's what makes an edge case like "customer opts
out an hour after the failure, a day before the retry" resolve correctly.

**LLM usage — deliberately narrow, never money-deciding:** five of the ten
stages may optionally call an LLM (off by default; `RECOVERY_ENGINE_USE_LLM`
env var). Every one of those calls is wrapped in a function that never
raises and always has a deterministic fallback if the model is
disabled, unreachable, or returns invalid output — so the system is fully
functional with zero API keys. Two of those five stages were added
specifically to *narrate*, never decide: `intervene/escalation_brief.py`
writes a note for the human support agent on an escalated case, and
`eval/batch_summary.py` writes one paragraph narrating already-computed
results — augmenting a human reader, exactly the "investigates but doesn't
decide" posture Razorpay's own Oncall Agent is built on.

**Data modelling:** Pydantic v2 models whose fields mirror Razorpay's real
Subscription/Payment objects field-for-field (`src/domain/entities.py`),
so a real integration later is a data-source swap, not a schema rewrite.

**Evaluation methodology:** every strategy (4 baselines + the engine) is
tested against the *same* deterministic, hash-seeded stochastic outcome
model, so a strategy's measured recovery rate reflects scheduling quality,
never RNG luck. Ablations (does the salary-cycle heuristic actually help?
does bank-health-awareness?) are the same code with feature flags flipped,
not separate re-implementations that could quietly drift.

---

## 6. The impact of the solution (measured, not projected)

On the actual test batch (800 synthetic-but-realistically-distributed
records, 640 train / 160 held-out, `EVALUATION.md` regenerated by
`python -m eval.run_eval`):

| | Compliant engine | Naive always-retry baseline |
|---|---|---|
| Rupees recovered (train, 640 records) | Rs 79,17,547 of Rs 1,33,71,264 at risk (**59.21%**) | Rs 97,02,832 (**72.56%**) |
| Compliance violations | **0** | **4,211** |
| Retries wasted on dead-end reasons | **0** | 108 |
| Held-out split (160 records, never tuned against) | Rs 16,04,900 recovered (53.61%), **0** violations | — |

**The honest, deliberately-not-hidden finding:** the reckless baseline
recovers *more raw rupees* — because it doesn't hold back from illegal or
wasteful retries. That's the whole point of reporting both numbers
side by side: a merchant recovering 73% at 4,211 compliance violations is
one enforcement letter away from an API restriction; 59% at zero
violations is the number that's actually sustainable to operate at scale.

**Two secondary, measured results:**
- **Intent inference** (the "won't pay vs. can't pay" detector) scores
  **81.8% precision, 100% recall** on the held-out split — it never misses
  a genuine intentional non-payer, and is right 4 times out of 5 when it
  flags one.
- **Zero LLM cost** for this committed run (`RECOVERY_ENGINE_USE_LLM=false`)
  — every classify/select/write/narrate decision took its deterministic
  fallback path, and the reported cost figure is read from a real counter,
  not hardcoded.

**At the real-world scale from §3:** this is a demonstration on a
simulated batch, not a claim about the ~20 million/month real figure — but
the *shape* of the result (a few percentage points of compliant recovery,
applied to a number that large) is exactly why Track 03's bar asks for a
measured batch result instead of a bare percentage.

---

## 7. What the project should do (the functional core)

- Ingest a failed-mandate event in Razorpay's real webhook shape, including
  malformed/unrecognised ones, without crashing.
- Decide, deterministically, whether a reason is retryable, terminal
  (never retry), or needs a human (`INVESTIGATE`).
- Detect the "used insufficient-funds as a cancel button" pattern from a
  mandate's own history, without an LLM judgment call.
- Schedule the next attempt inside a legal window, biased toward
  higher-success timing, without ever proposing an illegal time.
- Draft and screen customer-facing copy for dark patterns before it can
  send.
- Re-verify legality at the moment of every send/execute, not only when
  first scheduled.
- Log every decision, in plain English, per mandate.
- Measure itself honestly: rupees recovered vs. at risk, violations by
  type, exceptions with reasons, an ablation of its own heuristics — on a
  full batch, never a cherry-picked record.
- Degrade gracefully under 8 named failure conditions (malformed LLM
  output, timeouts, missing reference data, unreachable downtime API,
  unknown reason codes, clock-boundary edge cases, duplicate webhooks,
  opt-out races) instead of crashing or silently misbehaving.

---

## 8. Who will use it

- **Razorpay's Subscription Recovery product team** — the direct analogue
  of an already-shipped product this project intentionally goes deeper
  than on one specific angle (the regulatory constraint set + intent
  inference), rather than cloning it.
- **Merchant finance/ops teams** relying on Razorpay for recurring
  billing — the audit trail (`src/cli.py explain`) is built for them to
  self-serve "why did this customer's payment do what it did," not just
  for an engineer.
- **Compliance/risk teams** — the invariant violations table is the
  artifact they'd actually ask for first.
- **Customers, indirectly** — fewer nonsensical retries at 2 AM, honest
  "this failed because of your bank, not you" messaging, and a real
  cancel path instead of being chased after they've already said no.
- **The panel interviewer**, in the immediate term — every section above
  maps directly onto their published rubric (`docs/01-EVALUATION-CRITERIA.md`).

---

## 9. Components of the project

| Folder/file | What it is |
|---|---|
| `src/domain/` | Entities, enums, and every regulatory constant — each one sourced |
| `src/policy/` | The deterministic core: retryability gate, bank-health scoring, the allocator, stopping rules |
| `src/guardrails/` | The independent double-check layer — no LLM import, ever, enforced by a test |
| `src/classify/` | The optional LLM client + the narrow reason classifier |
| `src/intervene/` | Intervention selector, copy generator, consent bookkeeping, escalation briefs |
| `src/execute/` | The simulator (test-mode only) |
| `src/orchestrator.py` | Wires all 10 stages together for the engine strategy |
| `src/cli.py` | The demo interface — `list`, `explain`, `compare` |
| `data/generate.py` | The seeded synthetic mandate-book generator |
| `data/npci/` | Real NPCI bank identifiers + calibrated health reference data |
| `eval/baselines.py` | The 4 comparison strategies (B0–B3) |
| `eval/run_eval.py` | One command → `EVALUATION.md` + `results/*.json` |
| `eval/scenarios.py` | The 8 failure injections |
| `eval/batch_summary.py` | LLM-narrated (or templated) summary paragraph |
| `tests/` | 78 automated tests |
| `README.md` / `ARCHITECTURE.md` / `EVALUATION.md` | The problem, the design, the results |
| `DECISIONS.md` / `ASSUMPTIONS.md` / `LIMITATIONS.md` / `FAILURES.md` / `SOURCES.md` / `AI_USAGE.md` | Every choice, every guess, every gap, every source, every bug caught — named and dated |

---

## 10. Hackathon pitch script (timed to the required 5-minute structure)

Structure and timings match `docs/01-EVALUATION-CRITERIA.md` §9 exactly —
this is the rubric, not a suggestion. Read it once at natural pace to
check your own timing before recording; adjust wording to your own voice,
keep the numbers exact.

### 0:00–0:30 — The problem, in money
> "Every month, about 20 million UPI AutoPay payments fail in India — mostly
> because of low balance. Retrying sounds simple, but the regulator caps
> every merchant at exactly 4 attempts, confined to 3 fixed time windows a
> day. Get that wrong, and you don't just lose the payment — you risk the
> merchant's ability to onboard new customers at all. This is a recovery
> engine that gets every one of those 4 attempts right."

### 0:30–1:15 — Architecture
*(Show the diagram from `ARCHITECTURE.md` §3 or README.)*
> "Ten stages, left to right: ingest, classify, a retryability gate, bank
> health, the allocator — the core scheduling algorithm — an intervention
> selector, a copy generator, an independent guardrail, the executor, and
> an audit log. Four of those stages are LLM-assisted and optional; the
> four that decide legality, timing, and money are 100% deterministic Python
> — and that's not a promise, it's enforced by a test that parses the
> source code itself and fails the build if an LLM import ever sneaks in."

### 1:15–3:15 — Live run on the full batch
*(Screen-record this section live, narrate over it — see §11 below for
exact commands.)*
> "Let's run it for real, on the full batch — not one hand-picked record."
> *(run `python -m eval.run_eval`)*
> "800 synthetic-but-realistically-distributed mandates, 640 to train
> against, 160 held out and never tuned on. One command regenerates every
> number you're about to see."
> *(open `EVALUATION.md`, scroll through headline table)*
> "And here's one real mandate, end to end." *(run `python -m src.cli
> explain <id>`)* "Every decision, in plain English, for a support agent
> or a compliance reviewer to read directly — no black box."

### 3:15–4:00 — The numbers, baseline, exceptions
> "On the training split: the compliant engine recovers 59% of at-risk
> rupees with zero compliance violations. A naive always-retry baseline
> recovers more — 73% — by committing 4,211 violations to get there.
> That's the actual trade-off nobody else reports honestly. And here's the
> full exception list — every single mandate it could NOT recover, and
> why — not a cherry-picked success."

### 4:00–4:40 — A failure, handled gracefully
*(run `python -m eval.scenarios`)*
> "Here's a deliberate one: a customer opts out one hour after their
> payment fails — a full day before their next legal retry window. The
> schedule was completely valid when it was made. Watch: the guardrail
> re-checks consent at the *exact moment* of execution, not when it was
> first planned, and blocks the retry. That's the difference between a
> guardrail that's real and one that's decorative."

### 4:40–5:00 — Limitations and what's next
> "Honestly: this runs on simulated data, because no public dataset of
> real UPI AutoPay outcomes exists — every assumption is written down, not
> hidden. Two source documents — an RBI circular and Razorpay's own
> Subscriptions API shape — still need a final independent re-verification
> before this goes further. Next, I'd wire in Razorpay's real Downtime API
> instead of the synthetic version already built to the identical schema."

---

## 11. What to actually show on screen in the video

Rehearse this exact command sequence once before recording — every one of
these was verified working in this session:

1. **(0:30–1:15)** Have `ARCHITECTURE.md`'s diagram or the README's mermaid
   diagram open and visible — screenshot or scroll to it, don't just talk
   over a blank editor.
2. **(1:15–1:45)** Terminal: `python -m eval.run_eval` — let the printed
   summary lines appear on screen (`recovered=Rs..., violations=...` per
   strategy — this alone visually makes the "0 vs 4,211" point before you
   even say it).
3. **(1:45–2:30)** Open the freshly-generated `EVALUATION.md` in the
   editor, scroll through the headline table and the compliance-violations
   table (the one where the engine's row is all zeros).
4. **(2:30–3:15)** Terminal: `python -m src.cli list --limit 10`, pick one
   `mandate_id`, then `python -m src.cli explain <that_id>` — let the
   plain-English decision trail print fully on screen.
5. **(3:15–4:00)** Back in `EVALUATION.md`: scroll to the exception list
   and the ablation table.
6. **(4:00–4:40)** Terminal: `python -m eval.scenarios` — let all 8
   `[PASS]` lines print, then pause on scenario 8's line specifically
   (the opt-out one) and read it out loud as you point at it.
7. **(4:40–5:00)** Have `LIMITATIONS.md` open, scroll past the first two
   items (the two unverified sources) — point at them directly rather than
   paraphrasing from memory.

Screen-record, don't slideshow. No logo animation, no music, no team
intro — the rubric explicitly marks those down.
