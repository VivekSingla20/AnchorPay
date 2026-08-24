# CLAUDE.md

Project: **UPI AutoPay Mandate Recovery Engine**
Submission for the Razorpay AI Buildathon. Deadline **5 September 2026**.

---

## Read these before doing anything

| File | What it is | When to read |
|---|---|---|
| `docs/02-BUILD-SPEC.md` | **The operating contract.** Anti-hallucination protocol, verified constants, architecture, phased build plan, compliance invariants. | **Read in full at the start of every session.** Re-read Part 0 whenever you're unsure. |
| `docs/03-DOMAIN-CONTEXT.md` | Verified facts about UPI AutoPay, NPCI/RBI rules, Razorpay's stack, global prior art, real user behaviour. Every fact is source-tagged. | Reference. Read Parts 1–2 once; look up the rest as needed. |
| `docs/01-EVALUATION-CRITERIA.md` | How this submission is judged and what a winning entry looks like. | Read once at the start. Re-read before writing the README or planning the video. |

If these conflict, `02-BUILD-SPEC.md` wins.

---

## The rules that override everything

1. **Never state an unverified fact as established.** `02-BUILD-SPEC.md` Part 0
   defines a three-tier fact system. Tag which tier you're in. Facts not in
   Tier A or B are unknown — ask, mark `UNVERIFIED:`, or design around them.
   Never invent regulations, API fields, error codes, or statistics.

2. **When unsure, stop and use the §0.3 uncertainty format.** Do not guess and
   continue.

3. **The defensibility test.** Before adding anything, ask whether the operator
   can explain why it exists, in 90 seconds, from memory, under hostile
   questioning. If no, don't add it. Smaller and fully understood beats larger
   and partially understood.

4. **Deterministic where money moves.** No LLM call decides legality, timing,
   amounts, consent, or stopping. LLMs classify, select from enumerated options,
   and draft copy. Nothing else.

5. **Stop at every phase gate** (`02-BUILD-SPEC.md` Part 12) and report. Do not
   run ahead.

---

## Working agreement

- Keep `DECISIONS.md` current as you go — it becomes the operator's interview
  answers. Retrofitting it produces something nobody can defend.
- Comment non-obvious lines with *why*, not *what*.
- Real incremental commits with meaningful messages. Never squash.
- Log your own errors in `AI_USAGE.md`, including ones the operator caught.
- If the operator asks for scope you think is wrong, say so directly and ask
  what comes out in exchange.

  //if you want something else analyse EXTRA.md too , might you find your answer.