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
