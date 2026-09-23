from app.errors import DomainError


class IdempotencyKeyMissing(DomainError):
    status = 400
    type_slug = "idempotency-key-missing"
    title = "Idempotency-Key header is required"


class IdempotencyKeyInvalid(DomainError):
    status = 400
    type_slug = "idempotency-key-invalid"
    title = "Idempotency-Key header is invalid"


class IdempotencyKeyReused(DomainError):
    status = 422
    type_slug = "idempotency-key-reused"
    title = "Idempotency-Key was already used with a different payload"


class RequestInProgress(DomainError):
    status = 409
    type_slug = "request-in-progress"
    title = "A request with this Idempotency-Key is still being processed"

    def headers(self) -> dict[str, str]:
        return {"Retry-After": "1"}


class PostingNotFound(DomainError):
    status = 404
    type_slug = "posting-not-found"
    title = "Posting not found"


class PostingAlreadyReversed(DomainError):
    status = 409
    type_slug = "posting-already-reversed"
    title = "Posting has already been reversed"


class AppendOnlyViolation(DomainError):
    status = 500
    type_slug = "append-only-violation"
    title = "Attempted to rewrite append-only history"


class CursorInvalid(DomainError):
    status = 400
    type_slug = "cursor-invalid"
    title = "Pagination cursor is invalid"


class PostingInvalid(DomainError):
    status = 422
    type_slug = "posting-invalid"
    title = "The proposed entries do not satisfy the ledger invariants"

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons), reasons=reasons)
        self.reasons = reasons
