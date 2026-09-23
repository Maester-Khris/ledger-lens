from app.errors import DomainError


class ContractNotComparable(DomainError):
    status = 422
    type_slug = "contract-not-comparable"
    title = "This contract can't be compared with billing yet"
