from logging.config import fileConfig

from alembic import context
from sqlmodel import SQLModel

from app.core.config import settings

# Import every model module so SQLModel.metadata is fully populated
# before autogenerate compares it against the database.
from app.models import *  # noqa: F401,F403

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata

# The database URL is taken directly from settings rather than routed
# through config.set_main_option()/get_main_option() — those round-trip the
# value through configparser's string interpolation, which chokes on a
# literal "%" (e.g. a URL-encoded "%40" in a password).
DATABASE_URL = settings.database_url


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    from sqlalchemy import create_engine, pool

    connectable = create_engine(DATABASE_URL, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
