# Landing Hero Flow Diagram Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **This project:** Gemini executes the tasks in order; Claude reviews at each **REVIEW CHECKPOINT** before the next task starts. Stop at every checkpoint and hand over: commits, `npm run build` output, `git status`.

**Goal:** Replace the landing hero's 3-frame crossfading card (built for backlog N18) with a 4-node animated flow diagram, modeled on the mechanic in Modern Treasury's stablecoin-payments hero (`artifacts/modern_treasury.webm`, reviewed frame-by-frame on 2026-09-29): a source card and a destination card, connected through two inner "hub" cards with an exchange icon between them; each node highlights and its number counts up in sequence, left to right, then the whole thing resets and loops.

**Architecture:** A new self-contained component, `HeroFlow`, replaces the `<figure className="landing__compare">` block in `Landing.tsx`. A small custom hook, `useCountUp`, drives the animated numbers — this is the one place in the app's marketing/landing code that needs JavaScript-driven animation rather than pure CSS, because CSS cannot interpolate text content. A single `phase` state (0–6) advanced by a chained `setTimeout` drives which node is "active" at any moment; every visual (border highlight, traveling dot, counting number) is a pure function of that one integer, mirroring how N18's crossfade was driven by CSS keyframe phase math — same idea, moved to JS because this design needs live numbers, not opacity.

**Tech Stack:** React (Vite) + TypeScript; plain CSS (existing design tokens only); no animation library, no new npm dependency — confirmed in the 2026-09-29 chat discussion that consulted the `motion` skill for the original hero and reached the same conclusion here (a `requestAnimationFrame`-driven counter is a few lines; pulling in a library for one component would be the wrong tool).

**Spec:** None — bounded change (replaces one section of an already-built, already-approved page; no new subsystem, no interface other code depends on). Reviewed against the Modern Treasury reference video and confirmed with the user in chat on 2026-09-29: node mapping (Agreement → Contract states ⇄ Billing charges → Ledger) and the JS-counter approach were both explicitly approved before this plan was written.

## Global Constraints

- Branch `feat/demo-ready`. Never commit to `main`/`preview`. Stage files explicitly (never `git add -A`/`.`). Conventional commits. **No AI co-author line.** Do not push.
- TypeScript: no `any`; a props interface for every component.
- No new npm package.
- `cd frontend && npm run build` and `npm run lint` must pass with no new errors/warnings.
- Use the design system's existing CSS custom properties only (`--color-bg-dark`, `--color-surface-dark`, `--color-border-dark`, `--color-text-primary-dark`, `--color-text-secondary-dark`, `--color-accent`, `--color-accent-tint`, `--color-on-accent`, `--radius-card`, `--radius-pill`, `--space-*`, etc. — see `frontend/src/index.css`). Do not invent new tokens or hardcode colors. This is the dark hero section (`.landing__hero` sets `background: var(--color-bg-dark)`), so use the `-dark` token variants exactly as `.landing__compare*` did before it.
- Respect `prefers-reduced-motion: reduce` — in that mode, `HeroFlow` must render fully settled (final numbers shown immediately, no per-phase highlighting, no traveling dot, no exchange-icon pulse), matching the precedent already set by N18's landing hero animation and the round-2 workspace panel work.
- The real numbers used (0.85% contract rate, 0.80% billing rate, $400.00 posted correction) are the actual `compare_contract_to_billing` result verified live against the Tremblay household on 2026-09-29 (backlog N15) — not invented placeholder copy. Keep them exact.
- `aria-hidden="true"` on the whole diagram, same reasoning as N18: it's decorative and duplicates the accessible `landing__layers` list already on the page (Ops/Governance/Audit) — don't remove that list or its accessibility role.

## Review Focus

1. **The reduced-motion path must be a genuinely static end-state, not a paused animation.** A `setTimeout`-driven phase machine that simply doesn't advance would leave the diagram frozen mid-cycle (e.g. only the source card highlighted, other values at 0). Verify the reduced-motion render shows every value at its *final* number with no highlighting active anywhere (Task 1 Step 5).
2. **The `useCountUp` hook must reset to 0 when its node's phase ends, not hold its last value into the next loop**, so the recount is visible every cycle (matches the reference video's behavior) — verify by watching a full loop, not just the first one (Task 1 Step 6).
3. **The traveling dot's animation duration must exactly match the phase duration it's rendered during**, or it will visibly freeze mid-connector when React unmounts it at the phase boundary. Both dot phases are deliberately set to the same 1200ms in `PHASE_DURATIONS_MS` — don't let the two drift out of sync if either is changed (Task 1 Step 3).
4. **Removing `.landing__compare*` from `Landing.css` must not leave orphaned rules** that reference classes no longer in `Landing.tsx` (or, conversely, leave `Landing.tsx` referencing removed classes) — grep both directions after the edit (Task 1 Step 4).
5. **Narrow viewports (< 640px)**: four cards plus two connectors is a lot of horizontal content — verify the mobile stacked layout doesn't overflow or clip the hub's inner cards (Task 1 Step 6).

---

### Task 1: Build and wire in the hero flow diagram

**Files:**
- Create: `frontend/src/lib/useCountUp.ts`, `frontend/src/components/HeroFlow.tsx`, `frontend/src/components/HeroFlow.css`
- Modify: `frontend/src/screens/Landing.tsx`, `frontend/src/screens/Landing.css`

**Interfaces:**
- Consumes: `DocumentsIcon`, `LedgerIcon`, `RefreshIcon` from `frontend/src/components/Icons.tsx` (all already exist, unchanged).
- Produces: `useCountUp(target: number, active: boolean, durationMs: number, reduced: boolean): number`; `HeroFlow` (no props — self-contained, like the figure it replaces).

- [ ] **Step 1: The counter hook** — `frontend/src/lib/useCountUp.ts`:

```ts
import { useEffect, useRef, useState } from 'react';

/** Counts 0 → target over durationMs while active; resets to 0 when inactive; jumps straight to
 * target when reduced (no animation at all, per prefers-reduced-motion). */
export function useCountUp(target: number, active: boolean, durationMs: number, reduced: boolean): number {
  const [value, setValue] = useState(reduced ? target : 0);
  const frameRef = useRef<number | null>(null);

  useEffect(() => {
    if (reduced) {
      setValue(target);
      return;
    }
    if (!active) {
      setValue(0);
      return;
    }
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs);
      setValue(target * t);
      if (t < 1) frameRef.current = requestAnimationFrame(tick);
    };
    frameRef.current = requestAnimationFrame(tick);
    return () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    };
  }, [active, target, durationMs, reduced]);

  return value;
}
```

- [ ] **Step 2: The component** — `frontend/src/components/HeroFlow.tsx`:

```tsx
import { useEffect, useState } from 'react';
import { DocumentsIcon, LedgerIcon, RefreshIcon } from './Icons';
import { useCountUp } from '../lib/useCountUp';
import './HeroFlow.css';

// ponytail: a fixed 7-phase timeline for this one diagram, not a general animation engine.
// Phases: 0 source lit, 1 dot travels left, 2 contract rate counts up, 3 exchange icon pulses,
// 4 billing rate counts up, 5 dot travels right, 6 ledger lit + posted amount counts up (then holds).
const PHASE_DURATIONS_MS = [1200, 1200, 1800, 900, 1800, 1200, 2400];
const PHASE_COUNT = PHASE_DURATIONS_MS.length;

const CONTRACT_RATE = 0.85;
const BILLING_RATE = 0.8;
const POSTED_AMOUNT = 400;

function prefersReducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function useFlowPhase(reduced: boolean): number {
  const [phase, setPhase] = useState(0);
  useEffect(() => {
    if (reduced) return;
    const timer = setTimeout(() => setPhase((p) => (p + 1) % PHASE_COUNT), PHASE_DURATIONS_MS[phase]);
    return () => clearTimeout(timer);
  }, [phase, reduced]);
  return phase;
}

export function HeroFlow() {
  const [reduced] = useState(prefersReducedMotion);
  const phase = useFlowPhase(reduced);

  const sourceActive = !reduced && phase === 0;
  const dotLeft = !reduced && phase === 1;
  const contractCounting = !reduced && phase >= 2;
  const exchangeActive = !reduced && phase === 3;
  const billingCounting = !reduced && phase >= 4;
  const dotRight = !reduced && phase === 5;
  const ledgerActive = !reduced && phase === 6;

  const contractRate = useCountUp(CONTRACT_RATE, contractCounting, 1800, reduced);
  const billingRate = useCountUp(BILLING_RATE, billingCounting, 1800, reduced);
  const posted = useCountUp(POSTED_AMOUNT, ledgerActive, 1400, reduced);

  return (
    <div className="hero-flow" aria-hidden="true">
      <div className="hero-flow__row">
        <div className="hero-flow__node">
          <span className="hero-flow__label">Agreement</span>
          <div className={`hero-flow__card${sourceActive ? ' hero-flow__card--active' : ''}`}>
            <DocumentsIcon size={20} />
            <span className="hero-flow__value mono">§3 Fees · p.2</span>
          </div>
        </div>

        <div className="hero-flow__connector">{dotLeft && <span className="hero-flow__dot" />}</div>

        <div className="hero-flow__hub">
          <span className="hero-flow__label">Reconciliation</span>
          <div className="hero-flow__hub-inner">
            <div className="hero-flow__card hero-flow__card--inner">
              <span className="hero-flow__inner-label">Contract states</span>
              <span className="hero-flow__value mono">{contractRate.toFixed(2)}%</span>
            </div>
            <div className={`hero-flow__exchange${exchangeActive ? ' hero-flow__exchange--active' : ''}`}>
              <RefreshIcon size={16} />
            </div>
            <div className="hero-flow__card hero-flow__card--inner">
              <span className="hero-flow__inner-label">Billing charges</span>
              <span className="hero-flow__value mono">{billingRate.toFixed(2)}%</span>
            </div>
          </div>
        </div>

        <div className="hero-flow__connector">{dotRight && <span className="hero-flow__dot" />}</div>

        <div className="hero-flow__node">
          <span className="hero-flow__label">Ledger</span>
          <div className={`hero-flow__card${ledgerActive ? ' hero-flow__card--active' : ''}`}>
            <LedgerIcon size={20} />
            <span className="hero-flow__value mono">${posted.toFixed(2)}</span>
          </div>
        </div>
      </div>

      <ul className="hero-flow__chips">
        <li>PII tokenized locally</li>
        <li>Contract ↔ billing, always compared</li>
        <li>Human approval required</li>
        <li>Full audit trail</li>
      </ul>
    </div>
  );
}
```

(Review Focus 2: `contractCounting`/`billingCounting` are `phase >= 2`/`phase >= 4` — both false again the instant `phase` wraps to `0`, which is what drives `useCountUp`'s `!active` branch back to `0`. Don't "simplify" this to a one-shot flag that stays true after the first counted cycle.)

- [ ] **Step 3: The stylesheet** — `frontend/src/components/HeroFlow.css`:

```css
.hero-flow {
  width: 100%;
  max-width: 860px;
  margin: 0 auto;
}

.hero-flow__row {
  display: grid;
  grid-template-columns: 1fr auto 1.6fr auto 1fr;
  align-items: center;
  gap: var(--space-2);
}

.hero-flow__node,
.hero-flow__hub {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.hero-flow__label {
  font-size: 11px;
  color: var(--color-text-secondary-dark);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.hero-flow__card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: var(--space-2);
  border: 1px dashed transparent;
  border-radius: var(--radius-card);
  background: var(--color-surface-dark);
  min-width: 120px;
  transition: border-color 200ms ease;
}

.hero-flow__card--active {
  border-color: var(--color-accent);
}

.hero-flow__card--inner {
  min-width: 100px;
  background: var(--color-bg-dark);
}

.hero-flow__inner-label {
  font-size: 10px;
  color: var(--color-text-secondary-dark);
}

.hero-flow__value {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-primary-dark);
}

.hero-flow__connector {
  position: relative;
  height: 2px;
  min-width: 32px;
  background: var(--color-border-dark);
}

.hero-flow__dot {
  position: absolute;
  top: 50%;
  left: 0;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-accent);
  transform: translateY(-50%);
}

.hero-flow__hub-inner {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2);
  background: var(--color-accent-tint);
  border-radius: var(--radius-card);
}

.hero-flow__exchange {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--color-surface-dark);
  color: var(--color-text-secondary-dark);
  flex-shrink: 0;
  transition: background 200ms ease, color 200ms ease;
}

.hero-flow__exchange--active {
  background: var(--color-accent);
  color: var(--color-on-accent);
}

.hero-flow__chips {
  list-style: none;
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--space-2);
  margin: var(--space-3) 0 0;
  padding: 0;
  font-size: 12px;
  color: var(--color-text-secondary-dark);
}

.hero-flow__chips li {
  padding: 4px 10px;
  border: 1px solid var(--color-border-dark);
  border-radius: var(--radius-pill);
}

@media (prefers-reduced-motion: no-preference) {
  @keyframes hero-flow-rise {
    from {
      opacity: 0;
      transform: translateY(8px);
    }
    to {
      opacity: 1;
      transform: none;
    }
  }

  .hero-flow {
    animation: hero-flow-rise 400ms cubic-bezier(0.22, 1, 0.36, 1) 150ms both;
  }

  /* Review Focus 3: both dot phases are 1200ms in PHASE_DURATIONS_MS — this duration must match. */
  .hero-flow__dot {
    animation: hero-flow-travel 1200ms linear forwards;
  }

  @keyframes hero-flow-travel {
    from {
      left: 0%;
      opacity: 0;
    }
    10% {
      opacity: 1;
    }
    90% {
      opacity: 1;
    }
    to {
      left: 100%;
      opacity: 0;
    }
  }
}

@media (max-width: 640px) {
  .hero-flow__row {
    grid-template-columns: none;
    display: flex;
    flex-direction: column;
  }

  .hero-flow__connector {
    width: 2px;
    height: 20px;
    min-width: 0;
  }

  .hero-flow__dot {
    display: none;
  }

  .hero-flow__hub-inner {
    flex-direction: column;
  }
}
```

- [ ] **Step 4: Wire it into the Landing page, remove the old crossfade markup**

In `frontend/src/screens/Landing.tsx`, change the import line:

```tsx
import { CheckIcon, LockIcon, SparkleIcon } from '../components/Icons';
```

to:

```tsx
import { CheckIcon, SparkleIcon } from '../components/Icons';
import { HeroFlow } from '../components/HeroFlow';
```

(`LockIcon` was only used inside the figure this task removes — drop it. `CheckIcon` stays; it's still used in the `GUARANTEES` list further down the page.)

Replace the entire `<figure className="landing__compare">...</figure>` block (currently lines 76–130, right after the `landing__layers` list and before the `</section>` that closes `landing__hero`) with:

```tsx
        <HeroFlow />
```

In `frontend/src/screens/Landing.css`, delete every one of these rules (all exist only to style the removed figure — Review Focus 4, grep for `landing__compare` and `landing-frame-cycle`/`landing-dot-cycle`/`landing-rise` in both files afterward to confirm zero remaining references either direction):

```css
.landing__compare {
  margin: 0;
  width: 100%;
  max-width: 760px;
  text-align: left;
  border: 1px solid var(--color-border-dark);
  border-radius: var(--radius-card);
  background: var(--color-surface-dark);
  overflow: hidden;
}

.landing__compare-caption {
  display: block;
  font-size: 11px;
  color: var(--color-text-secondary-dark);
  padding: 10px var(--space-2);
  border-bottom: 1px solid var(--color-border-dark);
}

.landing__compare-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
}

.landing__compare-col {
  padding: var(--space-2);
}

.landing__compare-col + .landing__compare-col {
  border-left: 1px solid var(--color-border-dark);
}

.landing__compare-source {
  display: block;
  font-size: 11px;
  color: var(--color-text-secondary-dark);
  margin-bottom: 8px;
}

.landing__compare-quote {
  font-size: 15px;
  line-height: 1.5;
}

.landing__compare-billed {
  font-size: 15px;
}

.landing__compare-gap {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  flex-wrap: wrap;
  padding: 12px var(--space-2);
  border-top: 1px solid var(--color-border-dark);
  background: var(--color-accent-tint);
}

.landing__compare-frames {
  display: block;
}

.landing__compare-frame {
  border-top: 1px solid var(--color-border-dark);
}

.landing__compare-frame:first-child {
  border-top: none;
}

.landing__compare-proposal {
  padding: var(--space-2);
}

.landing__compare-entry {
  font-size: 15px;
  line-height: 1.5;
}

.landing__compare-dots {
  display: none;
}

.landing__gap-amount {
  font-size: 16px;
  font-weight: 600;
}

.landing__gap-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--color-text-secondary-dark);
}
```

Also delete, inside the `@media (max-width: 860px) { ... }` block, this rule (leave the rest of that media block — the `.landing__nav`, `.landing__nav-links`, `.landing__hero`, and `.landing__section--split` rules inside it are unrelated and stay):

```css
  .landing__compare-grid,
  .landing__section--split {
    grid-template-columns: 1fr;
  }

  .landing__compare-col + .landing__compare-col {
    border-left: none;
    border-top: 1px solid var(--color-border-dark);
  }
```

replacing it with just:

```css
  .landing__section--split {
    grid-template-columns: 1fr;
  }
```

Finally, delete the entire trailing `@media (prefers-reduced-motion: no-preference) { ... }` block at the end of the file (the `landing-rise`/`landing-frame-cycle`/`landing-dot-cycle` keyframes and the rules that used them) — every rule in it belonged to the removed figure. `HeroFlow.css` has its own self-contained reduced-motion handling now.

- [ ] **Step 5: Build, lint, and reduced-motion check**

Run: `cd frontend && npm run build` → no errors. Run: `npm run lint` → no new warnings.

In the browser with DevTools' Rendering tab set to "Emulate CSS media feature prefers-reduced-motion: reduce": reload `/`. Confirm (Review Focus 1): the diagram shows `0.85%`, `0.80%`, and `$400.00` immediately, no card has the accent dashed border, no dot is visible, and the exchange icon is in its resting (not accent-filled) color. Set it back to "No emulation" afterward.

- [ ] **Step 6: Full-motion and mobile verification**

With no reduced-motion emulation: watch at least one full ~10.8s loop. Confirm, in order: the Agreement card gets a dashed accent border; a dot travels the left connector; "Contract states" counts up from 0.00% to 0.85%; the exchange icon fills accent-colored briefly; "Billing charges" counts up from 0.00% to 0.80%; a dot travels the right connector; the Ledger card gets the dashed border and "$0.00" counts up to "$400.00"; everything holds briefly, then resets to the start and the whole cycle repeats with every number genuinely recounting from 0 (Review Focus 2) — not just re-appearing at its old value.

Resize to 375px width: confirm the diagram stacks vertically, the hub's two inner cards and the exchange icon between them don't overflow or clip (Review Focus 5).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/useCountUp.ts frontend/src/components/HeroFlow.tsx frontend/src/components/HeroFlow.css frontend/src/screens/Landing.tsx frontend/src/screens/Landing.css
git commit -m "feat(frontend): replace the landing hero card with an animated reconciliation flow diagram"
```

**REVIEW CHECKPOINT A** (final) — stop and hand over to Claude: commits, `npm run build`/`lint` output, `git status`, and confirmation of the Step 5 and Step 6 checks.
