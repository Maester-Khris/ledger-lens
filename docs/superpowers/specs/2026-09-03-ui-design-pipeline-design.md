# UI Design Pipeline — Competitor Research → Template → Stitch Design → Static React

Date: 2026-09-03
Status: Approved, in execution

## Context

`artifacts/product-backlog.md` scopes the project as PoC-only for the ledger
core (Week 1/2, no UI, never demoed) and a **minimal** chat UI for Iteration 3
(Document Intelligence Chat MVP — "polish is not the bar, a working demo
is"). The Icebox explicitly cuts "any user-facing UI beyond what's needed to
show a citation and a routing decision."

This spec is a deliberate, user-approved pivot beyond that written scope: the
ledger PoC itself stays headless, but the product going forward gets a full
UI — not just chat, but landing, dashboard, and other screens — with the
exact screen list set by what competitor research in Stage 0 establishes as
necessary, not pre-committed here.

Decisions locked by the user before this pipeline started:
- **Platform shape:** responsive web only. Mobile is a breakpoint of the same
  React app, not a separate native-feeling design or a future React
  Native/PWA target. Matches the locked stack (React/Vite, no RN anywhere in
  `product-backlog.md`'s stack table).
- **Stitch/template-source access:** the user's browser is already logged
  into `stitch.withgoogle.com` and has `aura.build` reachable; agents connect
  to that existing session via Playwright remote debugging (CDP), not a
  fresh/headless login.
- **Screen list:** deferred to Stage 0's output, confirmed with the user at
  one checkpoint before Stitch generation begins.

## Goal

Produce a static, pure-UI React implementation (no backend wiring) of the
product's web UI, informed by real competitor UX patterns and built through
Google Stitch mockups, landing in `frontend/src`.

## Pipeline

Five stages, sequential (each depends on the previous stage's output), one
human checkpoint after Stage 0.

### Stage 0 — Product research (competitor UX)
- One `general-purpose` agent (needs WebSearch/WebFetch/firecrawl).
- Researches 4-6 real competitor/adjacent fintech products with strong web
  UX (e.g. Mercury, Ramp, Brex, Modern Treasury, Wise, Stripe Dashboard) —
  navigation patterns, dashboard layout, data-density conventions, chat/AI
  assistant UI patterns where present.
- Output: `artifacts/ui-research/competitor-ux.md` — findings plus a
  recommended screen list.
- **Checkpoint:** recommended screen list is shown to the user for a quick
  confirm before any design/build effort is spent on it.

### Stage 1 — Template sourcing
- One agent using the `playwright-cli` skill, driving the existing
  logged-in browser via remote debugging.
- Browses `aura.build/design-systems` for a public template matching:
  enterprise-grade fintech feel, either a combined web+mobile system or two
  templates sharing tokens cleanly.
- Output: `artifacts/ui-research/template-selection.md` — chosen
  template(s), rationale, reference screenshots.

### Stage 2 — Stitch prompt authoring
- Uses the `frontend-design` (or `ui-ux-pro-max`) skill plus Stage 0 + Stage
  1 outputs to draft one Google Stitch prompt per confirmed screen, specifying
  layout, tone, component set, and responsive (web-only) behavior.

### Stage 3 — Google Stitch generation (review-optimize loop)
- One agent driving Stitch via the same remote-debugging browser session:
  submit each screen's prompt, screenshot the result, self-critique against a
  short rubric (matches template direction, matches competitor-research
  patterns, reads as fintech rather than generic SaaS), refine and regenerate
  on a miss.
- **Capped at 3 rounds per screen** — a bad prompt cannot loop indefinitely.
- Output: `artifacts/ui-research/stitch/<screen>.png`, final-accepted image
  per screen only.

### Stage 4 — Static React build
- One agent per screen (parallelizable — screens are independent once
  screenshots exist), implementing each accepted screenshot as pure static
  React/TSX in `frontend/src`, matching the existing Vite/TS scaffold. No
  backend wiring, no state beyond local UI state.
- Verified by running `npm run dev` and checking the rendered page in a
  browser, not just a successful `tsc` build.

## Guardrails

- Stage 3's round cap prevents an unbounded Stitch loop.
- Stage 0's checkpoint is the only human-in-the-loop gate before the
  expensive stages (Stitch generation, React build) run.
- Nothing in this pipeline touches `backend/` or the ledger PoC.

## Out of scope

- Backend wiring / API integration for any built screen (pure static UI
  only, per the user's explicit ask).
- React Native or any separate mobile codebase.
- Auth, multi-currency — these remain cut per the backlog's Icebox unless
  separately reopened.
