from app.errors import DomainError


class InvocationNotFound(DomainError):
    status = 404
    type_slug = "invocation-not-found"
    title = "Tool invocation not found"


class NotCritical(DomainError):
    status = 422
    type_slug = "not-critical"
    title = "Only critical tool results (ones that would post to the ledger) take a decision"


class AlreadyDecided(DomainError):
    status = 409
    type_slug = "already-decided"
    title = "This tool invocation has already been decided"