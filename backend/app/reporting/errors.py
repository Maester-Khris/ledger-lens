from app.errors import DomainError


class GlCodeMissing(DomainError):
    status = 422
    type_slug = "gl-code-missing"
    title = "Some accounts in this period have no GL code"


class UnknownCurrency(DomainError):
    status = 422
    type_slug = "unknown-currency"
    title = "Currency is not configured"


class GlExportNotFound(DomainError):
    status = 404
    type_slug = "gl-export-not-found"
    title = "GL export not found"


class GlExportIntegrityError(DomainError):
    status = 500
    type_slug = "gl-export-integrity"
    title = "Regenerated GL export does not match its recorded hash"