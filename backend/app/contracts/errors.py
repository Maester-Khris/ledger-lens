from app.errors import DomainError


class ContractNotComparable(DomainError):
    status = 422
    type_slug = "contract-not-comparable"
    title = "This contract can't be compared with billing yet"

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
