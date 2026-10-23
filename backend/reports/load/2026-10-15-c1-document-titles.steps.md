| Conversations | Turns/s | Turn p50 | Turn p95 | Failed | API CPU % (median) | DB connections (max) | Mock in flight (max) |
|---|---|---|---|---|---|---|---|
| 5 | 0.98 | 4.08 s | 6.73 s | 0 | 5 | 3 | 5 |
| 10 | 1.95 | 3.98 s | 6.36 s | 0 | 10 | 4 | 10 |
| 20 | 3.95 | 3.85 s | 6.87 s | 0 | 20 | 5 | 19 |
| 40 | 7.80 | 3.89 s | 6.55 s | 0 | 41 | 7 | 36 |
| 80 | 13.22 | 4.70 s | 7.50 s | 0 | 94 | 15 | 64 |
| 160 | 4.60 | 14.50 s | 20.31 s | 0 | 100 | 14 | 44 |

C1 (the chat's document list in one query, commit 4ae5b83, on top of N4 change 2). Same box and ladder as
`2026-10-15-n4-short-sessions.steps.md`: API alone in a 1 vCPU / 1 GiB cgroup, one uvicorn worker; Postgres, provider
mock (mean 1.25 s, sigma 0.55), stub index and k6 outside. The run stopped itself in the 160 step on turn p95 over
15 s, with **0 failed turns** in the whole run. Mock: 7,055 chat calls, 2,264 answer calls (about the turns served),
peak 124 in flight. CPU per turn at 40 conversations (median over the hold): 41% at 7.80 turns/s, about 53 ms (before: 47% at 7.75,
about 61 ms), **-13%**; the same at 20 (51 ms against 61). The prediction (-10 to 15%, from `list_documents` at
15.5% of GIL samples) held. Peak 13.22 turns/s at 80 (before 10.07, **+31%**), p95 at 80 7.50 s (before 12.67 s).
Limit: one run.

**Corrected 2026-10-15:** the CPU column is now the median over the hold. It was the max over a window that included one sample past the hold (the ramp to the next level), so it read that spike, not the hold. DB connections and mock in flight are still maxes, now over the hold only.
