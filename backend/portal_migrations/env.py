import os

from sqlalchemy import create_engine, pool

from alembic import context
from app.portal.models import PortalBase

url = os.environ["THERMOPOWER_PORTAL_DATABASE_URL"]
if context.is_offline_mode():
    context.configure(url=url, target_metadata=PortalBase.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=PortalBase.metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
