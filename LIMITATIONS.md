# LIMITATIONS.md

What doesn't work, what's stubbed, what's out of scope, and what would be
fixed first with more time. Volunteering these is worth more than hiding
them (Build Spec Part 14).

## Verification gaps (Tier B/C items not fully closed this session)

1. **RBI Circular RBI/DPSS/2026-27/396 was not independently re-fetched.**
   Every obligation attributed to it (24h pre-debit notice, post-debit
   confirmation, AFA thresholds, FASTag/NCMC carve-out) rests on the
   operator's prior research (`docs/03-DOMAIN-CONTEXT.md`), not a primary
   fetch performed in this build session. See `SOURCES.md` §2.
   **Action before submission:** fetch `rbi.org.in` directly and confirm.

2. **Razorpay's Subscriptions API create/fetch/cancel/pause exact field
   shapes were not independently re-verified.** `Subscription`'s field list
   (`src/domain/entities.py`) is taken from Build Spec §2.4, itself sourced
   from the operator's prior research, not re-diffed against the live API
   reference this session. See `SOURCES.md` §7.

3. **Whether Razorpay's documented card retry cadence applies identically
   to UPI mandates is genuinely unresolved** (Domain Context §7 item 3).
   This project does not assume it does — it models the NPCI 1+3 constraint
   (which explicitly names "autopay mandate") as authoritative for UPI, and
   never imports a card-specific cadence. If asked on this directly: "I
   checked; the docs describe the cadence for cards; I could not confirm
   parity for UPI, so I modelled UPI's own NPCI-stated constraint instead
   and did not assume the two are the same."

4. **NPCI's per-bank Ecosystem Statistics page's own decline-rate column
   semantics were not confirmed.** The page is real and was fetched live
   this session, but its column headers did not survive automated
   extraction — see `SOURCES.md` §6 and `data/npci/README.md`. The bank
   IDENTIFIERS used in this project's reference table are real; the
   PERCENTAGES are this project's own calibrated-synthetic estimate anchored
   to the confirmed system-wide OC-149 targets, not scraped per-bank data.

## Structural simplifications (known, deliberate, in scope of what this build attempts)

5. **A mandate's failure reason is held constant across its retry episode**
   in the simulator (ASSUMPTIONS.md #A8). A real mandate could in principle
   fail with a DIFFERENT reason on a later attempt (e.g. `insufficient_funds`
   on attempt 1, then `bank_technical_error` on attempt 2). Modelling that
   transition would require a per-attempt causal model this project has no
   real data to calibrate — deliberately out of scope rather than guessed.

6. **The outcome-success model (`src/execute/simulator.py`) is a
   calibration for demonstration, not an empirical success-rate figure.**
   No public labelled dataset of UPI AutoPay retry outcomes exists (Domain
   Context §7 item 2) to calibrate against. Every recovery number in
   `EVALUATION.md` is therefore a property of THIS simulation's assumptions,
   clearly labelled as such — not a claim about real-world recovery rates.

7. **Guardrail approval tokens are a plain SHA-256 digest
   (`guardrails/validator.py`'s `_mint_token`), not an HMAC signed with a
   server-held secret.** This is sufficient to prove the *shape* of "the
   executor only runs what the independent guardrail approved at this exact
   moment" for a simulation, but a real deployment must use an HMAC (or a
   KMS-backed signature) keyed to a secret only the guardrail service holds,
   so a compromised caller cannot forge a token itself.

8. **The dark-pattern screen (`guardrails/dark_pattern_screen.py`) is a
   deliberately narrow, regex-based screen over six named categories**
   (India's Guidelines for Prevention and Regulation of Dark Patterns,
   2023), not a general-purpose NLP classifier. It reliably catches the
   phrasings it's built to catch (tested in `tests/test_guardrails.py`) and
   can miss a creatively-reworded dark pattern that doesn't match any
   pattern in its list. Extending the pattern list is a one-line,
   independently-testable change; it was kept narrow deliberately, per
   Build Spec §0.4's defensibility test — a screen whose every rule can be
   explained beats a broader one nobody fully understands.

9. **`RECOVERY_ENGINE_USE_LLM` defaults to `false`, and the committed
   `EVALUATION.md` was generated with it off.** This is a deliberate
   reproducibility choice (Build Spec: "test the clean-clone path... no
   secrets"), not an oversight — see `AI_USAGE.md` for the LLM-enabled cost
   projection. Consequence: the LLM-assisted classify/intervene/copy/
   narration paths (`intervene/escalation_brief.py`, `eval/batch_summary.py`
   included) are exercised by `eval/scenarios.py` and unit tests using mocked
   responses, not against a real model's actual output distribution, in
   this submission's committed numbers.

## Explicitly out of scope (Tier 3, "mention in future work, don't build" —
Domain Context Part 5)

10. **Multi-rail fallback** (UPI → card → payment link). `InterventionType.
    ALTERNATE_RAIL_SUGGESTION` and its notification template exist in the
    enum/template set for documentation of the design space, but no
    selector logic currently chooses it.
11. **A learned/ML model in place of the rule-based classifier or
    allocator.** This project doesn't have the labelled data to train one,
    and says so rather than faking a model (Domain Context Part 5, Tier 3).
12. **Real-time NPCI TD/BD streaming.** The reference table
    (`data/npci/bank_health_reference.csv`) is a static file, refreshed
    manually, not a live feed.
13. **A merchant-facing configuration UI** for the grace-period allowlist,
    contact budget, or MCC carve-out list — these are code constants in
    `regulatory_constants.py`, editable directly, not exposed through any
    interface.
14. **Multi-language notification copy.** All templates and LLM prompts in
    `intervene/copy_generator.py` are English-only.

## Environment note

`make` is not installed on the Windows machine this was built on. A
`Makefile` is still shipped for spec compliance and Unix/CI graders; every
target has a documented direct `python -m ...` equivalent in `README.md` for
Windows users without `make` (or use WSL/Git Bash, where the Makefile works
as-is).
