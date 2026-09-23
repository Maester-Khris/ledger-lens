import pytest
from alembic import command

from app import config
from app.ledger.db import make_session_factory
from tests.support import alembic_config, reset_schema


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
