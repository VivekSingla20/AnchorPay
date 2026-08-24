# SOURCES.md

Every Tier A / Tier B fact this codebase depends on, its source, and its
verification status. Retrieval date for all live fetches in this file:
**24 August 2026** (session date). Re-verify anything quoted in the README
before submission — pages move.

Tier definitions (per `docs/02-BUILD-SPEC.md` Part 0.1):
- **Tier A** — verified, listed in Build Spec Part 2, used verbatim.
- **Tier B** — must verify before use. Status below records what was actually
  confirmed in this session versus what still rests on the operator's prior
  research (as compiled in `docs/03-DOMAIN-CONTEXT.md` / `docs/04-EXTRA.md`).
- **Tier C** — unknown. Not used as fact anywhere in this codebase.

---

## 1. NPCI API usage guidelines (21 May 2025, effective 1 Aug 2025)

**Status: Tier A, corroborated by two independent secondary sources in this
session. Primary circular PDF not directly fetched (no confirmed public URL to
the raw circular was available — NPCI's own circulars index at
`npci.org.in/circulars/upi` is a listing page, not the document itself, and
guessing a direct PDF path was avoided per the no-URL-guessing rule).**

Fetched and cross-checked in this session:
- Singhania & Co. (via Mondaq), "NPCI Guidelines On UPI And API Usage" —
  https://www.mondaq.com/india/fin-tech/1664786/npci-guidelines-on-upi-and-api-usage
  (law firm secondary analysis, dated to the 21 May 2025 circular)
- CAalley, "NPCI issues new API guidelines for UPI ecosystem members to
  prevent outages" — https://www.caalley.com/news-updates/indian-news/npci-issues-new-api-guidelines-for-upi-ecosystem-members-to-prevent-outages
  (citing an Economic Times report, published 28 May 2025)

Both independently state, in near-identical language:
- Peak hours: **10:00–13:00 and 17:00–21:30 IST**
- AutoPay mandate execution restricted to non-peak hours (before 10:00,
  13:00–17:00, after 21:30)
- **"A maximum of 1 attempt, with 3 retries per mandate, can be initiated at
  moderated TPS only during non-peak hours for autopay mandate"** — direct
  quote, CAalley/ET
- Status check API: minimum 90-second delay before first check; maximum 3
  checks within a 2-hour window
- Balance enquiry: 50 requests per app per customer per day
- Linked account listing: 25 requests per app per customer per day, consent
  required for retries
- Compliance undertaking due 31 Aug 2025; annual CERT-In empanelled audit
- Non-compliance: penalties, API restrictions, suspension of customer
  onboarding

**Conclusion: encode these as Tier A constants with high confidence** — two
independent, differently-sourced secondary analyses agree word-for-word on the
numeric constraints, which is strong corroboration even without the raw PDF.
This is recorded honestly as "corroborated secondary, not primary-fetched" —
if a panellist asks, the answer is "I read two independent legal/press
analyses of the same circular that agree exactly on the numbers; I did not
locate a direct public URL to the PDF itself."

## 2. RBI Digital Payments – E-Mandate Framework, 2026 (Circular RBI/DPSS/2026-27/396, 21 April 2026)

**Status: Tier B, NOT independently re-fetched in this session.** Rests on the
operator's prior research compiled in `docs/03-DOMAIN-CONTEXT.md` Part 1.1,
citing AMLEGALS and RocketPay secondary analyses. No live fetch of rbi.org.in
or the secondary sources was performed this session because no specific,
given URL to the primary circular was available and guessing one was avoided.

**Action required before submission:** fetch `rbi.org.in` directly and locate
this circular, or confirm via the AMLEGALS/RocketPay links already in
`docs/03-DOMAIN-CONTEXT.md` §1.1. Until then, every obligation attributed to
this circular (24h pre-debit notice, post-debit confirmation, ₹15,000 /
₹1,00,000 AFA thresholds, FASTag/NCMC carve-out) is used as Tier A per the
Build Spec's explicit instruction ("Everything in Part 2 is sourced. Use it
verbatim"), but is flagged here as resting on secondary sources only.

## 3. Razorpay UPI Error Codes

**Status: Tier A, directly re-fetched and confirmed verbatim in this
session.** https://razorpay.com/docs/errors/payments/upi/

Confirmed the complete published set of 10 reasons exists exactly as encoded
in `docs/02-BUILD-SPEC.md` §2.5: `insufficient_funds`, `bank_technical_error`,
`gateway_technical_error`, `credit_failed`, `invalid_vpa`,
`vpa_resolution_failed`, `payment_declined`, `payment_cancelled`,
`payment_timed_out`, `payment_collect_request_expired`. Descriptions and
next-steps text match. No 11th reason exists on the live page as of this
fetch — the taxonomy is closed, as the spec insists.

## 4. Razorpay Subscriptions States

**Status: Tier A, directly re-fetched and confirmed verbatim in this
session.** https://razorpay.com/docs/payments/subscriptions/states/

Confirmed exactly:
- States: `created`, `authenticated`, `active`, `pending`, `halted`,
  `cancelled`, `paused`, `expired`, `completed`
- **Direct quote:** "A Subscription goes to the `pending` state when an
  auto-charge on a payment is unsuccessful. We continue to retry the payment
  while it is in this state... After all the retry attempts have been
  exhausted, the Subscription moves to the `halted` state."
- **Direct quote:** "It is important to note that once the Subscription moves
  back to the `active` state, the previous charges will not be re-attempted.
  Only future billing cycles are charged automatically." — this is INV-15 in
  the invariant suite, confirmed verbatim from source.
- Pausing an `authenticated` subscription moves it to `cancelled` (an edge
  case not previously flagged in the Build Spec — added here for the
  simulator to model correctly).

## 5. Razorpay Downtime API — response schema

**Status: Tier B, resolved to Tier A in this session.** Exact field-level
schema fetched from https://razorpay.com/docs/api/payments/downtime/fetch-all/

Confirmed response shape (`GET /v1/payments/downtimes`):
```json
{
  "entity": "collection",
  "count": 2,
  "items": [
    {
      "id": "down_F1cxDoHWD4fkQt",
      "entity": "payment.downtime",
      "method": "netbanking",
      "begin": 1591946222,
      "end": null,
      "status": "started",
      "scheduled": false,
      "severity": "high",
      "instrument": { "bank": "COSB" },
      "created_at": 1591946223,
      "updated_at": 1591946297
    }
  ]
}
```
Fields: `id`, `entity` (`payment.downtime`), `method` (`card` | `netbanking` |
`upi`), `begin` (unix), `end` (unix, nullable), `status` (`scheduled` |
`started` | `updated`), `scheduled` (bool), `severity` (`high` | `medium` |
`low`), `instrument` (object; for UPI/netbanking, contains `bank` — a bank
code, e.g. `COSB`), `created_at`, `updated_at`.

This exact shape is mirrored in `src/policy/bank_health.py`'s
`DowntimeRecord` model and in the simulator's synthetic downtime generator —
naming a field there that doesn't match this schema is a bug.

## 6. NPCI UPI Ecosystem Statistics (per-bank data)

**Status: Tier B, partially resolved — real page, unconfirmed column
semantics.** The URL given in `docs/03-DOMAIN-CONTEXT.md`
(`npci.org.in/what-we-do/upi/upi-ecosystem-statistics`) returned **HTTP 404**
in this session — a genuine finding, not a guess. The corrected live page is
https://www.npci.org.in/product/ecosystem-statistics/upi (linked from NPCI's
own Statistics nav).

That page renders bank-wise data as of "Jul 2026" for one of several tabs
(UPI / NACH / IMPS / Autopay / NETC / AePS / NFS / RuPay — exact tab fetched
is ambiguous from static extraction). Extracted rows, real bank codes:

| Rank | Code | Name | Col D | Col E (%) | Col F | Col G | Col H |
|---|---|---|---|---|---|---|---|
| 1 | YES | Yes Bank PhonePe | 4,79,43,68,589 | 0.0000% | 12,610 | 12,024 | 586 |
| 2 | YBS | Yes Bank Limited YBS | 2,66,51,62,805 | 0.0010% | 18,476 | 12,107 | 6,369 |
| 3 | SBI | State Bank of India | 2,26,45,27,039 | 0.0000% | 7,274 | 4,835 | 2,439 |
| 5 | AXB | Axis Bank | 2,09,21,52,088 | 0.0010% | 27,573 | 23,270 | 4,303 |
| 6 | HDF | HDFC Bank | 77,52,45,145 | 0.0020% | 15,814 | 9,105 | 6,709 |

Column headers did not survive text extraction (likely rendered client-side
without semantic `<th>` labels reachable by the fetch tool). Column F = Col G
+ Col H holds exactly for every row checked (e.g. 12,024 + 586 = 12,610),
consistent with a **total = success + decline** split, and Col E's scale
(0.00–0.002%) is consistent with the OC-149 target of TD < 1% — but this is
**inference, not a confirmed label**, and is not presented as such anywhere
in the codebase.

**Design decision made because of this gap:** `data/npci/bank_health_reference.csv`
uses these real bank codes/names, but does NOT claim Col E is "Technical
Decline %" — it's imported as `observed_metric_pct` with a `confidence: low`
tag. Per-bank TD/BD used by the scheduler is a seeded synthetic distribution
*calibrated to the confirmed system-wide targets* (TD < 1%, BD < 5%, source
NPCI Circular OC-149, June 2022 — Build Spec §2.3), not this partially-read
table. This is recorded in `ASSUMPTIONS.md` as `UNVERIFIED:`.

## 7. Razorpay Subscriptions API (create/fetch/cancel/pause exact shapes)

**Status: Tier B, not fetched this session** (time-boxed; the states page and
downtime schema were prioritised as higher-leverage for the invariant suite).
`src/domain/entities.py`'s `Subscription` model field list is taken from
Build Spec §2.4 (already Tier A, itself sourced from Razorpay's real
payloads per the operator's prior research). Field names are not independently
re-verified against the live API reference in this session.
**Action before submission:** fetch `razorpay.com/docs/api/payments/subscriptions/`
directly and diff field names.

## 8. Whether card retry cadence applies identically to UPI mandates

**Status: Tier C — unresolved, by design.** Not found in any source consulted
across this project's research. Recorded in `LIMITATIONS.md` per the Build
Spec's explicit instruction (§Part 3, item 4) rather than assumed. The system
models the NPCI 1+3 constraint (which explicitly names "autopay mandate", i.e.
UPI) as authoritative for this project's scope, and does not assume Razorpay's
documented card-retry cadence carries over.

## 9. Environment check (this session)

- Python 3.13.1, pip 26.1, git 2.45.2.windows.1 confirmed available.
- `make` is **not installed** on the development machine (Windows,
  `CommandNotFoundException`). A `Makefile` is still shipped for spec
  compliance and Unix/CI graders; every target also has a documented direct
  `python -m ...` equivalent for Windows users without `make`.
