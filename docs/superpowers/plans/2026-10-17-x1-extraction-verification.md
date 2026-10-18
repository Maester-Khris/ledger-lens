# X1 Extraction Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Check every important extracted contract field with an independent second reading, send disagreements to
a person as a field-level diff, and measure the auto-accepted error rate per field class against its target.

**Architecture:** A new `VERIFY` stage (`extracted -> verified`) runs between extraction and indexing. It crops
each field's cited evidence from the PDF, re-reads it locally (RapidOCR, layer 1) and, for class A, with a vision
model on a PII-blacked-out crop (layer 2), compares the readings with pure agree rules, and appends one
`field_verifications` row per check. `terms.field_status` takes the verification outcomes as an input, so
`served_fields`, `terms_view` and `pending_reviews` all apply the serving rule from one definition. Labels,
reports and the model comparison are scripts that read these tables and write `reports/` files.

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy 2.0 / Alembic / Postgres 18; RapidOCR 3.9.2, pypdfium2 5.8.0,
Pillow 11.3.0 (installed, to be listed); LangChain `ChatOpenAI` (verifier `gpt-6-luna`, judges and candidate
extractors through OpenAI-compatible endpoints); React + TypeScript for the diff card.

**Spec:** `docs/superpowers/specs/2026-10-17-x1-extraction-verification-design.md`. Owner decisions with reasons:
`artifacts/2026-10-15-ingestion-quality-verification-decisions.md` section 9 (local, untracked).

## Global Constraints

- New tables are append-only: `forbid_mutation()` triggers on UPDATE/DELETE/TRUNCATE; `ledger_app` gets
  SELECT/INSERT only; `ledger_demo` gets SELECT (it serves fields). Migrations run as `ledger_owner`.
- Routes stay thin; DB access only in each package's `dao.py`; pure logic in framework-free files
  (`contracts/agree.py`, `contracts/terms.py`); `app/ingestion_pipeline.py` is the only module that knows stage order.
- A verifier result **never overwrites** an extracted value; it only routes to review.
- A class A extracted value is **never served** before it is verified (`agree` on every required layer) or reviewed.
- No raw personal data leaves the machine in text or image. `client` never goes to vision.
- `unreadable`, `error`, a timeout or malformed model output is never counted as `agree`.
- Money fields: no numeric tolerance; `parse_rate_bps` and `parse_amount_minor` from `contracts/fee_text.py` are the
  only parsers.
- Verifier model differs from the extractor (`gpt-4.1`); judges differ from the verifier (`gpt-6-luna`).
- Candidate extraction runs are written to `reports/x1-model-<model>.json`, never to `extraction_runs`.
- Dependencies: list `pillow==11.3.0`, `pypdfium2==5.8.0`, `rapidocr==3.9.2` in `requirements-worker.txt`; no
  `presidio-image-redactor`; nothing new in `requirements.txt` (the API serves crops as stored files).
- Run every backend command as `/home/niki/Documents/workenv/pydev/bin/<tool>`; never create a `.venv`.
- Before pytest or any CPU-heavy run, this guard must print nothing (pytest drops the `ledger_test` schema):
  `pgrep -af 'run_chat.sh|gate_runs.sh|grafana/k6|py-spy|pytest|token_report.py|uvicorn app.main:app' | grep -v pgrep`
- Commits: one line, conventional, files staged by name, no AI attribution, never on `main`/`preview`.
  `artifacts/` is gitignored on purpose. After code changes run `graphify update .` from the repo root.

## Owner gates (stop and ask; never skip)

| Gate | Before task | Why |
|---|---|---|
| OpenAI credit recharged | 5 (live smoke), 8, 9, 11 | balance exhausted 2026-10-17 |
| Data-use terms approved per provider (OpenAI, Anthropic, Groq, Google) | first document sent to that provider | owner decision 3 |
| `pg_dump` of `ledger_dev` taken | 8 | backfill writes the DB the golden gate reads |
| Golden gate run (~$0.46) | after 8, only if the owner asks | the serving rule changes what chat tools see (see Review Focus 5) |
| Prediction written | every measured run (8, 9, 10, 11) | a miss by more than half, or a broken guardrail, means stop and report |

## Review Focus

1. **Demo role reads the new tables.** `served_fields` under the `ledger_demo` session must not 500 because
   `field_verifications` lacks a grant. Pinned in Task 2 (`test_demo_role_can_read_verifications`).
2. **Malformed or refused vision output.** A response that fails the structured schema, is empty, or times out must
   record `error`, never `agree`, and the stage still completes. Pinned in Task 5
   (`test_vision_malformed_output_records_error`).
3. **Page-crop fallback still redacts.** An element with no box (pre-backfill, or a text mismatch) falls back to the
   whole page, which holds more personal data than a crop. Pinned in Task 4 (`test_page_fallback_crop_has_no_raw_pii`).
4. **Table correction with a different band count.** Taking a verifier's table that has a different number of bands
   than the run must be refused (422) with no band rows written. Pinned in Task 6
   (`test_table_correction_band_count_mismatch_writes_nothing`).
5. **Documents indexed before X1.** The 102 existing documents are already `indexed`; until their `verified` event
   exists, class A is unserved. The comparison tool and chat must say "not comparable / not yet verified", not
   crash or serve. Pinned in Task 6 (`test_compare_reports_unverified_class_a_as_not_comparable`). Because this
   changes what chat tools see, the golden gate may move after the backfill: ask the owner (gate above).

---

### Task 1: Agree rules

**Files:**
- Create: `backend/app/contracts/agree.py`
- Test: `backend/tests/test_contracts_agree.py`

**Interfaces:**
- Consumes: `parse_rate_bps(str) -> Decimal`, `parse_amount_minor(str) -> int | None` from `contracts/fee_text.py`.
- Produces:
  - `Outcome = Literal["agree", "disagree", "unreadable", "error"]`
  - `@dataclass(frozen=True) class Comparison: outcome: Outcome; detail: str | None` (detail names the first
    differing band, e.g. `"band 2: rate 85 vs 80 bps"`)
  - `compare_enum(a: str | None, b: str | None) -> Comparison`
  - `compare_date(a: str | None, b: str | None) -> Comparison` (uses `fields.DATE_FORMATS`)
  - `compare_int(a: int | None, b: int | None) -> Comparison`
  - `compare_text(a: str | None, b: str | None) -> Comparison`
  - `compare_names(a: Sequence[str], b: Sequence[str]) -> Comparison`
  - `compare_fee_table(a: Sequence[Mapping], b: Sequence[Mapping]) -> Comparison` — each band has `band_text`,
    `rate_text`
  - `normalise_text(text: str) -> str`
  - `compare_field(field_path: str, extracted: object, read: object) -> Comparison` — dispatch by field base name
  - `TEXT_SIMILARITY = 0.9` (ponytail comment: tuned on labels in Task 10)

- [ ] **Step 1: Write the failing tests**

```python
from app.contracts.agree import compare_fee_table, compare_field, compare_text, normalise_text

def test_fee_table_agrees_across_wording():
    a = [{"band_text": "first $1,000,000", "rate_text": "0.85%"}, {"band_text": "thereafter", "rate_text": "0.60%"}]
    b = [{"band_text": "On the first $1 million", "rate_text": "85 bps"}, {"band_text": "above", "rate_text": "60 basis points"}]
    assert compare_fee_table(a, b).outcome == "agree"

def test_fee_table_rate_off_by_five_bps_disagrees_and_names_band():
    a = [{"band_text": "first $1,000,000", "rate_text": "0.85%"}, {"band_text": "thereafter", "rate_text": "0.60%"}]
    b = [{"band_text": "first $1,000,000", "rate_text": "0.80%"}, {"band_text": "thereafter", "rate_text": "0.60%"}]
    result = compare_fee_table(a, b)
    assert result.outcome == "disagree" and result.detail.startswith("band 1")

def test_fee_table_band_count_mismatch_disagrees():
    a = [{"band_text": "first $1,000,000", "rate_text": "1%"}, {"band_text": "thereafter", "rate_text": "0.5%"}]
    assert compare_fee_table(a, a[:1]).outcome == "disagree"

def test_fee_table_unparseable_read_is_unreadable():
    a = [{"band_text": "first $1,000,000", "rate_text": "1%"}]
    assert compare_fee_table(a, [{"band_text": "first", "rate_text": "n/a"}]).outcome == "unreadable"

def test_text_normalises_legal_suffix_and_the():
    assert normalise_text("The Acme Capital, L.P.") == normalise_text("acme capital")
    assert compare_text("Acme Capital Inc.", "ACME CAPITAL").outcome == "agree"
    assert compare_text("Acme Capital", "Apex Partners").outcome == "disagree"

def test_null_rules():
    assert compare_field("currency", None, None).outcome == "agree"
    assert compare_field("currency", "USD", None).outcome == "disagree"
    assert compare_field("effective_date", None, "January 1, 2024").outcome == "disagree"

def test_date_and_enum_and_int():
    assert compare_field("effective_date", "January 1, 2024", "2024-01-01").outcome == "agree"
    assert compare_field("fee_method", "graduated", "cliff").outcome == "disagree"
    assert compare_field("termination_notice_days", 30, 30).outcome == "agree"
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && /home/niki/Documents/workenv/pydev/bin/pytest tests/test_contracts_agree.py -v`
Expected: FAIL, `ModuleNotFoundError: app.contracts.agree`.

- [ ] **Step 3: Implement `app/contracts/agree.py`**

Normalisation: casefold, `’`→`'`, strip punctuation, collapse whitespace, drop a leading `the`, drop trailing
`inc|llc|ltd|l p|lp|corp`. Similarity: `difflib.SequenceMatcher(None, a, b).ratio()` (stdlib; normalised
Levenshtein not needed for a 0.9 cut). `compare_fee_table`: a `FeeTextError` or a `None` rate/amount on the read
side → `unreadable`; on the extracted side → `disagree` with detail `"extracted table does not parse"`.
`compare_field` maps `fee_tiers` → table, `fee_method|currency|billing_frequency|payment_timing` → enum,
`*_date` → date, `termination_notice_days` → int, `signatories` → names, everything else → text.

- [ ] **Step 4: Run to verify they pass** — same command, expected PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/contracts/agree.py backend/tests/test_contracts_agree.py
git commit -m "feat(contracts): add X1 agree rules for verified field comparison"
```

---

### Task 2: Data model, migration and status logic

**Files:**
- Create: `backend/alembic/versions/0017_x1_verification.py`
- Modify: `backend/app/documents/types.py` (`VersionStage.verified`), `backend/app/documents/models.py`
  (`ElementBox`), `backend/app/contracts/models.py` (`FieldVerification`, `FieldLabel`),
  `backend/app/contracts/terms.py`, `backend/app/contracts/dao.py`
- Test: `backend/tests/test_migrations.py`, `backend/tests/test_contract_terms.py`, `backend/tests/test_contracts_dao.py`,
  `backend/tests/test_demo_role.py`

**Interfaces:**
- Consumes: `Outcome` from Task 1.
- Produces:
  - Migration `0017_x1_verification` (revises `0016_chat_turn_timing`):
    `ALTER TYPE version_stage ADD VALUE 'verified'`; enums `verification_layer ('ocr_local','vision')`,
    `crop_kind ('element','table','page')`, `verification_outcome ('agree','disagree','unreadable','error')`;
    tables per spec section 8: `element_boxes (element_id uuid PK → document_elements, boxes jsonb NOT NULL)`,
    `field_verifications (id bigint identity PK, run_id → extraction_runs, field_path, layer, verifier, crop_kind,
    read_value jsonb NULL, outcome, detail text NULL, input_tokens int, output_tokens int, cost_usd numeric(10,6),
    latency_ms int, created_at)` UNIQUE `(run_id, field_path, layer, verifier, crop_kind)`,
    `field_labels (run_id, field_path, labeller CHECK ~ '^(human:|judge:|adjudicated$)', label_value jsonb,
    blind bool, created_at)` PK `(run_id, field_path, labeller)`; append-only triggers on all three; grants
    SELECT/INSERT to `ledger_app`, SELECT to `ledger_demo`. Downgrade drops the tables and enums; it leaves the
    `verified` enum value (Postgres cannot drop one; say so in a comment).
  - `terms.FieldClass = Literal["A", "B", "C"]`; `terms.field_class(path: str) -> FieldClass`
  - `terms.required_layers(path: str) -> frozenset[str]` — `fee_tiers`, `fee_basis`: `{ocr_local, vision}`;
    the four inferred enums: `{vision}`; class B and C: `frozenset()` (checked when present, not required)
  - `terms.verification_path(path: str) -> str` — `fee_tiers[i]` → `fee_tiers`, else unchanged
  - `field_status(routing, decision, outcomes: Mapping[str, Outcome], path: str) -> FieldStatus` where `outcomes`
    is layer → outcome for the live crop kind. Rules, in order: a decision wins; `routing` needs_review →
    `needs_review`; any present outcome that is not `agree` → `needs_review`; a required layer missing →
    `needs_review`; else `accepted`.
  - `field_reason(...)` gains `outcomes` and returns `"awaiting verification"` (required layer missing) or
    `"verifier disagreed"` / `"verifier could not read it"` / `"verification failed"` before the existing reasons.
  - `dao.verification_outcomes(session, run_id) -> dict[str, dict[str, Outcome]]` (verification path → layer →
    outcome; a `page` row is used only when no `element`/`table` row exists for that layer)
  - `dao.save_verification(session, row: VerificationRow) -> None` with `@dataclass(frozen=True) VerificationRow`
    mirroring the table; `ON CONFLICT DO NOTHING` on the unique key (idempotent re-run)
  - `dao.save_boxes(session, element_id, boxes: list[dict]) -> None` lives in `documents/dao.py`
  - `served_fields`, `terms_view`, `pending_reviews` pass `outcomes.get(verification_path(path), {})` to
    `field_status`. `pending_reviews` lists a field when its status is `needs_review` **and** it is not only
    "awaiting verification" (a field waiting for the stage is not a reviewer's job yet).

- [ ] **Step 1: Write the failing tests**

```python
# test_contract_terms.py
def test_class_a_without_verification_is_not_served():
    assert field_status(FieldRouting.accepted, None, {}, "fee_tiers[0]") == "needs_review"

def test_class_a_served_when_all_required_layers_agree():
    assert field_status(FieldRouting.accepted, None, {"ocr_local": "agree", "vision": "agree"}, "fee_tiers[1]") == "accepted"
    assert field_status(FieldRouting.accepted, None, {"vision": "agree"}, "fee_method") == "accepted"

def test_error_or_unreadable_never_counts_as_agree():
    for bad in ("error", "unreadable", "disagree"):
        assert field_status(FieldRouting.accepted, None, {"ocr_local": "agree", "vision": bad}, "fee_basis") == "needs_review"

def test_class_b_served_as_today_unless_a_check_disagrees():
    assert field_status(FieldRouting.accepted, None, {}, "client") == "accepted"
    assert field_status(FieldRouting.accepted, None, {"ocr_local": "disagree"}, "client") == "needs_review"

def test_human_decision_outranks_verifier():
    assert field_status(FieldRouting.accepted, ReviewDecision.confirmed, {"vision": "disagree"}, "currency") == "confirmed"

# test_contracts_dao.py
def test_save_verification_is_idempotent(db_session, saved_run): ...  # same key twice -> one row
def test_field_verifications_are_append_only(db_session, saved_run): ...  # UPDATE raises
def test_awaiting_verification_is_not_in_pending_reviews(db_session, tenant_id, saved_run): ...

# test_demo_role.py
def test_demo_role_can_read_verifications(demo_session, ...): ...  # served_fields runs under ledger_demo
```

The `...` bodies follow the fixtures already in each file (`saved_run` = the `save_run` helper those tests use).

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && /home/niki/Documents/workenv/pydev/bin/pytest tests/test_contract_terms.py tests/test_contracts_dao.py tests/test_demo_role.py tests/test_migrations.py -v`
Expected: FAIL (`field_status` takes 2 arguments; table `field_verifications` does not exist).

- [ ] **Step 3: Write the migration, models, `terms.py` and `dao.py` changes** to the interfaces above. Update the
  existing `field_status` callers and tests to the new signature.

- [ ] **Step 4: Run the full suite** (`pytest`, after the guard). Expected: PASS. Existing tests that expected class A
  fields to be served without verification are updated to save `agree` rows first; list each one changed in the
  commit body's summary to the owner.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/0017_x1_verification.py backend/app/documents/types.py backend/app/documents/models.py \
  backend/app/documents/dao.py backend/app/contracts/models.py backend/app/contracts/terms.py backend/app/contracts/dao.py \
  backend/tests/test_migrations.py backend/tests/test_contract_terms.py backend/tests/test_contracts_dao.py backend/tests/test_demo_role.py
git commit -m "feat(contracts): add X1 verification tables and gate class A serving on verification"
```

---

### Task 3: Boxes, crops and the VERIFY stage with layer 1 (tracer)

**Files:**
- Create: `backend/app/contracts/crops.py`, `backend/app/contracts/verify.py`
- Modify: `backend/app/documents/parse.py` (boxes on `ParsedElement`), `backend/app/documents/ingest.py` (write
  boxes; `cpu_seconds` in the `parsed` event), `backend/app/ingestion_pipeline.py`, `backend/scripts/ingestion_worker.py`,
  `backend/requirements-worker.txt`
- Test: `backend/tests/test_contracts_verify.py`, `backend/tests/test_ingestion_pipeline.py`, `backend/tests/test_documents_parse.py`

**Interfaces:**
- Consumes: `compare_field` (Task 1); `save_verification`, `verification_outcomes`, `save_boxes` (Task 2);
  `documents_dao.reveal`, `documents_dao.tokenize_known_values`, `store.original_path`.
- Produces:
  - `parse.Box(page_no: int, l: float, t: float, r: float, b: float, coord_origin: str)`; `ParsedElement.boxes: tuple[Box, ...]`
    from each item's `prov[*].bbox`.
  - `crops.render_pages(pdf_path: Path, pages: Iterable[int], dpi: int = 200) -> dict[int, Image.Image]` (pypdfium2,
    once per document)
  - `crops.crop(page: Image.Image, page_size_pt: tuple[float, float], box: Box | None, pad_pt: float = 6) -> Image.Image`
    (handles `BOTTOMLEFT` and `TOPLEFT`; `box=None` → whole page)
  - `crops.ocr_lines(image: Image.Image) -> list[OcrLine]`, `OcrLine(text: str, box: tuple[int, int, int, int])`
    (RapidOCR engine built once, `lru_cache`)
  - `verify.read_local(field_path: str, ocr_text: str, extracted: object) -> object | None` — fee table: re-read
    (mechanic (b)): each OCR line holding a rate becomes a `{band_text, rate_text}` band, split at the rate match;
    text and dates: mechanic (a), return the extracted value if its normalised form is found in the normalised OCR
    text (a sliding window with `compare_text` similarity), else `None`.
  - `verify.run_verification(session, version_id, *, store_root: Path, hmac_key: str, vault_key: str,
    vision: VisionVerifier | None) -> None` — the stage runner; with `vision=None` only layer 1 runs. Appends the
    `verified` event with `{run_id, fields_checked, outcomes: Counter, ocr_ms, vision_ms, cost_usd}`. It also saves
    each checked field's unredacted crop as `DOCUMENT_STORE_DIR/crops/<run_id>/<verification_path>.png` (local
    only; the diff card serves it in Task 6).
  - `ingestion_pipeline`: `VERIFY = StageSpec("verify", extracted, verified)`; `INDEX` requires `verified`;
    `PIPELINE = (PARSE_REDACT, EXTRACT, VERIFY, INDEX)`.
  - Worker: `"verify": partial(run_verification, store_root=..., hmac_key=..., vault_key=..., vision=None)` in this
    task (Task 5 swaps in the verifier).
- Layer 1 fields: `fee_tiers`, `fee_basis`, `fund_or_account`, `adviser`, `effective_date`, `client`. Extracted
  values are revealed (`documents_dao.reveal`) before comparing with OCR text; `read_value` is stored after
  `tokenize_known_values`. Class C: no live check.

- [ ] **Step 1: Write the failing tests**

```python
def test_parse_returns_boxes_for_fixture(): ...           # client_agreement.pdf: every element has >= 1 box, page_no >= 1
def test_crop_bottomleft_box_maps_to_pixels(): ...        # synthetic 612x792 page, box -> expected pixel rect at 200 dpi
def test_read_local_rereads_fee_table_from_ocr_text():
    ocr = "On the first $1,000,000  0.85%\nThereafter  0.60%"
    assert compare_field("fee_tiers", EXTRACTED_TABLE, read_local("fee_tiers", ocr, EXTRACTED_TABLE)).outcome == "agree"
def test_pipeline_order_is_parse_extract_verify_index(): ...  # next_stage after extracted is verify; index waits for verified
def test_verify_stage_end_to_end_on_fixture(db_session, tenant_id, ...): ...
    # ingest client_agreement.pdf, save a run with the fixture's true values, run_verification(vision=None):
    # one ocr_local row per layer-1 field present, fee_tiers agree, a `verified` event, re-run writes no new rows
```

- [ ] **Step 2: Run to verify they fail.** Expected: import errors / wrong pipeline order.

- [ ] **Step 3: Implement** to the interfaces. List the three packages in `requirements-worker.txt`, then run
  `/home/niki/Documents/workenv/pydev/bin/pip check` (expected: no broken requirements).

- [ ] **Step 4: Run the full suite.** Expected: PASS.

- [ ] **Step 5: Measure layer 1 on the fixture** (no cost): record OCR ms per field and per document in the
  commit summary. If the fee-table re-read is more than 2× the presence search, report to the owner before Task 5.

- [ ] **Step 6: Commit**

```bash
git add backend/app/contracts/crops.py backend/app/contracts/verify.py backend/app/documents/parse.py backend/app/documents/ingest.py \
  backend/app/ingestion_pipeline.py backend/scripts/ingestion_worker.py backend/requirements-worker.txt \
  backend/tests/test_contracts_verify.py backend/tests/test_ingestion_pipeline.py backend/tests/test_documents_parse.py
git commit -m "feat(contracts): add the X1 verify stage with local OCR re-read before indexing"
```

---

### Task 4: Image redaction and the image egress test

**Files:**
- Modify: `backend/app/contracts/crops.py`
- Test: `backend/tests/test_image_pii_egress.py`

**Interfaces:**
- Consumes: `ocr_lines` (Task 3), `PiiDetector.detect(text) -> list[PiiSpan]`, `documents_dao.tokenize_known_values`.
- Produces: `crops.redact_image(image: Image.Image, is_personal: Callable[[str], bool]) -> Image.Image` — OCR the
  image, black out (filled rectangle, padded 2 px) every line for which `is_personal(line.text)` is true. The
  verifier builds `is_personal` as: Presidio finds any span **or** `tokenize_known_values(text) != text` (the
  tenant's known raw values). Line-level, coarser than word-level on purpose.

- [ ] **Step 1: Write the failing tests**

```python
RAW_PII = ("Marie Tremblay", "Tremblay", "130 692 544", "marie.tremblay@example.com", "514-555-0142")

@pytest.mark.slow
def test_no_raw_pii_in_any_outgoing_crop(...): ...
    # every crop the verifier would send for client_agreement.pdf (all layer-2 fields), redacted,
    # then OCR'd again: no RAW_PII value in the text
@pytest.mark.slow
def test_page_fallback_crop_has_no_raw_pii(...): ...      # same, with every box removed (whole-page crops)
def test_client_field_is_never_sent_to_vision(...): ...   # the vision request list holds no `client` path
```

- [ ] **Step 2: Run to verify they fail.** Expected: `redact_image` undefined.
- [ ] **Step 3: Implement `redact_image`.**
- [ ] **Step 4: Run** `pytest tests/test_image_pii_egress.py -v -m slow`. Expected: PASS.
- [ ] **Step 5: Commit**

```bash
git add backend/app/contracts/crops.py backend/tests/test_image_pii_egress.py
git commit -m "feat(contracts): black out personal data in crops and test that no raw value leaves in an image"
```

---

### Task 5: Layer 2 vision verifier

**Files:**
- Create: `backend/app/contracts/prompts/verify_v1.md`
- Modify: `backend/app/contracts/verify.py`, `backend/app/config.py`, `backend/scripts/ingestion_worker.py`,
  `backend/scripts/load/mock_openai.py` (only if it cannot answer an image request with a structured reply)
- Test: `backend/tests/test_contracts_verify.py`, `backend/tests/test_image_pii_egress.py`

**Interfaces:**
- Consumes: `redact_image` (Task 4), `compare_field` (Task 1), `save_verification` (Task 2).
- Produces:
  - `config.VERIFIER_MODEL = os.environ.get("VERIFIER_MODEL", "gpt-6-luna")`, `config.VERIFIER_TIMEOUT_SECONDS = 30`,
    `config.VERIFIER_CONCURRENCY = 16`; `VERIFIER_PRICE_PER_MTOK = (in, out)` with a comment naming the price page
    and date (list prices).
  - `verify.VisionVerifier(chat_model: BaseChatModel, model_id: str)` with
    `read(requests: Sequence[VisionRequest]) -> list[VisionReading]`; `VisionRequest(field_path, image_png: bytes)`;
    `VisionReading(value: object | None, outcome_if_failed: Outcome | None, input_tokens, output_tokens, latency_ms)`.
    One structured-output schema per field type (enum fields answer in the same enum as `schema.ContractTerms`),
    each with a `not_stated` option. Calls go through `chat_model.batch(..., config={"max_concurrency":
    VERIFIER_CONCURRENCY}, return_exceptions=True)`; an exception, timeout or parse failure → `error`. The prompt
    never contains the extracted value.
  - Layer 2 fields: class A always; `adviser`, `fund_or_account`, `effective_date` when layer 1 is not `agree`, plus a
    seeded 10% sample (seed = run_id) — ponytail: fixed rate, tune with labels. `client` never.

- [ ] **Step 1: Write the failing tests**

```python
def test_vision_agree_serves_class_a(...): ...            # fake chat model returns the true values -> fee_method accepted
def test_vision_malformed_output_records_error(...): ...  # fake returns invalid JSON / raises -> outcome 'error', stage completes
def test_vision_prompt_never_contains_extracted_value(...): ...  # recorded request has no extracted rate text
def test_layer2_runs_on_class_b_only_on_failure_or_sample(...): ...
```

Extend `test_no_raw_pii_in_any_outgoing_crop` to capture the real request bodies through `mock_openai` with the
event-hook pattern of `test_pii_egress.py`, decode each base64 image, OCR it, assert no `RAW_PII`.

- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement**; the worker builds `VisionVerifier(ChatOpenAI(model=VERIFIER_MODEL, reasoning_effort="none",
  timeout=..., max_retries=config.LLM_MAX_RETRIES), VERIFIER_MODEL)`.
- [ ] **Step 4: Run the full suite.** Expected: PASS.
- [ ] **Step 5 (owner gate: credit + OpenAI terms): live smoke on the fixture only.** Write a prediction (cost per
  document, outcomes) first. Run the worker `--once` against `ledger_test` data for the fixture; report cost,
  latency and outcomes.
- [ ] **Step 6: Commit**

```bash
git add backend/app/contracts/prompts/verify_v1.md backend/app/contracts/verify.py backend/app/config.py \
  backend/scripts/ingestion_worker.py backend/tests/test_contracts_verify.py backend/tests/test_image_pii_egress.py
git commit -m "feat(contracts): add the X1 vision verifier on redacted crops"
```

---

### Task 6: Serving paths and review queue for verification

**Files:**
- Modify: `backend/app/contracts/dao.py` (`PendingField`, `pending_reviews`, `record_review`),
  `backend/app/routes/reviews.py`, `backend/app/contracts/compare.py`, `backend/app/assistant/contract_tools.py` (only
  if its message for unserved fields needs the new reason)
- Test: `backend/tests/test_reviews_api.py`, `backend/tests/test_contracts_compare.py`, `backend/tests/test_guest_reviews.py`

**Interfaces:**
- Consumes: Task 2 status logic, Task 3/5 rows.
- Produces:
  - `PendingField` gains `field_class: str`, `verification: VerificationView | None` with
    `VerificationView(layer, verifier, read_value, outcome, detail, crop_url)`; `crop_url` is
    `/reviews/{run_id}/crops/{verification_path}` when a crop file exists.
  - The table is **one** item: `pending_reviews` returns `field_path="fee_tiers"` with `value` = the list of bands
    and `read_value` = the verifier's list, instead of one item per band.
  - `record_review(..., field_path="fee_tiers", ...)` expands to one `field_reviews` row per band in one
    transaction: `confirmed`/`rejected` → every band; `corrected` with a list → same length required, else
    `ReviewInvalid` (422) and nothing written. Guest overlay: same expansion into `guest_field_reviews`.
  - Queue order: class A first, then annual gap at stake from `compare` where known (descending), then document
    title.
  - `GET /reviews/{run_id}/crops/{field_path}` → the PNG stored by the verify stage at
    `DOCUMENT_STORE_DIR/crops/<run_id>/<field_path>.png` (unredacted: the reviewer is inside the boundary, no egress),
    same tenant check as the page file (Task 3 writes these files).
  - A route audit: `grep -rn "ExtractedField\|extracted_fields" backend/app` lists only `contracts/models.py`,
    `contracts/dao.py`, and the field-review FK; record the result in the commit summary.

- [ ] **Step 1: Write the failing tests**

```python
def test_disagreement_appears_as_one_table_item(client, ...): ...
def test_table_confirm_writes_every_band(client, ...): ...
def test_table_correction_band_count_mismatch_writes_nothing(client, ...): ...   # 422, zero field_reviews rows
def test_queue_orders_class_a_first(client, ...): ...
def test_crop_endpoint_is_tenant_scoped(client, ...): ...                         # other tenant -> 404
def test_compare_reports_unverified_class_a_as_not_comparable(db_session, ...): ...
def test_guest_table_review_stays_in_overlay(...): ...
```

- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the full suite.** Expected: PASS.
- [ ] **Step 5: Commit**

```bash
git add backend/app/contracts/dao.py backend/app/routes/reviews.py backend/app/contracts/compare.py \
  backend/tests/test_reviews_api.py backend/tests/test_contracts_compare.py backend/tests/test_guest_reviews.py
git commit -m "feat(reviews): queue verifier disagreements with fee tables reviewed as one unit"
```

---

### Task 7: Diff card

**Files:**
- Modify: `frontend/src/api.ts` (`ReviewItemDto.field_class`, `ReviewItemDto.verification`), `frontend/src/screens/Review.tsx`,
  `frontend/src/lib/review.ts`, `frontend/src/screens/Review.css`
- Test: `frontend/src/lib/review.test.ts` if the repo has a test runner for `lib/`; otherwise `npm run build` + `npm run lint`
  are the checks (no new npm package)

**Interfaces:**
- Consumes: Task 6 DTO.
- Produces: `DiffCard({ item, selected, onSelect, onDone }: FieldReviewCardProps)` rendered when `item.verification`
  is set, else the existing `FieldReviewCard`. `lib/review.ts`: `diffParts(a: string, b: string): { text: string;
  changed: boolean }[]` (character-level common prefix/suffix; ponytail: no diff library) and `flagReason(item)`
  (e.g. "vision read 0.80%, extraction read 0.85%").
- Layout per spec section 9: header (title, field label, class, reason), two values side by side with the changed part
  highlighted, crop `<img alt="Cited evidence for <field>">` from `crop_url`, "Open contract" link to the existing
  viewer, three actions: **Keep extracted** (`confirmed`), **Take verifier's** (`corrected` with `read_value`;
  disabled with a note when band counts differ), **Type the value** (existing correction input). For a table, both
  tables are rendered as rows (band text, rate), differing band highlighted.

- [ ] **Step 1:** If a test runner exists, write `diffParts` tests (`"0.85%"` vs `"0.80%"` → middle part changed).
- [ ] **Step 2:** Implement `DiffCard` and helpers.
- [ ] **Step 3:** `cd frontend && npm run build && npm run lint` — expected: no errors. Check the screen in the
  running app on a seeded disagreement (both themes, phone width).
- [ ] **Step 4: Commit**

```bash
git add frontend/src/api.ts frontend/src/screens/Review.tsx frontend/src/lib/review.ts frontend/src/screens/Review.css
git commit -m "feat(frontend): show verifier disagreements as a diff card in the review queue"
```

---

### Task 8: Backfill the 102 documents

**Files:**
- Create: `backend/scripts/x1_backfill_boxes.py`
- Test: `backend/tests/test_x1_backfill.py`

**Interfaces:**
- Consumes: `parse_pdf`, `apply_redaction`, `save_boxes`.
- Produces: `backfill_boxes(session, version_id, *, parser, detector, hmac_key) -> tuple[int, int]` (matched,
  skipped): re-parse, redact each element with the deterministic HMAC tokens, insert boxes only where the redacted
  text equals the stored `text_redacted` at the same `(version_id, ordinal)`; skip elements that already have a box.
  The `VERIFY` stage itself needs no backfill code: existing versions have `extracted` and no `verified`, so the worker
  picks them up.

- [ ] **Step 1: Test** `test_backfill_matches_only_identical_text` (one element's stored text altered → skipped) and
  `test_backfill_is_idempotent`.
- [ ] **Step 2–4:** fail, implement, pass (full suite).
- [ ] **Step 5 (owner gates: credit, dump):** `pg_dump -Fc` `ledger_dev` to a path outside the repo
  (`/home/niki/Documents/saas/backups/ledger_dev-<date>.dump`; `backend/reports/` is not gitignored); check `df -h /home`; write the prediction (match rate, verify cost and time
  for 102 documents); run the box backfill, then the worker until no `verify` stage is pending. Never Railway, never
  the contract-demo Pinecone index (the INDEX stage is already done for these versions and does not re-run).
- [ ] **Step 6:** report match rate, outcomes per class, review-queue size, cost, time; ask the owner whether to run
  the golden gate (~$0.46).
- [ ] **Step 7: Commit** script and test only:

```bash
git add backend/scripts/x1_backfill_boxes.py backend/tests/test_x1_backfill.py
git commit -m "feat(scripts): backfill element boxes for X1 verification of existing documents"
```

---

### Task 9: Labels — export, import, judges, crop vs page

**Files:**
- Create: `backend/scripts/x1_label_export.py`, `backend/scripts/x1_label_import.py`, `backend/scripts/x1_judge.py`,
  `backend/scripts/x1_crop_vs_page.py`
- Modify: `backend/app/contracts/dao.py` (`auto_accepted_fields`, `save_labels`)
- Test: `backend/tests/test_x1_labels.py`

**Interfaces:**
- Produces:
  - `dao.auto_accepted_fields(session) -> list[tuple[uuid.UUID, str, str]]` (run_id, verification path, class) —
    latest run per version, status `accepted`, no human decision.
  - `dao.save_labels(session, rows: Sequence[LabelRow]) -> None`, `LabelRow(run_id, field_path, labeller, label_value, blind)`.
  - `x1_label_export.py --out DIR --seed N --a 60 --b 60 --c 30`: stratified random sample; writes
    `DIR/crops/<n>.png` (redacted with `redact_image`, since the same files go to judges) and `DIR/labels.csv` with
    `item, run_id, field_path, crop_file, value` — `value` empty. The CSV never holds an extracted value.
  - `x1_label_import.py CSV --labeller human:<name>|judge:<model>|adjudicated`; rejects a labeller string outside the
    table's CHECK, and blank values.
  - `x1_judge.py CSV --provider anthropic|groq --model M`: fills `value` through `ChatOpenAI(base_url=...)` with the
    Task 5 field schemas; writes a new CSV. Confirm `json_schema` structured output works on each endpoint with one
    synthetic image first; if it does not, stop and ask before adding a package.
  - `x1_crop_vs_page.py`: on labelled class A items, vision on crop and on the redacted whole page; writes
    `reports/x1-crop-vs-page.json` (accuracy each), never `field_verifications`.
- Agreement (% and Cohen's kappa) is computed in Task 10.

- [ ] **Step 1: Tests:** `test_export_csv_has_no_extracted_values`, `test_export_is_stratified_and_seeded`,
  `test_import_rejects_unknown_labeller`, `test_judge_never_receives_unredacted_crop` (the crop bytes sent equal the
  exported redacted file).
- [ ] **Step 2–4:** fail, implement, pass.
- [ ] **Step 5 (owner gates: credit, Anthropic and Groq terms):** export; human labels; judges; adjudication CSV;
  import all. Prediction first.
- [ ] **Step 6: Commit** scripts, dao change and test.

```bash
git add backend/scripts/x1_label_export.py backend/scripts/x1_label_import.py backend/scripts/x1_judge.py \
  backend/scripts/x1_crop_vs_page.py backend/app/contracts/dao.py backend/tests/test_x1_labels.py
git commit -m "feat(scripts): add X1 blind label export, import and LLM judge scripts"
```

---

### Task 10: Per-stage report

**Files:**
- Create: `backend/scripts/x1_report.py`
- Modify: `backend/app/contracts/extract.py` (tokens and cost in the `extracted` event from `result["raw"].usage_metadata`),
  `backend/app/retrieval/index.py` (embedding token count in the `indexed` event)
- Test: `backend/tests/test_x1_report.py`

**Interfaces:**
- Produces (pure, testable):
  - `clopper_pearson_upper(errors: int, n: int, confidence: float = 0.95) -> float` — bisection on the binomial CDF
    with `math.comb` (no scipy).
  - `cohen_kappa(a: Sequence[str], b: Sequence[str]) -> float`
  - `class_verdict(errors: int, n: int, target: float) -> bool` (upper bound ≤ target)
  - `TARGETS = {"A": 0.05, "B": 0.05, "C": 0.10}`; `A_TIGHT = 0.01` reported once n_A ≥ 300.
  - `percentiles(values) -> (median, p95)`
  - CLI: `x1_report.py --label NAME` writes `reports/x1-<label>.json` and `reports/x1-<label>.md` with the spec
    section 11 table, the ground truth used (human / adjudicated judges), the count "verifier disagreed with a human
    decision", time to review-ready (`stored→verified`) and to searchable (`stored→indexed`), and the 100k projection on
    both axes, each line naming its prices and assumptions (chat $ per answer from N7's report file).

- [ ] **Step 1: Tests**

```python
def test_clopper_pearson_zero_errors_is_about_three_over_n():
    assert abs(clopper_pearson_upper(0, 60) - 0.0487) < 0.001
def test_class_a_passes_at_60_with_zero_errors():
    assert class_verdict(0, 60, TARGETS["A"]) is True
    assert class_verdict(1, 60, TARGETS["A"]) is False
def test_cohen_kappa_perfect_and_chance(): ...
def test_extracted_event_records_tokens(...): ...   # fake model with usage_metadata -> detail has input/output tokens
```

- [ ] **Step 2–4:** fail, implement, pass.
- [ ] **Step 5:** run on `ledger_dev` (no cost); prediction first. Tune `TEXT_SIMILARITY` on the labels only if the
  report shows text-field disagreements that are labelled correct; change it in its own commit.
- [ ] **Step 6: Commit**

```bash
git add backend/scripts/x1_report.py backend/app/contracts/extract.py backend/app/retrieval/index.py backend/tests/test_x1_report.py
git commit -m "feat(scripts): add the X1 per-stage cost, time and confidence report"
```

---

### Task 11: Extraction-model comparison

**Files:**
- Create: `backend/scripts/x1_model_compare.py`
- Test: `backend/tests/test_x1_model_compare.py`

**Interfaces:**
- Consumes: `extract.call_model`, `extract.render_input`, `fields.evaluate_terms`, `compare_field`, `field_labels`.
- Produces: `x1_model_compare.py --model M --base-url U --api-key-env VAR` → `reports/x1-model-<model>.json` with
  per-field outputs, routing, tokens and $; `score(outputs, labels) -> dict` joined on `(version_id, field_path)`,
  `fee_tiers` compared as one table. Shortlist: Gemini 3.5 Flash-Lite, gpt-5-mini (minimal reasoning), gpt-4.1-mini.
  Ranking: class A accuracy, then review rate, then price; gpt-4.1 stays unless a candidate matches it on class A.

- [ ] **Step 1: Tests:** `test_compare_never_writes_extraction_runs` (row count unchanged after a fake-model run),
  `test_score_joins_tables_as_one_unit`.
- [ ] **Step 2–4:** fail, implement, pass.
- [ ] **Step 5 (owner gates: credit, Google terms incl. the "contributor" policy):** confirm structured output on each
  endpoint with one document, prediction, then the 102 documents per candidate.
- [ ] **Step 6: Commit**

```bash
git add backend/scripts/x1_model_compare.py backend/tests/test_x1_model_compare.py
git commit -m "feat(scripts): add the X1 extraction-model comparison on the labelled set"
```

After each task: `graphify update .` from the repo root; a CHANGELOG `### Completed` line under X1 marked
`**Not epic-tracked**`.

## Skills that informed this plan

- **clean-architecture:** agree rules and status logic stay pure (`agree.py`, `terms.py`); OCR, rendering and the
  model sit behind `crops.py` and `VisionVerifier`, injected by the worker (the composition root).
- **ddia-systems:** append-only records with status derived at read time; the unique check key makes the stage
  idempotent; `element_boxes` derived from the source PDF and backfilled only on exact text match.
- **supabase-postgres-best-practices:** native enums for outcomes, composite keys matching `(run_id, field_path)`
  reads, `ON CONFLICT DO NOTHING` for retries, grants per role.
- **pragmatic-programmer:** tracer bullet (Task 3 runs end to end with layer 1 before any money is spent); one
  definition of agree shared with billing; fail loud (`error` routes to review).
- **test-driven-development:** every task starts with a failing test; the five Review Focus inputs each have one.
