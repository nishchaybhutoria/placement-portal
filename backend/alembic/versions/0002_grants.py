"""Create the application role and enforce append-only history grants.

Revision ID: 0002_grants
Revises: 0001_schema
"""

import os
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_grants"
down_revision: str | None = "0001_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    app_password = os.environ.get("CDS_APP_DB_PASSWORD")
    if not app_password:
        raise RuntimeError("CDS_APP_DB_PASSWORD is required to create the cds_app login role")

    op.execute(
        """
        DO $role$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cds_app') THEN
                CREATE ROLE cds_app LOGIN;
            END IF;
        END
        $role$;
        """
    )

    bind = op.get_bind()
    quoted_password = bind.execute(
        sa.text("SELECT quote_literal(:password)"), {"password": app_password}
    ).scalar_one()
    op.execute(f"ALTER ROLE cds_app WITH LOGIN PASSWORD {quoted_password}")

    op.execute("GRANT USAGE ON SCHEMA public TO cds_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO cds_app")
    op.execute("GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO cds_app")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO cds_app"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO cds_app"
    )

    for table_name in ("application_events", "audit_log"):
        op.execute(f"REVOKE ALL PRIVILEGES ON TABLE {table_name} FROM cds_app")
        op.execute(f"GRANT SELECT, INSERT ON TABLE {table_name} TO cds_app")


def downgrade() -> None:
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM cds_app"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE USAGE, SELECT, UPDATE ON SEQUENCES FROM cds_app"
    )
    op.execute("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM cds_app")
    op.execute("REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM cds_app")
    op.execute("REVOKE USAGE ON SCHEMA public FROM cds_app")
    op.execute("DROP ROLE IF EXISTS cds_app")
