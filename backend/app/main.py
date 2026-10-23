from contextlib import asynccontextmanager
import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import config
from app.problem import install_problem_handlers
from app.routes import health, postings, fee_runs, tool_invocations, gl_exports, documents, chat, reviews, stats, guests, contract_terms, document_timeline
from app.tracing import flush_tracing

from app.sentry_scrub import scrub_event

# ponytail: no traces and no PII (chat text and guest ids stay out of events); the dashboard scrubber is the second layer.
if config.SENTRY_DSN:
    sentry_sdk.init(
        dsn=config.SENTRY_DSN,
        environment=config.SENTRY_ENVIRONMENT,
        send_default_pii=False,
        before_send=scrub_event,
    )

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    flush_tracing()

def install_cors(app: FastAPI, origins: list[str]) -> None:
    """Direct browser calls from the Vercel frontend. No origins configured means no middleware."""
    if not origins:
        return
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        # Content-Type/X-Guest-Id/Idempotency-Key are sent by api.ts; Range is sent by pdf.js.
        allow_headers=["Content-Type", "X-Guest-Id", "Idempotency-Key", "Range"],
        expose_headers=["Accept-Ranges", "Content-Range", "Content-Length", "ETag"],
        max_age=600,
    )

SECURITY_HEADERS = [(b"x-content-type-options", b"nosniff"), (b"cross-origin-resource-policy", b"same-origin")]


class SecurityHeaders:
    """N8 S4a: nosniff and CORP on every response. Plain ASGI, so the chat's SSE stream is not buffered or wrapped.
    CORP covers no-cors loads only: the frontend's fetches (CORS) and page links (navigations) are unaffected."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", []), *SECURITY_HEADERS]
            await send(message)

        await self.app(scope, receive, send_with_headers)


def install_security_headers(app: FastAPI) -> None:
    app.add_middleware(SecurityHeaders)


app = FastAPI(title="Fintech Ledger + Document Intelligence", lifespan=lifespan)
install_problem_handlers(app)
install_cors(app, config.FRONTEND_ORIGINS)
install_security_headers(app)

# Reads and the two decision routes: mounted in every mode.
ROUTERS = (
    health.router, postings.router, fee_runs.router, tool_invocations.router, reviews.router, gl_exports.router,
    documents.router, chat.router, stats.router, guests.router, contract_terms.router, document_timeline.router,
)
# Public writes to shared state (corpus, ledger, billing, exports): not mounted in the public demo.
WRITE_ROUTERS = (documents.write_router, postings.write_router, fee_runs.write_router, gl_exports.write_router)


def include_routes(app: FastAPI, *, demo_mode: bool) -> None:
    for router in ROUTERS:
        app.include_router(router)
    if not demo_mode:
        for router in WRITE_ROUTERS:
            app.include_router(router)


include_routes(app, demo_mode=config.DEMO_MODE)
