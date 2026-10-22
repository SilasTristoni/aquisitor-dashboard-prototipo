from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool, text

from alembic import context
from app.core.config import get_settings
from app.core.database import Base
from app.models import entities  # noqa: F401
from app.services import company_identity  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        if connection.dialect.name == "postgresql":
            # Historical revision 0006 already exceeds Alembic's default VARCHAR(32).
            # Widen migration bookkeeping before replaying the existing revision chain.
            connection.execute(text(
                "CREATE TABLE IF NOT EXISTS alembic_version "
                "(version_num VARCHAR(128) NOT NULL PRIMARY KEY)"
            ))
            connection.execute(text(
                "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)"
            ))
            connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_offline() if context.is_offline_mode() else run_migrations_online()
