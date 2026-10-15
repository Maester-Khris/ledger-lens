# Landing Page Credibility Pass Implementation Plan

> **For agentic workers:** Implement this plan task by task, in order. Steps use checkbox (`- [ ]`) syntax for
> tracking. This plan is executed by Gemini and reviewed by Claude afterwards.

**Goal:** Make the landing page credible to a product visitor and a technical reviewer using only static content
that already exists in the repository.

**Architecture:** Three existing frontend files change and one small pure function is added with its test. The hero
diagram stops looping and holds its final state. The landing page gets reordered sections, corrected copy, a proof
table, a data-handling and limits section, and footer links. No backend, no API call, no new dependency.

**Tech Stack:** React 19 + TypeScript (Vite), plain CSS with the design tokens in `frontend/src/index.css`, vitest.

**Spec:** `docs/superpowers/specs/2026-10-04-landing-credibility-design.md`. Read it before starting.

## Global Constraints

- Work on the current branch (`feat/pre-launch-demo`). **Do not run `git add`, `git commit`, `git push` or change
  branches.** Leave every change uncommitted in the working tree so it can be reviewed and backed out.
- Touch only these files:
  - Create: `frontend/src/lib/flowPhase.ts`
  - Create: `frontend/src/lib/flowPhase.test.ts`
  - Modify: `frontend/src/components/HeroFlow.tsx`
  - Modify: `frontend/src/screens/Landing.tsx`
  - Modify: `frontend/src/screens/Landing.css`
- Do not touch `frontend/src/components/HeroFlow.css`, `frontend/src/lib/useCountUp.ts`, any other screen, anything
  under `backend/`, `package.json`, or any config file.
- No new npm package.
- Copy the text in this plan exactly, character for character. Do not rephrase, shorten, "improve" or add copy.
- Do not add any number, statistic, claim, section, icon or link that is not written in this plan.
- Never use an em dash (the long dash) anywhere. Use a hyphen, a comma or a full stop.
- Use only existing CSS custom properties (for example `var(--color-accent)`, `var(--space-3)`). Do not write a hex
  colour.
- TypeScript: no `any`.
- Run all commands from the `frontend/` directory.
- If a step's expected output does not match, stop and report what you saw. Do not work around it.

## Review Focus

These are the conditions most likely to go wrong that the unit test does not cover. The reviewer checks each one.

1. **Reduced motion.** With `prefers-reduced-motion: reduce`, the hero must show 0.85%, 0.80% and $400.00
   immediately, with no "· · ·" placeholder and no animation.
2. **Narrow screen (360px wide).** The proof table must not cause horizontal page scroll. Each row must stack into
   readable lines.
3. **Hero fit.** At 1440x800 the headline, subhead, both buttons and the diagram must still fit in the first
   screen now that a line was added above the headline.
4. **The phase never passes the last one.** Covered by the unit test in Task 1; the reviewer also confirms that
   after 10 seconds the diagram still shows its final values.
5. **External links.** Both footer links open in a new tab and carry `rel="noreferrer"`.

---

### Task 1: Hero diagram plays once and holds

**Files:**
- Create: `frontend/src/lib/flowPhase.ts`
- Create: `frontend/src/lib/flowPhase.test.ts`
- Modify: `frontend/src/components/HeroFlow.tsx` (whole file replaced)

**Interfaces:**
- Produces: `nextFlowPhase(phase: number, phaseCount: number): number` exported from
  `frontend/src/lib/flowPhase.ts`. It returns `phase + 1`, capped at `phaseCount - 1`.
- Consumes: `useCountUp(target: number, active: boolean, durationMs: number, reduced: boolean): number` from
  `frontend/src/lib/useCountUp.ts` (existing, unchanged). It counts from 0 to `target` while `active` is true,
  returns 0 while `active` is false, and returns `target` at once when `reduced` is true.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/flowPhase.test.ts` with exactly this content:

```ts
import { expect, it } from 'vitest';
import { nextFlowPhase } from './flowPhase';

it('advances one phase at a time', () => {
  expect(nextFlowPhase(0, 7)).toBe(1);
  expect(nextFlowPhase(5, 7)).toBe(6);
});

it('holds on the last phase and never loops back to the first', () => {
  expect(nextFlowPhase(6, 7)).toBe(6);
  expect(nextFlowPhase(99, 7)).toBe(6);
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npx vitest run src/lib/flowPhase.test.ts`
Expected: FAIL. The error says the module `./flowPhase` cannot be found or resolved.

- [ ] **Step 3: Write the function**

Create `frontend/src/lib/flowPhase.ts` with exactly this content:

```ts
/** The hero diagram plays once and holds on its last phase; it never loops back to the first. */
export function nextFlowPhase(phase: number, phaseCount: number): number {
  return Math.min(phase + 1, phaseCount - 1);
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npx vitest run src/lib/flowPhase.test.ts`
Expected: PASS, 2 tests passed.

- [ ] **Step 5: Replace `HeroFlow.tsx`**

Replace the whole content of `frontend/src/components/HeroFlow.tsx` with exactly this:

```tsx
import { useEffect, useState } from 'react';
import { DocumentsIcon, LedgerIcon, RefreshIcon } from './Icons';
import { nextFlowPhase } from '../lib/flowPhase';
import { useCountUp } from '../lib/useCountUp';
import './HeroFlow.css';

// ponytail: a fixed 7-phase timeline for this one diagram, not a general animation engine.
// Phases: 0 source lit, 1 dot travels left, 2 contract rate counts up, 3 exchange icon pulses,
// 4 billing rate counts up, 5 dot travels right, 6 ledger lit + posted amount counts up.
// It plays once and holds on phase 6, so the diagram never shows zeros after the first few seconds.
// One duration per phase that is followed by another; the last phase has none because it never ends.
const PHASE_DURATIONS_MS = [600, 600, 900, 500, 900, 600];
const PHASE_COUNT = PHASE_DURATIONS_MS.length + 1;
const LAST_PHASE = PHASE_COUNT - 1;
const COUNT_UP_MS = 900;

const CONTRACT_RATE = 0.85;
const BILLING_RATE = 0.8;
const POSTED_AMOUNT = 400;
// Shown in a value slot before its count-up starts, so the diagram never reads "0.00%".
const PENDING = '· · ·';

function prefersReducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function useFlowPhase(reduced: boolean): number {
  const [phase, setPhase] = useState(0);
  useEffect(() => {
    if (reduced || phase >= LAST_PHASE) return;
    const timer = setTimeout(() => setPhase((p) => nextFlowPhase(p, PHASE_COUNT)), PHASE_DURATIONS_MS[phase]);
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
  const ledgerActive = !reduced && phase === LAST_PHASE;

  const contractRate = useCountUp(CONTRACT_RATE, contractCounting, COUNT_UP_MS, reduced);
  const billingRate = useCountUp(BILLING_RATE, billingCounting, COUNT_UP_MS, reduced);
  const posted = useCountUp(POSTED_AMOUNT, ledgerActive, COUNT_UP_MS, reduced);

  const showContract = reduced || contractCounting;
  const showBilling = reduced || billingCounting;
  const showPosted = reduced || ledgerActive;

  return (
    <div className="hero-flow" aria-hidden="true">
      <div className="hero-flow__row">
        <div className="hero-flow__node">
          <span className="hero-flow__label">Agreement</span>
          <div className={`hero-flow__card${sourceActive ? ' hero-flow__card--active' : ''}`}>
            <DocumentsIcon size={20} />
            <span className="hero-flow__value mono">§3 Fees · p.1</span>
          </div>
        </div>

        <div className="hero-flow__connector">{dotLeft && <span className="hero-flow__dot" />}</div>

        <div className="hero-flow__hub">
          <span className="hero-flow__label">Reconciliation</span>
          <div className="hero-flow__hub-inner">
            <div className="hero-flow__card hero-flow__card--inner">
              <span className="hero-flow__inner-label">Contract states</span>
              <span className="hero-flow__value mono">{showContract ? `${contractRate.toFixed(2)}%` : PENDING}</span>
            </div>
            <div className={`hero-flow__exchange${exchangeActive ? ' hero-flow__exchange--active' : ''}`}>
              <RefreshIcon size={16} />
            </div>
            <div className="hero-flow__card hero-flow__card--inner">
              <span className="hero-flow__inner-label">Billing charges</span>
              <span className="hero-flow__value mono">{showBilling ? `${billingRate.toFixed(2)}%` : PENDING}</span>
            </div>
          </div>
        </div>

        <div className="hero-flow__connector">{dotRight && <span className="hero-flow__dot" />}</div>

        <div className="hero-flow__node">
          <span className="hero-flow__label">Ledger</span>
          <div className={`hero-flow__card${ledgerActive ? ' hero-flow__card--active' : ''}`}>
            <LedgerIcon size={20} />
            <span className="hero-flow__value mono">{showPosted ? `$${posted.toFixed(2)}` : PENDING}</span>
          </div>
        </div>
      </div>

      <ul className="hero-flow__chips">
        <li>PII tokenized locally</li>
        <li>Contract ↔ billing, compared on request</li>
        <li>Human approval required</li>
        <li>Full audit trail</li>
      </ul>
    </div>
  );
}
```

What changed compared with the old file, so you can check your work:
- The timer no longer wraps around with `% PHASE_COUNT`. It uses `nextFlowPhase` and stops at the last phase.
- Phase durations are shorter and the last phase has no duration.
- The three count-ups use one shared duration, `COUNT_UP_MS`.
- Each of the three values shows `PENDING` until its count-up starts.
- "§3 Fees · p.2" is now "§3 Fees · p.1".
- The second chip now reads "Contract ↔ billing, compared on request".

- [ ] **Step 6: Type-check**

Run: `npx tsc -b`
Expected: no output and exit code 0.

- [ ] **Step 7: Do not commit.** Leave the changes in the working tree.

---

### Task 2: Landing page content and order

**Files:**
- Modify: `frontend/src/screens/Landing.tsx` (whole file replaced)

**Interfaces:**
- Consumes: `HeroFlow` from `frontend/src/components/HeroFlow.tsx` (Task 1), and the existing `BrandMark`,
  `CheckIcon`, `LockIcon`, `RefreshIcon`, `SparkleIcon`.
- Produces: these new class names, which Task 3 styles: `landing__eyebrow`, `landing__proof`,
  `landing__proof-measured`, `landing__proof-source`, `landing__trust`, `landing__trust-title`, `landing__facts`,
  `landing__note`, `landing__footer-links`.

- [ ] **Step 1: Replace `Landing.tsx`**

Replace the whole content of `frontend/src/screens/Landing.tsx` with exactly this:

```tsx
import { Link } from 'react-router';
import { BrandMark } from '../components/BrandMark';
import { CheckIcon, LockIcon, RefreshIcon, SparkleIcon } from '../components/Icons';
import { HeroFlow } from '../components/HeroFlow';
import './Landing.css';

const REPO_URL = 'https://github.com/Maester-Khris/ledger-lens';
// The reports are on preview and not yet on main; switch to main after the next release.
const REPORTS_URL = `${REPO_URL}/tree/preview/backend/reports`;

const STEPS = [
  {
    title: 'Read the agreement',
    body: 'Upload an investment advisory agreement as a PDF. It is parsed and tokenised before anything reaches a model: names, emails, phone and account numbers are replaced with tokens, and the fee schedule is extracted together with the clause it came from.',
  },
  {
    title: 'Reconcile it with billing',
    body: 'Ask about any contract in plain language. Answers cite the clause and page, and billing reconciliation is computed in code from your billing schedule. The model never does the arithmetic.',
  },
  {
    title: 'Approve the correction',
    body: 'When the contract and billing disagree, the assistant proposes a balanced journal entry, logged in the AI decision audit trail with its model, inputs and citations. It reaches the ledger only after a person approves it, and it posts exactly once.',
  },
];

const GUARANTEES = [
  'Tools take document IDs, and code computes every fee. The model never supplies an amount.',
  'Every number in an answer traces to the page and clause that state it, never asserted without a citation.',
  "A field the extractor couldn't confirm sits in the extraction anomaly queue until a person resolves it; the assistant won't use it.",
  'The ledger is append-only. A mistake is undone with a reversal, never an edit.',
];

// Every figure here is copied from a file in the repository; the source column names it.
const PROOF = [
  {
    claim: 'No duplicate postings under load',
    measured: '0 of 500 concurrent requests',
    source: 'backend/reports/concurrency.json',
    date: '2026-09-23',
  },
  {
    claim: 'Answerable questions answered with the right numbers and a citation',
    measured: '27 to 28 of 28, across three runs',
    source: 'backend/reports/eval-5bfdd62942f4*.json',
    date: '2026-10-02',
  },
  {
    claim: 'Unanswerable questions refused or sent back for clarification',
    measured: '21 of 21, across three runs',
    source: 'backend/reports/eval-5bfdd62942f4*.json',
    date: '2026-10-02',
  },
  {
    claim: 'Automated backend tests',
    measured: '364',
    source: 'backend/tests/',
    date: '2026-10-04',
  },
];

const DATA_HANDLING = [
  'Names, emails, phone and account numbers are replaced with tokens before any text reaches a model.',
  'Parsing and tokenising run locally, with Docling and Presidio.',
  'Search vectors are stored in Pinecone (AWS us-east-1).',
  'Answers are generated by OpenAI.',
];

const DEMO_LIMITS = [
  'Agreements are synthetic or public EDGAR filings. There is no client data.',
  'Guests are identified for attribution, not authenticated.',
  'In the public demo, approvals are checked by the ledger but not recorded.',
  'One tenant.',
  'A comparison runs when you ask for it, against the billing schedule in effect, not against invoices.',
];

export function Landing() {
  return (
    <div className="landing">
      <header className="landing__nav">
        <div className="landing__brand">
          <BrandMark size={24} />
          Ledger Assistant
        </div>
        <nav className="landing__nav-links" aria-label="Page sections">
          <a href="#guarantees">Guarantees</a>
          <a href="#proof">Proof</a>
          <a href="#how-it-works">How it works</a>
        </nav>
        <Link to="/dashboard" className="btn btn-primary">
          Open the demo
        </Link>
      </header>

      <section className="landing__hero">
        <p className="landing__eyebrow mono">For billing operations and compliance teams at Canadian portfolio managers</p>
        <h1 className="landing__headline">Bill what the contract says.</h1>
        <p className="landing__subhead">
          Ledger Assistant reads your investment advisory agreements, answers questions with the clause cited, and
          checks each fee schedule against what your billing schedule would charge. When they disagree, it proposes a
          correcting entry that posts only after a person approves it.
        </p>
        <div className="landing__hero-actions">
          <Link to="/dashboard" className="btn btn-primary">
            Open the demo
          </Link>
          <Link to="/chat" className="btn landing__btn-ghost">
            Ask a contract
          </Link>
        </div>

        <HeroFlow />
      </section>

      <section className="landing__pillars" aria-label="What this demonstrates at three levels">
        <div className="landing__pillars-inner">
          <div className="landing__pillar landing__pillar--ops">
            <span className="landing__pillar-eyebrow">Rule engine</span>
            <div className="landing__pillar-title">
              <RefreshIcon size={16} className="landing__pillar-icon" />
              Ops
            </div>
            <p className="landing__pillar-desc">
              Billing reconciliation: the gap between contract and billing,{' '}
              <code className="mono landing__pillar-code">computed in code</code>, never by the model.
            </p>
          </div>
          <div className="landing__pillar landing__pillar--governance">
            <span className="landing__pillar-eyebrow">Decision log</span>
            <div className="landing__pillar-title">
              <LockIcon size={16} className="landing__pillar-icon" />
              Governance
            </div>
            <p className="landing__pillar-desc">
              Every AI tool call is <code className="mono landing__pillar-code">logged</code> with its model, inputs
              and decision, before anything reaches the ledger.
            </p>
          </div>
          <div className="landing__pillar landing__pillar--audit">
            <span className="landing__pillar-eyebrow">Reproducible export</span>
            <div className="landing__pillar-title">
              <CheckIcon size={16} className="landing__pillar-icon" />
              Audit
            </div>
            <p className="landing__pillar-desc">
              The GL export is byte-identical on regeneration and verified by its{' '}
              <code className="mono landing__pillar-code">SHA-256</code> hash.
            </p>
          </div>
        </div>
      </section>

      <section className="landing__section landing__section--split" id="guarantees">
        <div>
          <h2 className="landing__section-title">What it will not do</h2>
          <p className="landing__section-lede">
            The assistant is built for review, not autopilot. These rules are enforced in code and in the database, not
            in the prompt.
          </p>
        </div>
        <ul className="landing__guarantees">
          {GUARANTEES.map((line) => (
            <li key={line}>
              <CheckIcon size={14} className="landing__check" /> {line}
            </li>
          ))}
        </ul>
      </section>

      <section className="landing__section" id="proof">
        <h2 className="landing__section-title">Measured, with the source</h2>
        <p className="landing__section-lede">
          Each result below is copied from a report or a folder in the repository, so you can check it.
        </p>
        <table className="landing__proof">
          <thead>
            <tr>
              <th scope="col">Claim</th>
              <th scope="col">Measured</th>
              <th scope="col">Source</th>
              <th scope="col">Date</th>
            </tr>
          </thead>
          <tbody>
            {PROOF.map((row) => (
              <tr key={row.claim}>
                <th scope="row">{row.claim}</th>
                <td className="landing__proof-measured mono">{row.measured}</td>
                <td className="landing__proof-source mono">{row.source}</td>
                <td className="landing__proof-source mono">{row.date}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="landing__section" id="how-it-works">
        <h2 className="landing__section-title">How it works</h2>
        <ol className="landing__steps">
          {STEPS.map((step, index) => (
            <li key={step.title} className="landing__step">
              <span className="landing__step-number mono">{index + 1}</span>
              <h3>{step.title}</h3>
              <p>{step.body}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="landing__section" id="limits">
        <h2 className="landing__section-title">Before you rely on it</h2>
        <div className="landing__trust">
          <div>
            <h3 className="landing__trust-title">How your data is handled</h3>
            <ul className="landing__facts">
              {DATA_HANDLING.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </div>
          <div>
            <h3 className="landing__trust-title">Limits of this demo</h3>
            <ul className="landing__facts">
              {DEMO_LIMITS.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </div>
        </div>
        <p className="landing__note">
          The decision log records the tool, model, prompt version, inputs and approver for every AI action, in line
          with the transparency and accountability themes of CSA Staff Notice 11-348 on AI in capital markets. This
          demo has not been assessed for compliance with any regulation.
        </p>
      </section>

      <section className="landing__stack">
        <p className="mono">
          <SparkleIcon size={12} /> Docling and Presidio run locally · Postgres full-text + Pinecone retrieval · OpenAI via
          LangGraph · double-entry ledger on PostgreSQL
        </p>
      </section>

      <footer className="landing__footer">
        <div className="landing__brand landing__brand--dark">
          <BrandMark size={24} />
          Ledger Assistant
        </div>
        <span className="landing__footer-copy">A working demo: fee-contract reconciliation and a governed AI, on a double-entry ledger.</span>
        <div className="landing__footer-links">
          <a href={REPO_URL} target="_blank" rel="noreferrer">Source on GitHub</a>
          <a href={REPORTS_URL} target="_blank" rel="noreferrer">Evaluation reports</a>
          <Link to="/dashboard">Open the demo →</Link>
        </div>
      </footer>
    </div>
  );
}
```

What changed compared with the old file, so you can check your work:
- New constants: `REPO_URL`, `REPORTS_URL`, `PROOF`, `DATA_HANDLING`, `DEMO_LIMITS`.
- `STEPS[0].body` wording changed ("parsed and tokenised before anything reaches a model").
- Nav links: order is now Guarantees, Proof, How it works.
- Hero: a `landing__eyebrow` line above the headline, and a new two-sentence subhead.
- Pillar labels: "Chain of custody" is now "Decision log"; "Cryptographic audit" is now "Reproducible export".
- The "What it will not do" section moved from near the bottom to directly after the pillars. Its content is
  unchanged.
- New sections: `#proof` and `#limits`.
- Footer: the single link is now a group of three links.

- [ ] **Step 2: Type-check**

Run: `npx tsc -b`
Expected: no output and exit code 0.

- [ ] **Step 3: Do not commit.**

---

### Task 3: Styles for the new elements

**Files:**
- Modify: `frontend/src/screens/Landing.css`

**Interfaces:**
- Consumes: the class names produced by Task 2.

- [ ] **Step 1: Add the eyebrow rule**

In `frontend/src/screens/Landing.css`, find this existing rule:

```css
.landing__headline {
```

Insert the following block immediately **before** it:

```css
.landing__eyebrow {
  font-size: 12px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--color-text-secondary-dark);
  max-width: 60ch;
  text-wrap: balance;
  margin-bottom: var(--space-3);
}

```

- [ ] **Step 2: Add the proof, trust and footer-link rules**

In the same file, find this existing rule:

```css
.landing__stack {
```

Insert the following block immediately **before** it:

```css
/* Proof: a ledger-style table, one row per measured claim with its source. */
.landing__proof {
  width: 100%;
  margin-top: var(--space-4);
  border-collapse: collapse;
  text-align: left;
  font-size: 14px;
}

.landing__proof thead th {
  padding: 0 var(--space-2) var(--space-1) 0;
  border-bottom: 1px solid var(--color-border);
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--color-text-secondary);
}

.landing__proof tbody th,
.landing__proof tbody td {
  padding: var(--space-2) var(--space-2) var(--space-2) 0;
  border-bottom: 1px solid var(--color-border);
  vertical-align: baseline;
  line-height: 1.5;
}

.landing__proof tbody th {
  font-weight: 500;
  max-width: 34ch;
}

.landing__proof-measured {
  font-weight: 600;
  color: var(--color-text-primary);
}

.landing__proof-source {
  font-size: 12px;
  color: var(--color-text-secondary);
  overflow-wrap: anywhere;
}

/* Data handling and limits: two plain lists and one note. */
.landing__trust {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-5);
}

.landing__trust-title {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: var(--space-1);
}

.landing__facts {
  list-style: none;
  margin: 0;
  padding: 0;
}

.landing__facts li {
  padding: 12px 0;
  border-top: 1px solid var(--color-border);
  line-height: 1.55;
  color: var(--color-text-secondary);
}

.landing__note {
  margin-top: var(--space-4);
  padding-left: var(--space-2);
  border-left: 3px solid var(--color-accent);
  max-width: 80ch;
  font-size: 14px;
  line-height: 1.6;
  color: var(--color-text-secondary);
}

.landing__footer-links {
  display: flex;
  gap: var(--space-3);
  flex-wrap: wrap;
}

```

- [ ] **Step 3: Add the narrow-screen rules**

In the same file, find the existing media query that starts with this line:

```css
@media (max-width: 860px) {
```

Inside that media query, find this existing rule:

```css
  .landing__pillars-inner {
    grid-template-columns: 1fr;
  }
```

Insert the following block immediately **after** it (still inside the media query, keeping the two-space
indentation):

```css

  .landing__trust {
    grid-template-columns: 1fr;
    gap: var(--space-4);
  }

  /* The proof table stacks: each row becomes a block, each cell its own line. */
  .landing__proof thead {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
  }

  .landing__proof tbody tr {
    display: block;
    padding: var(--space-2) 0;
    border-bottom: 1px solid var(--color-border);
  }

  .landing__proof tbody th,
  .landing__proof tbody td {
    display: block;
    padding: 2px 0;
    border-bottom: none;
    max-width: none;
  }
```

- [ ] **Step 4: Confirm the file has no hex colour and no em dash in what you added**

Run: `git diff -U0 src/screens/Landing.css | grep -E "^\+.*(#[0-9a-fA-F]{3,6}|—)" ; echo "exit: $?"`
Expected: no matching lines, then `exit: 1`.

- [ ] **Step 5: Do not commit.**

---

### Task 4: Verify the whole change

**Files:** none modified.

- [ ] **Step 1: Run the unit tests**

Run: `npm run test`
Expected: all test files pass, including `src/lib/flowPhase.test.ts` with 2 tests. No failures.

- [ ] **Step 2: Build**

Run: `npm run build`
Expected: `tsc -b` prints nothing, then Vite prints a list of `dist/assets/...` files and a line starting with
`✓ built in`. No error.

- [ ] **Step 3: Lint**

Run: `npm run lint`
Expected: no **error**. Warnings named `react(set-state-in-effect)` already exist in other files and are fine. If
a new warning or error points at `Landing.tsx`, `HeroFlow.tsx` or `flowPhase.ts`, stop and report it.

- [ ] **Step 4: Confirm only the allowed files changed**

Run: `git -C .. status --short`
Expected: exactly these five paths, and no others under `frontend/` or `backend/`:

```
 M frontend/src/components/HeroFlow.tsx
 M frontend/src/screens/Landing.css
 M frontend/src/screens/Landing.tsx
?? frontend/src/lib/flowPhase.test.ts
?? frontend/src/lib/flowPhase.ts
```

Files under `docs/superpowers/` may also appear as untracked; ignore those. If any other file appears, stop and
report it. Do not try to revert it yourself.

- [ ] **Step 5: Confirm no em dash was introduced**

Run: `git diff -U0 -- src | grep -E "^\+.*—" ; echo "exit: $?"`
Expected: no matching lines, then `exit: 1`.

- [ ] **Step 6: Report**

Write a short report with:
1. The output of Steps 1 to 5.
2. Any step where the result did not match "Expected".
3. Any place where you deviated from the plan, however small, and why.

Do not commit. The reviewer checks the Review Focus items in a browser and decides what to commit.
