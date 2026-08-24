# Razorpay AI Buildathon — Build Brief for an AI Coding Agent

Paste this whole file into your agent (Claude Code, Cursor, Codex) as the standing
context for the project. Do not let it drift from these constraints.

---

## 0. Non-negotiable framing

You are building a submission for the Razorpay AI Buildathon 2026 (AI Builder
Intern, ₹75,000/mo, Bangalore). Deadline: **5 September 2026**.

Deliverables are exactly three things:
1. A **public GitHub repo**
2. A **5-minute pitch video**
3. An **architecture explanation**

Then a **live panel interview** where a Razorpay engineer interrogates the build.

**The single most important constraint:** every design decision must be one the
human operator can defend out loud, from memory, under questioning, in about
90 seconds. If the operator cannot explain why a choice was made, remove the
choice. A smaller system fully understood beats a larger system partially
understood. This overrides every other instruction here.

---

## 1. Razorpay's actual published rubric

Razorpay published nine operating principles for their Agent Studio marketplace
(razorpay.com/blog/razorpay-agent-studio-principles-guardrails-and-merchant-control).
This is the closest thing to a written grading rubric that exists. Implement as
many as apply. Name them in the README using their vocabulary.

| # | Razorpay principle | What to implement |
|---|---|---|
| 1 | Merchant always in control | A `review-first` mode flag. Agent does all work, holds output for human approval. Irreversible actions require double confirmation and are never auto-approved. One-tap kill switch. |
| 2 | Agents don't set prices or invent discounts | Any offer/discount must be selected from a merchant-configured allowlist with a hard ceiling. Agent picks from authorized options; it never generates a new one. Write a test that proves the ceiling holds. |
| 3 | Verified first-party data only | Read from the merchant's own connected systems (Razorpay test-mode API, a mock Shopify/Tally fixture). No web scraping, no external inference, no guessing at values. |
| 4 | Every action validated before execution | A validation layer independent of the agent: compliance boundary check, amount validation, PII handling, scope check, out-of-scope behaviour detection. Two layers — the agent proposes, the platform disposes. |
| 5 | Consent rules on customer communication | Consent verified before any outbound message. Opt-outs permanently suppressed, no exceptions, no retry loop. A "no" terminates the sequence. |
| 6 | No false urgency, no dark patterns | Explicitly comply with India's Guidelines for Prevention and Regulation of Dark Patterns, 2023. No fabricated scarcity, countdown timers, confirm-shaming, drip pricing, or escalating-offer pressure. Ship a linter or test that screens your own generated copy for these. |
| 7 | Transparent pricing / cost | Log and display per-action cost (tokens, calls, messages). Report cost-per-outcome. |
| 8 | Certification & accountability | Continuous evaluation: metrics, outcome rates, error patterns tracked over time, not measured once. |
| 9 | Data privacy & compliance | Reference DPDPA. Scope data per-merchant. No cross-tenant leakage. Redact PII in logs. |

Principles 1, 4, 5 and 6 are the highest-value ones for a student build because
almost nobody else will implement them and they are cheap to demonstrate.

---

## 2. Razorpay's reference architecture

Their flagship internal agent, **Bumblebee** (fraud/merchant risk review), is
publicly documented on dev.to/razorpaytech and engineering.razorpay.com. It is
the architecture their engineers think in. Mirror its shape:

```
Planner  →  decides what to gather, sets priorities and timeouts
   ↓
Fetchers →  run in PARALLEL, one per data source, each owning its domain
   ↓
Analyzers → specialised evaluation per risk/eval dimension
   ↓
Decision →  consolidates, emits verdict + confidence + evidence trail
```

Key properties to copy:
- **Orchestrator delegating to specialised sub-agents**, not one god-prompt.
- **Explicit timeouts per fetcher.** Partial results are acceptable; hangs are not.
- **Parallel execution** where sources are independent.
- Modelled on how the *human* team already worked (specialists working in
  parallel, then comparing notes). Ground your decomposition in a real workflow.

Their published Bumblebee numbers, for reference on how they frame impact:
~10,000–12,000 manual reviews/month at ~4 min each = 700–800 human hours/month,
accuracy moved 88% → 99%+, latency under 90 seconds per review. Note the shape
of that claim: **volume × time saved × accuracy delta × latency.** Frame your
own result the same way.

Also read their Oncall Agent post (LangGraph-based, MTTI framing, "don't replace
humans, augment them"). The stated lesson — the agent investigates but does not
make the judgment call — is the same posture the buildathon's "bounded and gated"
language is asking for.

---

## 3. Track selection rules

Pick ONE. Each track has a published "bar" sentence — that sentence is the rubric.

| Track | The bar (verbatim intent) | What you must produce |
|---|---|---|
| 01 Growth & Agentic Commerce | Every money action explainable, bounded, gated. Audit trail + one failure handled gracefully. | A deliberate, documented failure injection and graceful recovery |
| 02 AI Risk Manager | Honest metrics **including false-positive cost**. Defense-only. | Precision/recall on a held-out test set + rupee cost of false positives |
| 03 Revenue Recovery | **Measured money recovered across a batch**, compliant escalation, stopping rules, audit trail | ₹ recovered / ₹ at risk, on ≥100 records |
| 04 Finance Controller | Throughput + measured accuracy + honest exception list, on **50+ records** | Match rate + the list of what it could NOT resolve |
| 05 Open | Explicitly "not easier" — same bar | Everything above, on a problem you know deeply |

**Selection heuristic:** Tracks 03 and 04 have the most mechanically verifiable
bars (a number on a batch), which makes them the easiest place for a strong
student to produce undeniable evidence in limited time. Track 02 is the least
crowded but requires you to construct a labelled dataset. Track 01 is the most
crowded — it is the one the marketing emphasises.

**Warning:** Razorpay already ships production agents for most listed example
directions (Dispute Responder, Subscription Recovery, Cart Abandonment,
Cashflow Forecaster, RTO Shield, Settlement Insights). Do not build a naive
clone — you will be compared to their production version by the people who
built it. Take the problem *shape* and go somewhere they haven't: a specific
segment, a specific failure mode, a specific language, a specific edge case.

---

## 4. Build order — do not deviate

Work in this sequence. Do not start on UI until step 6.

1. **Dataset first.** Before writing agent code, generate a synthetic dataset of
   100–300 records with a realistic distribution, including a labelled
   **held-out test split** you never tune against. Commit the generator script,
   not just the data. If the dataset is fake, say so loudly and explain how you
   modelled the distribution.
2. **Baseline second.** Implement a dumb non-AI baseline (rules, regex, thresholds).
   Measure it. This number is your denominator forever. Most submissions will
   have no baseline; having one is instantly credible and it is the first thing
   a good interviewer asks for.
3. **Harness third.** Build the evaluation harness before the agent. It must run
   the whole batch end-to-end and emit a metrics report as a committed artifact.
4. **Agent fourth.** Planner → parallel fetchers → analyzers → decision.
   Structured outputs at every boundary. No free-text passed between stages.
5. **Guardrails fifth.** The independent validation layer from §1.4. Prove with
   tests that it blocks out-of-scope actions.
6. **Interface sixth.** Minimal. Enough to run a demo and view the audit trail.
   Do not spend more than 15% of total effort here.
7. **Failure injection seventh.** Deliberately break things (API timeout,
   malformed record, LLM returns garbage, rate limit, ambiguous case) and
   implement graceful degradation for each. Log every one.

---

## 5. Metrics you must emit

Commit these as a generated `EVALUATION.md` or `results/` artifact, regenerated
by a single command.

**Universal:**
- N records processed, wall-clock time, throughput (records/min)
- Cost per record (tokens + API calls, in ₹)
- Baseline vs. agent, side by side
- Exception list: every record it could not resolve, with the reason

**Track 02 additionally:**
- Precision, recall, F1 on held-out split
- Confusion matrix
- **False-positive cost in rupees** — assign a real number to a wrongly-blocked
  transaction and total it. This is the line they explicitly asked for and it is
  what separates a risk-minded builder from a demo builder.
- Threshold sensitivity curve

**Track 03 additionally:**
- ₹ at risk identified vs. ₹ recovered vs. ₹ leaked
- Recovery rate by intervention type
- Stopping-rule trigger counts
- Escalation compliance log

**Track 04 additionally:**
- Match rate on 50+ records
- Unmatched/exception count and taxonomy of *why*
- Precision of matches (are the matches actually correct?)

**Rule: never report a single cherry-picked success.** Razorpay wrote "one
cherry-picked match proves nothing" into the track. Report the whole batch.

---

## 6. Repository requirements

```
README.md              # see below
ARCHITECTURE.md        # diagram + every major decision with rationale + rejected alternatives
EVALUATION.md          # generated metrics report, whole batch
DECISIONS.md           # ADR-style log: what we chose, what we rejected, why
FAILURES.md            # what broke, how it was detected, how it degraded
data/generate.py       # synthetic data generator, seeded and reproducible
eval/run_eval.py       # one command reproduces every number in EVALUATION.md
src/                   # planner / fetchers / analyzers / guardrails cleanly separated
tests/                 # especially guardrail tests and ceiling tests
.env.example
Makefile               # make setup && make eval && make demo
```

**README must open with, in this order:**
1. One sentence: the problem, in money terms.
2. The headline number, with its denominator. ("Recovered ₹X of ₹Y at risk across N records" — never a bare percentage.)
3. A 30-second quickstart that actually works from a clean clone.
4. Architecture diagram.
5. Honest limitations section.

**Commit hygiene:** real incremental commits with meaningful messages. Do not
squash a two-week build into one commit — it reads as either purchased or
generated wholesale, and it destroys the story of how you worked.

**Reproducibility is a scored property.** Seed everything. Pin dependencies.
Test the clean-clone path on a fresh machine before submitting.

---

## 7. Disclose AI usage — do not hide it

Razorpay's own Full Stack Builder job description says: *"Most engineers, PMs &
designers use AI. Few are AI-native. We're hiring the latter."* It specifies
Claude Code or Cursor as a default environment, orchestrating agents, and
building with skills and MCPs.

So: include an `AI_USAGE.md` documenting how you used AI to build this — which
agent, how you structured context, what you delegated vs. wrote yourself, where
the agent was wrong and how you caught it. Commit your `CLAUDE.md` / `AGENTS.md`
/ `.cursor/rules`. Their own MCP server repo ships exactly these files.

This inverts the usual anxiety. Heavy, well-documented, well-supervised AI usage
is the *target profile*, not a confession. What loses is being unable to explain
code you shipped.

---

## 8. Hard disqualifiers — enforce these

- **Track 02 is defense-only.** Anything offense-capable is explicitly
  disqualified. Do not generate attack tooling, evasion techniques, synthetic
  fraud that could be operationalised, or "here's how the fraud works" detail
  beyond what detection requires. If in doubt, cut it.
- **No real payment credentials.** Test-mode API keys only. Never commit
  secrets. Add a secret scan to CI.
- **No real personal data.** Synthetic only. Redact PII in all logs.
- **No dark patterns**, per §1.6, including in generated customer-facing copy.
- **No scraping** of Razorpay or merchant properties. First-party APIs only.
- **No unbounded autonomous money movement.** Every money action gated.

---

## 9. The 5-minute video — exact structure

Ruthless. No logo animation, no team intro, no background music.

| Time | Content |
|---|---|
| 0:00–0:30 | The problem, in money. "Merchants lose ₹X to Y. Here's why it's hard." |
| 0:30–1:15 | Architecture. Show the diagram. Name the components. |
| 1:15–3:15 | **Live run on the full batch.** Not a happy-path demo. Show it processing N records and producing the metrics report. |
| 3:15–4:00 | The numbers, with the baseline for comparison, and the exception list. |
| 4:00–4:40 | **A failure.** Show something breaking and degrading gracefully. |
| 4:40–5:00 | Limitations and what you'd build next. |

Speak over a screen recording. The two segments almost nobody else will include
are the batch run and the failure — those are the two the track bars explicitly
ask for.

---

## 10. Panel preparation

Assume a Razorpay engineer who has built this class of system. Rehearse answers
to:

- Why this architecture and not a single LLM call?
- What's your baseline and by how much did you beat it?
- What's your false-positive rate and what does a false positive cost?
- Show me a case it got wrong. Why did it get it wrong?
- What happens when the LLM returns malformed output mid-batch?
- What's your p99 latency and cost per record?
- How would this behave at 100× volume?
- Which part of this did the AI write, and where did it get it wrong?
- What would you delete if you had to halve the codebase?
- What's the failure mode you haven't solved yet?

That last one matters. Their engineering blog on a *losing* hackathon entry
emphasises that the team shipped anyway because the idea had clear customer
impact. Their culture rewards honest, shipped, bounded work over impressive
claims. Volunteering a known weakness reads as senior. Claiming there are none
reads as junior.

---

## 11. Anti-patterns that will lose

- A chatbot wrapper around an LLM with no measurement
- A percentage with no denominator
- A demo that only works on one hand-picked record
- A beautiful UI over an unmeasured backend
- An architecture diagram with boxes the operator can't explain
- Vector DB / RAG / multi-agent framework used because it's fashionable rather
  than because the problem needed it (their JD explicitly warns against forcing
  unnecessary stacks)
- Hiding failures
- A single squashed commit
- A README that describes intentions rather than results
