| Conversations | Turns/s | Turn p50 | Turn p95 | Failed | API CPU % (max) | DB connections (max) | Mock in flight (max) |
|---|---|---|---|---|---|---|---|
| 5 | 0.98 | 3.81 s | 5.97 s | 0 | 5 | 3 | 5 |
| 10 | 1.92 | 4.15 s | 6.40 s | 0 | 10 | 4 | 10 |
| 20 | 4.00 | 3.74 s | 6.54 s | 0 | 22 | 5 | 21 |
| 40 | 7.77 | 3.94 s | 6.56 s | 0 | 54 | 10 | 45 |
| 80 | 14.20 | 4.36 s | 7.09 s | 0 | 100 | 15 | 69 |
| 160 | 10.75 | 12.83 s | 18.11 s | 0 | 100 | 15 | 101 |

C2 (the chat graph compiled once per runtime, each turn's context passed in the run config; commit 931d946, on top of
C1). Same box and ladder as `2026-10-15-c1-document-titles.steps.md`. The run stopped itself in the 160 step on turn
p95 over 15 s, with **0 failed turns** in the whole run. Mock: 8,368 chat calls, 2,688 answer calls (about the turns
served), peak 124 in flight. CPU per turn at 40 conversations: 54% at 7.77 turns/s, about 70 ms (after C1: 61% at
7.80, about 78 ms), **-11%**; the prediction (about -9%, `build_graph` at 9.5% of GIL samples) held. Peak 14.20
turns/s at 80 (after C1 13.22, +7%), p95 at 80 7.09 s; the 160 step held 10.75 turns/s (after C1 4.60). Limit: one
run.
