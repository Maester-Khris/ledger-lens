from alembic import command

from app import config
from tests.support import alembic_config, reset_schema


def test_migrations_upgrade_downgrade_upgrade():
    url = config.MIGRATION_ROUNDTRIP_DATABASE_URL
    reset_schema(url)
    alembic = alembic_config(url)

    command.upgrade(alembic, "head")
    command.downgrade(alembic, "base")
    command.upgrade(alembic, "head")
