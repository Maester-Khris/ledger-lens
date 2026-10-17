# X1: extraction quality verification — design

Date: 2026-10-17 · Sprint `feat/measured-evidence`, item X1 (CHANGELOG) · Status: approved in brainstorming,
awaiting plan.

Inputs (local, untracked): `artifacts/2026-10-15-ingestion-quality-verification-decisions.md` (section 9 is the
owner's decisions), `artifacts/research/2026-10-15-ingestion-quality-verification.md`,
`artifacts/research/2026-10-17-extraction-error-rate-targets.md`.

## 1. Intent

Today a contract field is `accepted` or `needs_review` on schema validity, grounding of its quote in the parsed
text, and page grade. Nothing checks that a grounded value is **correct**. A parser misread or a wrong band's rate
passes as "accepted" and can reach the fee comparison and the ledger proposal.

X1 adds an independent second reading of each important field, sends any disagreement to a person as a field-level
diff (not a whole document to reread), and **measures** the error rate of what is auto-accepted against a target per
field class. It also produces cost, time and confidence numbers per pipeline stage, so the system's cost and
reliability can be stated with method and sample.

## 2. Goals, non-goals, anti-goals

**Goals**
1. Every class A field is checked before it is served: by two independent readings where the value is written in
   the text, by the vision verifier alone where it is inferred (section 6, owner decision); class B by one local
   reading.
2. A disagreement reaches the reviewer as a diff card: both values, the cropped evidence, three actions.
3. The auto-accepted error rate per class is measured on a labelled random sample and passes or fails against its
   target with a stated confidence.
4. Per stage: cost per document, time (median/p95), and confidence, plus a projection to 100k documents and 100k
   daily active users.
5. The cheapest extraction model that matches gpt-4.1 on class A accuracy is identified on the same labels.

**Non-goals**
- Auto-accepting fields because verification agreed (selective prediction needs calibration first).
- Batch API lane (deferred; see section 12).
- Calibrated confidence scores, threshold tuning beyond the agree rules.
- Bounding-box highlight inside the PDF viewer (boxes are stored; the viewer change is later).
- Changing the chat model.

**Anti-goals (a failure even if it works)**
- A verifier result ever **overwrites** an extracted value. It only routes to review.
- Raw personal data leaves the machine in an image.
- A class A **extracted value** is served to chat or the comparison tool before it is verified or reviewed. (Raw
  contract text in search results is the source document itself, not an extracted value, and stays searchable once
  indexed; chat answers are already held to cited numbers.)
- An accuracy claim tighter than the labelled sample can support.
- A failed or timed-out check silently counts as "agree".

## 3. Constraints

- Append-only data: `extracted_fields`, `field_reviews`, `document_elements`, `extraction_runs` have
  append-only triggers and `ledger_app` holds INSERT/SELECT only. New tables follow the same rule. Migrations run
  as `ledger_owner`.
- Layering (CLAUDE.md): routes thin, DB access only in each package's `dao.py`, pure logic in framework-free files,
  dependencies point toward `ledger`; `app/ingestion_pipeline.py` is the only module that knows stage order.
- PII boundary (owner decision 3): personal data is removed from text **and images** before anything leaves the
  machine.
- No new dependency without listing it in `requirements-worker.txt` (Pillow, rapidocr, pypdfium2 are installed but
  must be listed explicitly; no `presidio-image-redactor`).
- The verifier model differs from the extractor; judges differ from the verifier.

## 4. Field classes and targets (owner decisions)

| Class | Fields (`extracted_fields.field_path`) | Checks | Target on auto-accepted fields | Labels |
|---|---|---|---|---|
| A, money-moving | `fee_tiers[*]`, `fee_method`, `fee_basis`, `currency`, `billing_frequency`, `payment_timing` | layer 1 + layer 2 | **≤ 5%**, tighten to **≤ 1%** at ~300 labels | 60 → ~300 |
| B, identity | `fund_or_account`, `adviser`, `client`, `effective_date` | layer 1; layer 2 for `adviser`, `fund_or_account`, `effective_date` only on failures + sample | **≤ 5%** | 60 |
| C, informational | `agreement_date`, `termination_notice_days`, `governing_law`, `signatories[*]` | none live; audit sample | **≤ 10%** | 30 |

Errors reaching billing: **0** — every posting is approved by a person (existing approval card, now showing the
cited clauses). A class **passes** when the 95% upper bound of its error rate (Clopper-Pearson; ≈ 3/n with 0
errors) is at or below its target. If a class fails: that class routes to review and the cause (prompt, parser,
rule) is fixed, not just the sampled items.

## 5. Agree rules (pure logic, `app/contracts/agree.py`)

Values are normalised, then compared. The parsers are the ones billing already uses (`contracts/fee_text.py`).

| Type | Fields | Agree when |
|---|---|---|
| Enum | fee method, currency, billing frequency, payment timing | same enum value (the verifier answers in the same enum) |
| Fee table | `fee_tiers[*]` | same band count; per band in order, `parse_rate_bps` equal **exactly** and `parse_amount_minor` of the upper bound equal **exactly**; wording ignored. A field result names the first differing band |
| Date | agreement date, effective date | same calendar date after parsing |
| Integer | notice days | equal |
| Short text | fee basis, fund or account, adviser, client, governing law | equal after normalising (case, punctuation, whitespace, legal suffixes Inc./LLC/Ltd./L.P., leading "The"), else normalised Levenshtein similarity ≥ 0.9 (threshold is a builder call, tuned on labels) |
| Name list | `signatories[*]` | same set after the same normalising |
| Null | any | both "not stated" → agree; exactly one → **disagree** |

**Fee table unit (my call).** `fee_tiers` is verified, reviewed and labelled as **one table**: the verification row
uses `field_path = 'fee_tiers'` and every `fee_tiers[i]` band follows that table outcome. A disagreement puts all bands
of the run into review as one diff card showing both tables. A band-count mismatch cannot be corrected through field
reviews (the missing band has no row): the reviewer rejects the table, which leaves the contract non-comparable until
a re-extraction creates a new run. For the label count, one fee table is one class A unit.

No numeric tolerance on money fields. Outcomes: `agree`, `disagree`, `unreadable` (the reading found nothing),
`error` (the check failed). `unreadable` and `error` route to review like `disagree`.

## 6. Verification layers and the privacy boundary

**Crops.** Cited pages are rendered locally once per document (pypdfium2); a field's crop is its cited element's
box, or the **whole table element** for `fee_tiers[*]`. Boxes come from `element_boxes` (section 8); without a box
the fallback is the whole cited page (owner decision 10 of the 2026-10-15 list).

**Layer 1 — local OCR re-read (no egress, no cost).** RapidOCR on the crop, compared with the extracted value by the
agree rules. Two candidate mechanics, decided by measurement on the 102 documents (owner: CPU time per field and
latency per document):
- (a) search the normalised extracted value in the OCR text;
- (b) re-read: run the same parsers over the OCR text to produce an independent value.
Builder note: (b) is a true second reading, (a) only confirms presence; prefer (b) if costs are close. "Not found"
→ `unreadable`.

**Layer 2 — vision verifier on redacted class A crops** (and the three non-personal class B fields on failure or
sample). `gpt-6-luna`, reasoning `none`, structured output in the field's own type. Before sending: OCR the crop
locally, run the existing Presidio analyzer on the words, black out the boxes of detected entities (Pillow). The
crop is sent as an image; the prompt never contains the extracted value (no anchoring).

**Which layers each field needs (owner decision, 2026-10-17).** Layer 1 applies only where the value is written in
the text. Fields the extractor *infers* from wording have no text for a re-read, so they are checked by layer 2
alone. Requiring layer 1 for them would send almost every contract to review.

| Field | Layer 1 (local OCR) | Layer 2 (vision) | Served when |
|---|---|---|---|
| `fee_tiers` (table), `fee_basis` | required | required | both agree, or reviewed |
| `fee_method`, `payment_timing`, `billing_frequency`, `currency` | not applied (inferred) | required | layer 2 agrees, or reviewed |
| `fund_or_account`, `adviser`, `effective_date` | required | on failure + sample | as today unless a check disagrees |
| `client` | required | never (personal data) | as today unless layer 1 disagrees |
| class C | none live | none live | as today; audit sample only |

**Layer 3 — never sent to vision:** `client` and any field holding personal data; verified by layer 1 only.

**Image egress test (pytest).** For the fixture PDF, every image that would be sent is OCR'd and asserted to contain
none of the known raw values; and no outgoing request mentions the `client` field. Mirrors `test_pii_egress.py`.

**Failure policy.** Timeouts and provider errors record `error` (routes to review); the stage still completes so one
bad call never blocks a document. Concurrency for layer 2 ≈ 16 calls in flight via LangChain `batch` with
`max_concurrency` inside the existing synchronous worker.

## 7. Pipeline and timing (owner: safety first)

`app/ingestion_pipeline.py`:

```
PARSE_REDACT  stored    -> parsed
EXTRACT       parsed    -> extracted
VERIFY        extracted -> verified     (new)
INDEX         verified  -> indexed      (was: parsed -> indexed)
```

- New `VersionStage.verified` (Postgres enum value, migration).
- Review-ready = `verified` event exists. **Time to review-ready** = `stored` → `verified`; **time to searchable** =
  `stored` → `indexed`; both reported per document as median and p95, with time per stage.
- Indexing last means a document is searchable in chat only after verification, and review-ready is reached sooner
  than with index first.
- **Serving rule:** a class A field is served only when it has a verification `agree` on every required layer, or a
  person's review decision. Classes B and C are served as today unless a verification disagrees. Every chat and
  comparison read path goes through `served_fields`; the builder must confirm no path reads `extracted_fields`
  directly.
- Backfill: the 102 existing documents run the same `VERIFY` stage (plus the box backfill). No separate code path.

## 8. Data model (all append-only, `ledger_app` INSERT/SELECT)

- **`element_boxes`** `(element_id PK → document_elements, boxes jsonb)`: list of `{page_no, l, t, r, b,
  coord_origin}` from Docling's `ProvenanceItem` (an element can span pages). Written by `parse_redact` from now on.
  Backfill re-parses each version and inserts boxes matched on `(version_id, ordinal)` **only if** the element text
  is identical to the stored one; a mismatch skips that element (it falls back to the page crop).
- **`field_verifications`** `(id, run_id, field_path, layer, verifier, crop_kind, read_value jsonb, outcome,
  input_tokens, output_tokens, cost_usd numeric, latency_ms, created_at)`, unique on `(run_id, field_path, layer,
  verifier, crop_kind)` so a re-run is idempotent. `read_value` is tokenised where it holds personal data. `layer`
  ∈ {`ocr_local`, `vision`}; `crop_kind` ∈ {`element`, `table`, `page`}; `outcome` ∈ {`agree`, `disagree`,
  `unreadable`, `error`}.
- **`field_labels`** `(run_id, field_path, labeller, label_value jsonb, blind bool, created_at)`, PK `(run_id,
  field_path, labeller)`. `labeller` is `human:<name>`, `judge:<model>` or `adjudicated`. Separate from
  `field_reviews` (operational decisions are not measurement).
- **Events:** `verified` joins the version events; the `extracted` event's `detail` gains extraction tokens and cost.
- **Existing human reviews (my call):** a field a person already decided keeps that decision. A person's decision
  always outranks a verifier. Verification still runs and is recorded; the report counts "verifier disagreed with
  a human decision" separately, as a signal about the verifier's own error rate. Guest overlay decisions likewise.
- **Status logic:** `contracts/terms.field_status` gains the verification outcome as an input; `served_fields` and
  `pending_reviews` use it. Code lives in `app/contracts` (a separate package would create a cycle with
  `served_fields`); verification DB access in `contracts/dao.py`.
- Guest overlay: verification is corpus-level, not per guest; guest review decisions keep working as today.

## 9. Reviewer experience (diff card)

A verifier disagreement is one more item in the existing Review queue (`GET /reviews`), shown as a diff:

- header: contract title, field name, class, why flagged ("vision read 0.80%, extraction read 0.85%");
- the two values side by side, normalised the same way, differing part highlighted;
- the cropped evidence image, rendered by our server (no new egress), with the full contract one click away;
- three actions mapped to the existing review decisions: keep extracted (`confirmed`), take the verifier's
  (`corrected` with that value), type the value (`corrected`); who and when are recorded as today;
- queue order: class A first, then by money at stake (the comparison's annual gap where known).

Fields where all readings agree are not shown unless the audit sample picks them. Daily review shows both values;
labelling (section 10) is blind.

## 10. Label protocol (accuracy measurement)

- Sample: random from **auto-accepted** fields, stratified by class: 60 A, 60 B, 30 C (A grows to ~300 for the 1%
  target).
- Blind: the labeller sees the crop (and may open the page), never the extracted value.
- Judges are called through the providers' OpenAI-compatible endpoints with the existing `ChatOpenAI` (my call: no
  new dependency; the builder confirms structured output works, otherwise asks before adding a package). The builder
  records each provider's data-use terms in the report, and the **owner approves before the first document is
  sent**.
- **Tooling (owner decision): scripts, no new screen.**
  - `scripts/x1_label_export.py` draws the stratified sample and writes the crops (redacted where they would leave
    the machine) to a folder, plus a CSV with `run_id, field_path, crop file` and an empty value column. The CSV
    never holds extracted values.
  - `scripts/x1_label_import.py --labeller human:<name>` (or `judge:<model>`) writes `field_labels`.
  - The judge script fills the same CSV through the models.
  - Adjudication is a third CSV imported as `adjudicated`.
- Labellers: a human plus a second human on a 20–30 field slice if time allows. Fallback: two LLM judges from
  different providers (an Anthropic model, then a Groq-hosted model), fed the **same redacted crops**, never raw
  pages; the free tier's data terms are checked first. Judges never include the verifier's model.
- Agreement between labellers: % and Cohen's kappa; disagreements adjudicated into an `adjudicated` row.
- Report states which ground truth was used: with judges, "error rate" means disagreement with the adjudicated
  judges, not human truth.

## 11. Per-stage report

One script (`backend/scripts/x1_report.py`) writes `reports/x1-<label>.json` and a markdown table:

| Stage | Cost per document | Time per document | Confidence |
|---|---|---|---|
| parse and redact | CPU seconds (local) | median, p95 | parse success rate, page-grade distribution |
| extract | tokens and $ (from the `extracted` event) | median, p95 | grounded %, validator failures, routing by class |
| verify | $ per field and per document by layer | median, p95 | agreement by class and layer; review rate; labelled error rate per class with its upper bound vs target |
| index | embeddings $ | median, p95 | n/a (retrieval quality stays the golden gate's job) |
| end to end | — | time to review-ready, time to searchable | — |

Plus a projection to 100k documents (ingestion, extraction, verification) and 100k daily active users (chat, from
N7's measured $ per answer), each line naming its prices and assumptions. List prices; the report says so.

## 12. Extraction model selection

- Shortlist: Gemini 3.5 Flash-Lite, gpt-5-mini (minimal reasoning), gpt-4.1-mini; `gpt-6-luna` excluded (it is the
  verifier).
- Gate before any run: the provider's data terms say "not used for training".
- **Candidate runs never touch `extraction_runs` (my call):** writing them there would make each candidate the
  latest run that `served_fields` and the review queue read. A script runs the existing extraction prompt and schema
  per candidate and writes the outputs to `reports/x1-model-<model>.json`. It scores them against the labels joined
  on `(version_id, field_path)`, with `fee_tiers` compared as one table, so band indices need not line up.
- Run each on the 102 documents through the existing extractor (OpenAI-compatible endpoint, no new dependency;
  confirm structured output works through it).
- Rank on the labels: class A accuracy first, then review rate, then price. gpt-4.1 stays until a candidate matches
  it on class A.
- Changing the extractor is a separate, owner-approved step after the result; it re-runs this report.

## 13. Left to the builder

- Layer 1 mechanics (a) vs (b), by the measurement rule above.
- The 0.9 similarity threshold and the exact normalisation list.
- Crop padding, render DPI, image size sent to the verifier.
- Prompt wording for the verifier and judges.
- Exact column types, index choices, migration split.
- How the diff highlight is computed for text values.

## 14. Deferred (not in this design)

- Batch lane: a 24 h quality SLA would allow it; batching **extraction** saves more (~$675 at 100k documents)
  than batching verification (~$35–230); needs a "pending verification" state, idempotent result writes and
  retroactive downgrades.
- PDF-viewer highlight from `element_boxes`.
- Calibrated confidence and auto-accept on agreement.
- Chat model change (its own golden gate).

## 15. Skills that informed this design

- **clean-architecture:** agree rules and status logic as pure functions (`agree.py`, `terms.py`); the pipeline
  module as the single composition point; verification kept inside `contracts` to avoid a dependency cycle.
- **ddia-systems:** append-only system of record with derived status computed at read time; idempotent writes keyed
  on the check's identity; `element_boxes` as a derived table rebuilt from the source PDF.
- **supabase-postgres-best-practices:** composite primary/unique keys matching the read patterns
  (`run_id, field_path`), enum for outcomes, migrations by the owner role.
- **pragmatic-programmer:** one definition of "agree" shared with billing parsers (DRY); fail loud on check errors
  (`error` routes to review); measure before choosing (layer 1 mechanics, extraction model).
