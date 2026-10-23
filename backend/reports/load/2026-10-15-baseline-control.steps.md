| Conversations | Turns/s | Turn p50 | Turn p95 | Failed | API CPU % (max) | DB connections (max) | Mock in flight (max) |
|---|---|---|---|---|---|---|---|
| 5 | 0.93 | 4.21 s | 6.12 s | 0 | 7 | 5 | 5 |
| 10 | 2.00 | 3.76 s | 6.02 s | 0 | 16 | 7 | 10 |
| 20 | 2.95 | 5.80 s | 7.86 s | 0 | 20 | 13 | 12 |
| 40 | 0.63 | 11.05 s | 43.15 s | 1 | 17 | 15 | 12 |
| 80 | (stopped) | — | — | yes | — | 15 | 12 |

Control: the baseline code (commit 3c5a4c3, checked out in a separate worktree) re-run at the end of the sprint with
today's runner and sampler, same 1 vCPU / 1 GiB box and ladder. It bends at the same point, **2.95 turns/s at 20
conversations** (p95 7.9 s), against 2.98 turns/s (p95 8.0 s) in the first baseline: -1%, within the 10% rule, so the
machine did not drift between runs. Past the bend the old code is unstable (40 conversations: 0.63 turns/s here, 1.88
in the first run), and the run stopped in the 80 step on failures (7.4% of 453 turns), as before.
