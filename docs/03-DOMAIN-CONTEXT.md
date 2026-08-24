# CONTEXT CORPUS — UPI AutoPay Mandate Recovery Engine

Companion to `SPEC.md` (the build prompt). Feed both to your agent.

`SPEC.md` says *what to build*. This file says *what is true about the world*.

**Compiled:** 24 August 2026. Every link was reachable on that date. Re-verify
anything you put in the README — pages move.

---

## HOW TO USE THIS FILE

Paste it as context alongside the build prompt. When the agent needs a fact
about the domain, it comes from here or it gets flagged as unknown.

**Reliability tiers — respect these:**

| Tier | Meaning | Use |
|---|---|---|
| **P** | Primary — regulator, NPCI, or Razorpay's own docs | Cite directly |
| **J** | Journalism — named outlet, named reporter | Cite with attribution |
| **V** | Vendor — a company selling the solution | Directionally useful, **never** a benchmark you claim |
| **C** | Community — forums, practitioner blogs | Colour and hypotheses only, never a number in the README |

Vendor numbers in this space are marketing. Stripe says 55–57% recovery; an
independent audit of 200+ of their accounts found 25–35%. **If you quote a
recovery benchmark in your README without saying which tier it came from, a
payments engineer will catch it.**

---

# PART 1 — PRIMARY SOURCES

## 1.1 Regulatory (fetch these first — SPEC Tier B)

| Source | Why it matters |
|---|---|
| NPCI — https://www.npci.org.in/ | Circular of **21 May 2025**, *Guidelines on usage of UPI and API*, effective **1 Aug 2025**. Contains the entire retry-budget and execution-window constraint set. **The single most important document for this project.** |
| RBI — https://www.rbi.org.in/ | **Digital Payments – E-Mandate Framework, 2026**, Circular **RBI/DPSS/2026-27/396**, dated **21 April 2026**. Issued under s.10(2) r/w s.18, Payment and Settlement Systems Act 2007. Consolidates 8 circulars (2019–2024). |
| https://www.npci.org.in/what-we-do/upi/upi-ecosystem-statistics | Per-bank TD/BD, uptime, MCC classification. **Your real dataset.** |
| NPCI Circular **OC-149**, June 2022 | Sets TD target <1%, BD target <5% |

**Secondary analyses of the circulars** (use to orient, then read the primary):
- https://www.scconline.com/blog/post/2025/07/30/upi-changes-starting-august-1-ncpi-guidelines-upi-api-usage-2025/ — SCC Online legal analysis
- https://www.mondaq.com/india/fin-tech/1664786/npci-guidelines-on-upi-and-api-usage — Singhania & Co. law firm breakdown, has the clearest per-API table
- https://amlegals.com/upi-autopay-and-recurring-payments-compliance-checklist-under-rbis-e-mandate-framework-2026/ — AMLEGALS compliance checklist on the 2026 framework
- https://www.caalley.com/news-updates/indian-news/npci-issues-new-api-guidelines-for-upi-ecosystem-members-to-prevent-outages — quotes the circular's retry language directly
- https://www.rocketpay.co.in/blog/rbi-e-mandate-recurring-payments-15000 — merchant-side reading of the 2026 obligations

## 1.2 Razorpay technical corpus

**Read every one of these before writing code.**

| URL | Contains |
|---|---|
| https://razorpay.com/docs/errors/payments/upi/ | **The authoritative UPI error reason list.** Ten reasons. Do not add to it. |
| https://razorpay.com/docs/errors/payments/list/ | Cross-method error codes |
| https://razorpay.com/docs/errors/error-codes | Error object anatomy: `code`, `description`, `field`, `source`, `step`, `reason`, `metadata` |
| https://razorpay.com/docs/build/browser/assets/images/payments_error_reasons.xlsx | **Downloadable full error-reason spreadsheet.** Get this. |
| https://razorpay.com/docs/payments/subscriptions/states/ | The state machine: `active → pending → halted` |
| https://razorpay.com/docs/payments/subscriptions/test/ | Test-mode charge simulation. Confirms 4 consecutive failures → halted |
| https://razorpay.com/docs/webhooks/subscriptions/ | Full event list + real payloads |
| https://razorpay.com/docs/subscriptions/notifications/ | Email/SMS/webhook notification triggers |
| https://razorpay.com/docs/api/payments/downtime/ | **Downtime API** — your bank-health signal |
| https://razorpay.com/docs/api/ | API reference root |
| https://github.com/razorpay/razorpay-mcp-server | MCP server. Go, MIT. Remote: `mcp.razorpay.com/mcp`. Docker: `razorpay/mcp`. Ships `.claude/skills/`, `.cursor/`, `AGENTS.md` |
| https://razorpay.com/blog/tackling-upi-payment-failures-with-razorpay/ | NPCI codes Z9, U28, U30, U69, Z7, Z8 explained by Razorpay |
| https://razorpay.com/blog/upi-autopay-vs-card-e-mandates/ | Razorpay's own comparison. Note: card AFA rules pushed failures to 20%+ in some categories, which opened the door for AutoPay |

## 1.3 Razorpay engineering — read for architecture and voice

| URL | Why |
|---|---|
| https://dev.to/razorpaytech/meet-bumblebee-agentic-ai-flagging-risky-merchants-in-under-90-seconds-2nlf | **Their reference multi-agent architecture.** Planner → parallel Fetchers → Analyzers. Authors: Ankur, with @parin-k, @sumit12dec, @yashshree_shinde |
| https://engineering.razorpay.com/meet-bumblebee-the-multi-agent-ai-architecture-that-changed-fraud-detection-at-razorpay-c2b6d5704f51 | Longer Medium version |
| https://engineering.razorpay.com/project-viveka-from-30-minute-investigations-to-90-second-ai-analysis-e49ec9db2638 | Oncall Agent. LangGraph. MTTI framing. Author: Anuj Gupta |
| https://engineering.razorpay.com/our-obsession-with-merchant-experience-breaking-the-risk-review-black-box-7fa38d699ef1 | Risk review UX. JSON-schema-driven checklists, dynamic templating, 72h SLA auto-acknowledgement. Author: Sumit Raj |
| https://razorpay.com/blog/razorpay-agent-studio-principles-guardrails-and-merchant-control/ | **The nine principles. Effectively your rubric.** |
| https://dev.to/razorpaytech | Their whole DEV feed |
| https://engineering.razorpay.com/ | Their Medium |

**Bumblebee's verified numbers, for framing yours the same way:**
10,000–12,000 manual reviews/month × ~4 min each = 700–800 human hours/month.
Accuracy 88% → 99%+. Latency under 90 seconds.
**Shape of the claim: volume × time × accuracy delta × latency.** Copy it.

Bumblebee's origin insight, in their words: the human risk team didn't have one
person doing everything — they had specialists working in parallel who then
compared notes. The architecture mirrors the org chart. **Ground your
decomposition in a real workflow the same way, and say so.**

---

# PART 2 — THE SCALE DATA

## 2.1 The headline source [J]

**Business Standard, Ajinkya Kawale, 7 September 2025**
https://www.business-standard.com/finance/news/upi-autopay-revocations-hit-20-mn-monthly-over-low-customer-balances-125090700500_1.html

This is your best single citation. Verified contents:

- **20 million+ AutoPay mandates revoked every month** on insufficient balance
- **Business declines across the top 50 banks averaged nearly 74%** for AutoPay
  transactions — rejections for non-technical reasons, chiefly insufficient funds
- Debt collection agencies did **151 million UPI transactions worth ₹77,000
  crore in August [2025] alone**
- Remitter banks logged **50m+ new mandate registrations in July 2025**, up from
  26m in July 2024
- **Mandate executions: 808 million in July 2025**, up from 392 million a year prior
- ₹15,000 cap for most MCCs; **₹1 lakh for securities brokers, dealers, and insurance**
- NPCI did not respond to the reporter's email

**Three on-record-anonymous quotes worth using:**

> "The revocations stand at 20 million every month… There is a debit execution
> failure which is because there is not enough money in the user's bank account.
> There are many cases of micro investment mandates, like for an SIP or loan
> repayments." — *source with knowledge of the matter*

> "The creation of an AutoPay mandate is generated during the loan disbursement
> journey, where registrations are successful. However, the execution fails due
> to insufficient funds in the user's bank account where the mandate was
> created." — *second payments executive*

That executive added that **analysing the payment error codes would further hint
at the major reasons for declines.** That sentence is, more or less, your
project's thesis stated by an industry insider. Quote it.

> "Users get a notification from the merchant or the payments app before a
> mandate is executed and money is debited. Users can cancel the mandates from
> the app they created it in, which may also get counted as a revoked payment."
> — *third executive at a top UPI company*

**That third quote is a measurement trap.** The 20m "revocations" figure
conflates *execution failures* with *deliberate user cancellations*. Acknowledge
this in your `ASSUMPTIONS.md` — it shows you read critically rather than
grabbing a big number. A revocation that was a deliberate cancellation is not
recoverable revenue and your engine must not chase it.

## 2.2 Supporting scale figures

| Figure | Value | Tier |
|---|---|---|
| UPI monthly volume, June 2026 | 22,716.07m (down 2.09% from 23,201.93m in May 2026) | J |
| UPI July 2025 record | 1,947 crore txns, ₹25.1 lakh crore | J |
| Banks live on UPI, June 2026 | 731 | J |
| Top PSP banks by volume | Axis Bank, Yes Bank | J |
| System TD trend | 8–10% (2016) → 0.7–0.8% (2025) | P/J |
| P2M limit | ₹10 lakh/day for selected verified categories (from 15 Sept 2025) | J |

**NACH historical bounce rates** — the adjacent rail, useful as a sanity
reference and a possible proxy dataset. NPCI publishes NACH debit bounce rates
monthly. August 2021: 32.98% of 87.68m transactions failed by volume, 26.82% by
value. Peak was **over 45% in June 2021**. ICRA's Anil Gupta commented on the
trend. Source: Business Standard, Subrata Panda, 9 Sept 2021 —
https://www.business-standard.com/article/finance/auto-debit-payment-failures-ease-in-august-shows-npci-data-121090900013_1.html

## 2.3 Real MCC codes from NPCI [P]

From the NPCI UPI Merchant Category Classification (Sep '24), classified by
approved transaction volume. **Use these in your synthetic generator — they're
real and they're ranked.**

**High-transacting (top 10 MCCs):** 5411 groceries/supermarkets · 5814 fast food
· 5812 eating places · 4814 telecom · 5541 service stations · 5816 digital goods:
games · 5912 drug stores/pharmacies · 5462 bakeries · 4900 utilities · 5993 cigar

**Medium (next 10):** 5451 dairies · 5311 department stores · **7322 debt
collection agencies** · 5813 drinking places · 5441 confectionery · 5422 meat
provisioners · 5921 liquor · 5262 online marketplaces · **6211 securities brokers
and dealers** · 7622 electronics repair

**Other:** 5732 electronics · 9399 govt services · 7230 beauty/barber · 5137
clothing · 4112 passenger railways · 5331 variety stores · 5691 clothing · 4121
taxi-cabs · 7011 lodging

MCC descriptions follow **ISO 18245:2003**.

**Why this matters concretely:**
- **6211** carries the ₹1 lakh AFA ceiling, not ₹15,000 — a different branch
- **7322** confirms debt collection runs on these rails at scale
- **4784** (NETC FASTag) and **7412** (RuPay NCMC) get the pre-debit
  notification carve-out
- **4900** and **4814** are the classic recurring-billing categories

---

# PART 3 — WHAT USERS ACTUALLY EXPERIENCE

## 3.1 An honest note on forums

I searched Reddit repeatedly — r/developersIndia, r/IndiaInvestments,
r/personalfinanceindia — across multiple phrasings and found **no substantial
indexed thread** on UPI AutoPay mandate failure mechanics. Same for X: nothing
of technical substance surfaced. Either it isn't there or it isn't indexed
where I can reach it.

**Do not let your agent invent forum quotes to fill this gap.** If you want
primary user voice, go read the threads yourself: search Reddit directly for
`UPI autopay failed`, `SIP mandate failed`, `autopay bounce charges`, and check
TechnoFino, which is where Indian banking power-users actually congregate.

What I did find is below, and it's genuinely useful.

## 3.2 The adversarial user — TechnoFino [C]

https://technofino.in/community/threads/upi-mandate-failure-due-to-low-balance-consequences.31074/

A real user, describing a deliberate strategy:

> "I have been setting up UPI mandates for some subscriptions from an account
> which has very low balance (<100). This is intentional, if I forget at any
> point of time to stop the mandate in future, the mandate should fail, on the
> other hand if I want the mandate to go through, I will have enough balance.
> Additionally, no rogue / buggy code of any app/service cannot mistakenly
> charge me more."

Another contributor on penalties:

> "No penalty charges except loan repayment or EMI payment. Other merchant UPI
> AutoPay no penalty charges. Also note - this fees are charged by banks. If you
> have good relation with banks then banks will reverse the charges."

**This is the most strategically valuable finding in the whole corpus.**

Some users deliberately keep the mandate account empty. They are using
`insufficient_funds` as a **cancellation mechanism** because the actual
cancellation flow isn't trusted. That means:

1. A material slice of `insufficient_funds` failures are **intentional
   non-payment wearing a technical costume.** Chasing them wastes retries,
   annoys the customer, and is arguably a dark pattern — you'd be overriding an
   expressed preference the customer signalled through the only lever they trust.
2. Your engine should attempt to **detect this pattern** — persistently low
   balance across cycles, or failure immediately after a trial-to-paid
   conversion — and route those to a *cancellation-confirmation* path, not a
   recovery path.
3. That's a genuinely novel contribution. No global dunning tool models "the
   customer is using failure as a cancel button," because in card-land the
   customer just cancels.

**Build this. Call it intent inference. It will be the most interesting thing
you say in the interview**, and it aligns exactly with Razorpay's published
principle that a customer's "no" must be respected without an escalation loop.

## 3.3 The confused user — Paytm's own troubleshooting content [V]

https://paytm.com/blog/bill-payments/upi-autopay/troubleshooting-common-issues-what-to-do-when-upi-autopay-fails-to-process/
https://paytm.com/blog/bill-payments/upi-autopay/what-happens-if-your-upi-autopay-transaction-fails-a-comprehensive-troubleshooting-guide/

An illustrative case they publish: "Rohan" gets an AutoPay failure notice on an
insurance premium. Balance is fine. Mandate is active. He calls his bank. It
turns out to be a temporary technical issue at the *insurance company's* payment
gateway. He's told to wait 24 hours and retry manually, which works.

The lesson they draw — *sometimes the issue isn't with your account but with
external systems* — is exactly what your bank-health-aware classifier
operationalises. The customer had no way to know. **Your system does.** A
notification that says "this failed on the bank's side, not yours — we'll retry
automatically, no action needed" is materially different from the generic "your
payment failed" that everyone sends, and it prevents the customer from
cancelling in confusion.

**Build differentiated notification copy by failure source. It's cheap and
nobody does it.**

## 3.4 The SIP investor [J]

https://www.zoomnews.in/en/news-detail/is-your-sip-safe-why-monthly-investment-payments-fail-and-how-to-fix-it.html

Reported causes of SIP failure: insufficient balance (most common — investors
deposit on the same day the SIP debits); stale or inactive mandates after a bank
change, mobile number change, or **bank merger**; and 2026 reports of SIP
failures tied specifically to UPI AutoPay, attributed to UPI infrastructure
changes and traffic volume.

Notably: investors **frequently ignore the automated notifications** sent by
payment apps or banks.

Three things to encode:
- "Deposits on the same day the SIP debits" is a **timing** problem, not a funds
  problem. Same-day retry fails; next-morning retry may succeed.
- Bank mergers invalidating mandates is a real, unglamorous failure class.
- If notifications are routinely ignored, **notification volume is not the
  lever — notification quality and timing are.** More nudges make it worse.

---

# PART 4 — GLOBAL PRIOR ART

This is the body of knowledge on this exact problem. **Know it, then show why it
doesn't transfer.** That contrast is your strongest technical argument.

## 4.1 Stripe Smart Retries [P — Stripe's own engineering blog]

https://stripe.com/blog/how-we-built-it-smart-retries
https://stripe.com/docs/billing/revenue-recovery/smart-retries

Verified from Stripe:

- ML trained on **billions of data points** across the Stripe network
- Predicts optimal retry timing rather than using a fixed schedule
- **Recovered subscriptions continue on average for seven more months** — "like
  acquiring a whole new subscriber"
- Stripe **does not retry** for: non-retryable issuer decline codes, unavailable
  payment methods, detached connected accounts
- Retry payment-method ordering: `subscription.default_payment_method` →
  `subscription.default_source` → `customer.invoice_settings.default_payment_method`
  → `customer.default_source`
- Stripe reports Smart Retries recovers **9% more revenue than fixed-schedule
  retries**

Stripe's framing of the core problem, which is also yours:

> "If a subscription payment fails, sometimes it makes sense to retry it almost
> immediately, such as in the case of a technical payment failure. Other times,
> the optimal time for a retry might be the next day — maybe the customer has
> replenished their bank account by then — or even the next week."

## 4.2 ⭐ THE COMPARISON THAT MAKES YOUR PROJECT

**Stripe Smart Retries defaults to roughly 8 attempts over two weeks**, ML-timed,
halted on hard declines. [J/V — digitalapplied, corroborated across sources]

**You get 1 attempt + 3 retries. Total. Inside three disjoint daily windows.**

Put that side by side in your README:

| | Stripe (global cards) | UPI AutoPay (India) |
|---|---|---|
| Attempt budget | ~8 over 2 weeks | **4, hard cap** |
| Timing freedom | Any time | **3 windows only** |
| Card updater available | Yes (fixes 30–50% of hard declines) | **No equivalent** |
| Funds guaranteed at mandate setup | Yes (bank-managed) | **No (stateless)** |
| Consequence of over-retrying | Network penalties | **API restrictions, onboarding embargo** |

**The argument:** with half the attempts and a fraction of the timing freedom,
*each individual attempt has to be far better chosen*. ML over billions of
transactions is not available to you and would be overkill for a four-slot
allocation. **Constraint-aware allocation is the right tool for this problem
shape, and it's a different tool than Stripe's.** That is a real engineering
opinion, defensible in a room, and it's why your project isn't "Stripe but
worse."

## 4.3 Recovery benchmarks — and why they conflict

**Read this section before you write a single number in your README.**

| Claim | Source | Tier |
|---|---|---|
| 55–57% of failed payments recovered | Stripe marketing | V |
| **25–35% actual**, audited across 200+ B2C Stripe Billing accounts, >$500M failed volume | Redux Payments | V (but adversarial to Stripe, so more credible) |
| 34.6% B2C recovery | Recurly published benchmarks | V |
| "B2B businesses had higher recovery rates than their B2C counterparts across all decline reasons" | Recurly, direct quote | V |
| Basic retries recover 15–25% | Finsi | V |
| Dedicated tools claim 55–80% | multiple | V |
| 72% at-risk save rate, 141-day median post-recovery lifetime, 38% of lifetime occurring after recovery | Recurly *2024 State of Subscriptions* | V |
| 70% involuntary churn recovery; 42% email/SMS-only | Churnkey *State of Retention 2025* | V |
| 20–40% of all SaaS churn is involuntary | Recurly + ProfitWell | V |
| Insufficient funds = 40%+ of online declines | EBANX | V |
| 26–30% of failures are insufficient-funds soft declines resolving in **2–5 business days once payroll completes** | Beast Insights | V |
| ~7.9% payment failure rate | Spreedly aggregated | V |
| Failed payments cost businesses **~$118.5 billion/year globally** | PYMNTS + Checkout.com | V |
| ~40% of cards replaced yearly | multiple | V |
| Multi-channel cuts involuntary churn up to 34% vs email-only | digitalapplied | V |
| Dunning emails recover most in first 72 hours, decay sharply after 2 weeks | digitalapplied | V |

**The Stripe 55% vs. audited 25–35% gap is a 20-point spread on the single most
cited number in the industry.** Put that in your README as a note on why you
report your own measured numbers rather than benchmarking against published
ones. It's an easy, honest, credibility-building paragraph.

Patrick Campbell (ProfitWell, now Paddle):

> "Most SaaS companies don't even know how much they're losing until they start
> measuring it separately from voluntary churn."

## 4.4 ⭐ THE PAYROLL-CYCLE INSIGHT

The strongest transferable idea in the entire global literature:

> Approximately 26–30% of all failures are insufficient-funds soft declines that
> **resolve within 2–5 business days once a customer's payroll cycle completes.**

And Stripe: *"maybe the customer has replenished their bank account by then."*

Now localise it. **Indian salary credit is heavily concentrated at month-end and
the first few days of the month.** Combine that with the verified fact that
`insufficient_funds` dominates AutoPay failures (74% BD, per §2.1) and you get:

**Salary-cycle-aware retry timing is the single highest-leverage feature you can
build, and no global tool encodes it, because no global tool has a reason to
model Indian salary cycles.**

Concretely: if a mandate fails on the 25th with `insufficient_funds`, retrying on
the 26th is close to worthless. Retrying in the 1 PM–5 PM window on the 1st or
2nd is a completely different proposition.

**Caveats to state honestly:**
- Treat the salary-cycle distribution as `UNVERIFIED:` unless you find hard data
- It doesn't hold for the self-employed, gig workers, or agricultural income
- It interacts with the billing anniversary — a mandate that bills on the 3rd is
  already well-timed and has no headroom
- It's a *hypothesis your harness can test*. Run with and without. Report the
  delta. If it doesn't help, that's a finding too.

## 4.5 The hard/soft decline doctrine

Universal across every source, and it maps onto your terminal-code gate:

- **Soft declines** (insufficient funds, network timeout) are temporary and
  recoverable by retry.
- **Hard declines** (stolen card, closed account) are permanent and **must never
  be retried.** Retrying a hard decline **increases your merchant risk profile
  with processors and can trigger monitoring programs and account restrictions.**

In UPI terms: `Z8` (per-transaction limit exceeded) and `invalid_vpa` are your
hard declines. **The penalty structure is stricter than card networks** — NPCI's
stated consequences include API restrictions and a customer-onboarding embargo,
not just fees.

## 4.6 The Indian practitioner view [C but high-quality]

https://productgrowth.in/insights/fintech/upi-autopay-guide/
https://productgrowth.in/insights/fintech/upi-payment-success-rates/

Best India-specific practitioner writing I found. The framing of the trilemma:

> "A single failed payment can cascade: if you don't retry, the user's
> subscription lapses. If you retry too aggressively, you violate RBI mandate
> rules. If you retry silently, the user doesn't know their subscription broke."

That is a three-way trade-off — **revenue vs. compliance vs. transparency** —
and stating it explicitly in your `ARCHITECTURE.md` frames your objective
function properly. Most submissions will optimise revenue alone.

Also from the same source:

> "The activation moment for UPI AutoPay is when the first payment succeeds. But
> the retention moment is when a payment fails — and the system recovers
> gracefully."

Its practical recommendations (treat the numbers as **unverified practitioner
estimates**, useful as hypotheses, never as citations):
- Pre-debit notifications 24–48h ahead catch insufficient-balance failures before
  they happen — *and* create a mental-accounting moment where some users cancel
  rather than fail
- One-tap retry (no form-filling) sees 30–40% immediate retry
- Space retries 24h / 72h / 7d — "don't do all three in rapid succession, that
  looks like spam and violates NPCI's intent"
- Grace periods of 2–3 days before termination recover ~15–20%
- Failure messaging should offer alternatives: retry, switch rail, or pause

Its structural explanation of *why* UPI fails more, which is worth restating in
your own words:

> "Every UPI payment requires the customer's bank to approve the transaction in
> real-time… Card mandates, by contrast, are pre-authorized at the bank level;
> the bank guarantees the funds when the mandate is set up."

## 4.7 The competitive landscape

Commercial players in dunning/recovery, so you can say what exists and why yours
is different: **FlyCode, Churn Buster, Churnkey, Butter Payments, Gravy,
Baremetrics Recover, ProsperStack, RecoverPing, Slicker, Revaly, Recova,
Redux Payments.**

**Every one of them is card-first and Western.** None models NPCI execution
windows, a 4-attempt statutory cap, UPI decline codes, or RBI pre-debit
notification obligations. The India-specific constraint set is genuinely
unaddressed by this entire industry.

Adjacent reading: https://www.reduxpayments.com/blog/stripe-smart-retries-explained
(the audit that contradicts Stripe's headline) · https://churnward.com/blog/stripe-smart-retries/
(what Smart Retries doesn't cover) · https://beastinsights.com/blog/dunning-management
(hard/soft decline doctrine)

**I found no open-source project implementing constraint-aware payment retry.**
Everything is SaaS. If that holds after you check GitHub yourself, say it in the
README — "no open-source prior art for this constraint set" is a legitimate,
checkable claim and a good reason for the repo to exist.

---

# PART 5 — IDEAS TO STRENGTHEN THE BUILD

Ranked by *impact per hour*, given a ~13-day window.

### ⭐⭐⭐ Tier 1 — do these

**1. Intent inference (§3.2).** Distinguish "couldn't pay" from "using failure
as a cancel button." Detect via persistent low balance, failure immediately
post-trial-conversion, or repeated same-reason failure across cycles. Route to
cancellation-confirmation, not recovery. **Nobody else will build this. It's
your signature feature.** It's also ethically correct and maps to Razorpay's
principle 5.

**2. Salary-cycle-aware timing (§4.4).** Highest expected lift. Test it
explicitly with an ablation.

**3. Source-differentiated notification copy (§3.3).** "This failed on the
bank's side, not yours" vs. "your balance was short." Cheap. Nobody does it.
Prevents confusion-driven cancellation.

**4. The Stripe comparison table (§4.2).** Costs an hour. Reframes your entire
project as solving a *harder* problem than the global benchmark.

**5. Terminal-code waste metric.** "Baseline burned N retries on codes that can
never succeed; engine burned 0." Trivial to compute, devastating in a demo.

### ⭐⭐ Tier 2 — if time allows

**6. Window-collision modelling.** Every merchant in India is constrained to the
same three windows. That means **contention** — and NPCI's stated motivation was
system load. Model it: if everyone retries at 21:31, TD spikes. Scheduling
*within* a window is a real optimisation. Very few people will think of this.

**7. Arrears handling (SPEC §2.4).** Returning to `active` does not re-collect
missed cycles. Most people will miss this and silently overstate recovery.
Handling it correctly and saying so is a strong signal.

**8. Notification fatigue budget.** §3.4 says users ignore notifications. Model
a contact budget per customer per period, and show that fewer, better-timed
messages beat more messages. Counter-intuitive results are memorable.

**9. Bank-merger / stale-mandate detection (§3.4).** Unglamorous, real, and
shows you read about the domain rather than just the API.

**10. Cost-per-recovered-rupee.** Recovery isn't free — notifications cost money.
Report net, not gross. Ties to Razorpay's principle 7.

### ⭐ Tier 3 — mention in "future work," don't build

Multi-rail fallback (UPI → card → link) · a learned model instead of heuristics
(you don't have the data; say so) · real-time NPCI TD streaming · a merchant-facing
config UI · multi-language notification copy.

**Listing these deliberately in `LIMITATIONS.md` with a one-line reason for each
is itself a signal of judgment.** It shows you considered and rejected, rather
than not having thought of it.

---

# PART 6 — DATASETS

| Dataset | Where | Real? | Use |
|---|---|---|---|
| NPCI per-bank TD/BD + uptime | npci.org.in UPI ecosystem statistics | ✅ Real | **Bank health signal. Your credibility anchor.** |
| NPCI MCC classification | Same page (see §2.3) | ✅ Real | MCC assignment in generator |
| NPCI monthly UPI volumes | npci.org.in | ✅ Real | Context, scale |
| NACH bounce rates | NPCI, monthly | ✅ Real | Adjacent-rail sanity check |
| Product-wise declined transactions | ckandev.indiadataportal.com — NPCI dataset with issuer bank, volume, approved %, BD %, TD % | ✅ Real (verify liveness) | Possible richer join |
| Razorpay error reasons | payments_error_reasons.xlsx (§1.2) | ✅ Real | Taxonomy ground truth |
| Mandate book | You generate it | ❌ Synthetic | **Say so, loudly, in the README** |

**The hybrid is the point:** synthetic events, real bank signal, real MCC
distribution, real error taxonomy. Be precise about which is which. An evaluator
who catches you presenting synthetic results as empirical is done listening.

---

# PART 7 — HONEST GAPS

State these in `LIMITATIONS.md`. Volunteering them is worth more than hiding them.

1. **No indexed Reddit or X discussion found** on this topic (§3.1). Either it's
   absent or unreachable. Go look yourself.
2. **No public labelled dataset** of UPI mandate failures with outcomes. Nobody
   has one. Your synthetic distribution is a modelling assumption, full stop.
3. **Razorpay's documented retry cadence is described for cards.** Whether it
   applies identically to UPI mandates is not clearly stated in the public docs.
   Flag it; model both; don't assume.
4. **The 20m revocation figure conflates failures with cancellations** (§2.1).
5. **The salary-cycle hypothesis is unverified** for the Indian population.
6. **Every recovery benchmark in §4.3 is vendor-published**, and the one
   independent audit contradicts the headline by 20+ points.
7. **No open-source prior art found** for constraint-aware retry — but verify on
   GitHub before claiming it.
8. **NPCI did not comment** to Business Standard, so the 74% BD figure is
   sourced but not officially confirmed.

---

# PART 8 — QUOTE BANK

Ready to use, attributed. Do not modify the wording.

**On scale** — Business Standard source: *"The revocations stand at 20 million
every month… There is a debit execution failure which is because there is not
enough money in the user's bank account."*

**On the diagnostic gap** — second payments executive, same article: an analysis
of the payment error codes may further hint towards the major reasons for
transaction declines.

**On the trilemma** — productgrowth.in: *"If you don't retry, the user's
subscription lapses. If you retry too aggressively, you violate RBI mandate
rules. If you retry silently, the user doesn't know their subscription broke."*

**On why failure is the moment that matters** — productgrowth.in: *"The
activation moment for UPI AutoPay is when the first payment succeeds. But the
retention moment is when a payment fails."*

**On the value of recovery** — Stripe: subscriptions recovered from involuntary
churn continue on average for seven more months.

**On measurement** — Patrick Campbell, ProfitWell/Paddle: *"Most SaaS companies
don't even know how much they're losing until they start measuring it separately
from voluntary churn."*

**On the user workaround** — TechnoFino: *"I have been setting up UPI mandates
for some subscriptions from an account which has very low balance (<100). This
is intentional."*

**On architecture** — Razorpay's Agent Studio principles: every agent operates
within boundaries set by the merchant, validated by the platform, logged with an
audit trail, and certified before it reaches the marketplace.

---

# PART 9 — THE THREE THINGS THAT DECIDE THIS

If your agent internalises nothing else:

**1. The constraint set is the moat.** Four attempts, three windows, terminal
codes, notification obligations. Encode them exactly, test them as invariants,
report violations as a metric. Nobody else will.

**2. Intent inference is the insight.** Some failures are cancellations in
disguise (§3.2). Detecting them and *not chasing them* is the ethically correct
and technically interesting move, and it's the thing a Razorpay engineer will
remember from your interview.

**3. Honesty is the differentiator.** Every benchmark in this space is inflated
by 20+ points. Report your own measured numbers, your own exception list, your
own failed hypotheses. In a pile of demos claiming 60% recovery, the submission
that says "we recovered X of Y, here are the 43 cases we couldn't, and here's
the hypothesis that didn't work" is the one that gets the call.
