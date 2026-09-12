"""Make the programme say how many disciplines it enrols a student in.

Revision ID: 0017_program_structure
Revises: 0016_academic_standing

A dual major was two booleans on the profile beside a secondary programme id,
which let the row contradict itself and left every rule naming a branch column
directly.  The programme carries the structure instead: a student is in one
programme, and "BTech Dual Major" is a programme the office admits them into.

The upgrade mints one combined programme per (programme, structure) pair the
data actually holds -- never a catalogue of every pair that could exist -- and
repoints the profiles that were describing themselves with the flags.  Profiles
with no programme are left exactly as they are; nothing here guesses one.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017_program_structure"
down_revision: str | None = "0016_academic_standing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "programs",
        sa.Column("structure", sa.Text(), nullable=False, server_default="single"),
    )
    op.add_column(
        "programs",
        sa.Column("primary_degree_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "programs",
        sa.Column("secondary_degree_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_programs_primary_degree_id_programs",
        "programs", "programs", ["primary_degree_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_programs_secondary_degree_id_programs",
        "programs", "programs", ["secondary_degree_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_programs_structure", "programs",
        "structure IN ('single', 'dual_major', 'dual_degree')",
    )
    op.create_check_constraint(
        "ck_programs_structure_components", "programs",
        "(structure = 'single') = "
        "(primary_degree_id IS NULL AND secondary_degree_id IS NULL)",
    )

    connection = op.get_bind()

    # One combined programme per dual-major base degree that profiles use.
    connection.execute(sa.text("""
        INSERT INTO programs (id, name, is_active, structure,
                              primary_degree_id, secondary_degree_id, updated_at)
        SELECT gen_random_uuid(), base.name || ' Dual Major', true, 'dual_major',
               base.id, base.id, now()
        FROM (
            SELECT DISTINCT p.program_id AS id FROM profiles p
            WHERE p.is_dual_major AND p.program_id IS NOT NULL
        ) used
        JOIN programs base ON base.id = used.id
        ON CONFLICT (name) DO NOTHING
    """))

    # One per (undergraduate, postgraduate) dual-degree pair that profiles use.
    connection.execute(sa.text("""
        INSERT INTO programs (id, name, is_active, structure,
                              primary_degree_id, secondary_degree_id, updated_at)
        SELECT gen_random_uuid(),
               ug.name || E'–' || pg.name || ' Dual Degree', true, 'dual_degree',
               ug.id, pg.id, now()
        FROM (
            SELECT DISTINCT p.program_id AS ug_id, p.secondary_program_id AS pg_id
            FROM profiles p
            WHERE p.is_dual_degree
              AND p.program_id IS NOT NULL
              AND p.secondary_program_id IS NOT NULL
        ) used
        JOIN programs ug ON ug.id = used.ug_id
        JOIN programs pg ON pg.id = used.pg_id
        ON CONFLICT (name) DO NOTHING
    """))

    connection.execute(sa.text("""
        UPDATE profiles p SET program_id = combined.id
        FROM programs combined
        WHERE p.is_dual_major
          AND combined.structure = 'dual_major'
          AND combined.primary_degree_id = p.program_id
    """))
    connection.execute(sa.text("""
        UPDATE profiles p SET program_id = combined.id
        FROM programs combined
        WHERE p.is_dual_degree
          AND combined.structure = 'dual_degree'
          AND combined.primary_degree_id = p.program_id
          AND combined.secondary_degree_id = p.secondary_program_id
    """))

    # A combined programme offers the disciplines its component degrees do, so
    # the branch a student already holds stays valid against their new one.
    connection.execute(sa.text("""
        INSERT INTO program_branches (id, program_id, branch_id, created_at)
        SELECT gen_random_uuid(), combined.id, pb.branch_id, now()
        FROM programs combined
        JOIN program_branches pb
          ON pb.program_id IN (combined.primary_degree_id, combined.secondary_degree_id)
        WHERE combined.structure <> 'single'
        ON CONFLICT (program_id, branch_id) DO NOTHING
    """))

    # Every profile whose dual enrollment this migration could not carry across,
    # including the ones that never named a programme: dropping the flags would
    # be the only record of them, and a combined programme cannot be built from
    # a postgraduate half alone. Refuse rather than lose the fact.
    stranded = connection.scalar(sa.text(
        "SELECT count(*) FROM profiles "
        "WHERE (is_dual_major OR is_dual_degree) "
        "AND (program_id IS NULL OR program_id NOT IN "
        "(SELECT id FROM programs WHERE structure <> 'single'))"
    ))
    if stranded:
        raise RuntimeError(
            f"{stranded} dual profile(s) could not be repointed at a combined "
            "programme -- most likely they name no programme at all. Record "
            "their programme first; nothing here has been dropped."
        )

    op.drop_constraint("ck_profiles_secondary_branch_kind", "profiles", type_="check")
    op.drop_constraint("ck_profiles_dual_degree_program", "profiles", type_="check")
    op.drop_constraint("ck_profiles_one_dual_kind", "profiles", type_="check")
    op.drop_column("profiles", "secondary_program_id")
    op.drop_column("profiles", "is_dual_degree")
    op.drop_column("profiles", "is_dual_major")


def downgrade() -> None:
    op.add_column(
        "profiles",
        sa.Column("is_dual_major", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "profiles",
        sa.Column("is_dual_degree", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("profiles", sa.Column("secondary_program_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_profiles_secondary_program_id_programs",
        "profiles", "programs", ["secondary_program_id"], ["id"], ondelete="RESTRICT",
    )

    connection = op.get_bind()
    connection.execute(sa.text("""
        UPDATE profiles p
        SET is_dual_major = (combined.structure = 'dual_major'),
            is_dual_degree = (combined.structure = 'dual_degree'),
            program_id = combined.primary_degree_id,
            secondary_program_id = CASE
                WHEN combined.structure = 'dual_degree' THEN combined.secondary_degree_id
            END
        FROM programs combined
        WHERE combined.id = p.program_id AND combined.structure <> 'single'
    """))

    op.create_check_constraint(
        "ck_profiles_one_dual_kind", "profiles", "NOT (is_dual_major AND is_dual_degree)"
    )
    op.create_check_constraint(
        "ck_profiles_dual_degree_program", "profiles",
        "is_dual_degree = (secondary_program_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_profiles_secondary_branch_kind", "profiles",
        "secondary_branch_id IS NULL OR is_dual_major OR is_dual_degree",
    )

    # The combined programmes themselves are left in place: a job rule may name
    # one, and dropping a programme a rule references would break that rule
    # silently. They are inert once no profile points at them.
    op.drop_constraint("ck_programs_structure_components", "programs", type_="check")
    op.drop_constraint("ck_programs_structure", "programs", type_="check")
    op.drop_constraint("fk_programs_secondary_degree_id_programs", "programs", type_="foreignkey")
    op.drop_constraint("fk_programs_primary_degree_id_programs", "programs", type_="foreignkey")
    op.drop_column("programs", "secondary_degree_id")
    op.drop_column("programs", "primary_degree_id")
    op.drop_column("programs", "structure")
