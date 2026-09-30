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
