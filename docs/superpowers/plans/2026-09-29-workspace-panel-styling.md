# Workspace Panel Styling Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **This project:** Gemini executes the tasks in order; Claude reviews at each **REVIEW CHECKPOINT** before the next task starts. Stop at every checkpoint and hand over: commits, `npm run build` output, `git status`.

**Goal:** Fix a layout bug and a set of visual-hierarchy/UX issues in the Chat screen's
document panel (Profile / Billing reconciliation / Ledger / Audit trail), reported from
live screenshots of the built N12/N13/N14/N17/N19 features.

**Architecture:** No new subsystem — five existing frontend files get targeted fixes, plus
one new self-contained component (`BillingReconciliation.tsx`, mirroring `ContractProfile.tsx`'s
existing self-fetching pattern). The panel's tab-button row is replaced with a native
`<select>`, which is both simpler and more accessible than the custom roving-tabindex
tablist it replaces.

**Tech Stack:** React (Vite) + TypeScript; plain CSS (existing design tokens only, no new
dependency).

**Spec:** None — bounded change (existing, already-built screens; no new subsystem or
interface others depend on). This plan carries the full design in place of a separate spec
file, per the same classification used for the 2026-09-28 landing hero animation plan.

## Global Constraints

- Branch `feat/demo-ready`. Never commit to `main`/`preview`. Stage files explicitly (never
  `git add -A`/`.`). Conventional commits. **No AI co-author line.** Do not push.
- TypeScript: no `any`; a props interface for every component.
- No new npm package.
- `cd frontend && npm run build` (`tsc -b && vite build`) and `npm run lint` must pass with
  no new errors/warnings after the task.
- Use the design system's existing CSS custom properties only (`--color-accent`,
  `--color-bg-subtle`, `--color-bg-muted`, `--color-warning`, `--radius-control`,
  `--motion-fast`, `--space-*`, etc. — see `frontend/src/index.css`). Do not invent new
  tokens or hardcode colors.
- Respect `prefers-reduced-motion` for the new refresh-spin animation (existing pattern:
  see `frontend/src/screens/Landing.css`'s `@media (prefers-reduced-motion: no-preference)`
  guard).

## Review Focus

1. **Long panel content must not stretch the chat column.** The root-cause fix (Task 1
   Step 1) must be checked with an actually-tall panel tab (Ledger with several timeline
   entries) next to a short chat thread, not just eyeballed at rest.
2. **The citation link must read as clickable, not as trailing prose.** A field with both
   a `reason` and a `page` must show visible separation and a distinct color/weight on the
   "Page N →" link — check a `needs_review` field specifically, since those are the ones
   that render both a reason and a link together (Task 1 Step 3).
3. **Audit trail emptiness must be diagnosed, not just re-styled.** Before touching
   `AuditLog.tsx`'s code, reproduce with a session that has actually triggered a tool call;
   only file it as a real bug if a fresh tool call still doesn't appear (Task 1 Step 7).
4. **The billing-reconciliation split must not silently drop the household-less case.**
   A document with no `household` (e.g. `calamos-emerging-market-equity`,
   `nomura-tax-free-colorado-ima`) must still render a clear "not linked" message in the
   new tab, not a blank pane (Task 2 Step 1).
5. **The `<select>` replacement must keep the panel usable on narrow screens.** The
   existing `@media (max-width: 1099px)` fixed-sheet behavior in `Workspace.css` is
   untouched by this plan, but the new select header must still fit and work inside that
   narrower fixed-sheet width (Task 2 Step 4).

---

### Task 1: Layout fix, refresh button, field hierarchy, coming-soon styling, audit-trail check

**Files:**
- Modify: `frontend/src/components/workspace/Workspace.css`, `frontend/src/components/workspace/RefreshButton.tsx`, `frontend/src/components/workspace/ContractProfile.tsx`

**Interfaces:**
- Consumes: existing `RefreshIcon` from `frontend/src/components/Icons.tsx` (already exists, no changes needed).
- Produces: `.ws-field__label`, `.ws-field__value`, `.ws-field__value-text`, `.ws-field__reason`, `.ws-field__page` CSS classes and matching JSX structure in `ContractProfile.tsx`, reused unchanged by Task 2's new `BillingReconciliation.tsx`.

- [ ] **Step 1: Fix the height-coupling bug** — in `frontend/src/components/workspace/Workspace.css`, line 1, add `flex: 1;`:

```css
.ws-layout { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--space-3); min-height: 0; flex: 1; }
```

Root cause: `.ws-layout` sits inside `.chat`, a fixed `height: 100dvh` flex column
(`frontend/src/screens/Chat.css:1-6`), but had no `flex: 1` of its own, so it sized to its
content instead of consuming `.chat`'s remaining height. As a grid row, the chat column and
side panel share that row's height, so a tall panel tab (e.g. a long Ledger timeline)
stretched the row and dragged the chat thread's height with it. The existing `min-height: 0`
on `.chat__column` and `.ws-panel` (both already flex columns) is what lets their internal
scroll areas (`.chat__scroll`, `.ws-pane`) cap and scroll independently once the row itself
is height-bound — no other change needed for this fix.

- [ ] **Step 2: RefreshButton — background and icon**

Replace the whole file `frontend/src/components/workspace/RefreshButton.tsx`:

```tsx
import { RefreshIcon } from '../Icons';

interface RefreshButtonProps {
  onClick(): void;
  busy: boolean;
}

export function RefreshButton({ onClick, busy }: RefreshButtonProps) {
  return (
    <button type="button" className="ws-refresh" onClick={onClick} disabled={busy} aria-label="Refresh">
      <RefreshIcon size={13} className={busy ? 'ws-refresh__icon ws-refresh__icon--spin' : 'ws-refresh__icon'} />
      {busy ? 'Refreshing…' : 'Refresh'}
    </button>
  );
}
```

In `Workspace.css`, replace the `.ws-refresh` rule (lines 20-21):

```css
.ws-refresh {
  display: inline-flex; align-items: center; gap: 6px;
  background: var(--color-bg-subtle); border: 1px solid var(--color-border); border-radius: var(--radius-control);
  padding: 6px var(--space-2); color: var(--color-text-secondary); cursor: pointer;
  transition: background var(--motion-fast), color var(--motion-fast);
}
.ws-refresh:hover:not(:disabled) { background: var(--color-bg-muted); color: var(--color-text-primary); }
.ws-refresh:disabled { opacity: 0.6; cursor: not-allowed; }

@media (prefers-reduced-motion: no-preference) {
  .ws-refresh__icon--spin { animation: ws-spin 800ms linear infinite; }
  @keyframes ws-spin { to { transform: rotate(360deg); } }
}
```

- [ ] **Step 3: Contract Profile field rows — visual hierarchy**

In `frontend/src/components/workspace/ContractProfile.tsx`, find the field row block
(inside the `GROUPS.map` section):

```tsx
                <div key={f.path} className="ws-field">
                  <dt>{f.label} <span className="ws-badge">{STATUS_LABEL[f.status]}</span></dt>
                  <dd>
                    {display(f.value)}
                    {f.reason && <div className="ws-reason">{f.reason}</div>}
                    {f.page !== null && (
                      <a href={documentPageUrl(terms.document_id, terms.version, f.page)} target="_blank" rel="noreferrer">
                        Page {f.page} →
                      </a>
                    )}
                  </dd>
                </div>
```

Replace with:

```tsx
                <div key={f.path} className="ws-field">
                  <dt className="ws-field__label">{f.label} <span className={`ws-badge ws-badge--${f.status}`}>{STATUS_LABEL[f.status]}</span></dt>
                  <dd className="ws-field__value">
                    <span className="ws-field__value-text">{display(f.value)}</span>
                    {f.reason && <p className="ws-field__reason">{f.reason}</p>}
                    {f.page !== null && (
                      <a className="ws-field__page" href={documentPageUrl(terms.document_id, terms.version, f.page)} target="_blank" rel="noreferrer">
                        Page {f.page} →
                      </a>
                    )}
                  </dd>
                </div>
```

In `Workspace.css`, replace the `.ws-field` line (line 26):

```css
.ws-field { display: grid; gap: 4px; margin-bottom: var(--space-3); }
.ws-field__label { display: flex; align-items: center; gap: 6px; font-size: 0.78em; font-weight: 600;
  color: var(--color-text-secondary); text-transform: uppercase; letter-spacing: 0.02em; }
.ws-field__value { margin: 0; }
.ws-field__value-text { display: block; font-size: 0.95em; color: var(--color-text-primary); }
.ws-field__reason { margin: 4px 0 0; font-size: 0.82em; color: var(--color-text-secondary); font-style: italic; }
.ws-field__page { display: inline-block; margin-top: 6px; font-size: 0.82em; font-weight: 600; color: var(--color-accent); }

.ws-badge--accepted, .ws-badge--confirmed { color: var(--color-success); border-color: var(--color-success); }
.ws-badge--needs_review, .ws-badge--rejected { color: var(--color-warning); border-color: var(--color-warning); }
```

Acceptance bar (Review Focus 2): the field label must read as clearly smaller/quieter than
the value; the reason (when present) must be visually distinct from the value; the
"Page N →" link must never look like a continuation of the reason text directly above it —
clear vertical space plus a distinct color/weight.

- [ ] **Step 4: "Coming soon" list styling**

In `Workspace.css`, after the `.ws-muted { opacity: 0.55; }` line, add:

```css
.ws-muted ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
.ws-muted li { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2);
  padding: 6px var(--space-2); border: 1px dashed var(--color-border); border-radius: var(--radius-control);
  font-size: 0.85em; color: var(--color-text-secondary); }
```

- [ ] **Step 5: Empty/loading state legibility**

In `Workspace.css`, replace `.ws-empty, .ws-error { color: var(--color-text-secondary); }`
(line 22):

```css
.ws-empty, .ws-error { color: var(--color-text-secondary); font-style: italic; padding: var(--space-2) 0; }
```

- [ ] **Step 6: Build and lint check**

Run: `cd frontend && npm run build` → no errors. Run: `npm run lint` → no new warnings on
the touched files.

- [ ] **Step 7: Verify the audit trail "can't see anything" report — diagnose before changing code**

`AuditLog.tsx` already has an explicit empty state ("No AI decisions in this conversation
yet."). The screenshots that prompted this report showed a session with an empty chat
thread (no questions asked yet) — that may be entirely correct behavior, not a bug.

In the running app: start a fresh chat session, ask any question against a scoped document
(the agent always calls `search_contracts` or `get_contract_fields`), then open the Audit
trail tab. Confirm a row appears with the tool name, model, inputs, and (if
`approval_required`) an "Awaiting approval →" link.

- If it works correctly: no code change needed here beyond Step 5's styling. Note this in
  the checkpoint report.
- If it's still blank after a real tool call happened in that exact session: this is a real
  bug. Check the network response from `GET /tool-invocations?session_id=...` in the
  browser and report the finding at the checkpoint — do not guess at a fix without seeing
  the actual response.

- [ ] **Step 8: Manual verification in the browser**

`cd frontend && npm run dev`. Confirm:
1. Select a document, ask enough questions to make the chat thread taller than the
   viewport, switch to a long panel tab — thread and panel scroll independently, neither
   stretches past the viewport (Review Focus 1).
2. A `needs_review` field (e.g. Signatory 1/2 on the AIM Global Trends document) shows a
   clearly separated, distinctly-colored "Page N →" link below its reason text (Review
   Focus 2).
3. Refresh button (Ledger, Audit trail tabs) has a visible background, shows the refresh
   icon, and the icon spins while busy (check with reduced-motion off; confirm no spin with
   it on).
4. Step 7's audit-trail check, with its actual result recorded.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/workspace/Workspace.css frontend/src/components/workspace/RefreshButton.tsx frontend/src/components/workspace/ContractProfile.tsx
git commit -m "fix(frontend): decouple panel height from the chat column, restyle refresh button and profile fields"
```

**REVIEW CHECKPOINT A** — stop and hand over to Claude: commits, `npm run build`/`lint`
output, `git status`, and the actual finding from Step 7 (bug or not).

---

### Task 2: Split Billing reconciliation into its own panel section; replace tabs with a select menu

**Files:**
- Create: `frontend/src/components/workspace/BillingReconciliation.tsx`
- Modify: `frontend/src/components/workspace/ContractProfile.tsx`, `frontend/src/components/workspace/DocumentPanel.tsx`, `frontend/src/components/workspace/Workspace.css`, `frontend/src/screens/Chat.tsx`

**Interfaces:**
- Consumes: `TermsDto`, `getTerms` from `frontend/src/api.ts` (unchanged); `PanelTab` from `DocumentPanel.tsx` (unchanged shape: `{ id: string; label: string; content: ReactNode }`).
- Produces: `BillingReconciliation({ documentId: string })` component; `DocumentPanel` now renders a `<select>` instead of a tab-button row (same props, same `PanelTab[]` contract — no changes needed by callers other than the new tab entry in Task 2 Step 3).

- [ ] **Step 1: New component** — `frontend/src/components/workspace/BillingReconciliation.tsx`:

```tsx
import { useEffect, useState } from 'react';
import { type TermsDto, getTerms } from '../../api';

function percent(bps: string): string {
  return `${(Number(bps) / 100).toFixed(2)}%`;
}

interface BillingReconciliationProps {
  documentId: string;
}

export function BillingReconciliation({ documentId }: BillingReconciliationProps) {
  const [terms, setTerms] = useState<TermsDto | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setTerms(null);
    setError(null);
    getTerms(documentId).then(setTerms).catch((e: unknown) => setError(e instanceof Error ? e.message : 'Could not load billing reconciliation'));
  }, [documentId]);

  if (error) return <p className="ws-error">{error}</p>;
  if (!terms) return <p className="ws-empty">Loading…</p>;
  if (!terms.household) return <p className="ws-empty">Not linked to a billing household.</p>;

  return (
    <div className="ws-billing">
      <p className="ws-billing__household">Household <strong>{terms.household.name}</strong></p>
      {terms.billing_schedule ? (
        <div className="ws-field">
          <dt className="ws-field__label">Billing schedule</dt>
          <dd className="ws-field__value">
            <span className="ws-field__value-text">
              v{terms.billing_schedule.version} ({terms.billing_schedule.method}) —{' '}
              {terms.billing_schedule.tiers.map((t) => percent(t.rate_bps)).join(' / ')}
            </span>
          </dd>
        </div>
      ) : <p className="ws-empty">No billing schedule in effect today.</p>}
    </div>
  );
}
```

This mirrors `ContractProfile.tsx`'s existing self-fetching pattern deliberately — each
panel section stays independently testable and doesn't need `Chat.tsx` to lift and share
fetch state. The duplicate `getTerms` call when switching tabs is a cheap local DB read, not
an LLM call.

(Review Focus 4: the `if (!terms.household)` branch above is exactly what must render for
`calamos-emerging-market-equity` and the other non-household documents — verify this in
Step 5, don't just assume the branch works.)

- [ ] **Step 2: Remove the billing section from ContractProfile.tsx**

In `frontend/src/components/workspace/ContractProfile.tsx`, delete this whole block (it now
lives in `BillingReconciliation.tsx`):

```tsx
      <section>
        <h3>Billing reconciliation</h3>
        {terms.household ? (
          <p>
            Household <strong>{terms.household.name}</strong>
            {terms.billing_schedule
              ? <> — billed on schedule v{terms.billing_schedule.version} ({terms.billing_schedule.method}):{' '}
                  {terms.billing_schedule.tiers.map((t) => percent(t.rate_bps)).join(' / ')}</>
              : ' — no billing schedule in effect today.'}
          </p>
        ) : <p className="ws-empty">Not linked to a billing household.</p>}
      </section>
```

Leave the `GROUPS.map` loop and the "Coming soon" section exactly as they are. If the
`percent` helper function in this file becomes unused after this removal, leave it — it's
still used elsewhere in the same file for fee-tier values in the `display()` path. (Check:
if `percent` really is now unused in this file, remove it; TypeScript/lint will flag it
either way.)

- [ ] **Step 3: Add the new tab in Chat.tsx**

In `frontend/src/screens/Chat.tsx`, add the import:

```tsx
import { BillingReconciliation } from '../components/workspace/BillingReconciliation';
```

Replace the `tabs` array (currently around lines 112-118):

```tsx
  const tabs: PanelTab[] = [
    ...(scopeId ? [
      { id: 'profile', label: 'Profile', content: <ContractProfile documentId={scopeId} /> },
      { id: 'ledger', label: 'Ledger', content: <LedgerTimeline documentId={scopeId} refreshKey={ledgerKey} /> },
    ] : []),
    { id: 'audit', label: 'Audit trail', content: <AuditLog sessionId={sessionId} refreshKey={auditKey} /> },
  ];
```

with:

```tsx
  const tabs: PanelTab[] = [
    ...(scopeId ? [
      { id: 'profile', label: 'Profile', content: <ContractProfile documentId={scopeId} /> },
      { id: 'billing', label: 'Billing reconciliation', content: <BillingReconciliation documentId={scopeId} /> },
      { id: 'ledger', label: 'Ledger', content: <LedgerTimeline documentId={scopeId} refreshKey={ledgerKey} /> },
    ] : []),
    { id: 'audit', label: 'Audit trail', content: <AuditLog sessionId={sessionId} refreshKey={auditKey} /> },
  ];
```

- [ ] **Step 4: Replace the tab-button row with a select menu**

Replace the whole file `frontend/src/components/workspace/DocumentPanel.tsx`:

```tsx
import { type ReactNode, useState } from 'react';

export interface PanelTab {
  id: string;
  label: string;
  content: ReactNode;
}

interface DocumentPanelProps {
  tabs: PanelTab[];
}

export function DocumentPanel({ tabs }: DocumentPanelProps) {
  const [activeId, setActiveId] = useState<string | null>(null);
  if (tabs.length === 0) return null;
  const active = tabs.find((t) => t.id === activeId) ?? tabs[0];
  return (
    <aside className="ws-panel" aria-label="Document details">
      <div className="ws-panel__head">
        <label className="ws-panel__select-label" htmlFor="ws-panel-select">Viewing</label>
        <select
          id="ws-panel-select"
          className="ws-panel__select"
          value={active.id}
          onChange={(event) => setActiveId(event.target.value)}
        >
          {tabs.map((t) => (
            <option key={t.id} value={t.id}>{t.label}</option>
          ))}
        </select>
      </div>
      <div className="ws-pane">
        {active.content}
      </div>
    </aside>
  );
}
```

This drops the custom `ArrowLeft`/`ArrowRight` roving-tabindex keyboard handling the
button-row version needed — a native `<select>` already has standard keyboard and
screen-reader behavior built in, so nothing is lost, only custom code.

In `Workspace.css`, replace the `.ws-tabs` and `.ws-tab` rules (lines 15-17):

```css
.ws-panel__head { display: flex; align-items: center; gap: var(--space-2); padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--color-border); }
.ws-panel__select-label { font-size: 0.78em; font-weight: 600; color: var(--color-text-secondary);
  text-transform: uppercase; letter-spacing: 0.02em; }
.ws-panel__select { flex: 1; border: 1px solid var(--color-border); border-radius: var(--radius-control);
  padding: 6px var(--space-2); font-size: 13px; font-weight: 500; color: var(--color-text-primary);
  background: var(--color-surface); }
.ws-panel__select:focus-visible { outline: 2px solid var(--color-accent); outline-offset: 1px; }
```

Also add, near the other `.ws-` rules:

```css
.ws-billing__household { margin: 0 0 var(--space-3); color: var(--color-text-secondary); }
```

Billing reconciliation is now its own top-level `<select>` option, reachable in one action
instead of being buried inside Profile — that satisfies "visible from the get-go" without
forcing it as the default selection (default stays whichever tab is first: Profile when a
document is scoped, Audit trail otherwise — unchanged from today).

- [ ] **Step 5: Build and lint check**

Run: `cd frontend && npm run build` → no errors. Run: `npm run lint` → no new warnings.

- [ ] **Step 6: Manual verification in the browser**

1. Select the Tremblay document (has a household): the panel selector shows 4 options
   (Profile, Billing reconciliation, Ledger, Audit trail); Billing reconciliation shows the
   household name and schedule/tiers directly, no scrolling through Profile first.
2. Select a document with no household (e.g. Calamos): Billing reconciliation shows "Not
   linked to a billing household." — not a blank pane (Review Focus 4).
3. Resize the viewport to under 1100px: the panel still opens as the fixed sheet (existing
   `@media (max-width: 1099px)` rule, untouched), and the select-menu header still fits and
   works at that narrower width (Review Focus 5).
4. Keyboard: focus the select, use arrow keys to change the active section — confirm the
   pane content updates.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/workspace/BillingReconciliation.tsx frontend/src/components/workspace/ContractProfile.tsx frontend/src/components/workspace/DocumentPanel.tsx frontend/src/components/workspace/Workspace.css frontend/src/screens/Chat.tsx
git commit -m "feat(frontend): split billing reconciliation into its own panel section, select-menu navigation"
```

**REVIEW CHECKPOINT B** (final) — stop and hand over to Claude: commits, `npm run
build`/`lint` output, `git status`, and confirmation of the four checks in Step 6.
