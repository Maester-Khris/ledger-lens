# Landing Hero Animation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **This project:** Gemini executes the tasks in order; Claude reviews at each **REVIEW CHECKPOINT** before the next task starts. Stop at every checkpoint and hand over: commits, `npm run build` output, `git status`.

**Goal:** Turn the landing hero's static "Example comparison" card into a looping 3-frame animated visual that illustrates the same ops → governance → audit story the hero's `landing__layers` list already tells in prose (backlog N18).

**Architecture:** No new component, no new dependency. The existing `<figure className="landing__compare">` in `Landing.tsx` gains three content frames (ops / governance / audit) stacked in one CSS grid cell. Under `prefers-reduced-motion: no-preference`, each frame gets a `@keyframes` opacity cycle on a shared 9s loop, staggered 3s apart, plus three small dots below the card that track which frame is active via the same keyframe timing. With no explicit motion preference set to "no preference" (i.e. `reduce`, or unsupported), none of that CSS applies and the three frames render as an always-visible static stack, exactly like the rest of the page's lists.

**Tech Stack:** React (Vite) + TypeScript; plain CSS (no animation library — see below).

**Spec:** None — classified as a bounded change during brainstorming (a well-scoped extension of an existing, already-built hero section, not a new subsystem) and approved in chat on 2026-09-28. This plan carries the full design in place of a separate spec file.

**Design record (why no animation library):** The `motion` skill was consulted and explicitly rules this case out — its own guidance lists "simple list animations" and "static content without interactions" under "Don't use Motion". This card has no drag, gesture, scroll-trigger, or layout-FLIP need; it's a passive looping crossfade, which plain CSS handles natively. Pulling in `motion` (34 KB, or 4.6 KB with LazyMotion) for this would also violate the project's "no new npm package without noting it" rule and the backlog's explicit "CSS/SVG animation first" instruction for N18.

## Global Constraints

- Read `CLAUDE.md` and `CLAUDE.local.md` first.
- Branch `feat/demo-ready`. Never commit to `main`/`preview`. Stage files explicitly (never `git add -A`/`.`). Conventional commits. **No AI co-author line.** Do not push.
- TypeScript: no `any`; a props interface for every component touched (none are added here, but any component this plan touches must keep its existing interface intact).
- No new npm package.
- `cd frontend && npm run build` (`tsc -b && vite build`) must pass with no errors after every task.
- CSS/SVG animation only (backlog N18); respect `prefers-reduced-motion`.
- Use the design system's existing CSS custom properties only (`--color-accent`, `--color-border-dark`, `--color-accent-tint`, `--space-*`, etc. — see `frontend/src/index.css` and `frontend/src/screens/Landing.css`). Do not invent new tokens or hardcode colors.
- Working labels already established by the fintech reframing (do not rephrase): "Correction proposed · awaiting approval", "AI decision audit trail", "GL export".

## Review Focus

1. **`prefers-reduced-motion: reduce` (or an environment where the media query doesn't match `no-preference`)**: all three frames must render fully, statically, stacked in normal document flow — never stuck showing only the first frame or overlapping illegibly. Task 1 Step 6 checks this by inspecting the base (non-media-query) CSS renders all three frames unconditionally.
2. **No layout shift/height jump between frames**: the three frames have different content (a 2-column grid vs. a single line of mono text) and must not resize the card as they cycle. Task 1 uses a single-grid-cell stacking technique (`grid-area: 1 / 1` on every frame) specifically because it auto-sizes to the tallest frame with no hardcoded height — Task 1 Step 6 checks this visually.
3. **Narrow viewport (375px–420px)**: the mono entry lines ("Trace a51f9c2e · GL export SHA-256 verified") must not overflow the card or force horizontal scroll. Task 1 Step 6 checks this at a mobile width.
4. **Screen readers should not get a looping, decorative animation read out or double narration of the same story** the `landing__layers` list right above already states accessibly. Task 1 marks the whole figure `aria-hidden="true"` — Task 1 Step 6 checks the visible text list above the card still carries the same ops/governance/audit narrative on its own.
5. **The backlog and changelog must reflect N18 as done**, per this project's convention that every changelog line links to its backlog item. Task 2 ticks `artifacts/product-backlog.md` N18 and adds the changelog scope line.

---

### Task 1: Animated 3-frame hero card (N18)

**Files:**
- Modify: `frontend/src/screens/Landing.tsx`, `frontend/src/screens/Landing.css`

**Interfaces:**
- Consumes: `CheckIcon`, `LockIcon` from `../components/Icons` (already imported in `Landing.tsx`).
- Produces: nothing consumed by other tasks — this task is self-contained.

- [ ] **Step 1: Replace the compare figure's contents in `frontend/src/screens/Landing.tsx`**

Find this block (currently lines 76–96):

```tsx
        <figure className="landing__compare" aria-label="Example: a contract compared with billing">
          <figcaption className="landing__compare-caption mono">Example comparison</figcaption>
          <div className="landing__compare-grid">
            <div className="landing__compare-col">
              <span className="landing__compare-source mono">Agreement · §3 Fees · p.2</span>
              <p className="landing__compare-quote">
                "1.00% per annum on the first $1,000,000 of assets under management"
              </p>
            </div>
            <div className="landing__compare-col">
              <span className="landing__compare-source mono">Billing schedule · household</span>
              <p className="landing__compare-billed mono">0.85% on the first $1,000,000</p>
            </div>
          </div>
          <div className="landing__compare-gap">
            <span className="mono landing__gap-amount">Annual gap 1,500.00 CAD</span>
            <span className="landing__gap-status">
              <LockIcon size={12} /> Correction proposed · awaiting approval
            </span>
          </div>
        </figure>
```

Replace it with:

```tsx
        <figure
          className="landing__compare"
          aria-label="Example: a contract compared with billing, reconciled and posted to the ledger"
          aria-hidden="true"
        >
          <figcaption className="landing__compare-caption mono">Example comparison</figcaption>
          <div className="landing__compare-frames">
            <div className="landing__compare-frame landing__compare-frame--ops">
              <div className="landing__compare-grid">
                <div className="landing__compare-col">
                  <span className="landing__compare-source mono">Agreement · §3 Fees · p.2</span>
                  <p className="landing__compare-quote">
                    "1.00% per annum on the first $1,000,000 of assets under management"
                  </p>
                </div>
                <div className="landing__compare-col">
                  <span className="landing__compare-source mono">Billing schedule · household</span>
                  <p className="landing__compare-billed mono">0.85% on the first $1,000,000</p>
                </div>
              </div>
              <div className="landing__compare-gap">
                <span className="mono landing__gap-amount">Annual gap 1,500.00 CAD</span>
              </div>
            </div>

            <div className="landing__compare-frame landing__compare-frame--governance">
              <div className="landing__compare-proposal">
                <span className="landing__compare-source mono">Proposed correcting entry</span>
                <p className="landing__compare-entry mono">Dr Fee receivable 1,500.00 · Cr Fee revenue 1,500.00</p>
              </div>
              <div className="landing__compare-gap">
                <span className="landing__gap-status">
                  <LockIcon size={12} /> Correction proposed · awaiting approval
                </span>
              </div>
            </div>

            <div className="landing__compare-frame landing__compare-frame--audit">
              <div className="landing__compare-proposal">
                <span className="landing__compare-source mono">Posted to the ledger</span>
                <p className="landing__compare-entry mono">Trace a51f9c2e · GL export SHA-256 verified</p>
              </div>
              <div className="landing__compare-gap">
                <span className="landing__gap-status">
                  <CheckIcon size={12} className="landing__check" /> Approved · posted once
                </span>
              </div>
            </div>
          </div>
          <div className="landing__compare-dots">
            <span className="landing__compare-dot landing__compare-dot--ops" />
            <span className="landing__compare-dot landing__compare-dot--governance" />
            <span className="landing__compare-dot landing__compare-dot--audit" />
          </div>
        </figure>
```

No new imports needed — `CheckIcon` and `LockIcon` are already imported at the top of the file.

- [ ] **Step 2: Add the static (reduced-motion-safe) frame styles**

In `frontend/src/screens/Landing.css`, find the existing `.landing__compare-gap` rule block (it ends right before `.landing__gap-amount`). Immediately after the closing `}` of `.landing__compare-gap`, and before `.landing__gap-amount`, insert:

```css
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
```

This is the fallback that always applies: three frames stacked in normal document flow, separated by the same hairline rule the rest of the page uses (see `.landing__guarantees li` for the identical pattern), no animation, no dots. It is correct on its own for `prefers-reduced-motion: reduce` and for any browser that doesn't evaluate the media query in Step 3.

- [ ] **Step 3: Add the animated variant, gated behind `prefers-reduced-motion: no-preference`**

At the very end of `frontend/src/screens/Landing.css`, there is already this block:

```css
@media (prefers-reduced-motion: no-preference) {
  @keyframes landing-rise {
    from {
      opacity: 0;
      transform: translateY(8px);
    }
    to {
      opacity: 1;
      transform: none;
    }
  }

  .landing__compare {
    animation: landing-rise 400ms cubic-bezier(0.22, 1, 0.36, 1) 150ms both;
  }
}
```

Add the following rules inside that same `@media (prefers-reduced-motion: no-preference)` block (after the existing `.landing__compare` rule, still inside the block's closing `}`):

```css
  .landing__compare-frames {
    display: grid;
  }

  .landing__compare-frame {
    grid-area: 1 / 1;
    border-top: none;
    opacity: 0;
    animation: landing-frame-cycle 9s ease-in-out infinite;
  }

  .landing__compare-frame--governance {
    animation-delay: 3s;
  }

  .landing__compare-frame--audit {
    animation-delay: 6s;
  }

  @keyframes landing-frame-cycle {
    0% {
      opacity: 1;
    }
    27% {
      opacity: 1;
    }
    33.3% {
      opacity: 0;
    }
    100% {
      opacity: 0;
    }
  }

  .landing__compare-dots {
    display: flex;
    justify-content: center;
    gap: 6px;
    padding: 10px 0;
    border-top: 1px solid var(--color-border-dark);
  }

  .landing__compare-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--color-border-dark);
    animation: landing-dot-cycle 9s ease-in-out infinite;
  }

  .landing__compare-dot--governance {
    animation-delay: 3s;
  }

  .landing__compare-dot--audit {
    animation-delay: 6s;
  }

  @keyframes landing-dot-cycle {
    0% {
      background: var(--color-accent);
    }
    30% {
      background: var(--color-accent);
    }
    33.3% {
      background: var(--color-border-dark);
    }
    100% {
      background: var(--color-border-dark);
    }
  }
```

**How the timing works (for review, not to change):** all three `.landing__compare-frame` elements share one 9-second `landing-frame-cycle` animation but start at different offsets (`animation-delay: 0s / 3s / 6s`). Before an element's delay elapses, it renders at its own base CSS value (`opacity: 0`, set in the rule above) rather than the animation's first keyframe — so the governance and audit frames stay invisible until their turn. Once a frame's delay elapses, its *local* clock restarts at 0% of the 9s keyframe timeline, which is why every frame can reuse the exact same `landing-frame-cycle` keyframes: frame `--ops` is visible during local 0%–27% (i.e. calendar seconds 0–2.4), frame `--governance` during its own local 0%–27% (calendar seconds 3–5.4), and so on, each with a `27%→33.3%` fade-out before the next frame's delay elapses. The three `grid-area: 1 / 1` frames occupy the same grid cell, so the card's height is always the tallest frame's height — no hardcoded pixel height, no layout shift as content changes. The dots mirror the same delays with a background-color cycle instead of opacity.

- [ ] **Step 4: Build check**

Run: `cd frontend && npm run build`
Expected: exits 0, no TypeScript or build errors.

- [ ] **Step 5: Lint check**

Run: `cd frontend && npm run lint`
Expected: exits 0, no new warnings on `Landing.tsx`.

- [ ] **Step 6: Manual verification in the browser**

Run: `cd frontend && npm run dev`, open the landing page (`/`).

Confirm, in order:
1. The "Example comparison" card cycles through three frames on a loop: the citation/billing comparison with the gap amount, then the proposed correcting entry with the lock icon, then the posted/audit line with the check icon. Roughly 3 seconds per frame.
2. Three small dots below the card, and the active one is lit while its frame is showing.
3. The card does not change height or jump as the frames cycle (Review Focus 2).
4. In Chrome DevTools, open the Rendering tab, set "Emulate CSS media feature prefers-reduced-motion" to "reduce", and reload: all three frames must now be visible at once, stacked vertically, separated by a thin rule, with no animation and no dots (Review Focus 1). Set it back to "no preference" (or "No emulation") afterward.
5. Resize the viewport to 375px wide: the mono lines in every frame stay on one line or wrap cleanly, no horizontal scrollbar on the card (Review Focus 3).
6. With a screen reader (or by inspecting the accessibility tree in DevTools), confirm the `<figure>` is hidden from the accessibility tree (`aria-hidden="true"`) and that the `landing__layers` list just above the card (Ops / Governance / Audit bullets) still reads the same three-layer story on its own (Review Focus 4).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/screens/Landing.tsx frontend/src/screens/Landing.css
git commit -m "feat(frontend): animate the landing hero's ops/governance/audit example"
```

**REVIEW CHECKPOINT A** — stop and hand over to Claude: commits, `npm run build` output, `git status`, and confirmation of the six checks in Step 6.

---

### Task 2: Backlog and changelog (N18)

**Files:**
- Modify: `artifacts/product-backlog.md`, `CHANGELOG.md`

**Interfaces:**
- Consumes: nothing (docs-only task).
- Produces: nothing.

- [ ] **Step 1: Tick N18 in the backlog**

In `artifacts/product-backlog.md`, find:

```
- [ ] **N18** **Landing hero: animated product visual.** Add a moving visual to the hero section
```

Change `- [ ]` to `- [x]` on that line only (leave the rest of the entry's text unchanged).

- [ ] **Step 2: Add the changelog scope line**

In `CHANGELOG.md`, inside the `## [Sprint — feat/demo-ready]` section's `### Scope` list, immediately after the line ending `...(fintech reframing, backlog N6-N10)`, add:

```
- [x] `frontend` — landing hero: animated ops/governance/audit product visual (CSS-only, respects `prefers-reduced-motion`) → **Not epic-tracked** (fintech reframing, backlog N18)
```

- [ ] **Step 3: Commit**

```bash
git add artifacts/product-backlog.md CHANGELOG.md
git commit -m "docs(backlog): tick N18 and record the landing hero animation"
```

**REVIEW CHECKPOINT B** (final) — stop and hand over to Claude: commits, `git status`, `git log --oneline -5`.
