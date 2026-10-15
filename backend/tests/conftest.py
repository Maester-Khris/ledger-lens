from fastapi.testclient import TestClient

import pytest
from alembic import command

from app import config
from app.ledger.db import make_session_factory
from tests.support import alembic_config, make_tenant, reset_schema


@pytest.fixture(scope="session")
def migrated_test_database() -> None:
    # Rebuilt once per session. Tests never clean up (the app role can't DELETE);
    # they isolate themselves with unique ids and a per-test tenant instead.
    reset_schema(config.TEST_OWNER_DATABASE_URL)
    command.upgrade(alembic_config(config.TEST_OWNER_DATABASE_URL), "head")


@pytest.fixture(scope="session")
def session_factory(migrated_test_database):
    return make_session_factory(config.TEST_DATABASE_URL)


@pytest.fixture(scope="session")
def owner_session_factory(migrated_test_database):
    return make_session_factory(config.TEST_OWNER_DATABASE_URL)


@pytest.fixture()
def db_session(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def owner_session(owner_session_factory):
    session = owner_session_factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def tenant_id(db_session):
    """A fresh tenant per test, so assertions never see other tests' rows."""
    return make_tenant(db_session)

@pytest.fixture()
def client(session_factory, tenant_id):
    from app.deps import get_session, get_tenant_id
    from app.main import app

    def test_session():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = test_session
    app.dependency_overrides[get_tenant_id] = lambda: tenant_id
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


from cryptography.fernet import Fernet  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def document_settings(tmp_path_factory):
    """Per-run secrets and store dir: tests never touch real keys or backend/var."""
    config.PII_HMAC_KEY = "test-hmac-key-" + "0" * 32
    config.PII_VAULT_KEY = Fernet.generate_key().decode()
    config.DOCUMENT_STORE_DIR = tmp_path_factory.mktemp("document-store")
    return config.DOCUMENT_STORE_DIR


@pytest.fixture(autouse=True)
def disable_tracing(monkeypatch, request):
    if "enable_tracing" in request.keywords:
        return
    monkeypatch.setattr("app.tracing.get_tracing_handler", lambda: None)
    monkeypatch.setattr("app.tracing.flush_tracing", lambda: None)
    monkeypatch.setattr("app.assistant.service.get_tracing_handler", lambda: None, raising=False)
    monkeypatch.setattr("app.contracts.extract.get_tracing_handler", lambda: None, raising=False)


@pytest.fixture(autouse=True)
def dense_floor_off(monkeypatch, request):
    """Unit tests use 8-dimension fake embeddings whose cosine scores mean nothing, so the dense floor is off, except in
    the gate tests (which set it) and in the eval (real embeddings, real threshold)."""
    if "eval" in request.keywords:
        return
    monkeypatch.setattr(config, "MIN_DENSE_SIMILARITY", -1.0)
