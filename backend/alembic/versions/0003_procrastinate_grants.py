"""Grant the application role access to Procrastinate-owned objects.

Revision ID: 0003_procrastinate_grants
Revises: 0002_grants
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_procrastinate_grants"
down_revision: str | None = "0002_grants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        r"""
        DO $grants$
        DECLARE
            obj record;
        BEGIN
            FOR obj IN
                SELECT namespace.nspname AS schema_name, relation.relname AS object_name
                FROM pg_class AS relation
                JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'public'
                  AND relation.relkind IN ('r', 'p')
                  AND relation.relname LIKE 'procrastinate\_%' ESCAPE '\'
            LOOP
                EXECUTE format(
                    'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE %I.%I TO cds_app',
                    obj.schema_name,
                    obj.object_name
                );
            END LOOP;

            FOR obj IN
                SELECT namespace.nspname AS schema_name, relation.relname AS object_name
                FROM pg_class AS relation
                JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'public'
                  AND relation.relkind = 'S'
                  AND relation.relname LIKE 'procrastinate\_%' ESCAPE '\'
            LOOP
                EXECUTE format(
                    'GRANT USAGE, SELECT, UPDATE ON SEQUENCE %I.%I TO cds_app',
                    obj.schema_name,
                    obj.object_name
                );
            END LOOP;

            FOR obj IN
                SELECT
                    namespace.nspname AS schema_name,
                    procedure.proname AS object_name,
                    pg_get_function_identity_arguments(procedure.oid) AS identity_arguments
                FROM pg_proc AS procedure
                JOIN pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
                WHERE namespace.nspname = 'public'
                  AND procedure.proname LIKE 'procrastinate\_%' ESCAPE '\'
            LOOP
                EXECUTE format(
                    'GRANT EXECUTE ON FUNCTION %I.%I(%s) TO cds_app',
                    obj.schema_name,
                    obj.object_name,
                    obj.identity_arguments
                );
            END LOOP;
        END
        $grants$;
        """
    )


def downgrade() -> None:
    op.execute(
        r"""
        DO $grants$
        DECLARE
            obj record;
        BEGIN
            FOR obj IN
                SELECT namespace.nspname AS schema_name, relation.relname AS object_name
                FROM pg_class AS relation
                JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'public'
                  AND relation.relkind IN ('r', 'p')
                  AND relation.relname LIKE 'procrastinate\_%' ESCAPE '\'
            LOOP
                EXECUTE format(
                    'REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLE %I.%I FROM cds_app',
                    obj.schema_name,
                    obj.object_name
                );
            END LOOP;

            FOR obj IN
                SELECT namespace.nspname AS schema_name, relation.relname AS object_name
                FROM pg_class AS relation
                JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'public'
                  AND relation.relkind = 'S'
                  AND relation.relname LIKE 'procrastinate\_%' ESCAPE '\'
            LOOP
                EXECUTE format(
                    'REVOKE USAGE, SELECT, UPDATE ON SEQUENCE %I.%I FROM cds_app',
                    obj.schema_name,
                    obj.object_name
                );
            END LOOP;

            FOR obj IN
                SELECT
                    namespace.nspname AS schema_name,
                    procedure.proname AS object_name,
                    pg_get_function_identity_arguments(procedure.oid) AS identity_arguments
                FROM pg_proc AS procedure
                JOIN pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
                WHERE namespace.nspname = 'public'
                  AND procedure.proname LIKE 'procrastinate\_%' ESCAPE '\'
            LOOP
                EXECUTE format(
                    'REVOKE EXECUTE ON FUNCTION %I.%I(%s) FROM cds_app',
                    obj.schema_name,
                    obj.object_name,
                    obj.identity_arguments
                );
            END LOOP;
        END
        $grants$;
        """
    )
