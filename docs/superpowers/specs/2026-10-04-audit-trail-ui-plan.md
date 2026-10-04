# Chat side panel restyle - spec

## Goal
Bring the four panes of the chat side panel (Profile, Billing reconciliation, Ledger, Audit trail) closer to
`artifacts/ui-updates/audit-trail/ui-update.png`, as a presentation-only change.

## Rule: nothing invented
The mockup contains elements the product has no data for. They are out of scope until the backend supplies them:
status dots ("Synchronized", "Stream Active", "Discrepancy Detected"), footer strips (checksums, "Provenance sealed"),
`VERIFIED 100%`, `AES-GCM-256`, entity IDs, per-row sha256 hashes, latency, the "zero state spec preview" block, the
rate-bracket comparison table, the variance box and the "Draft compensating entry" button.

Every piece of text and data on screen after this change was on screen before it. No API, DTO, route or state change.

## What changes
- **Header band** (`DocumentPanel.tsx`, `RefreshButton.tsx`): tinted band with `VIEWING` and the pane name in a pill.
  Each pane's own title and description sit in a `.ws-pane__intro` block that continues the band. Refresh is an
  icon-only bordered button.
- **Refresh placement**: the button is still rendered by the pane that owns the reload (so the spinner and disabled
  state are unchanged) and is anchored into the band with CSS (`.ws-refresh` is absolutely positioned against
  `.ws-panel`). If this proves fragile, the alternative is lifting refresh into `DocumentPanel` via `PanelTab`.
- **Profile** (`ContractProfile.tsx`): one card per field, status pill on the right, mono page link, Presidio tokens
  in the mono accent style. Existing groups are kept.
- **Billing reconciliation** (`BillingReconciliation.tsx`): schedule card with the rates large and the version and
  method as a chip.
- **Ledger** (`LedgerTimeline.tsx`) and **Audit trail** (`AuditLog.tsx`): shared rail, one dot and one card per event
  (`.ws-timeline`, `.ws-event`). Dot colour follows the event kind (ledger) or the human decision (audit).

## Files
`frontend/src/components/workspace/`: `Workspace.css`, `DocumentPanel.tsx`, `RefreshButton.tsx`,
`ContractProfile.tsx`, `BillingReconciliation.tsx`, `LedgerTimeline.tsx`, `AuditLog.tsx`. `Chat.tsx` is untouched.

## Verification
`tsc -b` and `vite build`, then screenshots of all four panes at 1400px and a check that the panel is still a fixed
drawer below 1100px.
