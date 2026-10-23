| Conversations | Turns/s | Turn p50 | Turn p95 | Failed | API CPU % (max) | DB connections (max) | Mock in flight (max) |
|---|---|---|---|---|---|---|---|
| 5 | 0.92 | 3.99 s | 6.54 s | 0 | 8 | 5 | 5 |
| 10 | 1.87 | 4.21 s | 6.45 s | 0 | 13 | 7 | 11 |
| 20 | 2.98 | 5.64 s | 8.01 s | 0 | 24 | 15 | 12 |
| 40 | 1.88 | 11.38 s | 13.86 s | 0 | 19 | 15 | 12 |
| 80 | (stopped) | — | — | 29 | — | 15 | 12 |

Local. The API alone confined to 1 vCPU / 1 GB (cgroup via systemd-run: cpu.max 100000/100000, memory.max 1 GiB),
one uvicorn worker; Postgres, the provider mock (mean 1.25 s, sigma 0.55), the stub index and k6 outside the limit.
2 golden questions per conversation, 1 s reading pause, 1 min per level. API CPU is the max over 5 s intervals of
CPU time used (100 = one core). The run stopped itself in the 80 step (chat_turn_failed 5.16% > 5%). Totals: 533 of
562 turns served. Mock: 1,687 chat calls, peak 12 in flight.
