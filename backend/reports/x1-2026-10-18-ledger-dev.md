# X1 Per-Stage Report: 2026-10-18-ledger-dev

Costs are list prices.

| Stage | Cost per document | Time per document | Confidence |
|---|---|---|---|
| parse and redact | — | — | parse success 100.0% |
| extract | — | — | grounded 63.9%, failures 324 |
| verify | $0.0004 | work 12.92s (p95 18.38s) (OCR + vision; backfill, no wall time) | review rate 55.1%, verifier vs human 0 |
| index | $0.00 | — | n/a (retrieval quality is the golden gate's job) |
| end to end | — | review-ready —, searchable — | — |

## Labelled Error Rates (one-sided 95% Clopper-Pearson)

| Class | Sample (n) | Errors | Upper Bound | Target | Verdict | Ground Truth |
|---|---|---|---|---|---|---|
| A | 59 | 0 | 4.95% | 5.0% | PASS | adjudicated |
| B | 48 | 1 | 9.51% | 5.0% | FAIL | adjudicated |
| C | 21 | 0 | 13.29% | 10.0% | SAMPLE TOO SMALL (needs 29) | adjudicated |

## 100k Projections

### 100k Documents Ingestion
- **Estimated Cost:** not measured: no cost recorded for extract, index on these documents (their events predate token logging)
- **Prices:**
  - `gpt-4.1-2025-04-14`: $2.00 in / $8.00 out per 1M tokens
  - `gpt-6-luna`: $0.10 in / $0.50 out per 1M tokens
  - `text-embedding-3-small`: $0.02 in / $0.00 out per 1M tokens
- **Assumptions:**
  - list prices
  - medians of 102 documents
  - local parse CPU not priced

### 100k Daily Active Users
- **Estimated Cost per Day:** $2782.5000
- **Turns per User per Day:** 3
- **Cost per Answer:** $0.0093
- **Assumptions:**
  - 100,000 daily active users
  - 3 turns per user per day
  - chat cost of $0.0093 per answer
  - list prices
