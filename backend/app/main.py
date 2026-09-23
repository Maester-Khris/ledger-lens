from fastapi import FastAPI

from app.problem import install_problem_handlers
from app.routes import health, postings, fee_runs, tool_invocations

app = FastAPI(title="Fintech Ledger + Document Intelligence")
install_problem_handlers(app)

app.include_router(health.router)
app.include_router(postings.router)
app.include_router(fee_runs.router)
app.include_router(tool_invocations.router)
