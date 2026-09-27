from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.problem import install_problem_handlers
from app.routes import health, postings, fee_runs, tool_invocations, gl_exports, documents, chat, reviews, stats, guests
from app.tracing import flush_tracing

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    flush_tracing()

app = FastAPI(title="Fintech Ledger + Document Intelligence", lifespan=lifespan)
install_problem_handlers(app)

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
