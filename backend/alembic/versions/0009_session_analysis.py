"""Official analysis window and manual annotations; original samples are untouched."""

import sqlalchemy as sa

from alembic import op

revision = "0009_session_analysis"
down_revision = "0008_session_metadata"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns("measurement_sessions")}
    for name, type_ in [
        ("analysis_start", sa.DateTime(timezone=True)),
        ("analysis_end", sa.DateTime(timezone=True)),
        ("analysis_label", sa.String(120)),
        ("analysis_selected_by", sa.Integer()),
        ("analysis_selected_at", sa.DateTime(timezone=True)),
    ]:
        if name in columns:
            continue
        if name == "analysis_selected_by" and op.get_bind().dialect.name == "sqlite":
            # SQLite supports a nullable inline REFERENCES column without rebuilding
            # the session table (which has historical samples with cascading FKs).
            op.execute(
                "ALTER TABLE measurement_sessions ADD COLUMN analysis_selected_by "
                "INTEGER CONSTRAINT fk_analysis_selected_by REFERENCES users(id)"
            )
        else:
            op.add_column("measurement_sessions", sa.Column(name, type_, nullable=True))
            if name == "analysis_selected_by":
                op.create_foreign_key(
                    "fk_analysis_selected_by", "measurement_sessions", "users", [name], ["id"]
                )
    if "session_annotations" not in inspector.get_table_names():
        op.create_table(
            "session_annotations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "session_id",
                sa.Integer(),
                sa.ForeignKey("measurement_sessions.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("kind", sa.String(32), nullable=False),
            sa.Column("title", sa.String(160), nullable=False),
            sa.Column("description", sa.Text()),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_session_annotations_session_id", "session_annotations", ["session_id"])


def downgrade():
    bind = op.get_bind()
    columns = [
        "analysis_start",
        "analysis_end",
        "analysis_label",
        "analysis_selected_by",
        "analysis_selected_at",
    ]
    if bind.dialect.name == "sqlite":
        # Alembic's isolated SQLite connection uses FK enforcement off. Refuse to
        # rebuild under cascading FK enforcement rather than risk historical rows.
        if bind.exec_driver_sql("PRAGMA foreign_keys").scalar():
            raise RuntimeError(
                "SQLite downgrade requires an isolated connection with foreign_keys=OFF"
            )
        op.drop_table("session_annotations")
        with op.batch_alter_table(
            "measurement_sessions",
            naming_convention={"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"},
        ) as batch:
            foreign_keys = sa.inspect(bind).get_foreign_keys("measurement_sessions")
            constraint = next(
                fk for fk in foreign_keys if fk["constrained_columns"] == ["analysis_selected_by"]
            )
            batch.drop_constraint(
                constraint["name"] or "fk_measurement_sessions_analysis_selected_by_users",
                type_="foreignkey",
            )
            for name in columns:
                batch.drop_column(name)
    else:
        op.drop_table("session_annotations")
        op.drop_constraint("fk_analysis_selected_by", "measurement_sessions", type_="foreignkey")
        for name in columns:
            op.drop_column("measurement_sessions", name)
