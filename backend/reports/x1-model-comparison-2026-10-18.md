# X1 extraction-model comparison (2026-10-18)

Same production prompt (`extract_v1`) and schema, 76 labelled ledger_dev documents, scored against 128 owner-adjudicated
labels (ground truth: one LLM judge, Claude Sonnet 5.5, adjudicated by the owner). Costs are list prices.
Caveat: the labels were drawn from fields **gpt-4.1** auto-accepted, which favours gpt-4.1. A candidate can tie it
on those fields or do worse; it cannot show what it would catch that gpt-4.1 misses.

| Model | Class A | Class B | Class C | Review rate | $ / document | Latency median (p95) |
|---|---|---|---|---|---|---|
| **gpt-4.1** (current) | **59/59** | 47/48 | 21/21 | 43.8% | ≈ $0.016 (2 / 8 per 1M) | — (existing runs) |
| gpt-4.1-mini | 50/59 | 42/48 | 17/21 | 43.1% | $0.0024 | 3.3 s (5.2 s) |
| gpt-5-mini (minimal reasoning) | 49/59 | 40/48 | 16/21 | 50.6% | $0.0024 | 7.6 s (13.5 s) |
| Gemini 3.5 Flash-Lite | 47/59 | 42/48 | 14/21 | 45.5% | $0.0015 | 3.0 s (5.8 s) |

## What the misses are (class A)

| Model | Same value, other extent (strict `fee_basis` rule) | Left empty (routes to review) | Wrong value |
|---|---|---|---|
| gpt-4.1-mini | 5 | 3 | 1, routed to review by extraction's own checks (never served) |
| gpt-5-mini | 4 | 6 | 0 |
| Gemini 3.5 Flash-Lite | 5 | 7 | 0 |

No candidate served a wrong class A value in this sample. Their shortfall is reviewer workload (empty fields), plus
`fee_basis` extent differences that a containment rule (deferred) would score as correct.

## Decision (spec rule: class A accuracy first, then review rate, then price)
**gpt-4.1 stays.** No candidate matches it on class A. Best candidate if the trade-off is reconsidered: gpt-4.1-mini
(closest on class A, lowest review rate, ~7× cheaper). Re-run this comparison after the deferred fixes (containment
rule for `fee_basis`, redaction) and on labels not drawn from gpt-4.1's own accepted fields.

Gemini ran on the free tier as an owner-approved exception (evaluation only, public SEC corpus, PII tokenised before
extraction); production use requires the paid tier (no training on inputs).
