import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.errors import DomainError

logger = logging.getLogger(__name__)
PROBLEM_MEDIA_TYPE = "application/problem+json"


def problem_response(
    status: int,
    type_slug: str,
    title: str,
    detail: str,
    headers: dict[str, str] | None = None,
    **extensions: object,
) -> JSONResponse:
    body = {"type": f"/problems/{type_slug}", "title": title, "status": status, "detail": detail}
    body.update(jsonable_encoder(extensions))
    return JSONResponse(body, status_code=status, media_type=PROBLEM_MEDIA_TYPE, headers=headers)


def install_problem_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError) -> JSONResponse:
        if exc.status >= 500:
            logger.error("domain error %s: %s", exc.type_slug, exc.detail)
        return problem_response(
            exc.status, exc.type_slug, exc.title, exc.detail, headers=exc.headers(), **exc.extensions
        )

    @app.exception_handler(RequestValidationError)
    async def request_invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        return problem_response(
            422, "request-invalid", "Request is invalid", "The request body or parameters are malformed.",
            errors=exc.errors(),
        )
