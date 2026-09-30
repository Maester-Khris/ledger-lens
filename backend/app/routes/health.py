from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.deps import get_session
from app.ledger import dao

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness only, so a database blip never fails the deploy check or restarts the container."""
    return {"status": "ok"}


# ponytail: only Postgres is checked; OpenAI and Pinecone pings would cost money and flake.
@router.get("/health/db")
def health_db(session: Annotated[Session, Depends(get_session)]):
    try:
        dao.ping(session)
    except SQLAlchemyError:
        return JSONResponse({"status": "unavailable", "database": "down"}, status_code=503)
    return {"status": "ok", "database": "ok"}
