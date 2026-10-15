from app.deps import get_session
from app.main import app


def test_health_is_liveness_only(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_health_db_ok(client):
    assert client.get("/health/db").json() == {"status": "ok", "database": "ok"}


def test_health_db_503_when_database_is_down(client):
    class Broken:
        def execute(self, *_):
            from sqlalchemy.exc import OperationalError
            raise OperationalError("SELECT 1", {}, Exception("down"))

        def close(self) -> None: ...

    app.dependency_overrides[get_session] = lambda: Broken()
    response = client.get("/health/db")
    assert response.status_code == 503 and response.json()["database"] == "down"
    assert client.get("/health").status_code == 200  # liveness unaffected
