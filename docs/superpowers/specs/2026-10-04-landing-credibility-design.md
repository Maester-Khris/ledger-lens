# Landing page credibility pass - design

Date: 2026-10-04. Source: `artifacts/2026-10-04-hiring-panel-review.md` and
`artifacts/2026-10-04-review-first-reactions.md` (both local, gitignored).

## Goal
Make the landing page credible to a product visitor and to a technical reviewer, today, using only what already
exists. It stays a product page.

## Constraints
- No backend change, no new feature, no new dependency, no data wiring. Content is static.
- Nothing invented. Every number on the page comes from a file in the repository and names that file.
- No claim of regulatory compliance.
- Files touched: `frontend/src/screens/Landing.tsx`, `frontend/src/screens/Landing.css`,
  `frontend/src/components/HeroFlow.tsx`, plus one new pure function and its test in `frontend/src/lib/`.

## Success criteria
1. The hero never displays "0.00%" or "$0.00".
2. The four claims the reviewers caught are reworded (section "Copy corrections").
3. A proof section shows measured results, each with its source file and date.
4. The page states how data is handled and what the demo does not do.
5. The repository is one click away from the footer.

## Page order
1. Nav (adds a "Proof" anchor)
2. Hero
3. Three pillars (unchanged position)
4. What it will not do (moved up from the bottom)
5. Proof (new)
6. How it works
7. Data handling and limits (new)
8. Stack line
9. Footer

## Hero
- New line above the headline: "For billing operations and compliance teams at Canadian portfolio managers".
- Headline unchanged: "Bill what the contract says."
- Subhead, two sentences: "Ledger Assistant reads your investment advisory agreements, answers questions with the
  clause cited, and checks each fee schedule against what your billing schedule would charge. When they disagree, it
  proposes a correcting entry that posts only after a person approves it."
- The diagram plays once, about twice as fast as today, then holds on its final state (0.85%, 0.80%, $400.00). It
  never loops back. Before a value starts counting, its slot shows "· · ·".
- With `prefers-reduced-motion`, the final state shows immediately (already the case).
- Agreement card: "§3 Fees · p.2" becomes "§3 Fees · p.1" (the Fees clause is on page 1).
- Chip: "Contract ↔ billing, always compared" becomes "Contract ↔ billing, compared on request".

## Copy corrections
| Where | Today | Becomes | Why |
|---|---|---|---|
| Hero subhead | "against what billing actually charges" | "against what your billing schedule would charge" | The comparison reads the billing schedule, not invoices or fee runs |
| Hero chip | "always compared" | "compared on request" | Comparison runs only from a chat question |
| Pillar label | "Chain of custody" | "Decision log" | Plainer, and accurate |
| Pillar label | "Cryptographic audit" | "Reproducible export" | A SHA-256 of an export is not a cryptographic audit |
| How it works, step 1 | "It is parsed on your machine" | "It is parsed and tokenized before anything reaches a model" | The hosted demo does not parse on the visitor's machine |

## Proof section
A ledger-style table, not stat tiles: claim, measured result, source, date. This suits the product and makes each
number checkable.

| Claim | Measured | Source | Date |
|---|---|---|---|
| No duplicate postings under load | 0 of 500 concurrent requests | `reports/concurrency.json` | 2026-09-23 |
| Answerable questions answered with the right numbers and a citation | 27 to 28 of 28, across three runs | `reports/eval-5bfdd62942f4*.json` | 2026-10-02 |
| Unanswerable questions refused or sent back for clarification | 21 of 21, across three runs | `reports/eval-5bfdd62942f4*.json` | 2026-10-02 |

The eval figure is stated as a range on purpose: one of the three runs scored 28 of 28 and two scored 27 of 28.

The source column shows paths without the `backend/` prefix, at the owner's request. The backend test count is
not shown: a test suite is expected, so the row added nothing.

Not included: answer latency. The only figure available (3.3 s median) comes from a local database. Measure it on
the deployed demo and add it later.

## Data handling and limits section
Two columns and one note.

**How your data is handled**
- Names, emails, phone and account numbers are tokenized before any text reaches a model.
- Parsing and tokenization run locally, with Docling and Presidio.
- Search vectors are stored in Pinecone (AWS us-east-1).
- Answers and extraction use OpenAI GPT-4.1, pinned to a dated snapshot.
- Search embeddings use OpenAI text-embedding-3-small.

**Limits of this demo**
- Agreements are synthetic or public EDGAR filings. There is no client data.
- Guests are identified for attribution, not authenticated.
- In the public demo, approvals are checked by the ledger but not recorded.
- One tenant.
- A comparison runs when you ask for it, against the billing schedule in effect, not against invoices.

**Note on regulation**
"The decision log records the tool, model, prompt version, inputs and approver for every AI action, in line with
the transparency and accountability themes of CSA Staff Notice 11-348 on AI in capital markets. This demo has not
been assessed for compliance with any regulation."

NI 31-103 is deliberately not mentioned. The reports that would map to it are not built, and three of the four
agreements in the corpus are US fund filings.

## Footer
Adds two external links, opening in a new tab:
- "Source on GitHub": `https://github.com/Maester-Khris/ledger-lens` (public).
- "Evaluation reports": `https://github.com/Maester-Khris/ledger-lens/tree/preview/backend/reports`. The reports
  exist on `preview` and not yet on `main`; switch the link to `main` after the next release.

## Deferred
- A "See it work" screenshot section. Both candidate screenshots show known defects (a citation rendered as a raw
  pipe table, and the wrong tier wording in the reconciliation answer). Add it after those are fixed.
- Architecture diagram and engineer pages.
- GL export screenshot (the feature has no screen yet).
- Answer latency measured on the deployed demo.

## Testing
- Unit test for the play-once phase function.
- `npm run build`, `npm run lint`, `npm run test` in `frontend/`.
- Manual check by the reviewer: hero end state, reduced motion, 360px and 1440px widths, external links.

## Skills that informed this design
- frontend-design: the proof section is a table that encodes real structure (claim, result, source) and the hero
  motion is one orchestrated play, then still.
- copywriting: specific over vague, honest over sensational, customer language in the audience line.
