| Conversations | Turns/s | Turn p50 | Turn p95 | Failed | API CPU % (max) | DB connections (max) | Mock in flight (max) |
|---|---|---|---|---|---|---|---|
| 5 | 1.00 | 3.93 s | 5.83 s | 0 | 9 | 3 | 5 |
| 10 | 1.92 | 3.82 s | 7.21 s | 0 | 14 | 4 | 11 |
| 20 | 3.92 | 3.89 s | 6.11 s | 0 | 31 | 6 | 27 |
| 40 | 7.75 | 3.87 s | 6.51 s | 0 | 87 | 14 | 38 |
| 80 | 10.07 | 6.23 s | 12.67 s | 0 | 100 | 15 | 49 |
| 160 | 4.07 | 14.47 s | 20.95 s | 0 | 100 | 15 | 60 |

Change 2 (short DB sessions off the event loop, commits f1b10db and db2ceec, on top of change 1). Same box and ladder
as the baseline: API alone in a 1 vCPU / 1 GiB cgroup, one uvicorn worker; Postgres, provider mock (mean 1.25 s,
sigma 0.55), stub index and k6 outside. The run stopped itself in the 160 step on turn p95 over 15 s, with **0 failed
turns** in the whole run. Totals: 1,954 turns served. Mock: 6,231 chat calls, peak 77 in flight. Prediction held: DB
connections no longer track turns in flight (6 at 20 conversations, 14 at 40) and the bend moved to CPU: 87% of the
core at 40 conversations, 100% at 80 and 160. Latency stays flat up to 40 conversations (7.75 turns/s, p95 6.5 s);
peak throughput is 10.07 turns/s at 80 with p95 12.7 s.
