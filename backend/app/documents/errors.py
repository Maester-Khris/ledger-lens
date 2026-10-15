from app.errors import DomainError


class UploadRejected(DomainError):
    status = 422
    type_slug = "upload-rejected"
    title = "The uploaded file was rejected"


class DocumentNotFound(DomainError):
    status = 404
    type_slug = "document-not-found"
    title = "Document not found"


class VersionNotFound(DomainError):
    status = 404
    type_slug = "version-not-found"
    title = "Document version not found"
