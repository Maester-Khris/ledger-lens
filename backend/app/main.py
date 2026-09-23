from fastapi import FastAPI

from app.problem import install_problem_handlers
from app.routes import health, postings

app = FastAPI(title="Fintech Ledger + Document Intelligence")
install_problem_handlers(app)

app.include_router(health.router)
app.include_router(postings.router)
