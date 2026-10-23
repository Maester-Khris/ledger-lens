| Conversations | Turns/s | Turn p50 | Turn p95 | Failed | API CPU % (median) | DB connections (max) | Mock in flight (max) |
|---|---|---|---|---|---|---|---|
| 5 | 0.97 | 3.72 s | 5.76 s | 0 | 16 | 3 | 5 |
| 10 | 1.80 | 4.21 s | 6.62 s | 0 | 26 | 5 | 10 |
| 20 | 3.47 | 4.29 s | 7.07 s | 0 | 52 | 10 | 17 |
| 40 | 5.12 | 6.10 s | 9.18 s | 0 | 93 | 15 | 34 |
| 80 | 1.30 | 16.71 s | 20.23 s | 0 | 100 | 15 | 24 |

Frozen configuration (batch A + key fix + T5, commit 7dc4824) on 2026-10-16, before the purge fix. Same box and
ladder as `2026-10-15-c3b-hmac-once.steps.md`. CPU per turn at 40 conversations: 93% at 5.12 turns/s, about 182 ms
(C3b on 2026-10-15: about 41 ms). A control run of the C3b code itself at the same time was just as slow (88% at
4.73 turns/s, about 186 ms; peak 4.73 at 40), so the code was not the cause. Cause: 11,211 of 12,143 guests (most
created by the load ladders of 2026-10-15) had passed the 24-hour overlay TTL, and every `POST /guests` read all
their ids and ran two DELETEs with 11,211 bind parameters each. Fixed in 9203dfa; see
`2026-10-16-ladder-purge-fixed.steps.md`.
