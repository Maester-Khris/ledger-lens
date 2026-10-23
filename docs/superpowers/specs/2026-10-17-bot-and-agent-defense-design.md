# Bot and agent defense (N6): design only, nothing built

Date 2026-10-17. Status: design, not built. Backlog: N6 (Not epic-tracked), OWASP LLM10 unbounded consumption.
Context: `artifacts/2026-10-16-security-review-decisions.md` sections 3 and 5.

## Threat

1. **Spend:** anonymous guests and scripted agents use the chat as a free gpt-4.1 endpoint. Every turn is about 3 to 4
   model calls.
2. **Denial of service by consumption:** the OpenAI project limit (30k tokens per minute on gpt-4.1) is shared by
   every visitor. One script can use it all up and stall everyone else. The same applies to the 1 vCPU API
   (peak 15.22 turns/s, N7).
3. **Cheap identity:** `POST /guests` is unauthenticated and not rate limited (`backend/app/routes/guests.py`).
   A new guest id resets the per-guest limit. On 2026-10-16, guest creation itself turned out to be a cost: every
   registration purged the overlays of all stale guests (11,211 of them after the load ladders), which slowed
   every later registration (fixed in `9203dfa`). Guest creation is an abuse surface, so it must be capped or
   challenged.

## Inputs (measured)

| Number | Value | Source |
|---|---|---|
| Cost per answer, every call counted | about **$0.026** at list price ($2 in / $8 out per million) | gate 3 run 1, `backend/reports/cost-gate3-1.json` ($0.85, 50 turns, 171 calls) |
| Prompt tokens per turn, every call | **8.0k** | gate 3, Langfuse (CHANGELOG N7) |
| Same, after L1 and L2 | 4.4k, $0.46 per run (about half) | gate 5, `backend/reports/cost-gate5.json` |
| Chat limits today | 10 turns per guest, 30 per IP, 10-minute sliding window | CHANGELOG P3, `CHAT_LIMIT_*` |

The ceilings below use the gate 3 figures as the conservative case.

- **Per abusive guest:** 10 turns per window × 144 windows = 1,440 turns/day, about **$37/day**.
- **Per IP:** 4,320 turns/day, about **$112/day**.
- Because guest ids cost nothing to mint, the per-IP limit is the real bound today.
- **Scale:** 100k DAU × 5 to 6 answers × 8.0k tokens is about 3M tokens/min on average. The limit is 30k TPM, so
  that is **about 100x short** before any peak.
- **Spend ceiling set by the TPM limit:** 30k TPM ÷ 8.0k is about 3.75 turns/min, so about 5,400 turns/day, or
  about $140/day whatever the abuse. The same limit is the denial of service: a single abuser reaches it.

## Controls, in order

1. **Challenge before an anonymous session.**
   - What: Cloudflare Turnstile (free, no puzzle for most humans) on `POST /guests`. The server checks the token
     with the siteverify endpoint before it registers a guest.
   - Also: cap registrations per IP, for example 5 per hour, with the same Redis limiter.
   - Purpose: makes minting guest ids cost something, so the per-guest budget means something.
2. **Per-guest daily budget.**
   - Size: **$0.50/day per guest, counted on measured tokens** (input and output at list price, recorded per turn),
     not on turn counts.
   - Why that size: a real visitor asks 5 to 6 answers, about $0.16 at $0.026 each. $0.50 is about 3x that
     (19 gate 3 answers, about 35 at gate 5 cost).
   - Effect: an abusive guest costs at most $0.50/day instead of $37, about 75x less.
   - Why money, not turns: one forced calculation turn costs as much as several small ones (the p95 turn is
     $0.030, the max $0.046).
   - When it runs out: a 429 with "daily demo budget used, come back tomorrow".
   - Global backstop: a **daily tenant-wide $ cap**, plus the provider spend caps still open in P3.
3. **Per-IP limits (N5, built).**
   - The Redis sliding window: 30 turns per 10 minutes, exact across replicas. The IP is the rightmost
     `X-Forwarded-For` entry.
   - Keep it as the outer bound for shared NATs and for bots that rotate guests.
4. **Identified agents through an API.**
   - Scripted use goes to a separate surface: API keys issued per client and stored hashed, each with its own
     tokens-per-minute and $/day quota, and its own tag in the logs and traces.
   - The guest chat stays for humans. A client that wants automation gets a key, not a bypass.
   - Not built, and only needed once someone actually asks for automation.
5. **Admission control (backlog X3) for overload.**
   - A bounded queue in front of the model: when tokens in flight would cross a share of the TPM limit, or turns in
     flight would cross what the CPU can serve, answer at once with 503 "busy, try again" and `Retry-After`.
   - This replaces the current behaviour, where the client backs off for up to about 59 s (P3).
   - Keyed agents get a reserved share, so one tenant's burst cannot starve the demo.

## When Redis is down

- The limiter **fails open** today: the request is allowed, with a `rate_limit_unavailable` warning and a Sentry
  message (`backend/app/rate_limit.py`). This was chosen so that a cache outage does not take the demo down.
- What still bounds the risk during the outage:
  - the provider's 30k TPM limit, a hard spend ceiling of about $140/day at gate 3 cost;
  - the per-turn timeouts (30 s per call, 60 s per turn);
  - the CPU ceiling (about 15 turns/s);
  - the provider spend cap, once P3 sets it.
- Design changes:
  - keep the budget and the daily cap in Postgres (a durable count, readable without Redis);
  - while Redis is down, enforce a fixed per-process limit (the in-memory limiter, which is correct per replica);
  - page on the Sentry message.
- Open: whether to fail closed instead, if a Sentry alert has not been acknowledged within N minutes.

## `X-Guest-Id` is a bearer token

- **What it does:** whoever holds the UUID acts as that guest, with their chat sessions, overlay decisions,
  approvals and budget.
- **Where it lives and can leak:**
  - `localStorage` (`ledgerlens.guest`, `frontend/src/api.ts`), so any XSS on the origin can read it. There is no
    CSP yet (S4a).
  - Shared screenshots or a copy of the dev-tools network panel.
  - Proxy or edge logs that record request headers.
  - Browser extensions.
- **Where it does not go:** it is not in URLs, and Sentry runs with `send_default_pii=False`.
- **What follows from a leak:**
  - the holder can read and continue that guest's chats and decide their pending proposals;
  - they can spend that guest's budget (bounded by control 2);
  - they cannot reach the ledger: in demo mode the write routes are not mounted, and approvals only touch the
    guest's overlay.
- **Mitigations, in order:**
  - bind `session_id` to its guest (H1, with S5);
  - a CSP;
  - later, move the id into an `HttpOnly; Secure; SameSite=Strict` cookie, so scripts cannot read it;
  - rotate the id on a new challenge.

## Open decisions (owner)

1. Budget size: $0.50/guest/day (proposed), and the tenant-wide daily cap, proposed at $20/day for the demo.
2. Turnstile, or plain per-IP caps on `POST /guests` for the demo only (Turnstile needs a Cloudflare site key and
   a frontend change).
3. Redis outage: keep failing open (bounded by TPM and the spend cap), or fail closed after an unacknowledged alert.
4. Is the keyed agent API in scope before a paying client asks for it? Proposed: no.
5. Raise the OpenAI usage tier (TPM) before launch, or ship admission control first. Either way, the 100x gap at
   100k DAU needs the tier raised, caching, or a cheaper model on the agent calls.
