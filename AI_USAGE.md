# AI_USAGE.md

Build Spec Part 7 / Razorpay's own hiring framing: disclose AI usage, don't
hide it. This document is about how this codebase was BUILT. For how the
ENGINE ITSELF optionally uses an LLM at runtime (classify/intervene/copy
stages), see `EVALUATION.md`'s "LLM cost" section and `ARCHITECTURE.md`'s
pipeline description — that is a separate, narrower use of AI than the one
described here.

## Agent and model

Built with GitHub Copilot in agentic mode, running on Claude Sonnet 4.5,
inside VS Code, working directly against the repository's files and a
local terminal (no separate scratch environment). Every file in this repo
was written or edited by the agent; the operator's role was context
curation (the four documents below), review, and direction, not authoring
code line-by-line.

## How context was structured

Four documents were provided at the start of the session and treated as
binding, in this priority order when they conflict:

1. `CLAUDE.md` — the working agreement (read first, always).
2. `docs/02-BUILD-SPEC.md` — the operating contract: anti-hallucination
   protocol, verified constants, architecture, phased build order,
   compliance invariants. Wins any conflict with the other three.
3. `docs/03-DOMAIN-CONTEXT.md` — verified domain facts, source-tagged by
   tier (Primary / Journalism / Vendor / Community).
4. `docs/01-EVALUATION-CRITERIA.md` — how the submission is judged.

The agent additionally performed its own live web fetches at the start of
the build to verify Tier B facts before writing dependent code (Build Spec
Part 3 / Part 12 Phase 0) — recorded with retrieval dates in `SOURCES.md`,
not re-used from the operator's earlier research uncritically. Two
corrections came out of that step: the NPCI Ecosystem Statistics URL given
in the domain-context document had moved (404), and the Downtime API's
exact response schema (Razorpay's live docs) was fetched fresh rather than
inferred from prose.

## What was delegated vs. what a human must still own

**Delegated to the agent, in full:** domain modelling (entities/enums/
constants), the deterministic policy core (retryability gate, bank-health
scoring, the scheduling allocator, stopping rules), the independent
guardrail layer, the LLM-assisted stages with their deterministic
fallbacks, the synthetic data generator, all four baselines, the evaluation
harness, the full test suite, the failure-injection scenarios, the minimal
CLI, and every document in this repository including this one.

**Still the operator's to own, before this goes in front of a panel:**

- The two Tier B verification gaps flagged in `LIMITATIONS.md` items 1-2
  (the RBI circular's primary text, and Razorpay's Subscriptions API field
  shapes) — the agent flagged them as unresolved rather than silently
  treating operator-supplied secondary research as independently verified.
  Fetch and confirm before claiming these are checked.
- Every `UNVERIFIED:`-tagged number in `ASSUMPTIONS.md` is a modelling
  CHOICE, not a fact. An operator standing in a room must be able to say,
  for each one, "here is why I chose this number and here is what changes
  if it's wrong" — the rationale is written, but it must be internalised,
  not read off a screen.
- Deciding whether to actually enable `RECOVERY_ENGINE_USE_LLM=true` with a
  real API key for the demo video, and rehearsing what the LLM-assisted
  paths look like with real (not mocked) model output.

## Where the agent was wrong, and how it was caught

Every one of these was found by actually RUNNING the code against real
generated data — smoke-testing a handful of mandates, then the full batch —
not by re-reading the code and reasoning it was correct. That distinction
is the main lesson of this build:

1. **Notification-before-stop ordering.** The orchestrator's first draft
   called the stopping-rule check before the intervention/notification
   step for TERMINAL/INVESTIGATE/INTENTIONAL verdicts, so a customer whose
   mandate stopped for one of those reasons was never actually told why —
   the notification code was unreachable dead code for that entire branch.
   Caught by printing `attempts`/`notifications` counts over 15 real
   records and noticing `invalid_vpa` mandates showed `notif=0`.

2. **A regulatory notice could be silently blocked by an unrelated,
   optional heuristic.** The daily contact-budget guardrail (an
   UNVERIFIED, self-imposed "fewer, better-timed messages" rule,
   ASSUMPTIONS.md #A1) could block a `post_debit_confirmation` — a
   regulation-mandated notice, INV-07 — if it happened to fall on the same
   calendar day as an earlier pre-debit notice. Caught by running
   `guardrails/invariants.py`'s checker over a real 200-mandate batch and
   seeing non-zero INV-06/07 counts for the ENGINE itself, which should be
   structurally impossible. Fixed by exempting the three regulation-
   mandated notice types from the discretionary contact budget.

3. **Opt-out only blocked messages, not the underlying debit.** The
   guardrail checked opt-out before sending a notification but not before
   executing an attempt, so a debit scheduled while a customer was still
   opted in could still execute after they opted out — producing a debit
   with no valid notice on either side of it. Caught by a test built
   specifically to exercise Failure Injection #8 (opt-out arriving mid-
   lifecycle), which is exactly the scenario this class of bug hides in.
   Fixed by adding the same opt-out check to `validate_execution`.

4. **A same-time-of-day generator bug that would have hidden window logic
   errors.** The first synthetic-data generator produced every failure
   event at exactly the same time of day (only the calendar day varied),
   which meant every window/peak-hour interaction in the whole batch was
   identical — a real risk of shipping a scheduler that looks correct
   because it was never actually tested against most of the clock. Caught
   by reasoning through what a fixed-offset baseline would do against that
   data before running it, not after.

5. **Entity IDs were not reproducible even with a fixed seed.** Every
   domain entity defaults its id to `uuid.uuid4()`, which reads OS entropy,
   not the generator's own seeded random number generator — so re-running
   `data/generate.py --seed 42` produced the same CONTENT but different
   IDs every time, silently breaking the "seed everything" reproducibility
   requirement. Caught by a test asserting exact reproducibility, which the
   agent then made pass by having the generator mint every id itself from
   its seeded generator instead of accepting entity defaults.

6. **A simulated "terminal" NPCI code wasn't actually guaranteed to fail
   in simulation.** `Z8` (structurally cannot succeed) was correctly
   classified as terminal by the policy layer, but the outcome simulator
   only force-failed `invalid_vpa`, not Z8-tagged attempts — meaning a
   baseline that illegally retried a Z8 case could, by chance, "succeed" in
   the simulation, undermining the "retries wasted on terminal codes"
   metric's honesty. Caught while writing that exact metric and asking
   whether the simulator's behaviour actually matched the claim.

7. **A heuristic that looked like it did nothing, because the test data
   never gave it a chance to matter.** The bank-health-aware scheduling
   heuristic showed a byte-identical ablation result on/off. Rather than
   concluding the heuristic was worthless, the agent traced it to the
   allocator's short (~2-day) candidate search horizon almost never
   intersecting a handful of scattered one-off synthetic downtime windows,
   and fixed the TEST DATA (a clear, honestly-labelled recurring pattern)
   rather than quietly deleting the heuristic. Both are legitimate
   findings and both are written up (`DECISIONS.md` ADR-010,
   `ASSUMPTIONS.md` #A10) — the honest version of this is "a modest,
   demonstrable lift, on data built to demonstrate it," not "proven to help
   on real traffic."

8. **Windows-specific numpy build issue.** `numpy<2` has no prebuilt wheel
   for Python 3.13 on Windows and silently fell back to an experimental,
   crash-warning MinGW source build. Caught immediately from the pip
   install's own printed warning, not from a later failure — fixed by
   relaxing the pin to `numpy>=2.0,<3`, which ships a proper wheel.

9. **Broken IST-aware time constants in the test suite itself.** Several
   tests computed a "peak hour" / "permitted window" reference timestamp
   using raw UTC modulo arithmetic (`ts - (ts % 86400) + hour*3600`), which
   silently ignores IST's +05:30 offset — the exact bug already fixed once
   in the data generator, re-introduced independently in test code. Caught
   because the first full test run failed with an IST timestamp nowhere
   near the intended hour. Fixed by routing every such computation through
   `src.domain.timeutils`, and centralising the two reference constants in
   `tests/factories.py` so this class of bug can only be fixed once, not
   independently in every test file that needs a reference time.

## What this pattern says about reviewing agent-built systems

None of the nine bugs above were found by re-reading code and confirming it
looked right — every one was found by constructing real data and running
the system against it, then treating a surprising number (a `notif=0` that
should be `1`, an invariant count that should be `0` but wasn't, an
ablation delta that should be nonzero but was exactly zero) as a lead to
chase rather than noise to explain away. That is the operator's actual job
when supervising an agent on a system where a "confident wrong fact is
worse than an admitted gap" (`docs/02-BUILD-SPEC.md` Part 0): run it, don't
just read it.

## LLM runtime cost (the engine's own optional AI usage, not this build)

See `EVALUATION.md`'s "LLM cost" section for the current, committed numbers
(`RECOVERY_ENGINE_USE_LLM=false`, Rs 0.00, 0 tokens, 0 calls — the
deterministic fallback path for every classify/intervene/copy decision).
Enabling `RECOVERY_ENGINE_USE_LLM=true` with a real `ANTHROPIC_API_KEY` and
re-running `python -m eval.run_eval` would report real token/cost figures
in the same section, satisfying Razorpay Agent Studio principle 7
("transparent pricing / cost") for the engine's own operation — this was
not done for the committed submission, to keep `make eval` reproducible
without secrets on a clean clone.

## A note on the commit history

Real, incremental commits with meaningful messages, staged in the same
dependency order the code was actually written in (constants and tests
first, then domain, policy, guardrails, data, baselines/eval, the
LLM-assisted stages, the test suite, failure injection, the interface,
then documentation) — not one squashed commit. This was built in a single
continuous agentic session rather than across the two weeks a human team
might take, so the commit boundaries reflect logical build PHASES, not
calendar days. Said plainly here rather than left to look like something
it isn't.

