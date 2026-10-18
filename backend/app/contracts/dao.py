import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy import Select, delete, func, select
from sqlalchemy.dialects.postgresql import insert

from app.billing.fee_math import validate_tiers
from app.contracts.errors import FieldAlreadyReviewed, FieldNotFound, ReviewInvalid
from app.contracts.fee_text import FeeBand, FeeTextError, tiers_from_bands
from app.contracts.fields import FieldResult, GRADE_ORDER
from app.contracts.agree import Outcome
from app.contracts.models import ExtractedField, ExtractionRun, FieldLabel, FieldReview, FieldVerification, GuestFieldReview
from app.contracts.types import FieldRouting, ReviewDecision
from app.documents import dao as documents_dao
from app.documents.models import DocumentVersion
from datetime import date, datetime
from app.billing import dao as billing_dao
from app.billing.errors import NoScheduleAssigned
from app.contracts.terms import (COMING_SOON, SERVED_STATUSES, FieldStatus, field_class, field_group,
                                 field_label, field_reason, field_sort_key, field_status, verification_path,
                                 verification_problem)


@dataclass(frozen=True)
class RunConfig:
    schema_version: str
    model_id: str
    prompt_version: str
    temperature: Decimal
    config_hash: str
    input_hash: str


@dataclass(frozen=True)
class ServedField:
    field_path: str
    value: object
    element_ids: list[uuid.UUID]
    quote: str


@dataclass(frozen=True)
class ServedTerms:
    version_id: uuid.UUID
    run_id: uuid.UUID
    fields: dict[str, ServedField]
    unserved: list[str]


# A real review, or a demo guest's own (spec P2+P9). Both expose field_path, decision, corrected_value, reason,
# decided_by and decided_at.
Review = FieldReview | GuestFieldReview


def _reviews_by_field(session: Session, run_id: uuid.UUID, overlay_guest: uuid.UUID | None) -> dict[str, Review]:
    """The run's real reviews, plus the guest's own when a guest is given. A guest can only decide a field that has
    no real review (record_review), so the two never overlap."""
    reviews: dict[str, Review] = {
        r.field_path: r for r in session.scalars(select(FieldReview).where(FieldReview.run_id == run_id))
    }
    if overlay_guest is not None:
        reviews |= {r.field_path: r for r in session.scalars(select(GuestFieldReview).where(
            GuestFieldReview.run_id == run_id, GuestFieldReview.guest_id == overlay_guest))}
    return reviews


@dataclass(frozen=True)
class VerificationRow:
    run_id: uuid.UUID
    field_path: str  # the verification path: 'fee_tiers' for the whole table
    layer: str
    verifier: str
    crop_kind: str
    read_value: object | None
    outcome: Outcome
    detail: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal(0)
    latency_ms: int = 0


@dataclass(frozen=True)
class VerificationView:
    layer: str            # "ocr_local" | "vision"
    verifier: str
    read_value: object | None   # tokenised where personal; the route reveals strings for display
    outcome: str          # never "agree" here
    detail: str | None
    crop_url: str         # f"/reviews/{run_id}/crops/{verification_path}"


def save_verification(session: Session, row: VerificationRow) -> None:
    """Idempotent on the check's identity (run, field, layer, verifier, crop kind): a re-run keeps the first result."""
    session.execute(insert(FieldVerification).values(**row.__dict__).on_conflict_do_nothing(
        constraint="uq_field_verifications_check"))


def verification_outcomes(session: Session, run_id: uuid.UUID) -> dict[str, dict[str, Outcome]]:
    """verification path -> layer -> outcome. An element or table crop is the live check; a page crop counts only
    when there is none for that layer (the fallback when an element has no box)."""
    outcomes: dict[str, dict[str, Outcome]] = {}
    rows = session.execute(select(FieldVerification.field_path, FieldVerification.layer, FieldVerification.crop_kind,
                                  FieldVerification.outcome).where(FieldVerification.run_id == run_id)
                           .order_by(FieldVerification.id))
    for path, layer, crop_kind, outcome in sorted(rows, key=lambda r: r.crop_kind != "page"):
        outcomes.setdefault(path, {})[layer] = outcome  # non-page rows sort last, so they win
    return outcomes


def _status(field: ExtractedField, review: Review | None, outcomes: dict[str, dict[str, Outcome]]) -> FieldStatus:
    return field_status(field.routing, None if review is None else review.decision,
                        outcomes.get(verification_path(field.field_path), {}), field.field_path)


def save_run(session: Session, version_id: uuid.UUID, config: RunConfig, raw_output: dict, results: Sequence[FieldResult], run_id: uuid.UUID | None = None) -> ExtractionRun:
    run = ExtractionRun(version_id=version_id, schema_version=config.schema_version, model_id=config.model_id,
                        prompt_version=config.prompt_version, temperature=config.temperature,
                        config_hash=config.config_hash, input_hash=config.input_hash, raw_output=raw_output)
    if run_id is not None:
        run.id = run_id
    session.add(run)
    session.flush()
    session.add_all(ExtractedField(
        run_id=run.id, field_path=r.field_path, value=r.value, element_ids=r.element_ids, quote=r.quote,
        grounded=r.grounded, validator_errors=r.validator_errors, page_grade=r.page_grade, routing=r.routing,
    ) for r in results)
    return run


def served_fields(session: Session, tenant_id: uuid.UUID, document_id: uuid.UUID, overlay_guest: uuid.UUID | None = None) -> ServedTerms | None:
    if documents_dao.find_document(session, tenant_id, document_id) is None:
        return None
    version_id = documents_dao.current_version_id(session, document_id)
    run = _latest_run(session, version_id)
    if run is None:
        return None
    reviews = _reviews_by_field(session, run.id, overlay_guest)
    outcomes = verification_outcomes(session, run.id)
    served, unserved = {}, []
    for field in session.scalars(select(ExtractedField).where(ExtractedField.run_id == run.id).order_by(ExtractedField.field_path)):
        review = reviews.get(field.field_path)
        status = _status(field, review, outcomes)
        if status in SERVED_STATUSES:
            value = review.corrected_value if status == "corrected" else field.value
            served[field.field_path] = ServedField(field.field_path, value, field.element_ids, field.quote)
        else:
            unserved.append(field.field_path)
    return ServedTerms(version_id, run.id, served, unserved)


def runs_with_reviews(session: Session, document_id: uuid.UUID, overlay_guest: uuid.UUID | None = None
                      ) -> list[tuple[ExtractionRun, list[Review]]]:
    runs = session.scalars(
        select(ExtractionRun).join(DocumentVersion, DocumentVersion.id == ExtractionRun.version_id)
        .where(DocumentVersion.document_id == document_id).order_by(ExtractionRun.created_at)
    ).all()
    return [(run, list(_reviews_by_field(session, run.id, overlay_guest).values())) for run in runs]


def accepted_count(session: Session, run_id: uuid.UUID) -> int:
    return session.scalar(select(func.count()).select_from(ExtractedField).where(
        ExtractedField.run_id == run_id, ExtractedField.routing == FieldRouting.accepted))


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
    field_class: str
    verification: VerificationView | None


def _latest_run(session: Session, version_id: uuid.UUID) -> ExtractionRun | None:
    return session.scalars(
        select(ExtractionRun).where(ExtractionRun.version_id == version_id).order_by(ExtractionRun.created_at.desc())
    ).first()


def latest_run(session: Session, version_id: uuid.UUID) -> ExtractionRun | None:
    return _latest_run(session, version_id)


def run_fields(session: Session, run_id: uuid.UUID) -> list[ExtractedField]:
    return list(session.scalars(select(ExtractedField).where(ExtractedField.run_id == run_id).order_by(ExtractedField.field_path)))


def _needs_a_reviewer(field: ExtractedField, outcomes: dict[str, dict[str, Outcome]]) -> bool:
    """The extraction routed it to review, or a check that ran flagged it. A field still waiting for the verify stage
    is not a reviewer's job yet: it is unserved, and it reaches the queue only if a check flags it."""
    if field.routing is FieldRouting.needs_review:
        return True
    problem = verification_problem(outcomes.get(verification_path(field.field_path), {}), field.field_path)
    return problem is not None and problem != "awaiting verification"


def _tier_index(field_path: str) -> int:
    return field_sort_key(field_path)[1]


def _pick_verification(
    v_rows: Sequence[FieldVerification],
    v_path: str,
    outcomes: dict[str, dict[str, Outcome]],
    run_id: uuid.UUID,
) -> VerificationView | None:
    path_outcomes = outcomes.get(v_path, {})
    if not any(outcome != "agree" for outcome in path_outcomes.values()):
        return None

    candidates = [
        r for r in v_rows
        if r.field_path == v_path and r.outcome != "agree" and path_outcomes.get(r.layer) == r.outcome
    ]
    if not candidates:
        candidates = [r for r in v_rows if r.field_path == v_path and r.outcome != "agree"]
    if not candidates:
        return None

    best = min(candidates, key=lambda r: (
        0 if r.layer == "vision" else (1 if r.layer == "ocr_local" else 2),
        0 if r.crop_kind != "page" else 1,
        r.id,
    ))
    return VerificationView(
        layer=best.layer,
        verifier=best.verifier,
        read_value=best.read_value,
        outcome=best.outcome,
        detail=best.detail,
        crop_url=f"/reviews/{run_id}/crops/{v_path}",
    )


def pending_reviews(session: Session, tenant_id: uuid.UUID, overlay_guest: uuid.UUID | None = None) -> list[PendingField]:
    # ponytail: a few queries per contract; fine for a demo corpus, one joined query when it isn't
    pending: list[PendingField] = []
    for row in documents_dao.list_documents(session, tenant_id):
        run = _latest_run(session, row.version.id)
        if run is None:
            continue
        reviewed = set(_reviews_by_field(session, run.id, overlay_guest))
        outcomes = verification_outcomes(session, run.id)
        v_rows = list(session.scalars(
            select(FieldVerification).where(FieldVerification.run_id == run.id).order_by(FieldVerification.id)
        ))
        fields = list(session.scalars(
            select(ExtractedField).where(ExtractedField.run_id == run.id).order_by(ExtractedField.field_path)
        ))

        tier_fields = sorted(
            [f for f in fields if verification_path(f.field_path) == "fee_tiers"],
            key=lambda f: _tier_index(f.field_path),
        )
        fee_table_qualifies = (
            bool(tier_fields)
            and not any(f.field_path in reviewed for f in tier_fields)
            and any(_needs_a_reviewer(f, outcomes) for f in tier_fields)
        )

        # A table already decided band by band (before X1) is no longer one unit: its open bands are listed singly.
        partly_reviewed = any(f.field_path in reviewed for f in tier_fields)
        fee_table_emitted = False
        for f in fields:
            if verification_path(f.field_path) == "fee_tiers" and not partly_reviewed:
                if fee_table_qualifies and not fee_table_emitted:
                    val_errors: list[str] = []
                    for tf in tier_fields:
                        for err in tf.validator_errors:
                            if err not in val_errors:
                                val_errors.append(err)
                    lowest_grade = min((tf.page_grade for tf in tier_fields), key=lambda g: GRADE_ORDER.get(g, 99))
                    tier_element_ids = [eid for tf in tier_fields for eid in tf.element_ids]
                    first_pg = documents_dao.first_page(session, tier_element_ids)
                    verification = _pick_verification(v_rows, "fee_tiers", outcomes, run.id)
                    pending.append(PendingField(
                        run_id=run.id,
                        field_path="fee_tiers",
                        value=[tf.value for tf in tier_fields],
                        quote=tier_fields[0].quote,
                        grounded=all(tf.grounded for tf in tier_fields),
                        validator_errors=val_errors,
                        page_grade=lowest_grade,
                        document_id=row.document.id,
                        document_title=row.document.title,
                        version=row.version.version,
                        page=first_pg,
                        field_class=field_class("fee_tiers"),
                        verification=verification,
                    ))
                    fee_table_emitted = True
            else:
                if f.field_path not in reviewed and _needs_a_reviewer(f, outcomes):
                    v_path = verification_path(f.field_path)
                    verification = _pick_verification(v_rows, v_path, outcomes, run.id)
                    pending.append(PendingField(
                        run_id=run.id,
                        field_path=f.field_path,
                        value=f.value,
                        quote=f.quote,
                        grounded=f.grounded,
                        validator_errors=list(f.validator_errors),
                        page_grade=f.page_grade,
                        document_id=row.document.id,
                        document_title=row.document.title,
                        version=row.version.version,
                        page=documents_dao.first_page(session, f.element_ids),
                        field_class=field_class(f.field_path),
                        verification=verification,
                    ))

    # ponytail: ordering by money at stake (the comparison's annual gap) is deferred; compare imports this DAO, so it needs a caller-side sort.
    pending.sort(key=lambda p: {"A": 0, "B": 1, "C": 2}.get(p.field_class, 99))
    return pending


def run_tenant(session: Session, run_id: uuid.UUID) -> uuid.UUID | None:
    """The tenant owning the run's document (None if no such run)."""
    run = session.get(ExtractionRun, run_id)
    if run is None:
        return None
    doc = documents_dao.get_document_for_version(session, run.version_id)
    return doc.tenant_id if doc is not None else None


def _record_fee_tiers_review(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
    decision: ReviewDecision,
    corrected_value: object | None,
    reason: str | None,
    decided_by: str,
    overlay_guest: uuid.UUID | None,
) -> Review:
    run = session.get(ExtractionRun, run_id)
    if run is None or documents_dao.get_document_for_version(session, run.version_id).tenant_id != tenant_id:
        raise FieldNotFound(f"Field fee_tiers of extraction run {run_id} does not exist.")

    tier_fields = sorted(
        [f for f in session.scalars(select(ExtractedField).where(ExtractedField.run_id == run_id))
         if verification_path(f.field_path) == "fee_tiers"],
        key=lambda f: _tier_index(f.field_path),
    )
    if not tier_fields:
        raise FieldNotFound(f"Field fee_tiers of extraction run {run_id} does not exist.")

    tier_paths = [f.field_path for f in tier_fields]
    existing_real = session.scalars(
        select(FieldReview.field_path).where(FieldReview.run_id == run_id, FieldReview.field_path.in_(tier_paths))
    ).all()
    if existing_real:
        raise FieldAlreadyReviewed(f"Field {existing_real[0]} of extraction run {run_id} has already been reviewed.")

    if overlay_guest is not None:
        existing_guest = session.scalars(
            select(GuestFieldReview.field_path).where(
                GuestFieldReview.run_id == run_id,
                GuestFieldReview.guest_id == overlay_guest,
                GuestFieldReview.field_path.in_(tier_paths),
            )
        ).all()
        if existing_guest:
            raise FieldAlreadyReviewed(f"Field {existing_guest[0]} of extraction run {run_id} has already been reviewed.")

    band_corrected_values: list[dict] = []
    if decision is ReviewDecision.corrected:
        if not isinstance(corrected_value, list) or len(corrected_value) != len(tier_fields):
            raise ReviewInvalid("A corrected fee table must provide a list with exactly as many items as bands.")
        for b in corrected_value:
            if not isinstance(b, Mapping) or "band_text" not in b or "rate_text" not in b:
                raise ReviewInvalid("Each band in corrected fee table must include 'band_text' and 'rate_text'.")
        try:
            fee_bands = [FeeBand(str(b["band_text"]), str(b["rate_text"])) for b in corrected_value]
            tiers = tiers_from_bands(fee_bands)
            validate_tiers(tiers)
        except (FeeTextError, ValueError) as exc:
            raise ReviewInvalid(f"Invalid fee tiers in review: {exc}") from exc

        band_corrected_values = [
            {
                "band_text": b["band_text"],
                "rate_text": b["rate_text"],
                "up_to_minor": tier.up_to_minor,
                "rate_bps": format(tier.rate_bps.normalize(), "f"),
            }
            for b, tier in zip(corrected_value, tiers)
        ]

    rows_to_add: list[Review] = []
    if overlay_guest is not None:
        for i, band_field in enumerate(tier_fields):
            val = band_corrected_values[i] if decision is ReviewDecision.corrected else None
            rows_to_add.append(GuestFieldReview(
                guest_id=overlay_guest,
                run_id=run_id,
                field_path=band_field.field_path,
                decision=decision,
                corrected_value=val,
                reason=reason,
            ))
    else:
        for i, band_field in enumerate(tier_fields):
            val = band_corrected_values[i] if decision is ReviewDecision.corrected else None
            rows_to_add.append(FieldReview(
                run_id=run_id,
                field_path=band_field.field_path,
                decision=decision,
                corrected_value=val,
                decided_by=decided_by,
                reason=reason,
            ))

    session.add_all(rows_to_add)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise FieldAlreadyReviewed(f"A band of fee_tiers for extraction run {run_id} has already been reviewed.") from exc

    return rows_to_add[0]


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
    overlay_guest: uuid.UUID | None = None,
) -> Review:
    if (decision is ReviewDecision.corrected) != (corrected_value is not None):
        raise ReviewInvalid("A corrected value is required for 'corrected' and not allowed for other decisions.")

    if field_path == "fee_tiers":
        return _record_fee_tiers_review(
            session,
            tenant_id=tenant_id,
            run_id=run_id,
            decision=decision,
            corrected_value=corrected_value,
            reason=reason,
            decided_by=decided_by,
            overlay_guest=overlay_guest,
        )

    field = session.get(ExtractedField, (run_id, field_path))
    run = session.get(ExtractionRun, run_id) if field is not None else None
    if run is None or documents_dao.get_document_for_version(session, run.version_id).tenant_id != tenant_id:
        raise FieldNotFound(f"Field {field_path} of extraction run {run_id} does not exist.")
    if overlay_guest is not None:
        return _record_guest_review(session, run_id=run_id, field_path=field_path, decision=decision,
                                    corrected_value=corrected_value, reason=reason, guest_id=overlay_guest)
    review = FieldReview(run_id=run_id, field_path=field_path, decision=decision, corrected_value=corrected_value,
                         decided_by=decided_by, reason=reason)
    session.add(review)
    try:
        session.commit()
    except IntegrityError as exc:  # the primary key allows one decision per field
        session.rollback()
        raise FieldAlreadyReviewed(f"Field {field_path} of extraction run {run_id} has already been reviewed.") from exc
    return review


def _record_guest_review(
    session: Session, *, run_id: uuid.UUID, field_path: str, decision: ReviewDecision, corrected_value: object | None,
    reason: str | None, guest_id: uuid.UUID,
) -> GuestFieldReview:
    """Demo mode: the decision goes to the guest's overlay. Final, like a real review: one per guest and field, and
    never on a field that already has a real review."""
    if session.get(FieldReview, (run_id, field_path)) is not None:
        raise FieldAlreadyReviewed(f"Field {field_path} of extraction run {run_id} has already been reviewed.")
    review = GuestFieldReview(guest_id=guest_id, run_id=run_id, field_path=field_path, decision=decision,
                              corrected_value=corrected_value, reason=reason)
    session.add(review)
    try:
        session.commit()
    except IntegrityError as exc:  # the primary key allows one decision per guest and field
        session.rollback()
        raise FieldAlreadyReviewed(f"Field {field_path} of extraction run {run_id} has already been reviewed.") from exc
    return review

@dataclass(frozen=True)
class TermField:
    path: str
    label: str
    group: str
    value: object
    status: FieldStatus
    reason: str | None
    page: int | None
    quote: str  # tokenised; the route reveals it for display


@dataclass(frozen=True)
class ScheduleView:
    version: int
    method: str
    tiers: list[dict]
    valid_from: date | None


@dataclass(frozen=True)
class TermsView:
    document_id: uuid.UUID
    title: str
    version: int
    run_id: uuid.UUID | None
    extracted_at: datetime | None
    fields: list[TermField]
    household: tuple[uuid.UUID, str] | None
    schedule: ScheduleView | None
    coming_soon: tuple[str, ...] = COMING_SOON


def _schedule_in_effect(session: Session, household_id: uuid.UUID, on: date) -> ScheduleView | None:
    try:
        _schedule, version, tiers = billing_dao.schedule_in_effect(session, household_id, on)
    except NoScheduleAssigned:
        return None
    return ScheduleView(version.version, version.method.value,
                        [{"up_to_minor": t.up_to_minor, "rate_bps": str(t.rate_bps)} for t in tiers],
                        version.valid_during.lower)


def terms_view(session: Session, tenant_id: uuid.UUID, document_id: uuid.UUID, on: date, overlay_guest: uuid.UUID | None = None) -> TermsView | None:
    """None = unknown document. A document without an extraction yet has run_id None and no fields."""
    document = documents_dao.find_document(session, tenant_id, document_id)
    if document is None:
        return None
    version_id = documents_dao.current_version_id(session, document_id)
    version_no = documents_dao.version_number(session, version_id)
    household = None
    schedule = None
    if document.household_id is not None and (row := billing_dao.find_household(session, tenant_id, document.household_id)):
        household = (row.id, row.name)
        schedule = _schedule_in_effect(session, row.id, on)
    run = _latest_run(session, version_id)
    if run is None:
        return TermsView(document_id, document.title, version_no, None, None, [], household, schedule)
    reviews = _reviews_by_field(session, run.id, overlay_guest)
    outcomes = verification_outcomes(session, run.id)
    fields = []
    for f in sorted(session.scalars(select(ExtractedField).where(ExtractedField.run_id == run.id)),
                    key=lambda f: field_sort_key(f.field_path)):
        review = reviews.get(f.field_path)
        status = _status(f, review, outcomes)
        problem = verification_problem(outcomes.get(verification_path(f.field_path), {}), f.field_path)
        fields.append(TermField(
            path=f.field_path, label=field_label(f.field_path), group=field_group(f.field_path),
            value=review.corrected_value if status == "corrected" else f.value, status=status,
            reason=field_reason(status, f.grounded, list(f.validator_errors), f.page_grade,
                                None if review is None else review.reason, problem),
            page=documents_dao.first_page(session, f.element_ids), quote=f.quote,
        ))
    return TermsView(document_id, document.title, version_no, run.id, run.created_at, fields, household, schedule)


def purge_guest_reviews(session: Session, guest_ids: Select | Sequence[uuid.UUID]) -> None:
    """Delete these guests' overlay reviews (the 24-hour purge). The caller commits."""
    session.execute(delete(GuestFieldReview).where(GuestFieldReview.guest_id.in_(guest_ids)))


@dataclass(frozen=True)
class LabelRow:
    run_id: uuid.UUID
    field_path: str      # verification path: "fee_tiers" for a whole table
    labeller: str        # "human:<name>" | "judge:<model>" | "adjudicated"
    label_value: object
    blind: bool = True


def auto_accepted_fields(session: Session) -> list[tuple[uuid.UUID, str, str]]:
    """Return (run_id, verification_path, field_class) for all auto-accepted fields across latest runs.

    A field counts when its status is exactly 'accepted' without a person's review decision.
    A fee table counts once, and only if every band is accepted.
    Ordered by run id then verification path for reproducible sampling.
    """
    version_ids = session.scalars(select(ExtractionRun.version_id).distinct()).all()
    items: list[tuple[uuid.UUID, str, str]] = []
    for vid in version_ids:
        run = _latest_run(session, vid)
        if run is None:
            continue
        reviews = _reviews_by_field(session, run.id, overlay_guest=None)
        outcomes = verification_outcomes(session, run.id)
        fields = session.scalars(
            select(ExtractedField).where(ExtractedField.run_id == run.id).order_by(ExtractedField.field_path)
        ).all()

        tier_fields = [f for f in fields if verification_path(f.field_path) == "fee_tiers"]
        other_fields = [f for f in fields if verification_path(f.field_path) != "fee_tiers"]

        if tier_fields and all(_status(f, reviews.get(f.field_path), outcomes) == "accepted" for f in tier_fields):
            items.append((run.id, "fee_tiers", field_class("fee_tiers")))

        for f in other_fields:
            if _status(f, reviews.get(f.field_path), outcomes) == "accepted":
                v_path = verification_path(f.field_path)
                items.append((run.id, v_path, field_class(v_path)))

    items.sort(key=lambda t: (t[0], t[1]))
    return items


def save_labels(session: Session, rows: Sequence[LabelRow]) -> None:
    """Insert ground-truth field labels. Table is append-only; caller commits."""
    for r in rows:
        session.add(FieldLabel(
            run_id=r.run_id,
            field_path=r.field_path,
            labeller=r.labeller,
            label_value=r.label_value,
            blind=r.blind,
        ))
    session.flush()

