"""Optional result selections and independent portal origin; old shares stay local."""

import sqlalchemy as sa

from alembic import op

revision = "0011_share_result_options"
down_revision = "0010_session_shares"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("session_shares")}
    for name, kind in [("report_options", sa.JSON()), ("portal_origin", sa.String(512))]:
        if name not in columns:
            op.add_column("session_shares", sa.Column(name, kind, nullable=True))


def downgrade():
    op.drop_column("session_shares", "portal_origin")
    op.drop_column("session_shares", "report_options")
