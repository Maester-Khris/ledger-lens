from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import config
from app.problem import install_problem_handlers
from app.routes import health, postings, fee_runs, tool_invocations, gl_exports, documents, chat, reviews, stats, guests, contract_terms, document_timeline
from app.tracing import flush_tracing

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

app = FastAPI(title="Fintech Ledger + Document Intelligence", lifespan=lifespan)
install_problem_handlers(app)
install_cors(app, config.FRONTEND_ORIGINS)

app.include_router(health.router)
app.include_router(postings.router)
app.include_router(fee_runs.router)
app.include_router(tool_invocations.router)
app.include_router(reviews.router)
app.include_router(gl_exports.router)
app.include_router(documents.router)
app.include_router(chat.router)
app.include_router(stats.router)
app.include_router(guests.router)
app.include_router(contract_terms.router)
app.include_router(document_timeline.router)
