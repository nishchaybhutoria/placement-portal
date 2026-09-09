"""Add override scope combinations and split/add rule domains.

Revision ID: 0015_override_scope_domains
Revises: 0014_audit_log_order

the design review sections 4.52-4.53 make two related changes to the same table.  The
four nullable target columns now admit exactly six combinations, enforced in
the database.  The old edit/withdraw domain is split without narrowing any
live authority: the old row keeps its id as ``edit_window`` and an otherwise
identical ``withdraw_window`` twin gets a new id.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015_override_scope_domains"
down_revision: str | None = "0014_audit_log_order"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCOPE_CHECK = """
    (cycle_id IS NOT NULL AND job_id IS NULL
        AND enrollment_id IS NULL AND application_id IS NULL)
    OR (cycle_id IS NULL AND job_id IS NOT NULL
        AND enrollment_id IS NULL AND application_id IS NULL)
    OR (cycle_id IS NULL AND job_id IS NULL
        AND enrollment_id IS NOT NULL AND application_id IS NULL)
    OR (cycle_id IS NOT NULL AND job_id IS NULL
        AND enrollment_id IS NOT NULL AND application_id IS NULL)
    OR (cycle_id IS NULL AND job_id IS NOT NULL
        AND enrollment_id IS NOT NULL AND application_id IS NULL)
    OR (cycle_id IS NULL AND job_id IS NULL
        AND enrollment_id IS NULL AND application_id IS NOT NULL)
"""

_NEW_DOMAINS = (
    "eligibility",
    "application_deadline",
    "edit_window",
    "withdraw_window",
    "outcome_gate",
    "offer_cap",
    "offer_deadline",
    "cycle_registration_window",
    "cycle_join_rule",
)

_OLD_DOMAINS = (
    "eligibility",
    "application_deadline",
    "edit_withdraw_window",
    "outcome_gate",
    "offer_cap",
    "offer_deadline",
)


def _create_enum(name: str, values: tuple[str, ...]) -> None:
    labels = ", ".join(f"'{value}'" for value in values)
    op.execute(f"CREATE TYPE {name} AS ENUM ({labels})")


def upgrade() -> None:
    op.execute("LOCK TABLE overrides IN ACCESS EXCLUSIVE MODE")
    op.execute("ALTER TYPE rule_domain_t RENAME TO rule_domain_t_pre_0015")
    _create_enum("rule_domain_t", _NEW_DOMAINS)
    op.execute(
        """
        ALTER TABLE overrides
        ALTER COLUMN rule_domain TYPE rule_domain_t
        USING (
            CASE
                WHEN rule_domain::text = 'edit_withdraw_window' THEN 'edit_window'
                ELSE rule_domain::text
            END
        )::rule_domain_t
        """
    )
    op.execute("DROP TYPE rule_domain_t_pre_0015")

    op.execute(
        """
        INSERT INTO overrides (
            id, created_at, updated_at, rule_domain, allow,
            cycle_id, job_id, enrollment_id, application_id,
            reason, granted_by, expires_at, is_active
        )
        SELECT
            gen_random_uuid(), created_at, updated_at, 'withdraw_window', allow,
            cycle_id, job_id, enrollment_id, application_id,
            reason, granted_by, expires_at, is_active
        FROM overrides
        WHERE rule_domain = 'edit_window'
        """
    )
    op.create_check_constraint(
        "ck_overrides_scope_combination", "overrides", _SCOPE_CHECK
    )


def downgrade() -> None:
    op.execute("LOCK TABLE overrides IN ACCESS EXCLUSIVE MODE")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM overrides
                WHERE rule_domain IN (
                    'cycle_registration_window', 'cycle_join_rule'
                )
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade while cycle-join override rows exist';
            END IF;
        END
        $$
        """
    )
    op.drop_constraint(
        "ck_overrides_scope_combination", "overrides", type_="check"
    )
    op.execute("ALTER TYPE rule_domain_t RENAME TO rule_domain_t_post_0015")
    _create_enum("rule_domain_t", _OLD_DOMAINS)
    op.execute(
        """
        ALTER TABLE overrides
        ALTER COLUMN rule_domain TYPE rule_domain_t
        USING (
            CASE
                WHEN rule_domain::text IN ('edit_window', 'withdraw_window')
                    THEN 'edit_withdraw_window'
                ELSE rule_domain::text
            END
        )::rule_domain_t
        """
    )
    op.execute("DROP TYPE rule_domain_t_post_0015")
