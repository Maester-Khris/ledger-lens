
from app.errors import DomainError


class HouseholdNotFound(DomainError):
    status = 404
    type_slug = "household-not-found"
    title = "Household not found"


class NoScheduleAssigned(DomainError):
    status = 422
    type_slug = "no-schedule-assigned"
    title = "No fee schedule applies to this household and period"


class MissingValuation(DomainError):
    status = 422
    type_slug = "missing-valuation"
    title = "A period-end valuation is missing"


class NothingToBill(DomainError):
    status = 422
    type_slug = "nothing-to-bill"
    title = "The household has no billable value in this period"


class AlreadyBilled(DomainError):
    status = 422
    type_slug = "already-billed"
    title = "The household is already billed for this period with different inputs"


class FeeCalculationNotFound(DomainError):
    status = 404
    type_slug = "fee-calculation-not-found"
    title = "Fee calculation not found"
