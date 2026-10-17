| Conversations | Turns/s | Turn p50 | Turn p95 | Failed | API CPU % (median) | DB connections (max) | Mock in flight (max) |
|---|---|---|---|---|---|---|---|
| 5 | 1.02 | 3.84 s | 6.11 s | 0 | 4 | 3 | 5 |
| 10 | 1.95 | 4.07 s | 6.59 s | 0 | 7 | 4 | 10 |
| 20 | 3.87 | 3.99 s | 6.70 s | 0 | 15 | 5 | 18 |
| 40 | 7.77 | 3.93 s | 6.55 s | 0 | 32 | 6 | 34 |
| 80 | 15.22 | 3.97 s | 6.79 s | 0 | 66 | 14 | 74 |
| 160 | 12.95 | 10.36 s | 15.03 s | 0 | 100 | 15 | 102 |

Frozen configuration plus the purge fix (commit 9203dfa: the stale-guest overlay purge deletes by subquery, so its
cost follows the overlay rows, not the number of guests). Same box and ladder, same database (12,143 guests, 11,211
stale). **0 failed turns**; the run stopped itself in the 160 step on p95 over 15 s. Mock: 9,612 chat calls, 3,128
answer calls, peak 132 in flight. CPU per turn at 40 conversations: 32% at 7.77 turns/s, about 41 ms (before the
fix: about 182 ms; C3b on 2026-10-15: about 41 ms). Peak 15.22 turns/s at 80 with flat latency (p95 6.79 s), the
160 step 12.95 turns/s. This run is the CPU "before" for the document lookup (L1). Limit: one run.
