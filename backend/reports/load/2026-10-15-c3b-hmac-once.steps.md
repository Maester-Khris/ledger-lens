| Conversations | Turns/s | Turn p50 | Turn p95 | Failed | API CPU % (median) | DB connections (max) | Mock in flight (max) |
|---|---|---|---|---|---|---|---|
| 5 | 0.95 | 3.87 s | 7.37 s | 0 | 4 | 3 | 5 |
| 10 | 1.95 | 3.89 s | 6.21 s | 0 | 8 | 3 | 10 |
| 20 | 3.97 | 3.81 s | 6.32 s | 0 | 15 | 7 | 18 |
| 40 | 7.75 | 3.92 s | 6.61 s | 0 | 32 | 9 | 36 |
| 80 | 14.75 | 4.11 s | 7.03 s | 0 | 82 | 14 | 70 |
| 160 | 11.28 | 12.08 s | 17.04 s | 0 | 100 | 15 | 123 |

C3b (the PII token HMAC keyed once per question and copied per candidate, each window normalised once; stored
tokens byte-identical, pinned by a known token; commit eee7b95, on top of C3a). Same box and ladder as
`2026-10-15-c3a-vault-any.steps.md`. **The whole ladder ran** (k6 did not stop the run at 160 conversations, a first
on this box), with **0 failed turns**. Mock: 9,190 chat calls, 2,994 answer calls, peak 128 in flight. CPU per turn
(median over the hold): at 40 conversations 32% at 7.75 turns/s, about 41 ms (after C3a: 47 ms, **-12%**); at 20 15%
at 3.97, about 38 ms (after C3a: 40 ms, -5%). The prediction (a few percent; `make_token` at 5% inclusive) was beaten.
Peak 14.75 turns/s at 80 (after C3a 14.65), with the core at 82% (median), no longer pinned. C3a and C3b together
against C2: -11% at 40, -16% at 20. Limit: one run.
