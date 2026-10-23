| Conversations | Turns/s | Turn p50 | Turn p95 | Failed | API CPU % (median) | DB connections (max) | Mock in flight (max) |
|---|---|---|---|---|---|---|---|
| 5 | 1.02 | 3.85 s | 5.77 s | 0 | 4 | 3 | 5 |
| 10 | 1.98 | 3.79 s | 6.00 s | 0 | 8 | 5 | 10 |
| 20 | 4.00 | 3.65 s | 6.67 s | 0 | 16 | 5 | 18 |
| 40 | 7.73 | 4.00 s | 6.64 s | 0 | 36 | 7 | 36 |
| 80 | 14.65 | 4.22 s | 7.04 s | 0 | 87 | 13 | 67 |
| 160 | 11.25 | 12.46 s | 17.40 s | 0 | 100 | 15 | 113 |

C3a (the vault lookup of known PII tokens sends its candidates as one Postgres array instead of an IN list; 621
binds for a 17-word question; commit e1f303c, on top of C2). Same box and ladder as
`2026-10-15-c2-graph-once.steps.md`. The run stopped itself in the 160 step on turn p95 over 15 s, with **0 failed
turns**. Mock: 8,882 chat calls, 2,859 answer calls, peak 128 in flight. CPU per turn (median over the hold): at 20
conversations 16% at 4.00 turns/s, about 40 ms (after C2: 45 ms, -11%); at 40 36% at 7.73, about 47 ms (after C2:
46 ms, +2%, inside the 5% noise band). Peak 14.65 turns/s at 80 (after C2 14.20, +3%). **Inconclusive**: kept
(two lines, no failure, better at 20 and at peak) on the owner's decision, not claimed as a gain. Limit: one run.
