# data/npci/bank_health_reference.csv — provenance

This file is a **hybrid**, and the two columns of numbers in it are not the
same kind of fact. Read this before citing anything from it in the README.

## What is real

- **`bank_code` / `bank_name`** for the first 10 rows (YES, YBS, SBI, YOM,
  AXB, HDF, BOB, PNB, UOB, CNB) were observed directly on NPCI's live
  Ecosystem Statistics page during this project's build session — see
  `SOURCES.md` §6 for the exact fetch, date, and the raw extracted rows.
  These are real bank/PSP-partnership identifiers that NPCI itself lists.
- The remaining 6 rows (ICIC, KKBK, IDFB, INDB, FDRL, PYTM) are well-known
  major Indian banks / payment banks, added so the synthetic generator has
  enough variety to draw from. They were not specifically re-observed on the
  fetched page in this session (`data_provenance =
  bank_identity_from_public_knowledge`).

## What is NOT real (and why)

- **`technical_decline_pct` / `business_decline_pct`** are **calibrated
  synthetic values for every row, including the 10 confirmed-real banks.**
  The live NPCI page did return a numeric column that looked like it could
  be a decline-rate percentage (values like `0.0010%`–`0.0020%`), but the
  column headers did not survive automated text extraction, so which
  percentage that column actually represents was never confirmed — see
  `SOURCES.md` §6 for the raw evidence and reasoning.

  Rather than present an unconfirmed number as if it were read off the
  page, every row's percentages here were instead **calibrated to the one
  figure that IS confirmed**: NPCI Circular OC-149's system-wide targets of
  **Technical Decline < 1%** and **Business Decline < 5%** (Build Spec
  §2.3). Values are spread around those targets with deliberate variation
  (some banks modelled as healthier, a few as currently underperforming the
  target — plausible since a target is not a guarantee every bank meets it)
  so the bank-health-aware scheduling heuristic in
  `src/policy/allocator.py` has real signal to act on.

## Bottom line for anyone defending this file

"The bank identifiers are real, sourced from NPCI's own live statistics
page. The per-bank health percentages are this engine's own calibrated
synthetic estimate, anchored to the one system-wide regulatory target that
is independently confirmed, because the live page's own per-bank column
semantics could not be confirmed from an automated fetch." That sentence is
the honest answer to "is this real data" — see `ASSUMPTIONS.md` #A9 for the
same statement in that document's format.
