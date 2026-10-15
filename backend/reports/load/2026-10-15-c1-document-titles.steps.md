| Conversations | Turns/s | Turn p50 | Turn p95 | Failed | API CPU % (max) | DB connections (max) | Mock in flight (max) |
|---|---|---|---|---|---|---|---|
| 5 | 0.98 | 4.08 s | 6.73 s | 0 | 7 | 3 | 5 |
| 10 | 1.95 | 3.98 s | 6.36 s | 0 | 12 | 4 | 13 |
| 20 | 3.95 | 3.85 s | 6.87 s | 0 | 29 | 5 | 24 |
| 40 | 7.80 | 3.89 s | 6.55 s | 0 | 61 | 8 | 52 |
| 80 | 13.22 | 4.70 s | 7.50 s | 0 | 100 | 15 | 64 |
| 160 | 4.60 | 14.50 s | 20.31 s | 0 | 100 | 14 | 44 |

C1 (the chat's document list in one query, commit 4ae5b83, on top of N4 change 2). Same box and ladder as
`2026-10-15-n4-short-sessions.steps.md`: API alone in a 1 vCPU / 1 GiB cgroup, one uvicorn worker; Postgres, provider
mock (mean 1.25 s, sigma 0.55), stub index and k6 outside. The run stopped itself in the 160 step on turn p95 over
15 s, with **0 failed turns** in the whole run. Mock: 7,055 chat calls, 2,264 answer calls (about the turns served),
peak 124 in flight. CPU per turn at 40 conversations: 61% at 7.80 turns/s, about 78 ms (before: 87% at 7.75, about
112 ms), **-30%**. Peak 13.22 turns/s at 80 (before 10.07, **+31%**), p95 at 80 7.50 s (before 12.67 s). The
prediction (-10 to 15%, from `list_documents` at 15.5% of GIL samples) was beaten: the profile counts only Python
holding the GIL, while the about 409 queries per call this removes also cost psycopg's C work and Postgres round
trips. Limit: one run.
