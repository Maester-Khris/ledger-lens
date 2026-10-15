# Demo-ready UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every screen of the React frontend tell the truth about the product — real data on Dashboard and Ledger, a working human-review loop for extracted fields and proposed fee corrections, a chat that reads well, and a landing page that describes the fee-contract product — so `preview` can be promoted.

**Architecture:** Two small additive backend changes (account labels on posting entries and proposed entries; a `/reviews` queue over the existing append-only `field_reviews` table), then the frontend is rewired screen by screen onto the existing API. Framework-free logic (markdown parsing, money/time formatting, posting and pipeline view models, review helpers) lives in `frontend/src/lib/*.ts` and is unit-tested with Vitest; React components stay thin.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + pytest (backend); React 19 + TypeScript + Vite 8 + react-router 8 (frontend); Vitest (new dev dependency, the only new package).

**Spec:** the audit of 2026-09-26 reproduced in [Findings](#findings) below (F1–F19). There is no separate spec file; this plan argues from those findings.

## Findings

| ID | Finding | Task |
|---|---|---|
| F1 | Dashboard is hardcoded tax-era mock data; "3 to review" links to an all-green `/documents` | 3, 6, 8 |
| F2 | Ledger is hardcoded (T4/W-2 postings in CAD); `GET /postings` and reversal exist but are unused | 2, 4, 5 |
| F3 | No UI to approve a proposed fee correction; `/tool-invocations` endpoints unused; `.tool-card` CSS dead | 2, 4, 6 |
| F4 | Landing page and `index.html` meta describe tax slips, Form 941, Textract, pgvector, LiteLLM, bounding boxes | 9 |
| F5 | Chat: no vertical space between question and answer; citation cards stack flush | 1 |
| F6 | Chat: markdown shows as raw text; line breaks collapse | 1 |
| F7 | Chat: no auto-scroll to the newest answer | 1 |
| F8 | Chat: input disabled while busy and focus not returned | 1 |
| F9 | Chat: `100vh` ignores mobile browser chrome (use `dvh`) | 1 |
| F10 | Chat: "Indexed contracts" pill has no count | 1 |
| F11 | Documents: default-selected row is not highlighted (`selectedId` vs `currentId`) | 7 |
| F12 | Documents: "Show all N chunks →" is a dead `#chunks` link | 7 |
| F13 | Documents: the active pipeline step never renders (`duration === '…'` never produced) | 7 |
| F14 | Documents: "Used by" is hardcoded `[]` | 7 |
| F15 | Documents: detail refetched on every 3 s poll; error message never clears | 7 |
| F16 | Documents and Ledger rows are mouse-only (`<tr onClick>`) | 5, 7 |
| F17 | No `:focus-visible` styles; Ledger filter input has no label | 5, 10 |
| F18 | Sidebar always says "API connected" | 10 |
| F19 | Side-stripe borders, per-section eyebrows, hero-metric tiles, 39 hardcoded hex colours | 8, 9, 10 |

## Global Constraints

- Work on branch `feat/demo-ready`. Never commit to `preview` or `main`. Check with `git branch --show-current` before every commit.
- Conventional commits (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`). **No `Co-Authored-By` line and no AI attribution of any kind** in commits.
- Stage files explicitly (`git add <file> ...`), never `git add -A` / `git add .`. Run `git status` and `git diff --staged --stat` before each commit; if unexpected files appear, stop and report.
- Backend commands run from `backend/` with the shared env: `$PYDEV/bin/pytest`, `$PYDEV/bin/python`. Never create a `.venv`.
- Backend layering: routes stay thin (parse → call a package function → return). DB access only in each package's own `dao.py`. The ledger package imports no other package. No new Python dependency.
- Frontend: no `any`; a named `interface` for every component's props; no new npm package except `vitest` (dev), which must be listed in the PR summary. No markdown library — the renderer in Task 1 is the one to use.
- Frontend styling: colours only through the CSS custom properties in `frontend/src/index.css`; no `border-left`/`border-right` wider than 1px as an accent; radius ≤ 8px except pills; transitions 150–200 ms; every animation has a `prefers-reduced-motion` fallback.
- Copy: sentence case, plain verbs. Never mention tax slips, T4, W-2, 1099, Form 941, Textract, pgvector, LiteLLM, bounding boxes, confidence percentages, "authenticated reviewer", or street-address redaction (addresses are *not* redacted yet). The product name stays **Ledger Assistant**.
- Keep `npm run build`, `npm run lint`, `npm test` (frontend) and `$PYDEV/bin/pytest` (backend) green at the end of every task.
- After code changes in a task, run `graphify update .` from the repo root before committing.

## Review Focus

1. **Backend down or slow.** Every screen shows a readable error or loading state, never a blank panel or an uncaught promise; the sidebar says "API unreachable". Pinned by `checkHealth` tests in Task 4 and the manual checklist in Task 11.
2. **Double submission.** Clicking "Approve and post" or "Reverse posting" twice must create exactly one posting. Reversal uses the deterministic `Idempotency-Key: reverse:<posting id>` (test in Task 4); approval buttons disable while submitting and a 409 is shown as a message, not a crash (test in Task 4 for the problem detail).
3. **Non-string field values.** A fee-tier list or a number under review is shown as JSON and can be corrected as JSON or plain text. Pinned by `formatValue`/`parseCorrection` tests in Task 6.
4. **Model answers with markdown edge cases.** A line starting with `**bold**` is not a list; a dash mid-sentence is not a list; a list right after a paragraph line still renders as a list. Pinned by Task 1 tests.
5. **Review of an unknown or foreign field, or a correction without a value.** 404 and 422 problem responses, and a second decision on the same field is a 409. Pinned by Task 3 tests.

## Design lenses used

- **clean-architecture / clean-code:** pure view logic in framework-free `lib/*.ts` files with tests; React components stay humble renderers; routes stay thin and call package DAOs.
- **domain-driven-design:** UI copy uses the domain's own words — contract, fee schedule, billing, correction, approval, reversal — instead of system terms.
- **pragmatic-programmer:** one derived idempotency key per reversal; one source for formatting money and time (DRY); no speculative flexibility, such as markdown features the assistant never emits.
- **test-driven-development:** every task that adds logic starts with a failing test.
- **frontend-design / impeccable:** keep the existing token palette; the landing hero's contract-vs-billing comparison is its one signature element; no eyebrows, stripes or hero-metric tiles.

## Out of scope (other sprint items)

- The citation-click → highlighted-quote Playwright test (D18).
- Langfuse tracing.
- The redaction security review. Note for it: a value a reviewer types into "Correct" (Task 6) is stored as typed and later served to the model; the security review must decide whether to tokenise it.
- The "not comparable" answer decision.

---

### Task 1: Frontend test runner, markdown renderer and chat fixes (F5–F10)

**Files:**
- Modify: `frontend/package.json` (add `vitest`, add `test` script)
- Create: `frontend/src/lib/markdown.ts`
- Create: `frontend/src/lib/markdown.test.ts`
- Create: `frontend/src/components/Markdown.tsx`
- Modify: `frontend/src/screens/Chat.tsx` (full replacement below)
- Modify: `frontend/src/screens/Chat.css`

**Interfaces:**
- Produces: `parseMarkdown(source: string): Block[]`, `parseInline(text: string): Inline[]`, types `Block`, `Inline`; component `Markdown({ text, className })`.

- [ ] **Step 1: Install Vitest and add the test script**

```bash
cd frontend
npm install --save-dev vitest
```

Then in `frontend/package.json` add to `"scripts"`:

```json
"test": "vitest run"
```

- [ ] **Step 2: Write the failing markdown tests**

`frontend/src/lib/markdown.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { parseInline, parseMarkdown } from './markdown';

describe('parseMarkdown', () => {
  it('returns no blocks for empty text', () => {
    expect(parseMarkdown('')).toEqual([]);
  });

  it('splits paragraphs on blank lines and joins wrapped lines', () => {
    expect(parseMarkdown('First line\nstill first.\n\nSecond.')).toEqual([
      { kind: 'paragraph', inlines: [{ kind: 'text', text: 'First line still first.' }] },
      { kind: 'paragraph', inlines: [{ kind: 'text', text: 'Second.' }] },
    ]);
  });

  it('renders dash and star bullets as one unordered list', () => {
    expect(parseMarkdown('- one\n* two')).toEqual([
      { kind: 'list', ordered: false, items: [[{ kind: 'text', text: 'one' }], [{ kind: 'text', text: 'two' }]] },
    ]);
  });

  it('renders numbered lines as an ordered list', () => {
    expect(parseMarkdown('1. one\n2) two')).toEqual([
      { kind: 'list', ordered: true, items: [[{ kind: 'text', text: 'one' }], [{ kind: 'text', text: 'two' }]] },
    ]);
  });

  it('starts a list right after a paragraph line', () => {
    expect(parseMarkdown('Fees:\n- 1.00% on the first $1,000,000')).toEqual([
      { kind: 'paragraph', inlines: [{ kind: 'text', text: 'Fees:' }] },
      { kind: 'list', ordered: false, items: [[{ kind: 'text', text: '1.00% on the first $1,000,000' }]] },
    ]);
  });

  it('does not treat a line starting with bold as a bullet', () => {
    expect(parseMarkdown('**Total**: 1,500.00')).toEqual([
      { kind: 'paragraph', inlines: [{ kind: 'strong', text: 'Total' }, { kind: 'text', text: ': 1,500.00' }] },
    ]);
  });

  it('keeps a dash in the middle of a sentence as text', () => {
    expect(parseMarkdown('From $1,000 - $2,000 the rate is 0.85%.')).toEqual([
      { kind: 'paragraph', inlines: [{ kind: 'text', text: 'From $1,000 - $2,000 the rate is 0.85%.' }] },
    ]);
  });

  it('renders a hash line as a heading', () => {
    expect(parseMarkdown('### Fee schedule')).toEqual([
      { kind: 'heading', inlines: [{ kind: 'text', text: 'Fee schedule' }] },
    ]);
  });
});

describe('parseInline', () => {
  it('splits bold spans from text', () => {
    expect(parseInline('Rate is **1.00%** per year')).toEqual([
      { kind: 'text', text: 'Rate is ' },
      { kind: 'strong', text: '1.00%' },
      { kind: 'text', text: ' per year' },
    ]);
  });
});
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/lib/markdown.test.ts`
Expected: FAIL — `Failed to resolve import "./markdown"`.

- [ ] **Step 4: Implement the parser**

`frontend/src/lib/markdown.ts`:

```ts
export type Inline = { kind: 'text' | 'strong'; text: string };

export type Block =
  | { kind: 'heading'; inlines: Inline[] }
  | { kind: 'paragraph'; inlines: Inline[] }
  | { kind: 'list'; ordered: boolean; items: Inline[][] };

type ListDraft = { ordered: boolean; items: Inline[][] };

const BULLET = /^\s*[-*•]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;
const HEADING = /^\s*#{1,6}\s+(.*)$/;
const BOLD = /\*\*(.+?)\*\*/g;

export function parseInline(text: string): Inline[] {
  const parts: Inline[] = [];
  let last = 0;
  for (const match of text.matchAll(BOLD)) {
    if (match.index > last) parts.push({ kind: 'text', text: text.slice(last, match.index) });
    parts.push({ kind: 'strong', text: match[1] });
    last = match.index + match[0].length;
  }
  if (last < text.length) parts.push({ kind: 'text', text: text.slice(last) });
  return parts;
}

// ponytail: the subset the assistant actually emits (paragraphs, lists, bold, headings); no links, tables or code
export function parseMarkdown(source: string): Block[] {
  const blocks: Block[] = [];
  let paragraph: string[] = [];
  let list = null as ListDraft | null;

  const flushParagraph = () => {
    if (paragraph.length) blocks.push({ kind: 'paragraph', inlines: parseInline(paragraph.join(' ')) });
    paragraph = [];
  };
  const flushList = () => {
    if (list) blocks.push({ kind: 'list', ordered: list.ordered, items: list.items });
    list = null;
  };

  for (const line of source.split('\n')) {
    const bullet = BULLET.exec(line);
    const numbered = NUMBERED.exec(line);
    const heading = HEADING.exec(line);
    const item = bullet ?? numbered;
    if (item) {
      flushParagraph();
      const ordered = bullet === null;
      if (list && list.ordered !== ordered) flushList();
      list ??= { ordered, items: [] };
      list.items.push(parseInline(item[1].trim()));
    } else if (heading) {
      flushParagraph();
      flushList();
      blocks.push({ kind: 'heading', inlines: parseInline(heading[1].trim()) });
    } else if (!line.trim()) {
      flushParagraph();
      flushList();
    } else {
      flushList();
      paragraph.push(line.trim());
    }
  }
  flushParagraph();
  flushList();
  return blocks;
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/lib/markdown.test.ts`
Expected: PASS (9 tests).

- [ ] **Step 6: Add the Markdown component**

`frontend/src/components/Markdown.tsx`:

```tsx
import { type Inline, parseMarkdown } from '../lib/markdown';

interface InlinesProps {
  inlines: Inline[];
}

function Inlines({ inlines }: InlinesProps) {
  return (
    <>
      {inlines.map((inline, index) =>
        inline.kind === 'strong' ? <strong key={index}>{inline.text}</strong> : <span key={index}>{inline.text}</span>,
      )}
    </>
  );
}

interface MarkdownProps {
  text: string;
  className?: string;
}

export function Markdown({ text, className }: MarkdownProps) {
  return (
    <div className={className}>
      {parseMarkdown(text).map((block, index) => {
        if (block.kind === 'heading') {
          return (
            <p key={index} className="markdown__heading">
              <Inlines inlines={block.inlines} />
            </p>
          );
        }
        if (block.kind === 'paragraph') {
          return (
            <p key={index}>
              <Inlines inlines={block.inlines} />
            </p>
          );
        }
        const items = block.items.map((item, itemIndex) => (
          <li key={itemIndex}>
            <Inlines inlines={item} />
          </li>
        ));
        return block.ordered ? <ol key={index}>{items}</ol> : <ul key={index}>{items}</ul>;
      })}
    </div>
  );
}
```

- [ ] **Step 7: Replace `frontend/src/screens/Chat.tsx`**

```tsx
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { ArrowUpIcon, SparkleIcon } from '../components/Icons';
import { Markdown } from '../components/Markdown';
import { StatusPill } from '../components/StatusPill';
import { type ChatEvent, type Citation, fileUrl, listDocuments, streamChat } from '../api';
import './Chat.css';

const SUGGESTED_QUESTIONS = [
  'What is the fee schedule in the Tremblay agreement?',
  'How much notice is needed to terminate the Tremblay agreement?',
  'Which law governs the Tremblay agreement?',
  'What is the Calamos fund’s rate in excess of $26 billion?',
];

interface AssistantHeadProps {
  label: string;
  variant: 'neutral' | 'accent' | 'warning';
  detail?: string;
}

function AssistantHead({ label, variant, detail }: AssistantHeadProps) {
  return (
    <div className="chat__assistant-head">
      <SparkleIcon size={15} className="chat__sparkle" />
      <StatusPill variant={variant}>{label}</StatusPill>
      {detail && <span className="chat__tag mono">{detail}</span>}
    </div>
  );
}

type Turn = {
  question: string;
  step: string | null;
  outcome: 'pending' | 'answer' | 'refused' | 'error';
  text: string;
  citations: Citation[];
};

interface CitationCardProps {
  citation: Citation;
}

function CitationCard({ citation }: CitationCardProps) {
  const href = fileUrl(citation);
  return (
    <div className="citation-card">
      <div className="citation-card__head">
        <span className="citation-card__doc">{citation.document_title ?? citation.tool}</span>
        {citation.page !== undefined && (
          <span className="citation-card__loc">
            v{citation.version} · p.{citation.page}
            {citation.section ? ` · ${citation.section}` : ''}
          </span>
        )}
      </div>
      {citation.quote && <p className="mono citation-card__excerpt">{citation.quote}</p>}
      <div className="citation-card__foot">
        <span className="mono">{citation.id}</span>
        {href && (
          <a href={href} target="_blank" rel="noreferrer">
            Open page →
          </a>
        )}
      </div>
    </div>
  );
}

function newSessionId(): string {
  return `ses_${crypto.randomUUID().slice(0, 8)}`;
}

function prefersReducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function indexedLabel(count: number | null): string {
  if (count === null) return 'Indexed contracts';
  return `${count} indexed contract${count === 1 ? '' : 's'}`;
}

export function Chat() {
  const [inputValue, setInputValue] = useState('');
  const [sessionId, setSessionId] = useState(newSessionId);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [indexedCount, setIndexedCount] = useState<number | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const busy = turns.some((t) => t.outcome === 'pending');

  useEffect(() => {
    listDocuments()
      .then((docs) => setIndexedCount(docs.filter((d) => d.status === 'ready').length))
      .catch(() => setIndexedCount(null));
  }, []);

  useEffect(() => {
    const scroller = scrollRef.current;
    scroller?.scrollTo({ top: scroller.scrollHeight, behavior: prefersReducedMotion() ? 'auto' : 'smooth' });
  }, [turns]);

  const updateLast = (patch: Partial<Turn>) =>
    setTurns((all) => all.map((t, i) => (i === all.length - 1 ? { ...t, ...patch } : t)));

  const ask = async (question: string) => {
    if (!question.trim() || busy) return;
    setInputValue('');
    setTurns((all) => [...all, { question, step: null, outcome: 'pending', text: '', citations: [] }]);
    const onEvent = (event: ChatEvent) => {
      if (event.type === 'progress') updateLast({ step: event.data.step });
      else if (event.type === 'error') updateLast({ outcome: 'error', text: event.data.text });
      else updateLast({ outcome: event.type, text: event.data.text, citations: event.data.citations });
    };
    try {
      await streamChat(sessionId, question, onEvent);
    } catch (error) {
      updateLast({ outcome: 'error', text: error instanceof Error ? error.message : 'Chat failed' });
    } finally {
      inputRef.current?.focus();
    }
  };

  return (
    <div className="chat">
      <div className="chat__header">
        <div className="chat__header-main">
          <span className="chat__breadcrumb">Chat</span>
          <div className="chat__title-row">
            <h1 className="chat__title">Ask your contracts</h1>
            <Link to="/documents" className="chat__indexed-pill">
              <StatusPill variant="accent" dot>
                {indexedLabel(indexedCount)}
              </StatusPill>
            </Link>
            <span className="chat__session mono">session {sessionId}</span>
          </div>
        </div>
        <button
          type="button"
          className="btn btn-secondary chat__new-session"
          onClick={() => {
            setSessionId(newSessionId());
            setTurns([]);
          }}
        >
          + New session
        </button>
      </div>

      <div className="chat__scroll" ref={scrollRef}>
        <div className="chat__thread">
          {turns.length === 0 && (
            <div className="chat__prompts">
              <span className="chat__prompts-label">Suggested questions</span>
              <div className="chat__prompt-chips">
                {SUGGESTED_QUESTIONS.map((question) => (
                  <button type="button" className="chat__prompt-chip" key={question} onClick={() => void ask(question)}>
                    {question}
                  </button>
                ))}
              </div>
            </div>
          )}

          {turns.map((turn, index) => (
            <div className="chat__exchange" key={index}>
              <div className="chat__turn chat__turn--user">
                <div className="chat__bubble--user">{turn.question}</div>
              </div>
              <div className="chat__turn chat__turn--assistant" aria-live="polite">
                {turn.outcome === 'pending' && <AssistantHead label={turn.step ?? 'thinking'} variant="accent" />}
                {turn.outcome === 'answer' && (
                  <>
                    <AssistantHead label="Answer" variant="neutral" detail={`${turn.citations.length} citation(s)`} />
                    <Markdown className="chat__prose" text={turn.text} />
                    {turn.citations.length > 0 && (
                      <div className="chat__citations">
                        {turn.citations.map((c) => (
                          <CitationCard key={c.id} citation={c} />
                        ))}
                      </div>
                    )}
                  </>
                )}
                {(turn.outcome === 'refused' || turn.outcome === 'error') && (
                  <>
                    <AssistantHead label={turn.outcome === 'refused' ? 'No answer' : 'Error'} variant="warning" />
                    <Markdown className="chat__prose" text={turn.text} />
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="chat__composer">
        <form
          className="chat__composer-inner"
          onSubmit={(event) => {
            event.preventDefault();
            void ask(inputValue);
          }}
        >
          <div className="chat__composer-bar">
            <input
              ref={inputRef}
              type="text"
              className="chat__composer-input"
              placeholder="Ask about your indexed contracts…"
              aria-label="Ask about your indexed contracts"
              value={inputValue}
              onChange={(event) => setInputValue(event.target.value)}
            />
            <button
              type="submit"
              className="chat__composer-send"
              aria-label="Send message"
              disabled={busy || !inputValue.trim()}
            >
              <ArrowUpIcon size={16} />
            </button>
          </div>
          <div className="chat__composer-foot">
            Answers come only from your indexed contracts, every number is checked against the cited text, and the
            assistant says so when it can't find an answer.
          </div>
        </form>
      </div>
    </div>
  );
}
```

- [ ] **Step 8: Update `frontend/src/screens/Chat.css`**

1. Change `.chat { height: 100vh; }` to `height: 100dvh;` and inside `@media (max-width: 860px)` change `height: calc(100vh - 64px);` to `height: calc(100dvh - 64px);`.
2. Replace the `.chat__prompts-label` rule with (drops the uppercase tracked eyebrow):

```css
.chat__prompts-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-text-secondary);
  display: block;
  margin-bottom: 8px;
}
```

3. Replace the `.chat__prose` rule with:

```css
.chat__exchange {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.chat__prose {
  font-size: 14px;
  line-height: 1.65;
  margin-bottom: var(--space-1);
  max-width: 72ch;
}

.chat__prose > * + * {
  margin-top: 8px;
}

.chat__prose ul,
.chat__prose ol {
  margin: 0;
  padding-left: 20px;
}

.chat__prose li + li {
  margin-top: 4px;
}

.chat__prose .markdown__heading {
  font-weight: 600;
}

.chat__citations {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
```

4. Delete the unused rules `.chat__figure`, `.citation-card__score`, `.chat__no-answer-meta`, `.chat__no-answer-nudge`, `.chat__no-answer-nudge a`.
5. Add after `.chat__composer-send:hover`:

```css
.chat__composer-send:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
```

- [ ] **Step 9: Verify build, lint and tests**

Run: `cd frontend && npm test && npm run lint && npm run build`
Expected: all pass, no TypeScript errors.

- [ ] **Step 10: Check in the browser**

Start the backend (`cd backend && $PYDEV/bin/uvicorn app.main:app --reload`) and the frontend (`cd frontend && npm run dev`). Open `/chat`, ask two suggested questions. Confirm: a clear gap between each question and its answer and between exchanges; lists render as bullets; the thread scrolls to the newest answer; you can type while the answer streams; the pill reads "N indexed contracts".

- [ ] **Step 11: Commit**

```bash
graphify update .
git add frontend/package.json frontend/package-lock.json frontend/src/lib/markdown.ts frontend/src/lib/markdown.test.ts frontend/src/components/Markdown.tsx frontend/src/screens/Chat.tsx frontend/src/screens/Chat.css graphify-out
git commit -m "fix(frontend): space chat turns, render answer markdown and follow the newest answer"
```

(Stage `graphify-out` only if `graphify update` changed tracked files there; check `git status`.)

---

### Task 2: Account names on posting entries and proposed entries (backend, for F2/F3)

**Files:**
- Modify: `backend/app/ledger/dao.py` (add `AccountLabel`, `account_labels`)
- Modify: `backend/app/routes/postings.py` (`EntryOut`, `posting_out` and its three callers)
- Modify: `backend/app/routes/tool_invocations.py` (`_invocation_out` labels proposed entries)
- Test: `backend/tests/test_api_postings.py`, `backend/tests/test_governance.py`

**Interfaces:**
- Produces: `app.ledger.dao.account_labels(session: Session, account_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, AccountLabel]`, `AccountLabel(name: str, currency: str)`.
- API: every posting entry gains `"account_name": str, "currency": str`; every item of `proposed_entries` in `/tool-invocations` gains the same two keys.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_api_postings.py`:

```python
def test_entries_carry_account_name_and_currency(client, pair):
    created = _post(client, _body(pair), key=str(uuid.uuid4())).json()
    assert {e["account_name"]: e["currency"] for e in created["entries"]} == {"Cash": "CAD", "Revenue": "CAD"}
    listed = client.get("/postings").json()["items"][0]
    assert {e["account_name"] for e in listed["entries"]} == {"Cash", "Revenue"}
    fetched = client.get(f"/postings/{created['id']}").json()
    assert {e["account_name"] for e in fetched["entries"]} == {"Cash", "Revenue"}
```

Append to `backend/tests/test_governance.py` (in the API section):

```python
def test_listing_labels_proposed_entries_with_account_names(client, db_session, tenant_id, accounts):
    _record(db_session, tenant_id, accounts)
    [row] = client.get("/tool-invocations", params={"pending": "true"}).json()
    assert [(e["account_name"], e["direction"]) for e in row["proposed_entries"]] == [
        ("Employment Income Receivable", "debit"),
        ("Reported Income", "credit"),
    ]
    assert {e["currency"] for e in row["proposed_entries"]} == {"CAD"}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && $PYDEV/bin/pytest tests/test_api_postings.py::test_entries_carry_account_name_and_currency tests/test_governance.py::test_listing_labels_proposed_entries_with_account_names -v`
Expected: FAIL with `KeyError: 'account_name'`.

- [ ] **Step 3: Add `account_labels` to the ledger DAO**

In `backend/app/ledger/dao.py` (reuse the existing imports; add `Iterable` from `collections.abc` and `dataclass` if not imported):

```python
@dataclass(frozen=True)
class AccountLabel:
    name: str
    currency: str


def account_labels(session: Session, account_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, AccountLabel]:
    ids = set(account_ids)
    if not ids:
        return {}
    rows = session.execute(select(Account.id, Account.name, Account.currency).where(Account.id.in_(ids)))
    return {row.id: AccountLabel(row.name, row.currency) for row in rows}
```

- [ ] **Step 4: Label posting entries**

In `backend/app/routes/postings.py`:

```python
class EntryOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    account_name: str
    currency: str
    direction: Direction
    amount: int


def posting_out(posting: Posting, reversed_by: uuid.UUID | None, labels: dict[uuid.UUID, AccountLabel]) -> PostingOut:
    return PostingOut(
        id=posting.id,
        idempotency_key=posting.idempotency_key,
        description=posting.description,
        effective_at=posting.effective_at,
        created_at=posting.created_at,
        source=posting.source,
        reverses_posting_id=posting.reverses_posting_id,
        reversed_by_posting_id=reversed_by,
        entries=[
            EntryOut(id=e.id, account_id=e.account_id, account_name=labels[e.account_id].name,
                     currency=labels[e.account_id].currency, direction=e.direction, amount=e.amount)
            for e in posting.entries
        ],
    )


def _labels_for(session: Session, postings: list[Posting]) -> dict[uuid.UUID, AccountLabel]:
    return account_labels(session, (e.account_id for p in postings for e in p.entries))
```

Add `AccountLabel` and `account_labels` to the `from app.ledger.dao import (...)` list. Update the three callers:

```python
# _respond
return posting_out(result.posting, reversed_by, _labels_for(session, [result.posting]))

# list_postings_endpoint
labels = _labels_for(session, postings)
return PostingPage(items=[posting_out(p, reversals.get(p.id), labels) for p in postings], next_cursor=next_cursor)

# get_posting_endpoint
return posting_out(posting, reversal_ids_for(session, [posting.id]).get(posting.id), _labels_for(session, [posting]))
```

Run `grep -rn "posting_out(" backend/app` and confirm no other caller remains unchanged.

- [ ] **Step 5: Label proposed entries**

In `backend/app/routes/tool_invocations.py` import `account_labels` from `app.ledger.dao`, then:

```python
def _labelled(session: Session, entries: list | None) -> list | None:
    if entries is None:
        return None
    labels = account_labels(session, (uuid.UUID(e["account_id"]) for e in entries))
    return [
        e | {"account_name": labels[uuid.UUID(e["account_id"])].name, "currency": labels[uuid.UUID(e["account_id"])].currency}
        for e in entries
    ]
```

Give `_invocation_out` a leading `session: Session` parameter, use `proposed_entries=_labelled(session, invocation.proposed_entries)`, and pass `session` from `list_tool_invocations`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && $PYDEV/bin/pytest tests/test_api_postings.py tests/test_governance.py -v`
Expected: PASS. Then the full suite: `$PYDEV/bin/pytest` — expected: all green.

- [ ] **Step 7: Commit**

```bash
graphify update .
git add backend/app/ledger/dao.py backend/app/routes/postings.py backend/app/routes/tool_invocations.py backend/tests/test_api_postings.py backend/tests/test_governance.py
git commit -m "feat(api): name the account and currency on posting and proposed entries"
```

---

### Task 3: Review queue endpoints for `needs_review` fields (backend, for F1)

**Files:**
- Modify: `backend/app/contracts/errors.py` (three errors)
- Modify: `backend/app/contracts/dao.py` (`PendingField`, `_latest_run`, `pending_reviews`, `record_review`; `served_fields` reuses `_latest_run`)
- Modify: `backend/app/documents/dao.py` (`first_page`)
- Create: `backend/app/routes/reviews.py`
- Modify: `backend/app/main.py` (register router)
- Test: `backend/tests/test_reviews_api.py`

**Interfaces:**
- Produces: `GET /reviews` → `list[ReviewItemOut]` with keys `run_id, field_path, value, quote, grounded, validator_errors, page_grade, document_id, document_title, version, page`; `POST /reviews` body `{run_id, field_path, decision: "confirmed"|"corrected"|"rejected", corrected_value?, reason?}` → 201 `{run_id, field_path, decision, corrected_value, decided_by, reason, decided_at}`. Problems: 404 `/problems/field-not-found`, 409 `/problems/field-already-reviewed`, 422 `/problems/review-invalid`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_reviews_api.py`:

```python
import uuid
from decimal import Decimal

from sqlalchemy import select

from app.contracts import dao
from app.contracts.fields import FieldResult
from app.contracts.types import FieldRouting
from app.documents.models import DocumentElement
from tests.test_retrieval_index import parsed_version

CONFIG = dao.RunConfig("contract-terms-v1", "scripted", "p", Decimal(0), "c" * 64, "d" * 64)


def _run(db_session, tenant_id):
    version = parsed_version(db_session, tenant_id)
    element_ids = list(db_session.scalars(select(DocumentElement.id).where(DocumentElement.version_id == version.id)))
    run = dao.save_run(db_session, version.id, CONFIG, {"raw": True}, [
        FieldResult("currency", "CAD", [], "q", True, [], "GOOD", FieldRouting.accepted),
        FieldResult("fee_method", "cliff", element_ids[:1], "on the entire", False, [], "FAIR", FieldRouting.needs_review),
        FieldResult("termination_notice_days", 30, [], "thirty days", False, ["not a number"], "GOOD", FieldRouting.needs_review),
    ])
    db_session.commit()
    return version, run


def _decide(client, run, field_path, decision, **extra):
    return client.post("/reviews", json={"run_id": str(run.id), "field_path": field_path, "decision": decision, **extra})


def test_queue_lists_only_unreviewed_needs_review_fields(client, db_session, tenant_id):
    version, _ = _run(db_session, tenant_id)
    rows = client.get("/reviews").json()
    assert [r["field_path"] for r in rows] == ["fee_method", "termination_notice_days"]
    first = rows[0]
    assert first["document_id"] == str(version.document_id) and first["document_title"] == "Tremblay IMA"
    assert (first["version"], first["page"], first["page_grade"], first["value"]) == (1, 1, "FAIR", "cliff")
    assert rows[1]["page"] is None and rows[1]["validator_errors"] == ["not a number"]


def test_confirming_serves_the_field_and_leaves_the_queue(client, db_session, tenant_id):
    version, run = _run(db_session, tenant_id)
    response = _decide(client, run, "termination_notice_days", "confirmed")
    assert response.status_code == 201 and response.json()["decided_by"] == "demo_user"
    assert [r["field_path"] for r in client.get("/reviews").json()] == ["fee_method"]
    assert dao.served_fields(db_session, tenant_id, version.document_id).fields["termination_notice_days"].value == 30


def test_correction_requires_a_value_and_serves_it(client, db_session, tenant_id):
    version, run = _run(db_session, tenant_id)
    missing = _decide(client, run, "fee_method", "corrected")
    assert missing.status_code == 422 and missing.json()["type"] == "/problems/review-invalid"
    stray = _decide(client, run, "fee_method", "confirmed", corrected_value="graduated")
    assert stray.status_code == 422
    corrected = _decide(client, run, "fee_method", "corrected", corrected_value="graduated", reason="table says next")
    assert corrected.status_code == 201 and corrected.json()["corrected_value"] == "graduated"
    assert dao.served_fields(db_session, tenant_id, version.document_id).fields["fee_method"].value == "graduated"


def test_a_second_decision_is_a_conflict(client, db_session, tenant_id):
    _, run = _run(db_session, tenant_id)
    assert _decide(client, run, "fee_method", "rejected").status_code == 201
    again = _decide(client, run, "fee_method", "confirmed")
    assert again.status_code == 409 and again.json()["type"] == "/problems/field-already-reviewed"


def test_unknown_field_or_run_is_not_found(client, db_session, tenant_id):
    _, run = _run(db_session, tenant_id)
    assert _decide(client, run, "nope", "confirmed").status_code == 404
    unknown = client.post("/reviews", json={"run_id": str(uuid.uuid4()), "field_path": "fee_method", "decision": "confirmed"})
    assert unknown.status_code == 404 and unknown.json()["type"] == "/problems/field-not-found"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && $PYDEV/bin/pytest tests/test_reviews_api.py -v`
Expected: FAIL — `GET /reviews` returns 404 (route missing).

- [ ] **Step 3: Add the errors**

Append to `backend/app/contracts/errors.py`:

```python
class FieldNotFound(DomainError):
    status = 404
    type_slug = "field-not-found"
    title = "Extracted field not found"


class FieldAlreadyReviewed(DomainError):
    status = 409
    type_slug = "field-already-reviewed"
    title = "This field has already been reviewed"


class ReviewInvalid(DomainError):
    status = 422
    type_slug = "review-invalid"
    title = "The review decision is invalid"
```

- [ ] **Step 4: Add `first_page` to the documents DAO**

In `backend/app/documents/dao.py` (`func` and `DocumentElement` are already imported there; `Sequence` from `collections.abc` if missing):

```python
def first_page(session: Session, element_ids: Sequence[uuid.UUID]) -> int | None:
    if not element_ids:
        return None
    return session.scalar(select(func.min(DocumentElement.page_start)).where(DocumentElement.id.in_(element_ids)))
```

- [ ] **Step 5: Add the queue and decision to the contracts DAO**

In `backend/app/contracts/dao.py` add imports `from sqlalchemy.exc import IntegrityError` and `from app.contracts.errors import FieldAlreadyReviewed, FieldNotFound, ReviewInvalid`, then:

```python
@dataclass(frozen=True)
class PendingField:
    run_id: uuid.UUID
    field_path: str
    value: object
    quote: str
    grounded: bool
    validator_errors: list[str]
    page_grade: str
    document_id: uuid.UUID
    document_title: str
    version: int
    page: int | None


def _latest_run(session: Session, version_id: uuid.UUID) -> ExtractionRun | None:
    return session.scalars(
        select(ExtractionRun).where(ExtractionRun.version_id == version_id).order_by(ExtractionRun.created_at.desc())
    ).first()


def pending_reviews(session: Session, tenant_id: uuid.UUID) -> list[PendingField]:
    # ponytail: a few queries per contract; fine for a demo corpus, one joined query when it isn't
    pending: list[PendingField] = []
    for row in documents_dao.list_documents(session, tenant_id):
        run = _latest_run(session, row.version.id)
        if run is None:
            continue
        reviewed = set(session.scalars(select(FieldReview.field_path).where(FieldReview.run_id == run.id)))
        fields = session.scalars(
            select(ExtractedField)
            .where(ExtractedField.run_id == run.id, ExtractedField.routing == FieldRouting.needs_review)
            .order_by(ExtractedField.field_path)
        )
        pending += [
            PendingField(run.id, f.field_path, f.value, f.quote, f.grounded, list(f.validator_errors), f.page_grade,
                         row.document.id, row.document.title, row.version.version,
                         documents_dao.first_page(session, f.element_ids))
            for f in fields
            if f.field_path not in reviewed
        ]
    return pending


def record_review(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
    field_path: str,
    decision: ReviewDecision,
    corrected_value: object | None,
    reason: str | None,
    decided_by: str,
) -> FieldReview:
    if (decision is ReviewDecision.corrected) != (corrected_value is not None):
        raise ReviewInvalid("A corrected value is required for 'corrected' and not allowed for other decisions.")
    field = session.get(ExtractedField, (run_id, field_path))
    run = session.get(ExtractionRun, run_id) if field is not None else None
    if run is None or documents_dao.get_document_for_version(session, run.version_id).tenant_id != tenant_id:
        raise FieldNotFound(f"Field {field_path} of extraction run {run_id} does not exist.")
    review = FieldReview(run_id=run_id, field_path=field_path, decision=decision, corrected_value=corrected_value,
                         decided_by=decided_by, reason=reason)
    session.add(review)
    try:
        session.commit()
    except IntegrityError as exc:  # the primary key allows one decision per field
        session.rollback()
        raise FieldAlreadyReviewed(f"Field {field_path} of extraction run {run_id} has already been reviewed.") from exc
    return review
```

In `served_fields`, replace the inline `run = session.scalars(...).first()` with `run = _latest_run(session, version_id)`.

- [ ] **Step 6: Add the route**

`backend/app/routes/reviews.py`:

```python
import uuid
from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app import config
from app.contracts import dao as contracts_dao
from app.contracts.types import ReviewDecision
from app.deps import DECIDED_BY, get_session, get_tenant_id
from app.documents import dao as documents_dao

router = APIRouter(prefix="/reviews", tags=["contracts"])
SessionDep = Annotated[Session, Depends(get_session)]
TenantDep = Annotated[uuid.UUID, Depends(get_tenant_id)]


class ReviewItemOut(BaseModel):
    run_id: uuid.UUID
    field_path: str
    value: Any
    quote: str
    grounded: bool
    validator_errors: list[str]
    page_grade: str
    document_id: uuid.UUID
    document_title: str
    version: int
    page: int | None


class ReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: uuid.UUID
    field_path: str = Field(min_length=1, max_length=200)
    decision: ReviewDecision
    corrected_value: Any = None
    reason: str | None = Field(default=None, max_length=1000)


class ReviewOut(BaseModel):
    run_id: uuid.UUID
    field_path: str
    decision: ReviewDecision
    corrected_value: Any
    decided_by: str
    reason: str | None
    decided_at: datetime


@router.get("", response_model=list[ReviewItemOut])
def list_pending_reviews(session: SessionDep, tenant_id: TenantDep) -> list[ReviewItemOut]:
    items = contracts_dao.pending_reviews(session, tenant_id)
    if not items:
        return []
    # ponytail: detokenises for the single demo user, like the document preview; gate on permissions once auth exists
    quotes = documents_dao.reveal(session, tenant_id, [i.quote for i in items], config.require("PII_VAULT_KEY"))
    return [ReviewItemOut(**(asdict(item) | {"quote": quote})) for item, quote in zip(items, quotes)]


@router.post("", status_code=201, response_model=ReviewOut)
def submit_review(body: ReviewIn, session: SessionDep, tenant_id: TenantDep) -> ReviewOut:
    review = contracts_dao.record_review(
        session, tenant_id=tenant_id, run_id=body.run_id, field_path=body.field_path, decision=body.decision,
        corrected_value=body.corrected_value, reason=body.reason, decided_by=DECIDED_BY,
    )
    return ReviewOut(run_id=review.run_id, field_path=review.field_path, decision=review.decision,
                     corrected_value=review.corrected_value, decided_by=review.decided_by, reason=review.reason,
                     decided_at=review.decided_at)
```

In `backend/app/main.py` add `reviews` to the `from app.routes import ...` line and `app.include_router(reviews.router)`.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd backend && $PYDEV/bin/pytest tests/test_reviews_api.py tests/test_contracts_dao.py -v`
Expected: PASS. If a test fails with `permission denied for table field_reviews`, the app role lacks INSERT on it: **stop and report** — do not add a migration without approval. Then run the full suite: `$PYDEV/bin/pytest` — all green.

- [ ] **Step 8: Commit**

```bash
graphify update .
git add backend/app/contracts/errors.py backend/app/contracts/dao.py backend/app/documents/dao.py backend/app/routes/reviews.py backend/app/main.py backend/tests/test_reviews_api.py
git commit -m "feat(contracts): serve the needs_review queue and record review decisions"
```

---

### Task 4: Frontend API client and shared view helpers

**Files:**
- Modify: `frontend/src/api.ts`
- Create: `frontend/src/api.test.ts`
- Create: `frontend/src/lib/money.ts`, `frontend/src/lib/money.test.ts`
- Create: `frontend/src/lib/time.ts`, `frontend/src/lib/time.test.ts`
- Create: `frontend/src/lib/postings.ts`, `frontend/src/lib/postings.test.ts`
- Create: `frontend/src/lib/rowSelect.ts`

**Interfaces:**
- Consumes: the Task 2 and Task 3 API shapes.
- Produces (exact names later tasks use):
  - Types: `EntryDto`, `PostingSourceDto`, `PostingDto`, `PostingPage`, `ProposedEntryDto`, `ToolDecisionDto`, `ToolInvocationDto`, `ReviewItemDto`, `ReviewDecision`, `ReviewSubmission`.
  - Functions: `listPostings(options?: ListPostingsOptions): Promise<PostingPage>`, `reversePosting(postingId: string): Promise<PostingDto>`, `listToolInvocations(options?: ListInvocationsOptions): Promise<ToolInvocationDto[]>`, `decideToolInvocation(id: string, decision: 'approved' | 'rejected', reason?: string): Promise<ToolDecisionDto>`, `listReviews(): Promise<ReviewItemDto[]>`, `submitReview(input: ReviewSubmission): Promise<void>`, `checkHealth(): Promise<boolean>`, `documentPageUrl(documentId: string, version: number, page: number | null): string`.
  - `formatMinor(amountMinor: number, currency: string): string`; `formatUtc(iso: string): string`; `formatUtcFull(iso: string): string`.
  - `toPostingView(posting: PostingDto): PostingView`, types `PostingView`, `PostingStatus`, `JournalLineView`.
  - `selectableRow(selected: boolean, onSelect: () => void)`.

- [ ] **Step 1: Write the failing helper tests**

`frontend/src/lib/money.test.ts`:

```ts
import { expect, it } from 'vitest';
import { formatMinor } from './money';

it('formats minor units with two decimals, grouping and the currency code', () => {
  expect(formatMinor(150000, 'CAD')).toBe('1,500.00 CAD');
  expect(formatMinor(5, 'USD')).toBe('0.05 USD');
  expect(formatMinor(0, 'CAD')).toBe('0.00 CAD');
});
```

`frontend/src/lib/time.test.ts`:

```ts
import { expect, it } from 'vitest';
import { formatUtc, formatUtcFull } from './time';

it('formats an ISO timestamp as a short UTC label', () => {
  expect(formatUtc('2026-09-22T14:22:04Z')).toBe('22 Sep 2026 14:22 UTC');
});

it('formats an ISO timestamp with seconds', () => {
  expect(formatUtcFull('2026-09-22T14:22:04Z')).toBe('22 Sep 2026 14:22:04 UTC');
});
```

`frontend/src/lib/postings.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import type { EntryDto, PostingDto } from '../api';
import { toPostingView } from './postings';

function entry(direction: 'debit' | 'credit', amount: number, name: string): EntryDto {
  return { id: name, account_id: name, account_name: name, currency: 'CAD', direction, amount };
}

function posting(overrides: Partial<PostingDto> = {}): PostingDto {
  return {
    id: 'p1',
    idempotency_key: 'ai:i1',
    description: 'Approved compare_contract_to_billing result',
    effective_at: '2026-09-24T10:00:00Z',
    created_at: '2026-09-24T10:00:00Z',
    source: 'ai_tool',
    reverses_posting_id: null,
    reversed_by_posting_id: null,
    entries: [entry('debit', 150000, 'Fees receivable'), entry('credit', 150000, 'Advisory fee revenue')],
    ...overrides,
  };
}

describe('toPostingView', () => {
  it('uses the debit total as the amount and labels lines by account name', () => {
    const view = toPostingView(posting());
    expect(view.amount).toBe('1,500.00 CAD');
    expect(view.lines).toEqual([
      { account: 'Fees receivable', debit: '1,500.00 CAD', credit: null },
      { account: 'Advisory fee revenue', debit: null, credit: '1,500.00 CAD' },
    ]);
    expect(view.balanced).toBe(true);
  });

  it('flags an unbalanced posting', () => {
    expect(toPostingView(posting({ entries: [entry('debit', 100, 'A'), entry('credit', 90, 'B')] })).balanced).toBe(false);
  });

  it('derives the status from the reversal links', () => {
    expect(toPostingView(posting()).status).toBe('posted');
    expect(toPostingView(posting({ reversed_by_posting_id: 'p2' })).status).toBe('reversed');
    expect(toPostingView(posting({ reverses_posting_id: 'p0' })).status).toBe('reversal');
  });

  it('names a posting without a description', () => {
    expect(toPostingView(posting({ description: null })).description).toBe('No description');
  });
});
```

`frontend/src/api.test.ts`:

```ts
import { afterEach, expect, it, vi } from 'vitest';
import { API_BASE, checkHealth, decideToolInvocation, listPostings, reversePosting } from './api';

type Call = { url: string; init?: RequestInit };

function respondWith(body: unknown, status = 200): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal('fetch', (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
  });
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

it('reports the API unreachable when the request fails', async () => {
  vi.stubGlobal('fetch', () => Promise.reject(new TypeError('Failed to fetch')));
  expect(await checkHealth()).toBe(false);
});

it('reports the API connected on a 200', async () => {
  respondWith({ status: 'ok' });
  expect(await checkHealth()).toBe(true);
});

it('reverses with a key derived from the posting id so a retry replays', async () => {
  const calls = respondWith({ id: 'p2' }, 201);
  await reversePosting('p1');
  expect(calls[0].url).toBe(`${API_BASE}/postings/p1/reversal`);
  expect(new Headers(calls[0].init?.headers).get('Idempotency-Key')).toBe('reverse:p1');
});

it('passes list filters as query parameters', async () => {
  const calls = respondWith({ items: [], next_cursor: null });
  await listPostings({ source: 'ai_tool', includeStress: true, limit: 20 });
  expect(calls[0].url).toBe(`${API_BASE}/postings?source=ai_tool&include_stress=true&limit=20`);
});

it('surfaces the problem detail as the error message', async () => {
  respondWith({ detail: 'Tool invocation i1 has already been decided.' }, 409);
  await expect(decideToolInvocation('i1', 'approved')).rejects.toThrow('already been decided');
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd frontend && npm test`
Expected: FAIL — missing modules `./money`, `./time`, `./postings` and missing exports in `./api`.

- [ ] **Step 3: Implement the helpers**

`frontend/src/lib/money.ts`:

```ts
export function formatMinor(amountMinor: number, currency: string): string {
  const major = (amountMinor / 100).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${major} ${currency}`;
}
```

`frontend/src/lib/time.ts`:

```ts
// "Tue, 22 Sep 2026 14:22:04 GMT" → "22 Sep 2026 14:22"
export function formatUtc(iso: string): string {
  return `${new Date(iso).toUTCString().slice(5, 22)} UTC`;
}

export function formatUtcFull(iso: string): string {
  return `${new Date(iso).toUTCString().slice(5, 25)} UTC`;
}
```

`frontend/src/lib/postings.ts`:

```ts
import type { PostingDto, PostingSourceDto } from '../api';
import { formatMinor } from './money';

export type PostingStatus = 'posted' | 'reversed' | 'reversal';

export interface JournalLineView {
  account: string;
  debit: string | null;
  credit: string | null;
}

export interface PostingView {
  id: string;
  description: string;
  source: PostingSourceDto;
  status: PostingStatus;
  createdAt: string;
  amount: string;
  idempotencyKey: string;
  reversedBy: string | null;
  reverses: string | null;
  lines: JournalLineView[];
  debitTotal: string;
  creditTotal: string;
  balanced: boolean;
}

function statusOf(posting: PostingDto): PostingStatus {
  if (posting.reversed_by_posting_id) return 'reversed';
  if (posting.reverses_posting_id) return 'reversal';
  return 'posted';
}

// ponytail: totals use the first entry's currency; a multi-currency posting would need one total per currency
export function toPostingView(posting: PostingDto): PostingView {
  const currency = posting.entries[0]?.currency ?? '';
  const total = (side: 'debit' | 'credit') =>
    posting.entries.filter((e) => e.direction === side).reduce((sum, e) => sum + e.amount, 0);
  const debit = total('debit');
  const credit = total('credit');
  return {
    id: posting.id,
    description: posting.description ?? 'No description',
    source: posting.source,
    status: statusOf(posting),
    createdAt: posting.created_at,
    amount: formatMinor(debit, currency),
    idempotencyKey: posting.idempotency_key,
    reversedBy: posting.reversed_by_posting_id,
    reverses: posting.reverses_posting_id,
    lines: posting.entries.map((e) => ({
      account: e.account_name,
      debit: e.direction === 'debit' ? formatMinor(e.amount, e.currency) : null,
      credit: e.direction === 'credit' ? formatMinor(e.amount, e.currency) : null,
    })),
    debitTotal: formatMinor(debit, currency),
    creditTotal: formatMinor(credit, currency),
    balanced: debit === credit,
  };
}
```

`frontend/src/lib/rowSelect.ts`:

```ts
import type { KeyboardEvent } from 'react';

// Makes a clickable table row reachable and operable from the keyboard.
export function selectableRow(selected: boolean, onSelect: () => void) {
  return {
    tabIndex: 0,
    'aria-current': selected ? ('true' as const) : undefined,
    onClick: onSelect,
    onKeyDown: (event: KeyboardEvent) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        onSelect();
      }
    },
  };
}
```

- [ ] **Step 4: Extend `frontend/src/api.ts`**

Append (keep everything already there):

```ts
export type PostingSourceDto = 'api' | 'fee_run' | 'ai_tool' | 'stress_test';

export interface EntryDto {
  id: string;
  account_id: string;
  account_name: string;
  currency: string;
  direction: 'debit' | 'credit';
  amount: number;
}

export interface PostingDto {
  id: string;
  idempotency_key: string;
  description: string | null;
  effective_at: string;
  created_at: string;
  source: PostingSourceDto;
  reverses_posting_id: string | null;
  reversed_by_posting_id: string | null;
  entries: EntryDto[];
}

export interface PostingPage {
  items: PostingDto[];
  next_cursor: string | null;
}

export interface ProposedEntryDto {
  account_id: string;
  account_name: string;
  currency: string;
  direction: 'debit' | 'credit';
  amount: number;
}

export interface ToolDecisionDto {
  invocation_id: string;
  decision: 'approved' | 'rejected';
  decided_by: string;
  reason: string | null;
  decided_at: string;
  posting_id: string | null;
}

export interface ToolInvocationDto {
  id: string;
  session_id: string;
  created_at: string;
  tool_name: string;
  tool_version: string;
  model_provider: string;
  model_id: string;
  prompt_version: string;
  temperature: string;
  input: Record<string, unknown>;
  result_amount_minor: number | null;
  result_currency: string | null;
  citation: Record<string, unknown> | null;
  proposed_entries: ProposedEntryDto[] | null;
  approval_required: boolean;
  decision: ToolDecisionDto | null;
}

export type ReviewDecision = 'confirmed' | 'corrected' | 'rejected';

export interface ReviewItemDto {
  run_id: string;
  field_path: string;
  value: unknown;
  quote: string;
  grounded: boolean;
  validator_errors: string[];
  page_grade: string;
  document_id: string;
  document_title: string;
  version: number;
  page: number | null;
}

export interface ReviewSubmission {
  run_id: string;
  field_path: string;
  decision: ReviewDecision;
  corrected_value: unknown;
  reason: string | null;
}

export interface ListPostingsOptions {
  source?: PostingSourceDto;
  includeStress?: boolean;
  limit?: number;
  cursor?: string;
}

export interface ListInvocationsOptions {
  pending?: boolean;
  postingId?: string;
  limit?: number;
}

function withQuery(path: string, params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value !== undefined) search.set(key, String(value));
  const query = search.toString();
  return query ? `${path}?${query}` : path;
}

function postJson(url: string, body: unknown, headers: Record<string, string> = {}): Promise<Response> {
  return fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json', ...headers }, body: JSON.stringify(body) });
}

export function listPostings(options: ListPostingsOptions = {}): Promise<PostingPage> {
  const url = withQuery(`${API_BASE}/postings`, {
    source: options.source,
    include_stress: options.includeStress,
    limit: options.limit,
    cursor: options.cursor,
  });
  return fetch(url).then((r) => json<PostingPage>(r));
}

// The key is derived from the posting, so a double click or a retry replays the same reversal.
export function reversePosting(postingId: string): Promise<PostingDto> {
  return postJson(`${API_BASE}/postings/${postingId}/reversal`, {}, { 'Idempotency-Key': `reverse:${postingId}` }).then((r) =>
    json<PostingDto>(r),
  );
}

export function listToolInvocations(options: ListInvocationsOptions = {}): Promise<ToolInvocationDto[]> {
  const url = withQuery(`${API_BASE}/tool-invocations`, {
    pending: options.pending,
    posting_id: options.postingId,
    limit: options.limit,
  });
  return fetch(url).then((r) => json<ToolInvocationDto[]>(r));
}

export function decideToolInvocation(
  invocationId: string,
  decision: 'approved' | 'rejected',
  reason?: string,
): Promise<ToolDecisionDto> {
  return postJson(`${API_BASE}/tool-invocations/${invocationId}/decision`, { decision, reason: reason ?? null }).then((r) =>
    json<ToolDecisionDto>(r),
  );
}

export function listReviews(): Promise<ReviewItemDto[]> {
  return fetch(`${API_BASE}/reviews`).then((r) => json<ReviewItemDto[]>(r));
}

export function submitReview(input: ReviewSubmission): Promise<void> {
  return postJson(`${API_BASE}/reviews`, input).then((r) => json<unknown>(r)).then(() => undefined);
}

export function checkHealth(): Promise<boolean> {
  return fetch(`${API_BASE}/health`)
    .then((r) => r.ok)
    .catch(() => false);
}

export function documentPageUrl(documentId: string, version: number, page: number | null): string {
  const url = `${API_BASE}/documents/${documentId}/versions/${version}/file`;
  return page === null ? url : `${url}#page=${page}`;
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd frontend && npm test && npm run lint && npm run build`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
graphify update .
git add frontend/src/api.ts frontend/src/api.test.ts frontend/src/lib/money.ts frontend/src/lib/money.test.ts frontend/src/lib/time.ts frontend/src/lib/time.test.ts frontend/src/lib/postings.ts frontend/src/lib/postings.test.ts frontend/src/lib/rowSelect.ts
git commit -m "feat(frontend): add API client calls and view helpers for ledger, approvals and reviews"
```

---

### Task 5: Ledger screen on real postings (F2, F16, F17)

**Files:**
- Modify: `frontend/src/screens/Ledger.tsx` (full replacement below)
- Modify: `frontend/src/screens/Ledger.css` (add three rules)

**Interfaces:**
- Consumes: `listPostings`, `listToolInvocations`, `reversePosting`, `PostingSourceDto`, `ToolInvocationDto` (Task 4); `toPostingView`, `PostingView`, `PostingStatus`, `formatUtc`, `formatUtcFull`, `selectableRow` (Task 4).
- Produces: route `/ledger?posting=<id>` preselects that posting (used by Tasks 6 and 7).

- [ ] **Step 1: Replace `frontend/src/screens/Ledger.tsx`**

```tsx
import { useCallback, useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { type PostingSourceDto, type ToolInvocationDto, listPostings, listToolInvocations, reversePosting } from '../api';
import { CheckIcon, LockIcon, SearchIcon } from '../components/Icons';
import { CopyButton } from '../components/CopyButton';
import { StatusPill, type StatusVariant } from '../components/StatusPill';
import { type PostingStatus, type PostingView, toPostingView } from '../lib/postings';
import { selectableRow } from '../lib/rowSelect';
import { formatUtc, formatUtcFull } from '../lib/time';
import './Ledger.css';

const PAGE_SIZE = 50;

const SOURCE_FILTERS: Array<{ id: 'all' | PostingSourceDto; label: string }> = [
  { id: 'all', label: 'All' },
  { id: 'ai_tool', label: 'AI tool' },
  { id: 'fee_run', label: 'Fee run' },
  { id: 'api', label: 'API' },
];

const SOURCE_CHIP: Record<PostingSourceDto, { variant: StatusVariant; label: string }> = {
  ai_tool: { variant: 'accent', label: 'AI tool' },
  fee_run: { variant: 'neutral', label: 'Fee run' },
  api: { variant: 'neutral', label: 'API' },
  stress_test: { variant: 'warning', label: 'Stress test' },
};

const STATUS_PILL: Record<PostingStatus, { variant: StatusVariant; label: string }> = {
  posted: { variant: 'success', label: 'Posted' },
  reversed: { variant: 'neutral', label: 'Reversed' },
  reversal: { variant: 'purple', label: 'Reversal' },
};

interface ProvenanceProps {
  postingId: string;
}

function Provenance({ postingId }: ProvenanceProps) {
  const [invocations, setInvocations] = useState<ToolInvocationDto[] | null>(null);

  useEffect(() => {
    listToolInvocations({ postingId })
      .then(setInvocations)
      .catch(() => setInvocations([]));
  }, [postingId]);

  if (invocations === null) return <p className="ledger__help">Loading provenance…</p>;
  const invocation = invocations[0];
  if (!invocation) return <p className="ledger__help">No tool invocation is linked to this posting.</p>;
  return (
    <dl className="ledger__provenance">
      <dt>Tool</dt>
      <dd className="mono">{invocation.tool_name}</dd>
      <dt>Model</dt>
      <dd className="mono">{invocation.model_id}</dd>
      <dt>Prompt</dt>
      <dd className="mono">{invocation.prompt_version}</dd>
      <dt>Chat session</dt>
      <dd className="mono">{invocation.session_id}</dd>
      <dt>Approved by</dt>
      <dd className="mono">
        {invocation.decision ? `${invocation.decision.decided_by} · ${formatUtc(invocation.decision.decided_at)}` : '—'}
      </dd>
    </dl>
  );
}

interface ReverseActionProps {
  posting: PostingView;
  onReversed: (reversalId: string) => void;
}

function ReverseAction({ posting, onReversed }: ReverseActionProps) {
  const [confirming, setConfirming] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reverse = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const reversal = await reversePosting(posting.id);
      onReversed(reversal.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The reversal was not posted');
    } finally {
      setSubmitting(false);
    }
  };

  if (!confirming) {
    return (
      <>
        <button type="button" className="btn btn-secondary ledger__reverse-btn" onClick={() => setConfirming(true)}>
          Reverse posting
        </button>
        <p className="ledger__help">Creates a compensating posting. The original stays in the ledger.</p>
      </>
    );
  }
  return (
    <>
      <div className="ledger__confirm-row">
        <button type="button" className="btn btn-primary" disabled={submitting} onClick={() => void reverse()}>
          {submitting ? 'Posting reversal…' : 'Confirm reversal'}
        </button>
        <button type="button" className="btn btn-secondary" disabled={submitting} onClick={() => setConfirming(false)}>
          Cancel
        </button>
      </div>
      {error && (
        <p className="ledger__error" role="alert">
          {error}
        </p>
      )}
    </>
  );
}

export function Ledger() {
  const [searchParams] = useSearchParams();
  const [postings, setPostings] = useState<PostingView[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(searchParams.get('posting'));
  const [query, setQuery] = useState('');
  const [sourceFilter, setSourceFilter] = useState<'all' | PostingSourceDto>('all');
  const [includeStress, setIncludeStress] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (cursor?: string) => {
      setLoading(true);
      setError(null);
      try {
        const page = await listPostings({
          source: sourceFilter === 'all' ? undefined : sourceFilter,
          includeStress,
          limit: PAGE_SIZE,
          cursor,
        });
        const views = page.items.map(toPostingView);
        setPostings((current) => (cursor ? [...current, ...views] : views));
        setNextCursor(page.next_cursor);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Could not load postings');
      } finally {
        setLoading(false);
      }
    },
    [sourceFilter, includeStress],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const q = query.trim().toLowerCase();
  const rows = postings.filter(
    (p) => !q || [p.id, p.idempotencyKey, p.description].some((field) => field.toLowerCase().includes(q)),
  );
  const selected = postings.find((p) => p.id === selectedId) ?? rows[0];

  return (
    <div className="ledger">
      <div className="ledger__topbar">
        <span className="ledger__breadcrumb">
          Ledger / <span>Postings</span>
        </span>
      </div>

      <div className="ledger__body">
        <div className="ledger__header">
          <h1 className="ledger__title">
            Postings
            <span className="ledger__readonly-badge mono">
              <LockIcon size={11} /> Append-only
            </span>
          </h1>
          <p className="ledger__subtitle">
            Every journal entry in the double-entry ledger. Postings are never edited — a correction is a compensating
            reversal.
          </p>
        </div>

        <div className="ledger__toolbar">
          <div className="ledger__filter-input">
            <SearchIcon size={14} />
            <input
              type="text"
              aria-label="Filter postings"
              placeholder="Filter by posting ID, idempotency key, or description…"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </div>
          <div className="segmented" role="group" aria-label="Filter by source">
            {SOURCE_FILTERS.map((f) => (
              <button
                type="button"
                key={f.id}
                aria-pressed={sourceFilter === f.id}
                className={`segmented__item${sourceFilter === f.id ? ' segmented__item--active' : ''}`}
                onClick={() => setSourceFilter(f.id)}
              >
                {f.label}
              </button>
            ))}
          </div>
          <label className="ledger__checkbox">
            <input type="checkbox" checked={includeStress} onChange={(event) => setIncludeStress(event.target.checked)} />
            Include stress-test postings
          </label>
          <span className="ledger__count mono">{rows.length} postings</span>
        </div>

        {error && (
          <p className="ledger__error" role="alert">
            {error}
          </p>
        )}

        <div className="ledger__grid">
          <div className="panel ledger__table-panel">
            <div className="scroll-x">
              <table className="data-table">
                <colgroup>
                  <col className="col-id" />
                  <col />
                  <col className="col-amount" />
                  <col className="col-created" />
                  <col className="col-source" />
                </colgroup>
                <thead>
                  <tr>
                    <th>Posting</th>
                    <th>Description</th>
                    <th style={{ textAlign: 'right' }}>Amount</th>
                    <th>Created</th>
                    <th>Source</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((posting) => {
                    const pill = STATUS_PILL[posting.status];
                    const chip = SOURCE_CHIP[posting.source];
                    return (
                      <tr
                        key={posting.id}
                        className={posting.id === selected?.id ? 'ledger__row--selected' : undefined}
                        {...selectableRow(posting.id === selected?.id, () => setSelectedId(posting.id))}
                      >
                        <td className="mono ledger__id">{posting.id.slice(0, 8)}</td>
                        <td>
                          <div className="ledger__desc">{posting.description}</div>
                          <div className="ledger__desc-sub mono" title={posting.idempotencyKey}>
                            {posting.idempotencyKey}
                          </div>
                        </td>
                        <td className="ledger__amount-cell">
                          <div className={`mono ledger__amount${posting.status === 'reversed' ? ' ledger__amount--struck' : ''}`}>
                            {posting.amount}
                          </div>
                          <StatusPill variant={pill.variant}>{pill.label}</StatusPill>
                        </td>
                        <td className="mono ledger__created">{formatUtc(posting.createdAt)}</td>
                        <td>
                          <StatusPill variant={chip.variant}>{chip.label}</StatusPill>
                        </td>
                      </tr>
                    );
                  })}
                  {!loading && rows.length === 0 && (
                    <tr>
                      <td colSpan={5} className="ledger__empty">
                        No postings match. Approve a fee correction in Review, or post through the API.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <div className="ledger__table-foot">
              <span>
                {loading ? 'Loading…' : `Showing ${rows.length} postings`}
                {nextCursor && !loading && (
                  <>
                    {' · '}
                    <button type="button" className="ledger__link-btn" onClick={() => void load(nextCursor)}>
                      Load more
                    </button>
                  </>
                )}
              </span>
              <span className="ledger__invariant">
                <CheckIcon size={13} /> Every posting balances — debits = credits enforced by a database constraint
              </span>
            </div>
          </div>

          {selected ? (
            <aside className="panel ledger__detail-panel">
              <div className="ledger__detail-head">
                <span className="ledger__label mono">Posting</span>
                <span className="ledger__detail-id-value mono">{selected.id}</span>
                <CopyButton value={selected.id} />
                <span className="ledger__detail-immutable">
                  <StatusPill variant="neutral">
                    <LockIcon size={10} /> Immutable
                  </StatusPill>
                </span>
              </div>

              <h2 className="ledger__detail-desc">{selected.description}</h2>
              <div className={`ledger__detail-amount mono${selected.status === 'reversed' ? ' ledger__amount--struck' : ''}`}>
                {selected.amount}
              </div>
              <div className="ledger__detail-meta">
                <StatusPill variant={STATUS_PILL[selected.status].variant}>{STATUS_PILL[selected.status].label}</StatusPill>
                <span className="mono">Created {formatUtcFull(selected.createdAt)}</span>
              </div>

              <section className="ledger__detail-section">
                <div className="ledger__detail-section-head">
                  <span>Journal entries</span>
                  <StatusPill variant={selected.balanced ? 'success' : 'error'}>
                    {selected.balanced ? 'Balanced' : 'Unbalanced'}
                  </StatusPill>
                </div>
                <table className="ledger__journal">
                  <thead>
                    <tr>
                      <th>Account</th>
                      <th className="num">Debit</th>
                      <th className="num">Credit</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selected.lines.map((line, index) => (
                      <tr key={index}>
                        <td>{line.account}</td>
                        <td className="num mono">{line.debit ?? '—'}</td>
                        <td className="num mono">{line.credit ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr>
                      <td>Total</td>
                      <td className="num mono">{selected.debitTotal}</td>
                      <td className="num mono">{selected.creditTotal}</td>
                    </tr>
                  </tfoot>
                </table>
              </section>

              <section className="ledger__detail-section">
                <div className="ledger__detail-section-head">
                  <span>Idempotency</span>
                </div>
                <div className="ledger__key-box mono">
                  <span>{selected.idempotencyKey}</span>
                  <CopyButton value={selected.idempotencyKey} />
                </div>
                <p className="ledger__help">
                  Replaying this key returns this same posting. Same key with a different payload is rejected (409).
                </p>
              </section>

              {selected.source === 'ai_tool' && (
                <section className="ledger__detail-section">
                  <div className="ledger__detail-section-head">
                    <span>AI provenance</span>
                  </div>
                  <Provenance postingId={selected.id} />
                </section>
              )}

              <div className="ledger__detail-actions">
                {selected.reversedBy ? (
                  <button type="button" className="ledger__link-btn" onClick={() => setSelectedId(selected.reversedBy)}>
                    Reversed by {selected.reversedBy.slice(0, 8)} →
                  </button>
                ) : selected.status === 'reversal' ? (
                  <Link to={`/ledger?posting=${selected.reverses}`} onClick={() => setSelectedId(selected.reverses)}>
                    Reverses {selected.reverses?.slice(0, 8)} →
                  </Link>
                ) : (
                  <ReverseAction
                    key={selected.id}
                    posting={selected}
                    onReversed={(reversalId) => {
                      setSelectedId(reversalId);
                      void load();
                    }}
                  />
                )}
              </div>
            </aside>
          ) : (
            <aside className="panel ledger__detail-panel">
              <p className="ledger__help">{loading ? 'Loading…' : 'Select a posting to see its journal entries.'}</p>
            </aside>
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Add the CSS rules**

Append to `frontend/src/screens/Ledger.css`:

```css
.ledger__confirm-row {
  display: flex;
  gap: var(--space-1);
  flex-wrap: wrap;
}

.ledger__error {
  color: var(--color-error);
  font-size: 13px;
  margin: var(--space-1) 0;
}

.ledger__empty {
  color: var(--color-text-secondary);
  text-align: center;
  padding: var(--space-4) var(--space-2);
}
```

- [ ] **Step 3: Verify**

Run: `cd frontend && npm test && npm run lint && npm run build`
Expected: pass. In the browser (backend running, `backend/scripts/seed_demo.py` run once if the ledger is empty): `/ledger` lists real postings with account names; Tab reaches rows and Enter selects; "Include stress-test postings" shows stress rows; "Reverse posting" → "Confirm reversal" posts a reversal that becomes selected and the original shows "Reversed".

- [ ] **Step 4: Commit**

```bash
graphify update .
git add frontend/src/screens/Ledger.tsx frontend/src/screens/Ledger.css
git commit -m "feat(frontend): show real ledger postings with provenance and reversal"
```

---

### Task 6: Review screen and approval card (F1, F3)

**Files:**
- Create: `frontend/src/lib/review.ts`, `frontend/src/lib/review.test.ts`
- Create: `frontend/src/components/ApprovalCard.tsx`, `frontend/src/components/ApprovalCard.css`
- Create: `frontend/src/screens/Review.tsx`, `frontend/src/screens/Review.css`
- Modify: `frontend/src/screens/Chat.tsx`, `frontend/src/screens/Chat.css`
- Modify: `frontend/src/App.tsx`, `frontend/src/components/Sidebar.tsx`

**Interfaces:**
- Consumes: `listReviews`, `submitReview`, `listToolInvocations`, `decideToolInvocation`, `documentPageUrl`, `ReviewItemDto`, `ReviewDecision`, `ToolInvocationDto`, `ToolDecisionDto`, `formatMinor`, `formatUtc` (Task 4).
- Produces: route `/review` with anchor `#approvals`; component `ApprovalCard({ invocation, onDecided? })`; `formatValue(value: unknown): string`, `parseCorrection(text: string): unknown`, `reviewReasons(item: ReviewItemDto): string[]`.

- [ ] **Step 1: Write the failing helper tests**

`frontend/src/lib/review.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import type { ReviewItemDto } from '../api';
import { formatValue, parseCorrection, reviewReasons } from './review';

describe('formatValue', () => {
  it('shows strings as-is and everything else as JSON', () => {
    expect(formatValue('graduated')).toBe('graduated');
    expect(formatValue(30)).toBe('30');
    expect(formatValue([{ up_to: 1000000, rate_bps: 100 }])).toBe('[{"up_to":1000000,"rate_bps":100}]');
  });
});

describe('parseCorrection', () => {
  it('parses JSON when it can and keeps plain text otherwise', () => {
    expect(parseCorrection('30')).toBe(30);
    expect(parseCorrection('[1,2]')).toEqual([1, 2]);
    expect(parseCorrection('"USD"')).toBe('USD');
    expect(parseCorrection('graduated')).toBe('graduated');
  });

  it('treats blank or null input as no correction', () => {
    expect(parseCorrection('   ')).toBeUndefined();
    expect(parseCorrection('null')).toBeUndefined();
  });
});

describe('reviewReasons', () => {
  const item: ReviewItemDto = {
    run_id: 'r1', field_path: 'fee_method', value: 'cliff', quote: 'on the entire', grounded: false,
    validator_errors: ['tiers overlap'], page_grade: 'FAIR', document_id: 'd1', document_title: 'Tremblay IMA',
    version: 1, page: 2,
  };

  it('explains why a field was held back', () => {
    expect(reviewReasons(item)).toEqual([
      'The quote was not found in the cited text.',
      'Validator: tiers overlap',
      'Page quality is FAIR (needs GOOD or better).',
    ]);
  });

  it('returns nothing for a grounded field on a good page', () => {
    expect(reviewReasons({ ...item, grounded: true, validator_errors: [], page_grade: 'GOOD' })).toEqual([]);
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/lib/review.test.ts`
Expected: FAIL — cannot resolve `./review`.

- [ ] **Step 3: Implement `frontend/src/lib/review.ts`**

```ts
import type { ReviewItemDto } from '../api';

const ACCEPTED_GRADES = ['GOOD', 'EXCELLENT'];

export function formatValue(value: unknown): string {
  return typeof value === 'string' ? value : JSON.stringify(value);
}

// A reviewer can type JSON (numbers, tier lists) or plain text; blank and null mean "nothing entered".
export function parseCorrection(text: string): unknown {
  const trimmed = text.trim();
  if (!trimmed) return undefined;
  try {
    const parsed: unknown = JSON.parse(trimmed);
    return parsed === null ? undefined : parsed;
  } catch {
    return trimmed;
  }
}

export function reviewReasons(item: ReviewItemDto): string[] {
  const reasons: string[] = [];
  if (!item.grounded) reasons.push('The quote was not found in the cited text.');
  for (const error of item.validator_errors) reasons.push(`Validator: ${error}`);
  if (!ACCEPTED_GRADES.includes(item.page_grade)) reasons.push(`Page quality is ${item.page_grade} (needs GOOD or better).`);
  return reasons;
}
```

Run: `cd frontend && npx vitest run src/lib/review.test.ts` — expected PASS.

- [ ] **Step 4: Move the tool-card styles into `ApprovalCard.css`**

Cut from `frontend/src/screens/Chat.css` every rule from the comment `/* Tool-call card — visually distinct from a retrieval answer */` through `.tool-card__posted a { … }`, plus the `.tool-card__facts` and `.tool-card__actions` rules inside the `@media (max-width: 860px)` block, and paste them into `frontend/src/components/ApprovalCard.css` (wrap the two media rules in their own `@media (max-width: 860px)` block). Then append:

```css
.tool-card__error {
  color: var(--color-error);
  font-size: 12px;
}
```

- [ ] **Step 5: Create `frontend/src/components/ApprovalCard.tsx`**

```tsx
import { useState } from 'react';
import { Link } from 'react-router';
import { type ToolDecisionDto, type ToolInvocationDto, decideToolInvocation } from '../api';
import { formatMinor } from '../lib/money';
import { formatUtc } from '../lib/time';
import { StatusPill } from './StatusPill';
import './ApprovalCard.css';

interface ApprovalCardProps {
  invocation: ToolInvocationDto;
  onDecided?: (decision: ToolDecisionDto) => void;
}

export function ApprovalCard({ invocation, onDecided }: ApprovalCardProps) {
  const [decision, setDecision] = useState<ToolDecisionDto | null>(invocation.decision);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const entries = invocation.proposed_entries ?? [];
  const result =
    invocation.result_amount_minor !== null && invocation.result_currency
      ? formatMinor(invocation.result_amount_minor, invocation.result_currency)
      : '—';

  const decide = async (choice: 'approved' | 'rejected') => {
    setSubmitting(true);
    setError(null);
    try {
      const recorded = await decideToolInvocation(invocation.id, choice);
      setDecision(recorded);
      onDecided?.(recorded);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The decision was not recorded');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="tool-card">
      <div className="tool-card__head">
        <span className="tool-card__name mono">{invocation.tool_name}</span>
        {decision === null ? (
          <StatusPill variant="warning">Awaiting approval</StatusPill>
        ) : (
          <StatusPill variant={decision.decision === 'approved' ? 'success' : 'neutral'}>
            {decision.decision === 'approved' ? 'Approved' : 'Rejected'}
          </StatusPill>
        )}
      </div>
      <dl className="tool-card__facts">
        <div>
          <dt>Result</dt>
          <dd className="mono tool-card__result">{result}</dd>
        </div>
        <div>
          <dt>Model</dt>
          <dd className="mono">{invocation.model_id}</dd>
        </div>
        <div>
          <dt>Session</dt>
          <dd className="mono">{invocation.session_id}</dd>
        </div>
        <div>
          <dt>Proposed</dt>
          <dd className="mono">{formatUtc(invocation.created_at)}</dd>
        </div>
      </dl>
      <div className="tool-card__section">
        <div className="tool-card__section-head">Proposed journal entry</div>
        <table className="tool-card__table">
          <thead>
            <tr>
              <th>Account</th>
              <th className="num">Debit</th>
              <th className="num">Credit</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry, index) => (
              <tr key={index}>
                <td>{entry.account_name}</td>
                <td className="num mono">{entry.direction === 'debit' ? formatMinor(entry.amount, entry.currency) : '—'}</td>
                <td className="num mono">{entry.direction === 'credit' ? formatMinor(entry.amount, entry.currency) : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="tool-card__actions">
        {decision === null ? (
          <>
            <button type="button" className="btn btn-primary" disabled={submitting} onClick={() => void decide('approved')}>
              Approve and post
            </button>
            <button type="button" className="btn btn-secondary" disabled={submitting} onClick={() => void decide('rejected')}>
              Reject
            </button>
            <span className="tool-card__help">Approving posts exactly these entries to the ledger, once.</span>
          </>
        ) : decision.posting_id ? (
          <span className="tool-card__posted">
            Posted · <Link to={`/ledger?posting=${decision.posting_id}`}>View in ledger →</Link>
          </span>
        ) : (
          <span className="tool-card__help">Rejected by {decision.decided_by}. Nothing was posted.</span>
        )}
        {error && (
          <span className="tool-card__error" role="alert">
            {error}
          </span>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Create `frontend/src/screens/Review.tsx`**

```tsx
import { useCallback, useEffect, useState } from 'react';
import {
  type ReviewDecision,
  type ReviewItemDto,
  type ToolInvocationDto,
  documentPageUrl,
  listReviews,
  listToolInvocations,
  submitReview,
} from '../api';
import { ApprovalCard } from '../components/ApprovalCard';
import { formatValue, parseCorrection, reviewReasons } from '../lib/review';
import './Review.css';

interface FieldReviewCardProps {
  item: ReviewItemDto;
  onDone: () => void;
}

function FieldReviewCard({ item, onDone }: FieldReviewCardProps) {
  const [correcting, setCorrecting] = useState(false);
  const [draft, setDraft] = useState(formatValue(item.value));
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = async (decision: ReviewDecision) => {
    const corrected = decision === 'corrected' ? parseCorrection(draft) : null;
    if (decision === 'corrected' && corrected === undefined) {
      setError('Enter the corrected value.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await submitReview({
        run_id: item.run_id,
        field_path: item.field_path,
        decision,
        corrected_value: corrected ?? null,
        reason: reason.trim() || null,
      });
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The decision was not recorded');
      setSubmitting(false);
    }
  };

  return (
    <article className="field-card">
      <div className="field-card__head">
        <span className="field-card__path mono">{item.field_path}</span>
        <span className="field-card__doc">
          {item.document_title} · v{item.version}
          {item.page !== null && ` · p.${item.page}`}
        </span>
        <a href={documentPageUrl(item.document_id, item.version, item.page)} target="_blank" rel="noreferrer">
          Open page →
        </a>
      </div>
      <dl className="field-card__facts">
        <dt>Extracted value</dt>
        <dd className="mono">{formatValue(item.value)}</dd>
        <dt>Quote</dt>
        <dd className="field-card__quote">“{item.quote}”</dd>
      </dl>
      <ul className="field-card__reasons">
        {reviewReasons(item).map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      {correcting && (
        <div className="field-card__correct">
          <label>
            Corrected value
            <input className="mono" value={draft} onChange={(event) => setDraft(event.target.value)} />
          </label>
          <label>
            Reason (optional)
            <input value={reason} onChange={(event) => setReason(event.target.value)} />
          </label>
        </div>
      )}
      <div className="field-card__actions">
        {correcting ? (
          <>
            <button type="button" className="btn btn-primary" disabled={submitting} onClick={() => void send('corrected')}>
              Save correction
            </button>
            <button type="button" className="btn btn-secondary" disabled={submitting} onClick={() => setCorrecting(false)}>
              Cancel
            </button>
          </>
        ) : (
          <>
            <button type="button" className="btn btn-primary" disabled={submitting} onClick={() => void send('confirmed')}>
              Confirm value
            </button>
            <button type="button" className="btn btn-secondary" disabled={submitting} onClick={() => setCorrecting(true)}>
              Correct
            </button>
            <button type="button" className="btn btn-secondary" disabled={submitting} onClick={() => void send('rejected')}>
              Reject
            </button>
          </>
        )}
        {error && (
          <span className="field-card__error" role="alert">
            {error}
          </span>
        )}
      </div>
    </article>
  );
}

export function Review() {
  const [items, setItems] = useState<ReviewItemDto[] | null>(null);
  const [approvals, setApprovals] = useState<ToolInvocationDto[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    Promise.all([listReviews(), listToolInvocations({ pending: true })])
      .then(([reviewItems, pending]) => {
        setItems(reviewItems);
        setApprovals(pending);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="review">
      <div className="review__topbar">
        <span>Review</span>
      </div>
      <div className="review__body">
        <h1 className="review__title">Review</h1>
        <p className="review__subtitle">
          Decisions made here are recorded append-only with your name and the time. Nothing below reaches the assistant
          or the ledger until someone decides.
        </p>
        {error && (
          <p className="review__error" role="alert">
            {error}
          </p>
        )}

        <section className="review__section">
          <h2 className="review__section-title">Extracted fields to review ({items?.length ?? '…'})</h2>
          <p className="review__hint">
            The extractor held these back because it could not ground the quote, a validator failed, or the page was hard
            to read. The assistant does not use them until you confirm or correct them.
          </p>
          {items === null ? (
            <p className="review__empty">Loading…</p>
          ) : items.length === 0 ? (
            <p className="review__empty">No fields are waiting. Every extracted field is either accepted or decided.</p>
          ) : (
            <div className="review__list">
              {items.map((item) => (
                <FieldReviewCard key={`${item.run_id}:${item.field_path}`} item={item} onDone={load} />
              ))}
            </div>
          )}
        </section>

        <section className="review__section" id="approvals">
          <h2 className="review__section-title">Fee corrections to approve ({approvals?.length ?? '…'})</h2>
          <p className="review__hint">
            Proposed by the assistant when a contract's fee schedule and billing disagree. Approving posts exactly the
            entries shown.
          </p>
          {approvals === null ? (
            <p className="review__empty">Loading…</p>
          ) : approvals.length === 0 ? (
            <p className="review__empty">No corrections are waiting. Ask the assistant to compare a contract with billing.</p>
          ) : (
            <div className="review__list">
              {approvals.map((invocation) => (
                <ApprovalCard key={invocation.id} invocation={invocation} />
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
```

- [ ] **Step 7: Create `frontend/src/screens/Review.css`**

```css
.review {
  display: flex;
  flex-direction: column;
  flex: 1;
}

.review__topbar {
  padding: 12px var(--space-3);
  border-bottom: 1px solid var(--color-border);
  font-size: 13px;
  color: var(--color-text-secondary);
}

.review__body {
  padding: var(--space-3);
  max-width: 960px;
}

.review__title {
  font-size: 24px;
  font-weight: 600;
}

.review__subtitle,
.review__hint {
  color: var(--color-text-secondary);
  font-size: 14px;
  margin-top: 4px;
  max-width: 72ch;
}

.review__error,
.field-card__error {
  color: var(--color-error);
  font-size: 13px;
}

.review__section {
  margin-top: var(--space-5);
}

.review__section-title {
  font-size: 16px;
  font-weight: 600;
}

.review__list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

.review__empty {
  margin-top: var(--space-2);
  font-size: 14px;
  color: var(--color-text-secondary);
}

.field-card {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  padding: var(--space-2);
  background: var(--color-surface);
}

.field-card__head {
  display: flex;
  align-items: baseline;
  gap: 12px;
  flex-wrap: wrap;
  font-size: 13px;
}

.field-card__path {
  font-weight: 600;
  font-size: 14px;
}

.field-card__doc {
  color: var(--color-text-secondary);
  flex: 1;
}

.field-card__facts {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 6px var(--space-2);
  margin: 12px 0;
  font-size: 13px;
}

.field-card__facts dt {
  color: var(--color-text-secondary);
}

.field-card__facts dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.field-card__quote {
  font-style: italic;
}

.field-card__reasons {
  margin: 0 0 12px;
  padding-left: 18px;
  font-size: 12px;
  color: var(--color-warning);
}

.field-card__correct {
  display: grid;
  gap: var(--space-1);
  margin-bottom: 12px;
  font-size: 12px;
  color: var(--color-text-secondary);
}

.field-card__correct input {
  display: block;
  width: 100%;
  margin-top: 4px;
  padding: 8px 10px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  font-size: 13px;
  color: var(--color-text-primary);
}

.field-card__actions {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  flex-wrap: wrap;
}
```

(`--color-surface` is added in Task 10; until then add `--color-surface: #ffffff;` to `:root` in `frontend/src/index.css` in this task.)

- [ ] **Step 8: Wire the route and nav**

`frontend/src/App.tsx`: `import { Review } from './screens/Review';` and inside the `AppShell` route add `<Route path="/review" element={<Review />} />`.

`frontend/src/components/Sidebar.tsx`: import `CheckIcon` and make `NAV_ITEMS`:

```tsx
const NAV_ITEMS: NavItem[] = [
  { to: '/dashboard', label: 'Dashboard', icon: DashboardIcon },
  { to: '/review', label: 'Review', icon: CheckIcon },
  { to: '/chat', label: 'Chat', icon: ChatIcon },
  { to: '/documents', label: 'Documents', icon: DocumentsIcon },
  { to: '/ledger', label: 'Ledger', icon: LedgerIcon },
];
```

- [ ] **Step 9: Show proposed corrections in Chat**

In `frontend/src/screens/Chat.tsx`:
- change the React import to `import { useCallback, useEffect, useRef, useState } from 'react';`
- add `import { ApprovalCard } from '../components/ApprovalCard';` and add `type ToolInvocationDto, listToolInvocations` to the `../api` import;
- inside `Chat()` after the `indexedCount` state:

```tsx
  const [approvals, setApprovals] = useState<ToolInvocationDto[]>([]);

  const refreshApprovals = useCallback((session: string) => {
    listToolInvocations({ limit: 50 })
      .then((rows) => setApprovals(rows.filter((row) => row.session_id === session && row.approval_required)))
      .catch(() => setApprovals([]));
  }, []);
```

- in `ask`, extend the `finally` block to `inputRef.current?.focus(); refreshApprovals(sessionId);`
- in the "New session" button handler add `setApprovals([]);`
- inside `.chat__thread`, after the `turns.map(...)` block:

```tsx
          {approvals.length > 0 && (
            <div className="chat__approvals">
              <span className="chat__approvals-label">Correction proposed in this session</span>
              {approvals.map((invocation) => (
                <ApprovalCard key={invocation.id} invocation={invocation} />
              ))}
            </div>
          )}
```

Append to `frontend/src/screens/Chat.css`:

```css
.chat__approvals {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.chat__approvals-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-text-secondary);
}
```

- [ ] **Step 10: Verify**

Run: `cd frontend && npm test && npm run lint && npm run build` — all pass.
In the browser: `/review` lists `needs_review` fields (if the live DB has none, the empty state shows). "Confirm value" removes the card. In `/chat` ask a leakage question on a contract with a billing household ("Compare the Tremblay agreement with what we bill"); a card with the proposed entry appears under the thread; "Approve and post" shows "Posted · View in ledger →", which opens `/ledger` with that posting selected. The same pending correction also appears in `/review#approvals`.

- [ ] **Step 11: Commit**

```bash
graphify update .
git add frontend/src/lib/review.ts frontend/src/lib/review.test.ts frontend/src/components/ApprovalCard.tsx frontend/src/components/ApprovalCard.css frontend/src/screens/Review.tsx frontend/src/screens/Review.css frontend/src/screens/Chat.tsx frontend/src/screens/Chat.css frontend/src/App.tsx frontend/src/components/Sidebar.tsx frontend/src/index.css
git commit -m "feat(frontend): add the review screen and approve fee corrections from chat"
```

---

### Task 7: Documents screen fixes (F11–F16)

**Files:**
- Create: `frontend/src/lib/documents.ts`, `frontend/src/lib/documents.test.ts`
- Modify: `frontend/src/screens/Documents.tsx` (full replacement below)
- Modify: `frontend/src/screens/Documents.css`

**Interfaces:**
- Consumes: `listDocuments`, `getDocument`, `uploadDocument`, `listToolInvocations`, `DocumentSummary`, `DocumentDetail`, `DocumentEvent`, `DocumentStatus`, `ToolInvocationDto` (Task 4 / existing); `formatUtc`, `formatUtcFull`, `selectableRow` (Task 4).
- Produces: `pipelineSteps(events: DocumentEvent[], status: DocumentStatus): PipelineStep[]`, type `PipelineStep`.

- [ ] **Step 1: Write the failing pipeline tests**

`frontend/src/lib/documents.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import type { DocumentEvent } from '../api';
import { pipelineSteps } from './documents';

function event(stage: string, at: string): DocumentEvent {
  return { stage, at, detail: {} };
}

const STORED = event('stored', '2026-09-24T10:00:00Z');
const PARSED = event('parsed', '2026-09-24T10:00:12.5Z');
const INDEXED = event('indexed', '2026-09-24T10:00:15Z');
const EXTRACTED = event('extracted', '2026-09-24T10:00:30Z');

describe('pipelineSteps', () => {
  it('marks the next stage active while processing', () => {
    expect(pipelineSteps([STORED, PARSED], 'processing').map((s) => s.state)).toEqual(['done', 'done', 'active', 'waiting']);
  });

  it('marks the stage that did not complete as failed', () => {
    const steps = pipelineSteps([STORED, event('failed', '2026-09-24T10:00:05Z')], 'failed');
    expect(steps.map((s) => s.state)).toEqual(['done', 'failed', 'waiting', 'waiting']);
  });

  it('shows only completed stages with durations when ready', () => {
    const steps = pipelineSteps([STORED, PARSED, INDEXED, EXTRACTED], 'ready');
    expect(steps.map((s) => [s.stage, s.state, s.duration])).toEqual([
      ['stored', 'done', null],
      ['parsed', 'done', '12.5s'],
      ['indexed', 'done', '2.5s'],
      ['extracted', 'done', '15.0s'],
    ]);
  });

  it('labels stages in product language', () => {
    expect(pipelineSteps([STORED], 'processing')[1].label).toBe('Parsed + PII tokenised (Docling, Presidio)');
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/lib/documents.test.ts`
Expected: FAIL — cannot resolve `./documents`.

- [ ] **Step 3: Implement `frontend/src/lib/documents.ts`**

```ts
import type { DocumentEvent, DocumentStatus } from '../api';

const STAGES = ['stored', 'parsed', 'indexed', 'extracted'] as const;

const STAGE_LABELS: Record<(typeof STAGES)[number], string> = {
  stored: 'Stored (content-addressed)',
  parsed: 'Parsed + PII tokenised (Docling, Presidio)',
  indexed: 'Indexed (Postgres full-text + Pinecone)',
  extracted: 'Fee terms extracted',
};

export interface PipelineStep {
  stage: string;
  label: string;
  state: 'done' | 'active' | 'waiting' | 'failed';
  duration: string | null;
}

export function pipelineSteps(events: DocumentEvent[], status: DocumentStatus): PipelineStep[] {
  const reached = new Map<string, string | null>();
  events.forEach((e, i) => {
    if (!(STAGES as readonly string[]).includes(e.stage)) return;
    const seconds = i === 0 ? null : (Date.parse(e.at) - Date.parse(events[i - 1].at)) / 1000;
    reached.set(e.stage, seconds === null ? null : `${seconds.toFixed(1)}s`);
  });
  const failed = status === 'failed' || events.some((e) => e.stage === 'failed');
  let pendingMarked = false;
  const steps: PipelineStep[] = [];
  for (const stage of STAGES) {
    if (reached.has(stage)) {
      steps.push({ stage, label: STAGE_LABELS[stage], state: 'done', duration: reached.get(stage) ?? null });
    } else if (status !== 'ready') {
      const state = pendingMarked ? 'waiting' : failed ? 'failed' : 'active';
      pendingMarked = true;
      steps.push({ stage, label: STAGE_LABELS[stage], state, duration: null });
    }
  }
  return steps;
}
```

Run: `cd frontend && npx vitest run src/lib/documents.test.ts` — expected PASS.

- [ ] **Step 4: Replace `frontend/src/screens/Documents.tsx`**

```tsx
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import {
  type DocumentDetail,
  type DocumentStatus,
  type DocumentSummary,
  type ToolInvocationDto,
  getDocument,
  listDocuments,
  listToolInvocations,
  uploadDocument,
} from '../api';
import { CheckIcon, UploadIcon } from '../components/Icons';
import { CopyButton } from '../components/CopyButton';
import { StatusPill } from '../components/StatusPill';
import { type PipelineStep, pipelineSteps } from '../lib/documents';
import { selectableRow } from '../lib/rowSelect';
import { formatUtc, formatUtcFull } from '../lib/time';
import './Documents.css';

const POLL_MS = 3000;
const USED_BY_LIMIT = 5;

type Filter = 'all' | DocumentStatus;

const FILTERS: Array<{ id: Filter; label: string }> = [
  { id: 'all', label: 'All documents' },
  { id: 'ready', label: 'Indexed' },
  { id: 'processing', label: 'Processing' },
  { id: 'failed', label: 'Failed' },
];

function formatBytes(bytes: number): string {
  return bytes < 1024 * 1024 ? `${Math.round(bytes / 1024)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function shortSha(sha: string): string {
  return `${sha.slice(0, 6)}…${sha.slice(-4)}`;
}

interface StatusCellProps {
  doc: DocumentSummary;
}

function StatusCell({ doc }: StatusCellProps) {
  if (doc.status === 'ready') return <StatusPill variant="success">Indexed</StatusPill>;
  if (doc.status === 'processing') return <StatusPill variant="accent">Processing…</StatusPill>;
  return (
    <>
      <StatusPill variant="warning">Failed</StatusPill> <span className="mono documents__status-note">{doc.status_note}</span>
    </>
  );
}

interface PipelineProps {
  steps: PipelineStep[];
}

function Pipeline({ steps }: PipelineProps) {
  return (
    <ol className="documents__stepper">
      {steps.map((step) => (
        <li key={step.stage}>
          <span className={`documents__step-dot documents__step-dot--${step.state}`}>
            {step.state === 'done' && <CheckIcon size={10} />}
          </span>
          <span className="documents__step-label">{step.label}</span>
          <span className="mono documents__step-time">
            {step.state === 'active' ? 'running' : step.state === 'failed' ? 'failed' : step.duration ?? ''}
          </span>
        </li>
      ))}
    </ol>
  );
}

interface UsedByProps {
  invocations: ToolInvocationDto[];
}

function UsedBy({ invocations }: UsedByProps) {
  if (invocations.length === 0) return <p className="documents__empty">Not used by any tool invocation yet.</p>;
  return (
    <>
      {invocations.slice(0, USED_BY_LIMIT).map((invocation) => (
        <div key={invocation.id} className="documents__used-by">
          <div>
            <div className="mono documents__used-tool">{invocation.tool_name}</div>
            <div className="mono documents__id">{formatUtc(invocation.created_at)}</div>
          </div>
          {invocation.decision?.posting_id ? (
            <Link to={`/ledger?posting=${invocation.decision.posting_id}`}>View posting →</Link>
          ) : invocation.approval_required && invocation.decision === null ? (
            <Link to="/review#approvals">Awaiting approval →</Link>
          ) : (
            <span className="documents__empty">{invocation.decision ? 'Rejected' : 'Lookup'}</span>
          )}
        </div>
      ))}
    </>
  );
}

export function Documents() {
  const [filter, setFilter] = useState<Filter>('all');
  const [summaries, setSummaries] = useState<DocumentSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<DocumentDetail | undefined>();
  const [invocations, setInvocations] = useState<ToolInvocationDto[]>([]);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      listDocuments()
        .then((rows) => {
          if (cancelled) return;
          setSummaries(rows);
          setError(null);
        })
        .catch((e: Error) => !cancelled && setError(e.message));
    void load();
    const timer = window.setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    listToolInvocations({ limit: 200 })
      .then(setInvocations)
      .catch(() => setInvocations([]));
  }, []);

  const currentId = selectedId ?? summaries[0]?.id ?? null;
  const current = summaries.find((s) => s.id === currentId);
  // refetch the detail only when the selection or its ingestion progress changes, not on every poll
  const progressKey = current ? `${current.status}:${current.element_count}` : null;

  useEffect(() => {
    if (!currentId) return;
    getDocument(currentId)
      .then(setDetail)
      .catch((e: Error) => setError(e.message));
  }, [currentId, progressKey]);

  const rows = filter === 'all' ? summaries : summaries.filter((d) => d.status === filter);
  const count = (id: Filter) => (id === 'all' ? summaries.length : summaries.filter((d) => d.status === id).length);
  const indexedChunks = summaries.reduce((sum, d) => sum + (d.status === 'ready' ? d.element_count : 0), 0);
  const preview = detail && detail.id === currentId ? detail.preview : [];
  const usedBy = current ? invocations.filter((inv) => inv.input.document_id === current.id) : [];

  const onUpload = async (file: File | undefined) => {
    if (!file) return;
    setError(null);
    try {
      const { document_id } = await uploadDocument(file);
      setSelectedId(document_id);
      setSummaries(await listDocuments());
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed');
    }
  };

  return (
    <div className="documents">
      <div className="documents__topbar">
        <span className="documents__breadcrumb">
          <span>Documents</span>
        </span>
      </div>

      <div className="documents__body">
        <div className="documents__header">
          <div>
            <h1 className="documents__title">Documents</h1>
            <p className="documents__subtitle">
              Every uploaded contract and its ingestion pipeline — parse, tokenise, index, extract. Answers in Chat cite
              these chunks by page and section.
            </p>
            <p className="documents__stack mono">
              Parser: Docling (local) · PII: Presidio tokens · Search: Postgres full-text + Pinecone · Embeddings:
              text-embedding-3-small
            </p>
          </div>
          <div className="documents__upload">
            <input
              ref={fileInput}
              type="file"
              accept="application/pdf"
              hidden
              onChange={(e) => void onUpload(e.target.files?.[0])}
            />
            <button type="button" className="btn btn-primary" onClick={() => fileInput.current?.click()}>
              <UploadIcon size={14} /> Upload document
            </button>
            <span className="mono">PDF with a text layer · scanned files are rejected</span>
            {error && (
              <span className="mono documents__status-note--error" role="alert">
                {error}
              </span>
            )}
          </div>
        </div>

        <div className="documents__filters">
          {FILTERS.map((f) => (
            <button
              type="button"
              key={f.id}
              aria-pressed={filter === f.id}
              className={`documents__filter-chip${filter === f.id ? ' documents__filter-chip--active' : ''}`}
              onClick={() => setFilter(f.id)}
            >
              {f.label} <span className="mono documents__filter-count">{count(f.id)}</span>
            </button>
          ))}
        </div>

        <div className="documents__grid">
          <div className="panel documents__table-panel">
            <div className="scroll-x">
              <table className="data-table">
                <colgroup>
                  <col />
                  <col className="col-num" />
                  <col className="col-num" />
                  <col className="col-uploaded" />
                  <col className="col-status" />
                </colgroup>
                <thead>
                  <tr>
                    <th>Document</th>
                    <th style={{ textAlign: 'right' }}>Pages</th>
                    <th style={{ textAlign: 'right' }}>Chunks</th>
                    <th>Uploaded</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((doc) => (
                    <tr
                      key={doc.id}
                      className={doc.id === currentId ? 'documents__row--selected' : undefined}
                      {...selectableRow(doc.id === currentId, () => setSelectedId(doc.id))}
                    >
                      <td>
                        <div className="documents__name" title={doc.title}>
                          {doc.title}
                        </div>
                        <div className="documents__id mono">{doc.id}</div>
                      </td>
                      <td className="num">{doc.page_count}</td>
                      <td className="num">{doc.element_count || '—'}</td>
                      <td className="mono documents__uploaded">{formatUtc(doc.uploaded_at)}</td>
                      <td>
                        <StatusCell doc={doc} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="documents__table-foot mono">
              <span>
                {summaries.length} documents · {indexedChunks} chunks indexed
              </span>
              <span>All timestamps UTC</span>
            </div>
          </div>

          {current ? (
            <aside className="panel documents__detail">
              <div className="documents__detail-head">
                <span className="documents__label mono">Document</span>
                <StatusCell doc={current} />
              </div>
              <h2 className="documents__detail-name">{current.title}</h2>
              <div className="documents__detail-id mono">
                {current.id} <CopyButton value={current.id} />
              </div>

              <dl className="documents__meta">
                <dt>Pages</dt>
                <dd className="mono">{current.page_count}</dd>
                <dt>Chunks</dt>
                <dd className="mono">{current.element_count || '—'}</dd>
                <dt>Uploaded</dt>
                <dd className="mono">{formatUtcFull(current.uploaded_at)}</dd>
                <dt>Size</dt>
                <dd className="mono">{formatBytes(current.byte_size)}</dd>
                <dt>SHA-256</dt>
                <dd className="mono">
                  {shortSha(current.file_sha256)} <CopyButton value={current.file_sha256} />
                </dd>
              </dl>

              <section className="documents__section">
                <div className="documents__section-head">Pipeline</div>
                <Pipeline steps={pipelineSteps(current.events, current.status)} />
                {current.status === 'failed' && current.status_note && (
                  <p className="documents__empty">{current.status_note}</p>
                )}
              </section>

              <section className="documents__section">
                <div className="documents__section-head">
                  Chunks
                  <span className="mono documents__filter-count">{current.element_count}</span>
                </div>
                {preview.length === 0 ? (
                  <p className="documents__empty">No chunks indexed yet.</p>
                ) : (
                  <>
                    <ul className="documents__chunks">
                      {preview.map((c) => (
                        <li key={c.ordinal} className="documents__chunk">
                          <div className="mono documents__chunk-loc">
                            p.{c.page_start} · {c.section_path.join(' › ') || c.kind}
                          </div>
                          <div className="documents__chunk-text">{c.text}</div>
                        </li>
                      ))}
                    </ul>
                    <p className="documents__empty">
                      Showing the first {preview.length} of {current.element_count} chunks.
                    </p>
                  </>
                )}
              </section>

              <section className="documents__section">
                <div className="documents__section-head">Used by</div>
                <UsedBy invocations={usedBy} />
              </section>
            </aside>
          ) : (
            <aside className="panel documents__detail">
              <p className="documents__empty">Upload a contract to get started.</p>
            </aside>
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Update `frontend/src/screens/Documents.css`**

Replace the `.documents__step-dot--active` rule and add the other states (the base `.documents__step-dot` stays as the "done" look):

```css
.documents__step-dot--active {
  background: var(--color-accent-tint);
  border: 1.5px solid var(--color-accent);
}

.documents__step-dot--waiting {
  background: transparent;
  border: 1.5px solid var(--color-border);
}

.documents__step-dot--failed {
  background: var(--color-error);
}
```

Delete the now-unused `.documents__more` rule if present.

- [ ] **Step 6: Verify**

Run: `cd frontend && npm test && npm run lint && npm run build` — pass.
In the browser: the first row is highlighted on load; Tab + Enter selects rows; upload a PDF and watch the pipeline show a "running" step; stop the backend and confirm an error appears, start it again and confirm the error clears within 3 s; the network tab shows no `GET /documents/{id}` on every poll.

- [ ] **Step 7: Commit**

```bash
graphify update .
git add frontend/src/lib/documents.ts frontend/src/lib/documents.test.ts frontend/src/screens/Documents.tsx frontend/src/screens/Documents.css
git commit -m "fix(frontend): show live pipeline progress, real tool usage and keyboard selection on documents"
```

---

### Task 8: Dashboard on real data (F1, F19)

**Files:**
- Modify: `frontend/src/screens/Dashboard.tsx` (full replacement below)
- Modify: `frontend/src/screens/Dashboard.css` (full replacement below)
- Modify: `frontend/src/index.css` (move the shared `.panel*` rules here)

**Interfaces:**
- Consumes: `listDocuments`, `listReviews`, `listToolInvocations`, `listPostings`, `DocumentSummary`, `ReviewItemDto`, `ToolInvocationDto` (Task 4); `toPostingView`, `PostingView`, `formatUtc` (Task 4).

- [ ] **Step 1: Move the shared panel styles**

Cut the rules `.panel`, `.panel__head`, `.panel__title`, `.panel__hint`, `.panel__footer-link` from `frontend/src/screens/Dashboard.css` and paste them at the end of `frontend/src/index.css` (they are used by Documents and Ledger too).

- [ ] **Step 2: Replace `frontend/src/screens/Dashboard.tsx`**

```tsx
import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import {
  type DocumentSummary,
  type ReviewItemDto,
  type ToolInvocationDto,
  listDocuments,
  listPostings,
  listReviews,
  listToolInvocations,
} from '../api';
import { StatusPill } from '../components/StatusPill';
import { type PostingView, toPostingView } from '../lib/postings';
import { formatUtc } from '../lib/time';
import './Dashboard.css';

const RECENT_POSTINGS = 5;
const CONTRACTS_SHOWN = 6;

interface DashboardData {
  documents: DocumentSummary[];
  reviews: ReviewItemDto[];
  approvals: ToolInvocationDto[];
  postings: PostingView[];
}

interface QueueRowProps {
  count: number;
  label: string;
  detail: string;
  to: string;
  action: string;
}

function QueueRow({ count, label, detail, to, action }: QueueRowProps) {
  return (
    <li className="queue__row">
      <span className={`queue__count mono${count === 0 ? ' queue__count--zero' : ''}`}>{count}</span>
      <div className="queue__text">
        <span className="queue__label">{label}</span>
        <span className="queue__detail">{detail}</span>
      </div>
      <Link to={to} className="queue__action">
        {action} →
      </Link>
    </li>
  );
}

const DOC_STATUS: Record<DocumentSummary['status'], { variant: 'success' | 'accent' | 'warning'; label: string }> = {
  ready: { variant: 'success', label: 'Indexed' },
  processing: { variant: 'accent', label: 'Processing' },
  failed: { variant: 'warning', label: 'Failed' },
};

export function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([listDocuments(), listReviews(), listToolInvocations({ pending: true }), listPostings({ limit: RECENT_POSTINGS })])
      .then(([documents, reviews, approvals, page]) => {
        if (!cancelled) setData({ documents, reviews, approvals, postings: page.items.map(toPostingView) });
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const failed = data?.documents.filter((d) => d.status === 'failed').length ?? 0;
  const byStatus = (status: DocumentSummary['status']) => data?.documents.filter((d) => d.status === status).length ?? 0;

  return (
    <div className="dashboard">
      <div className="dashboard__topbar">
        <span className="dashboard__breadcrumb">Dashboard</span>
      </div>

      <div className="dashboard__body">
        <div className="dashboard__header">
          <div>
            <h1 className="dashboard__title">Dashboard</h1>
            <p className="dashboard__subtitle">What needs a person, and what the system did recently.</p>
          </div>
          <Link to="/chat" className="btn btn-primary">
            Ask the assistant
          </Link>
        </div>

        {error && (
          <div className="panel dashboard__error" role="alert">
            <strong>Couldn't reach the API.</strong> {error}. Start the backend with{' '}
            <code className="mono">uvicorn app.main:app</code> and reload.
          </div>
        )}

        {!error && data === null && <p className="dashboard__loading">Loading…</p>}

        {data && (
          <div className="dashboard__grid">
            <section className="panel">
              <div className="panel__head">
                <h2 className="panel__title">Needs a person</h2>
              </div>
              <ul className="queue">
                <QueueRow
                  count={data.reviews.length}
                  label="extracted fields to review"
                  detail="Held back because the quote couldn't be grounded, a validator failed, or the page was hard to read."
                  to="/review"
                  action="Review fields"
                />
                <QueueRow
                  count={data.approvals.length}
                  label="fee corrections to approve"
                  detail="Proposed by the assistant. Nothing posts to the ledger until someone approves it."
                  to="/review#approvals"
                  action="Review corrections"
                />
                <QueueRow
                  count={failed}
                  label="documents failed ingestion"
                  detail="Usually a scanned PDF without a text layer."
                  to="/documents"
                  action="Open documents"
                />
              </ul>
            </section>

            <section className="panel">
              <div className="panel__head">
                <h2 className="panel__title">Contracts</h2>
                <span className="panel__hint mono">
                  {byStatus('ready')} indexed · {byStatus('processing')} processing · {failed} failed
                </span>
              </div>
              {data.documents.length === 0 ? (
                <p className="dashboard__empty">
                  No contracts yet. <Link to="/documents">Upload one</Link> to start.
                </p>
              ) : (
                <ul className="contract-list">
                  {data.documents.slice(0, CONTRACTS_SHOWN).map((doc) => (
                    <li key={doc.id} className="contract-list__row">
                      <span className="contract-list__title" title={doc.title}>
                        {doc.title}
                      </span>
                      <StatusPill variant={DOC_STATUS[doc.status].variant}>{DOC_STATUS[doc.status].label}</StatusPill>
                    </li>
                  ))}
                </ul>
              )}
              <Link className="panel__footer-link" to="/documents">
                All documents →
              </Link>
            </section>

            <section className="panel dashboard__wide">
              <div className="panel__head">
                <h2 className="panel__title">Recent postings</h2>
              </div>
              {data.postings.length === 0 ? (
                <p className="dashboard__empty">No postings yet. Approved corrections and fee runs will appear here.</p>
              ) : (
                <div className="scroll-x">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Created</th>
                        <th>Description</th>
                        <th>Source</th>
                        <th style={{ textAlign: 'right' }}>Amount</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.postings.map((p) => (
                        <tr key={p.id}>
                          <td className="mono">{formatUtc(p.createdAt)}</td>
                          <td>
                            <Link to={`/ledger?posting=${p.id}`}>{p.description}</Link>
                          </td>
                          <td className="mono">{p.source}</td>
                          <td className="num">{p.amount}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <Link className="panel__footer-link" to="/ledger">
                Open the ledger →
              </Link>
            </section>
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Replace `frontend/src/screens/Dashboard.css`**

```css
.dashboard {
  display: flex;
  flex-direction: column;
  flex: 1;
}

.dashboard__topbar {
  padding: 12px var(--space-3);
  border-bottom: 1px solid var(--color-border);
  font-size: 13px;
  color: var(--color-text-secondary);
}

.dashboard__body {
  padding: var(--space-3);
  flex: 1;
}

.dashboard__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
  flex-wrap: wrap;
}

.dashboard__title {
  font-size: 24px;
  font-weight: 600;
}

.dashboard__subtitle {
  color: var(--color-text-secondary);
  font-size: 14px;
  margin-top: 4px;
}

.dashboard__grid {
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
  gap: var(--space-3);
}

.dashboard__wide {
  grid-column: 1 / -1;
}

.dashboard__error {
  color: var(--color-text-primary);
  background: var(--color-error-tint);
  border-color: var(--color-error);
  font-size: 14px;
}

.dashboard__loading,
.dashboard__empty {
  font-size: 14px;
  color: var(--color-text-secondary);
}

.queue {
  list-style: none;
  margin: 0;
  padding: 0;
}

.queue__row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 12px 0;
  border-top: 1px solid var(--color-border);
}

.queue__row:first-child {
  border-top: none;
  padding-top: 0;
}

.queue__count {
  font-size: 22px;
  font-weight: 600;
  min-width: 2ch;
  text-align: right;
  color: var(--color-warning);
}

.queue__count--zero {
  color: var(--color-text-secondary);
}

.queue__text {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
}

.queue__label {
  font-weight: 500;
}

.queue__detail {
  font-size: 13px;
  color: var(--color-text-secondary);
}

.queue__action {
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
}

.contract-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.contract-list__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  font-size: 14px;
}

.contract-list__title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 1080px) {
  .dashboard__grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .queue__row {
    flex-wrap: wrap;
  }
}
```

- [ ] **Step 4: Verify**

Run: `cd frontend && npm test && npm run lint && npm run build` — pass.
In the browser: every number on `/dashboard` matches `/review`, `/documents` and `/ledger`; "Review fields" lands on `/review`; with the backend stopped, the red error panel appears instead of blank tiles. `grep -rn "Form\|K-1\|Merkle\|pgvector\|1,428" frontend/src/screens/Dashboard.tsx` returns nothing.

- [ ] **Step 5: Commit**

```bash
graphify update .
git add frontend/src/screens/Dashboard.tsx frontend/src/screens/Dashboard.css frontend/src/index.css
git commit -m "feat(frontend): rebuild the dashboard as a work queue on real data"
```

---

### Task 9: Landing page describes the fee-contract product (F4, F19)

**Files:**
- Modify: `frontend/src/screens/Landing.tsx` (full replacement below)
- Modify: `frontend/src/screens/Landing.css` (full replacement below)
- Modify: `frontend/index.html` (description meta tags)

**Interfaces:** none (leaf page). Keeps the existing token palette: dark hero `--color-bg-dark`, single blue accent.

- [ ] **Step 1: Replace `frontend/src/screens/Landing.tsx`**

```tsx
import { Link } from 'react-router';
import { CheckIcon, LockIcon, SparkleIcon } from '../components/Icons';
import './Landing.css';

const STEPS = [
  {
    title: 'Read the agreement',
    body: 'Upload an investment advisory agreement as a PDF. It is parsed on your machine, names, emails, phone and account numbers are replaced with tokens, and the fee schedule is extracted together with the clause it came from.',
  },
  {
    title: 'Compare it with billing',
    body: 'Ask about any contract in plain language. Answers cite the clause and page, and the fee comparison is computed in code from your billing schedule — the model never does the arithmetic.',
  },
  {
    title: 'Approve the correction',
    body: 'When the contract and billing disagree, the assistant proposes a balanced journal entry. It reaches the ledger only after a person approves it, and it posts exactly once.',
  },
];

const GUARANTEES = [
  'Tools take document IDs, and code computes every fee. The model never supplies an amount.',
  'Every number in an answer is checked against the passage it cites.',
  'Fields the extractor could not ground wait for a person before the assistant can use them.',
  'The ledger is append-only. A mistake is undone with a reversal, never an edit.',
];

export function Landing() {
  return (
    <div className="landing">
      <header className="landing__nav">
        <div className="landing__brand">
          <span className="landing__brand-mark" aria-hidden="true" />
          Ledger Assistant
        </div>
        <nav className="landing__nav-links" aria-label="Page sections">
          <a href="#how-it-works">How it works</a>
          <a href="#guarantees">Guarantees</a>
        </nav>
        <Link to="/dashboard" className="btn btn-primary">
          Open the demo
        </Link>
      </header>

      <section className="landing__hero">
        <h1 className="landing__headline">Bill what the contract says.</h1>
        <p className="landing__subhead">
          Ledger Assistant reads your investment advisory agreements, answers questions with the clause cited, and checks
          each fee schedule against what billing actually charges. When they differ, it proposes the correction — and a
          person approves it before anything posts.
        </p>
        <div className="landing__hero-actions">
          <Link to="/dashboard" className="btn btn-primary">
            Open the demo
          </Link>
          <Link to="/chat" className="btn landing__btn-ghost">
            Ask a contract
          </Link>
        </div>

        <figure className="landing__compare" aria-label="Example: a contract compared with billing">
          <figcaption className="landing__compare-caption mono">Example comparison</figcaption>
          <div className="landing__compare-grid">
            <div className="landing__compare-col">
              <span className="landing__compare-source mono">Agreement · §3 Fees · p.2</span>
              <p className="landing__compare-quote">
                “1.00% per annum on the first $1,000,000 of assets under management”
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

      <section className="landing__stack">
        <p className="mono">
          <SparkleIcon size={12} /> Docling and Presidio run locally · Postgres full-text + Pinecone retrieval · OpenAI via
          LangGraph · double-entry ledger on PostgreSQL
        </p>
      </section>

      <footer className="landing__footer">
        <div className="landing__brand landing__brand--dark">
          <span className="landing__brand-mark" aria-hidden="true" />
          Ledger Assistant
        </div>
        <span className="landing__footer-copy">A working demo: fee-contract review on a double-entry ledger.</span>
        <Link to="/dashboard">Open the demo →</Link>
      </footer>
    </div>
  );
}
```

- [ ] **Step 2: Replace `frontend/src/screens/Landing.css`**

```css
.landing {
  background: var(--color-bg);
  color: var(--color-text-primary);
}

.landing__brand {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 600;
  font-size: 15px;
  color: var(--color-text-primary-dark);
}

.landing__brand--dark {
  color: var(--color-text-primary);
}

.landing__brand-mark {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--color-accent);
  flex-shrink: 0;
}

.landing__nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-4);
  background: var(--color-bg-dark);
}

.landing__nav-links {
  display: flex;
  gap: var(--space-3);
}

.landing__nav-links a {
  color: var(--color-text-secondary-dark);
  font-size: 14px;
  font-weight: 500;
}

.landing__nav-links a:hover {
  color: var(--color-text-primary-dark);
}

.landing__hero {
  background: var(--color-bg-dark);
  color: var(--color-text-primary-dark);
  padding: var(--space-6) var(--space-4) var(--space-section);
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}

.landing__headline {
  font-size: clamp(2.5rem, 6vw, 4rem);
  font-weight: 500;
  line-height: 1.08;
  letter-spacing: -0.02em;
  max-width: 16ch;
  text-wrap: balance;
  margin-bottom: var(--space-3);
}

.landing__subhead {
  font-size: 17px;
  line-height: 1.6;
  color: var(--color-text-secondary-dark);
  max-width: 60ch;
  text-wrap: pretty;
  margin-bottom: var(--space-4);
}

.landing__hero-actions {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
  justify-content: center;
  margin-bottom: var(--space-6);
}

.landing__btn-ghost {
  color: var(--color-text-primary-dark);
  border-color: var(--color-border-dark);
}

.landing__btn-ghost:hover {
  color: var(--color-text-primary-dark);
  border-color: var(--color-text-secondary-dark);
}

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

.landing__section {
  max-width: 1080px;
  margin: 0 auto;
  padding: var(--space-section) var(--space-4) 0;
}

.landing__section-title {
  font-size: 32px;
  font-weight: 500;
  letter-spacing: -0.01em;
  text-wrap: balance;
  margin-bottom: var(--space-3);
}

.landing__steps {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: var(--space-4);
}

.landing__step h3 {
  font-size: 18px;
  font-weight: 600;
  margin: 12px 0 8px;
}

.landing__step p {
  color: var(--color-text-secondary);
  line-height: 1.6;
}

.landing__step-number {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: 1px solid var(--color-accent);
  color: var(--color-accent);
  font-size: 13px;
  font-weight: 600;
}

.landing__section--split {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(0, 3fr);
  gap: var(--space-5);
  align-items: start;
}

.landing__section-lede {
  color: var(--color-text-secondary);
  line-height: 1.6;
  max-width: 45ch;
}

.landing__guarantees {
  list-style: none;
  margin: 0;
  padding: 0;
}

.landing__guarantees li {
  display: flex;
  gap: 12px;
  align-items: baseline;
  padding: var(--space-2) 0;
  border-top: 1px solid var(--color-border);
  line-height: 1.55;
}

.landing__guarantees li:first-child {
  border-top: none;
  padding-top: 0;
}

.landing__check {
  color: var(--color-success);
  flex-shrink: 0;
}

.landing__stack {
  max-width: 1080px;
  margin: var(--space-section) auto 0;
  padding: var(--space-3) var(--space-4);
  border-top: 1px solid var(--color-border);
  border-bottom: 1px solid var(--color-border);
  font-size: 12px;
  color: var(--color-text-secondary);
}

.landing__stack p {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.landing__footer {
  max-width: 1080px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  flex-wrap: wrap;
  padding: var(--space-4);
  font-size: 13px;
}

.landing__footer-copy {
  color: var(--color-text-secondary);
}

@media (max-width: 860px) {
  .landing__nav {
    padding: var(--space-2);
  }

  .landing__nav-links {
    display: none;
  }

  .landing__hero {
    padding: var(--space-5) var(--space-2) var(--space-6);
  }

  .landing__compare-grid,
  .landing__section--split {
    grid-template-columns: 1fr;
  }

  .landing__compare-col + .landing__compare-col {
    border-left: none;
    border-top: 1px solid var(--color-border-dark);
  }

  .landing__section {
    padding: var(--space-6) var(--space-2) 0;
  }
}

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

(`--color-surface` must exist in `index.css` — added in Task 6.)

- [ ] **Step 3: Update `frontend/index.html`**

Replace the three description `content` values (`description`, `og:description`, `twitter:description`) with:

```
Checks investment advisory agreements against billing, cites the clause, and proposes a correction a person approves before it posts.
```

- [ ] **Step 4: Verify**

Run: `cd frontend && npm run lint && npm run build` — pass.
Run: `grep -rniE "tax|T4|W-2|1099|941|textract|pgvector|litellm|coordinate|confidence" frontend/src/screens/Landing.tsx frontend/index.html` — expected: no output.
In the browser at 1440px and 390px wide: no horizontal scroll, the headline wraps cleanly, the comparison stacks on mobile, nav links hide on mobile, both CTAs work.

- [ ] **Step 5: Commit**

```bash
graphify update .
git add frontend/src/screens/Landing.tsx frontend/src/screens/Landing.css frontend/index.html
git commit -m "feat(frontend): rewrite the landing page around fee-contract review"
```

---

### Task 10: Accessibility, API status and design tokens sweep (F17, F18, F19)

**Files:**
- Create: `frontend/src/lib/useApiHealth.ts`
- Modify: `frontend/src/components/Sidebar.tsx`, `frontend/src/components/Sidebar.css`
- Modify: `frontend/src/index.css`
- Modify: any `frontend/src/**/*.css` still holding raw hex colours

**Interfaces:**
- Consumes: `checkHealth` (Task 4).
- Produces: `useApiHealth(intervalMs?: number): ApiHealth`, type `ApiHealth = 'checking' | 'connected' | 'unreachable'`.

- [ ] **Step 1: Add the health hook**

`frontend/src/lib/useApiHealth.ts`:

```ts
import { useEffect, useState } from 'react';
import { checkHealth } from '../api';

export type ApiHealth = 'checking' | 'connected' | 'unreachable';

const HEALTH_POLL_MS = 15000;

export function useApiHealth(intervalMs: number = HEALTH_POLL_MS): ApiHealth {
  const [health, setHealth] = useState<ApiHealth>('checking');

  useEffect(() => {
    let cancelled = false;
    const check = () =>
      checkHealth().then((ok) => {
        if (!cancelled) setHealth(ok ? 'connected' : 'unreachable');
      });
    void check();
    const timer = window.setInterval(check, intervalMs);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [intervalMs]);

  return health;
}
```

(`checkHealth` itself is covered by the Task 4 tests; this hook is a thin timer around it.)

- [ ] **Step 2: Show the real status in the sidebar**

In `frontend/src/components/Sidebar.tsx` import `{ type ApiHealth, useApiHealth } from '../lib/useApiHealth'`, add above the component:

```tsx
const HEALTH_LABEL: Record<ApiHealth, string> = {
  checking: 'Checking API…',
  connected: 'API connected',
  unreachable: 'API unreachable',
};
```

Call `const health = useApiHealth();` at the top of `Sidebar()`, and replace the footer role line with:

```tsx
        <div className="sidebar__footer-role mono" role="status">
          <span className={`sidebar__status-dot sidebar__status-dot--${health}`} aria-hidden="true" /> {HEALTH_LABEL[health]}
        </div>
```

Append to `frontend/src/components/Sidebar.css`:

```css
.sidebar__status-dot--checking {
  background: var(--color-text-secondary-dark);
}

.sidebar__status-dot--unreachable {
  background: var(--color-error);
}
```

- [ ] **Step 3: Tokens and focus styles in `frontend/src/index.css`**

Add to `:root` (keep `--color-surface` if Task 6 added it):

```css
  --color-surface: #ffffff;
  --color-on-accent: #ffffff;
  --color-bg-hover: #fafafa;
  --color-bg-muted: #f4f4f5;
```

Append:

```css
:focus-visible {
  outline: 2px solid var(--color-accent);
  outline-offset: 2px;
}

tr[tabindex]:focus-visible {
  outline-offset: -2px;
}
```

Delete the unused `.data-table .flagged` and `.data-table .flagged td:first-child` rules (side-stripe border; nothing renders `.flagged` any more — confirm with `grep -rn "flagged" frontend/src` first). In the same file replace `background: #ffffff;` in `.btn-secondary` with `var(--color-surface)`, `color: #ffffff;` in `.btn-primary` with `var(--color-on-accent)`, and `#fafafa` in `.data-table tbody tr:hover` with `var(--color-bg-hover)`.

- [ ] **Step 4: Replace raw hex colours in component and screen CSS**

```bash
cd frontend/src
sed -i -E 's/background: #ffffff;/background: var(--color-surface);/; s/color: #ffffff;/color: var(--color-on-accent);/; s/#fafafa/var(--color-bg-hover)/; s/#f4f4f5/var(--color-bg-muted)/' screens/*.css components/*.css
grep -nE "#[0-9a-fA-F]{3,6}\b" screens/*.css components/*.css
```

For every remaining hit, replace it with the closest existing token (`--color-border`, `--color-text-secondary`, `--color-accent`, …). If no token fits, add a named token to `:root` in `index.css` and use it. The final `grep` must print nothing.

- [ ] **Step 5: Verify**

Run: `cd frontend && npm test && npm run lint && npm run build` — pass.
In the browser: Tab through every screen — each focused control shows a blue outline; stop the backend and within 15 s the sidebar reads "API unreachable" with a red dot; start it and it returns to "API connected". Screens look unchanged apart from focus rings.

- [ ] **Step 6: Commit**

```bash
graphify update .
git add frontend/src/lib/useApiHealth.ts frontend/src/components/Sidebar.tsx frontend/src/components/Sidebar.css frontend/src/index.css frontend/src/screens/*.css frontend/src/components/*.css
git commit -m "fix(frontend): report real API status, add focus styles and move colours onto tokens"
```

---

### Task 11: End-to-end verification and sprint records

**Files:**
- Modify: `CHANGELOG.md` (tick the sprint's UI scope lines)
- Modify: `artifacts/product-backlog.md` (tick the fixed "Found in the 2026-09-24 live run" items)

- [ ] **Step 1: Run every automated check**

```bash
cd backend && $PYDEV/bin/pytest
cd ../frontend && npm test && npm run lint && npm run build
```

Expected: all green. Record the backend test count.

- [ ] **Step 2: Manual walk-through with the backend running**

Tick each or report it failing:
- [ ] `/` — fee-contract copy only; both CTAs work; no horizontal scroll at 390px.
- [ ] `/dashboard` — counts match `/review`, `/documents`, `/ledger`; each queue link lands on the right screen.
- [ ] `/review` — confirm, correct (with a JSON value and a plain value) and reject a field; each card leaves the queue; approve one pending correction.
- [ ] `/chat` — spacing between turns, rendered lists, auto-scroll, typing while streaming, proposed-correction card with a working "View in ledger →".
- [ ] `/documents` — first row highlighted, keyboard selection, live pipeline states, "Used by" shows the compare tool for a compared contract.
- [ ] `/ledger` — real postings, provenance for the AI posting, reversal via confirm step, `?posting=` preselects.
- [ ] Backend stopped — every screen shows an error, the sidebar reads "API unreachable".

- [ ] **Step 3: Update the records**

In `CHANGELOG.md` under `## [Sprint — feat/demo-ready]`, tick `- [x]` the `frontend` UI-fixes, human-review-loop and landing-copy scope lines, and add under them:

```markdown
- `frontend` — ledger and dashboard read real data; approvals from chat and the review screen; keyboard selection, focus styles, live API status → **Not epic-tracked** (UI audit 2026-09-26)
- `api` — `/reviews` queue and decisions over `field_reviews`; account names on posting and proposed entries → **Not epic-tracked** (UI audit 2026-09-26)
```

In `artifacts/product-backlog.md`, tick `- [x]` "Chat: messages have no vertical spacing", "Review path broken", "Markdown shows as raw text", "Landing page copy" (both occurrences), and the "Human review loop is broken" and "UI issues" lines in the "Next sprint" list.

- [ ] **Step 4: Commit**

```bash
graphify update .
git add CHANGELOG.md artifacts/product-backlog.md
git commit -m "docs: record the demo-ready UI work in the changelog and backlog"
```

- [ ] **Step 5: Report**

Report: each task's commit hash, the backend test count and frontend test count, the manual checklist with any failures, and any deviation from this plan (with the reason). Do not push or open a PR — the owner runs `/end-sprint`.
