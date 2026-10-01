class DomainError(Exception):
    """An expected business error that the API renders as RFC 9457 problem+json."""

    status: int = 500
    type_slug: str = "internal-error"
    title: str = "Internal error"

    def __init__(self, detail: str, **extensions: object) -> None:
        super().__init__(detail)
        self.detail = detail
        self.extensions = extensions

    def headers(self) -> dict[str, str]:
        return {}




class GuestRequired(DomainError):
    """Demo mode: a decision needs a known guest, so it can never fall through to the shared tables."""

    status = 400
    type_slug = "guest-required"
    title = "A known guest is required"


class RateLimited(DomainError):
    """Public demo: a guest or an IP asked too many questions within the window (P3)."""

    status = 429
    type_slug = "rate-limited"
    title = "Too many questions"

    def __init__(self, retry_after: int) -> None:
        super().__init__(f"Too many questions for now; try again in {retry_after} seconds.", retry_after=retry_after)
        self.retry_after = retry_after

    def headers(self) -> dict[str, str]:
        return {"Retry-After": str(self.retry_after)}
