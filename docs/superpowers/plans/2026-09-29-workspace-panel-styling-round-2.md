# Workspace Panel Styling Fixes, Round 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **This project:** Gemini executes the tasks in order; Claude reviews at each **REVIEW CHECKPOINT** before the next task starts. Stop at every checkpoint and hand over: commits, `npm run build` output, `git status`.

**Goal:** Fix the remaining issues from live review of `docs/superpowers/plans/2026-09-29-workspace-panel-styling.md`'s result: the Ledger timeline and "Coming soon" list still render with no real styling, the refresh button doesn't use the app's accent color, and Contract Profile page-citation links open the raw PDF in a new browser tab instead of the in-app pdf.js viewer.

**Architecture:** No new subsystem. Task 3 is CSS-only (Ledger timeline items, coming-soon list, refresh button color). Task 4 reuses the existing `DocumentViewer` component and its `.viewer-sheet` overlay presentation — already built and working on `Documents.tsx`/`Review.tsx` — from Contract Profile's page links, instead of building a new 3-column layout. The `.viewer-sheet` CSS moves from `Documents.css` into `DocumentViewer.css` since it's now shared by two screens (soon three): it styles how `DocumentViewer` is presented, so it belongs next to the component, not duplicated per screen.

**Tech Stack:** React (Vite) + TypeScript; plain CSS (existing design tokens only).

**Spec:** None — bounded change (existing, already-built screens; the viewer-integration decision was discussed and confirmed in chat on 2026-09-29: reuse the existing overlay pattern rather than build a new responsive 3-column layout, specifically to avoid two responsive systems — the panel's existing sub-1100px fixed-sheet behavior and a hypothetical new 3-column breakpoint — needing to be kept in sync).

## Global Constraints

- Branch `feat/demo-ready`. Never commit to `main`/`preview`. Stage files explicitly (never `git add -A`/`.`). Conventional commits. **No AI co-author line.** Do not push.
- TypeScript: no `any`; a props interface for every component.
- No new npm package.
- `cd frontend && npm run build` and `npm run lint` must pass with no new errors/warnings after the task.
- Use the design system's existing CSS custom properties only (`--color-accent`, `--color-accent-hover`, `--color-on-accent`, `--color-success`, `--color-warning`, `--radius-control`, `--space-*`, `--z-sheet`, `--color-shadow`, etc. — see `frontend/src/index.css`). Do not invent new tokens or hardcode colors.
- Reuse existing components/patterns before writing new ones — this plan exists specifically to avoid a second styled-overlay implementation.

## Review Focus

1. **The `.viewer-sheet` CSS move must not leave `Documents.tsx`/`Review.tsx` broken.** Moving CSS out of `Documents.css` into `DocumentViewer.css` must be a *move*, not a copy — verify both screens' existing "open the viewer" flow still renders correctly after the change (Task 4 Step 3).
2. **Ledger timeline badges must be readable against every `kind`,** not just the ones visible in a short demo document — check a document whose timeline includes an `ai_proposed`/`decided` pair (the Tremblay document, after the N15 walkthrough) alongside `ingested`/`extracted` (Task 3 Step 4).
3. **The refresh button's new accent-blue background must keep sufficient contrast** for the icon and "Refreshing…" label in both idle and `disabled` states — don't let `opacity: 0.6` on disabled make the icon unreadable against the blue (Task 3 Step 3).
4. **Opening the viewer from Contract Profile must not lose the current panel tab.** Closing the viewer should return to whichever tab (Profile, Billing reconciliation, Ledger, Audit trail) was active before it opened, not reset to the first tab (Task 4 Step 2).
5. **A field with `f.page === null`** (no page to cite) must not attempt to open the viewer — verify the existing `{f.page !== null && (...)}` guard is preserved when the `<a>` becomes a `<button>` (Task 4 Step 2).

---

### Task 3: Ledger timeline, coming-soon list, and refresh button styling

**Files:**
- Modify: `frontend/src/components/workspace/Workspace.css`, `frontend/src/components/workspace/LedgerTimeline.tsx`, `frontend/src/components/workspace/ContractProfile.tsx`

**Interfaces:**
- Consumes: existing `LockIcon` from `frontend/src/components/Icons.tsx` (already exists, used elsewhere in the app for "not yet" states).
- Produces: nothing consumed by later tasks — this task is self-contained.

- [ ] **Step 1: Refresh button — accent color**

In `frontend/src/components/workspace/Workspace.css`, replace the `.ws-refresh` rule block (added in the previous round):

```css
.ws-refresh {
  display: inline-flex; align-items: center; gap: 6px;
  background: var(--color-bg-subtle); border: 1px solid var(--color-border); border-radius: var(--radius-control);
  padding: 6px var(--space-2); color: var(--color-text-secondary); cursor: pointer;
  transition: background var(--motion-fast), color var(--motion-fast);
}
.ws-refresh:hover:not(:disabled) { background: var(--color-bg-muted); color: var(--color-text-primary); }
.ws-refresh:disabled { opacity: 0.6; cursor: not-allowed; }
```

with:

```css
.ws-refresh {
  display: inline-flex; align-items: center; gap: 6px;
  background: var(--color-accent); border: 1px solid var(--color-accent); border-radius: var(--radius-control);
  padding: 6px var(--space-2); color: var(--color-on-accent); cursor: pointer;
  transition: background var(--motion-fast), border-color var(--motion-fast);
}
.ws-refresh:hover:not(:disabled) { background: var(--color-accent-hover); border-color: var(--color-accent-hover); }
.ws-refresh:disabled { opacity: 0.6; cursor: not-allowed; }
```

(Leave the `.ws-refresh__icon--spin`/`@keyframes ws-spin` block right after it untouched.)

- [ ] **Step 2: Ledger timeline — real item styling**

In `frontend/src/components/workspace/LedgerTimeline.tsx`, the badge currently has no per-kind class. Change:

```tsx
            <div><span className="ws-badge">{KIND_LABEL[item.kind]}</span> {item.title}</div>
```

to:

```tsx
            <div><span className={`ws-badge ws-badge--${item.kind}`}>{KIND_LABEL[item.kind]}</span> {item.title}</div>
```

In `frontend/src/components/workspace/Workspace.css`, after the `.ws-timeline { ... }` rule (last line of the file), add:

```css
.ws-timeline__item { padding-bottom: var(--space-2); }
.ws-timeline__item:last-child { padding-bottom: 0; }
.ws-timeline__item > div:first-child { display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  font-size: 0.95em; font-weight: 500; color: var(--color-text-primary); }
.ws-timeline__item details { margin-top: 6px; font-size: 0.85em; }
.ws-timeline__item details summary { cursor: pointer; color: var(--color-text-secondary); }
.ws-timeline__item details ul { margin: 6px 0 0; padding-left: var(--space-3); }
.ws-timeline__item > a { display: inline-block; margin-top: 6px; font-size: 0.82em; font-weight: 600; color: var(--color-accent); }

.ws-badge--ingested { color: var(--color-text-secondary); }
.ws-badge--extracted { color: var(--color-accent); border-color: var(--color-accent); }
.ws-badge--reviewed { color: var(--color-accent); border-color: var(--color-accent); }
.ws-badge--ai_proposed { color: var(--color-warning); border-color: var(--color-warning); }
.ws-badge--decided { color: var(--color-accent); border-color: var(--color-accent); }
.ws-badge--posted { color: var(--color-success); border-color: var(--color-success); }
```

(Review Focus 2: these six kinds are exactly `KIND_LABEL`'s keys in `LedgerTimeline.tsx:6-9` — don't add or rename any.)

- [ ] **Step 3: "Coming soon" list — replace the redundant badge with an icon, add contrast**

The section header already says "Coming soon" (`<h3>Coming soon</h3>`), so repeating "Coming soon" as a badge on every single item is redundant clutter. Replace it with the existing lock icon instead — the same visual language the app already uses elsewhere for not-yet-available/locked states.

In `frontend/src/components/workspace/ContractProfile.tsx`, add `LockIcon` to the import on line 1:

```tsx
import { useEffect, useState } from 'react';
import { type TermFieldDto, type TermsDto, documentPageUrl, getTerms } from '../../api';
```

becomes:

```tsx
import { useEffect, useState } from 'react';
import { type TermFieldDto, type TermsDto, documentPageUrl, getTerms } from '../../api';
import { LockIcon } from '../Icons';
```

Then change the coming-soon list item (near the end of the file):

```tsx
            <li key={id}>{COMING_SOON_LABEL[id] ?? id} <span className="ws-badge">Coming soon</span></li>
```

to:

```tsx
            <li key={id}><LockIcon size={12} /> {COMING_SOON_LABEL[id] ?? id}</li>
```

In `frontend/src/components/workspace/Workspace.css`, replace the `.ws-muted li` rule:

```css
.ws-muted li { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2);
  padding: 6px var(--space-2); border: 1px dashed var(--color-border); border-radius: var(--radius-control);
  font-size: 0.85em; color: var(--color-text-secondary); }
```

with:

```css
.ws-muted li { display: flex; align-items: center; gap: 8px; padding: 8px var(--space-2);
  border: 1px dashed var(--color-border); border-radius: var(--radius-control); background: var(--color-bg-subtle);
  font-size: 0.85em; color: var(--color-text-secondary); }
```

- [ ] **Step 4: Build, lint, and manual check**

Run: `cd frontend && npm run build` → no errors. Run: `npm run lint` → no new warnings.

In the browser: open the Tremblay document's Ledger tab (has a full `ingested → extracted → ai_proposed → decided → posted` chain after the N15 walkthrough — if it doesn't, ask a reconciliation question and approve the proposal first, same as the N15 demo script). Confirm each badge has a distinct color (Review Focus 2), items have breathing room between them, the "Entries" `<details>` disclosure and "View in ledger →" link are clearly separated from the row above. Then check the Coming soon list on any document's Profile tab: each item shows a small lock icon, no redundant "Coming soon" text repeated per row, and a subtle background tint. Then check the refresh button's disabled state (mid-refresh) is still legible (Review Focus 3).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/workspace/Workspace.css frontend/src/components/workspace/LedgerTimeline.tsx frontend/src/components/workspace/ContractProfile.tsx
git commit -m "fix(frontend): style the ledger timeline and coming-soon list, accent the refresh button"
```

**REVIEW CHECKPOINT A** — stop and hand over to Claude: commits, `npm run build`/`lint` output, `git status`, and the manual check results from Step 4.

---

### Task 4: Contract Profile page links open the in-app viewer instead of a new tab

**Files:**
- Modify: `frontend/src/screens/Documents.css`, `frontend/src/components/DocumentViewer/DocumentViewer.css`, `frontend/src/components/workspace/ContractProfile.tsx`, `frontend/src/screens/Chat.tsx`

**Interfaces:**
- Consumes: `DocumentViewer` (lazy-loaded from `frontend/src/components/DocumentViewer/index.ts`, unchanged: `{ documentId, version, page, title, onClose }`).
- Produces: `ContractProfile`'s new `onOpenPage?: (documentId: string, version: number, page: number) => void` prop — optional so `ContractProfile` still works if a future caller doesn't wire a viewer.

- [ ] **Step 1: Move `.viewer-sheet` from `Documents.css` to `DocumentViewer.css`**

It styles how `DocumentViewer` is presented as an overlay — that's the component's own concern, not each screen's. Moving it (not copying) means every screen that renders `<div className="viewer-sheet"><DocumentViewer .../></div>` gets the same overlay for free.

In `frontend/src/screens/Documents.css`, **delete** this whole block (currently near the end of the file):

```css
.viewer-sheet {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: min(760px, 100vw);
  z-index: var(--z-sheet);
  border-left: 1px solid var(--color-border);
  box-shadow: -4px 0 8px var(--color-shadow);
  background: var(--color-bg-subtle);
}

.viewer-sheet__loading {
  padding: var(--space-3);
  font-size: 13px;
  color: var(--color-text-secondary);
}

@media (prefers-reduced-motion: no-preference) {
  .viewer-sheet {
    animation: viewer-sheet-in 200ms cubic-bezier(0.22, 1, 0.36, 1);
  }

  @keyframes viewer-sheet-in {
    from {
      transform: translateX(24px);
      opacity: 0;
    }
    to {
      transform: none;
      opacity: 1;
    }
  }
}

@media (max-width: 860px) {
  .viewer-sheet {
    bottom: 64px;
  }
}
```

In `frontend/src/components/DocumentViewer/DocumentViewer.css`, **append** that exact same block, unchanged, at the end of the file. (The `@media (max-width: 860px) { .viewer-sheet { bottom: 64px; } }` rule was there to clear `Documents.tsx`'s bottom nav on mobile — keep it; it's harmless on screens without that nav, since the selector simply won't matter there.)

- [ ] **Step 2: `ContractProfile.tsx` — page links call back instead of navigating**

Add an `onOpenPage` prop. Change the `ContractProfileProps` interface (near the top of the file):

```tsx
interface ContractProfileProps {
  documentId: string;
}
```

to:

```tsx
interface ContractProfileProps {
  documentId: string;
  onOpenPage?: (documentId: string, version: number, page: number) => void;
}
```

Update the function signature:

```tsx
export function ContractProfile({ documentId }: ContractProfileProps) {
```

to:

```tsx
export function ContractProfile({ documentId, onOpenPage }: ContractProfileProps) {
```

Replace the page-link block (inside the `GROUPS.map` section):

```tsx
                    {f.page !== null && (
                      <a className="ws-field__page" href={documentPageUrl(terms.document_id, terms.version, f.page)} target="_blank" rel="noreferrer">
                        Page {f.page} →
                      </a>
                    )}
```

with:

```tsx
                    {f.page !== null && (
                      onOpenPage ? (
                        <button type="button" className="ws-field__page ws-field__page--button"
                                onClick={() => onOpenPage(terms.document_id, terms.version, f.page as number)}>
                          Page {f.page} →
                        </button>
                      ) : (
                        <a className="ws-field__page" href={documentPageUrl(terms.document_id, terms.version, f.page)} target="_blank" rel="noreferrer">
                          Page {f.page} →
                        </a>
                      )
                    )}
```

(Review Focus 5: the `f.page !== null` guard is unchanged — both branches are still inside it. The `documentPageUrl` import stays, since the fallback `<a>` branch still needs it for any caller that doesn't pass `onOpenPage`.)

In `frontend/src/components/workspace/Workspace.css`, add a rule so the new `<button>` looks identical to the existing `<a>` (no browser default button chrome):

```css
.ws-field__page--button { background: none; border: none; padding: 0; font: inherit; cursor: pointer; text-align: left; }
```

- [ ] **Step 3: `Chat.tsx` — render the viewer, wire the callback**

Add `Suspense` to the React import (line 1):

```tsx
import { useCallback, useEffect, useRef, useState } from 'react';
```

becomes:

```tsx
import { Suspense, useCallback, useEffect, useRef, useState } from 'react';
```

Add the `DocumentViewer` import, after the existing workspace imports:

```tsx
import { DocumentViewer } from '../components/DocumentViewer';
```

Add viewer state, right after the existing `useState` declarations in `Chat()` (after `const [indexedCount, setIndexedCount] = useState<number | null>(null);`):

```tsx
  const [viewer, setViewer] = useState<{ documentId: string; version: number; page: number; title: string } | null>(null);
```

Pass `onOpenPage` into `ContractProfile` in the `tabs` array — change:

```tsx
      { id: 'profile', label: 'Profile', content: <ContractProfile documentId={scopeId} /> },
```

to:

```tsx
      {
        id: 'profile',
        label: 'Profile',
        content: (
          <ContractProfile
            documentId={scopeId}
            onOpenPage={(id, version, page) => setViewer({ documentId: id, version, page, title: scoped?.title ?? 'Document' })}
          />
        ),
      },
```

(Review Focus 4: `viewer` state lives in `Chat`, entirely separate from `DocumentPanel`'s own internal `activeId` state — opening or closing the viewer never touches which panel tab is selected, so the previously-active tab is exactly where it was when the viewer closes. No extra code needed for this — it falls out of keeping the two pieces of state independent.)

Finally, render the overlay. Find the closing of the `.ws-layout` div near the end of the component:

```tsx
        {(panelOpen || window.matchMedia('(min-width: 1100px)').matches) && <DocumentPanel tabs={tabs} />}
      </div>
    </div>
  );
}
```

Replace with:

```tsx
        {(panelOpen || window.matchMedia('(min-width: 1100px)').matches) && <DocumentPanel tabs={tabs} />}
      </div>
      {viewer && (
        <div className="viewer-sheet" role="dialog" aria-modal="false" aria-label={`${viewer.title} viewer`}>
          <Suspense fallback={<p className="viewer-sheet__loading">Loading viewer…</p>}>
            <DocumentViewer
              documentId={viewer.documentId}
              version={viewer.version}
              page={viewer.page}
              title={viewer.title}
              onClose={() => setViewer(null)}
            />
          </Suspense>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Build, lint, and manual check**

Run: `cd frontend && npm run build` → no errors. Run: `npm run lint` → no new warnings.

In the browser:
1. Open `/documents`, open any document's viewer the existing way — confirm it still renders identically to before (Review Focus 1: the CSS move didn't break it).
2. Open `/chat`, select a document, open the Profile tab, click a "Page N →" link — the in-app viewer opens as a right-side overlay on the correct page, not a new browser tab.
3. Close the viewer (X button or Escape, if `DocumentViewer` supports it — check `onClose` wiring) — confirm you land back on the same panel tab you had open (Profile), not reset to a different one (Review Focus 4).
4. A field with no page (`f.page === null`, e.g. an unextracted/coming-soon field never reaches this code path at all, but any accepted field whose extractor didn't return a page — check the API response if unsure) renders no page control at all, not a broken button.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/screens/Documents.css frontend/src/components/DocumentViewer/DocumentViewer.css frontend/src/components/workspace/ContractProfile.tsx frontend/src/components/workspace/Workspace.css frontend/src/screens/Chat.tsx
git commit -m "feat(frontend): open contract profile page citations in the in-app viewer"
```

**REVIEW CHECKPOINT B** (final) — stop and hand over to Claude: commits, `npm run build`/`lint` output, `git status`, and confirmation of the four checks in Step 4.
