"""Convert internal string IDs to PostgreSQL UUIDs and add foreign keys.

Revision ID: 09c1cf9d2cd9
Revises: a20ea69766f1
Create Date: 2026-08-24 00:58:45.335912
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "09c1cf9d2cd9"
down_revision: str | Sequence[str] | None = "a20ea69766f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


UUID = postgresql.UUID(as_uuid=True)


def _drop_foreign_keys_for_column(table_name: str, column_name: str) -> None:
    """Drop every FK on a table column without relying on its name."""
    connection = op.get_bind()

    constraint_names = (
        connection.execute(
            sa.text(
                """
            SELECT DISTINCT constraint_info.conname
            FROM pg_constraint AS constraint_info
            JOIN pg_class AS table_info
              ON table_info.oid = constraint_info.conrelid
            JOIN pg_namespace AS schema_info
              ON schema_info.oid = table_info.relnamespace
            JOIN unnest(constraint_info.conkey) AS key_column(attnum)
              ON TRUE
            JOIN pg_attribute AS column_info
              ON column_info.attrelid = table_info.oid
             AND column_info.attnum = key_column.attnum
            WHERE constraint_info.contype = 'f'
              AND schema_info.nspname = current_schema()
              AND table_info.relname = :table_name
              AND column_info.attname = :column_name
            """
            ),
            {
                "table_name": table_name,
                "column_name": column_name,
            },
        )
        .scalars()
        .all()
    )

    for constraint_name in constraint_names:
        op.drop_constraint(
            constraint_name,
            table_name,
            type_="foreignkey",
        )


def upgrade() -> None:
    """Convert internal identifiers to native PostgreSQL UUID columns."""

    # gen_random_uuid() is native in modern PostgreSQL and is also provided by
    # pgcrypto on older supported installations.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # Fail before changing anything if the populated UUID-string columns contain
    # invalid values. Only users and projects currently contain data.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM users
                WHERE id IS NULL
                   OR id !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            ) THEN
                RAISE EXCEPTION 'users.id contains a value that cannot be cast to UUID';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM projects
                WHERE id IS NULL
                   OR user_id IS NULL
                   OR id !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                   OR user_id !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            ) THEN
                RAISE EXCEPTION 'projects.id or projects.user_id contains a value that cannot be cast to UUID';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM projects AS project
                LEFT JOIN users AS app_user
                  ON app_user.id = project.user_id
                WHERE app_user.id IS NULL
            ) THEN
                RAISE EXCEPTION 'A project references a user that does not exist';
            END IF;
        END
        $$;
        """
    )

    # Drop constraints that couple VARCHAR parent and child columns. Constraint
    # discovery makes this migration independent of generated constraint names.
    for table_name, column_name in (
        ("subscriptions", "user_id"),
        ("projects", "user_id"),
        ("forms", "project_id"),
        ("submissions", "form_id"),
        ("integrations", "user_id"),
        ("form_integrations", "form_id"),
        ("form_integrations", "integration_id"),
    ):
        _drop_foreign_keys_for_column(table_name, column_name)

    # Parent tables and their populated foreign keys.
    op.alter_column(
        "users",
        "id",
        existing_type=sa.String(length=36),
        type_=UUID,
        existing_nullable=False,
        postgresql_using="id::uuid",
        server_default=sa.text("gen_random_uuid()"),
    )

    op.alter_column(
        "projects",
        "id",
        existing_type=sa.String(length=36),
        type_=UUID,
        existing_nullable=False,
        postgresql_using="id::uuid",
        server_default=sa.text("gen_random_uuid()"),
    )
    op.alter_column(
        "projects",
        "user_id",
        existing_type=sa.String(length=36),
        type_=UUID,
        existing_nullable=False,
        postgresql_using="user_id::uuid",
    )

    # Empty dependent tables. Explicit USING clauses are still required by
    # PostgreSQL for VARCHAR-to-UUID schema changes.
    op.alter_column(
        "subscriptions",
        "id",
        existing_type=sa.String(),
        type_=UUID,
        existing_nullable=False,
        postgresql_using="id::uuid",
        server_default=sa.text("gen_random_uuid()"),
    )
    op.alter_column(
        "subscriptions",
        "user_id",
        existing_type=sa.String(length=36),
        type_=UUID,
        existing_nullable=False,
        postgresql_using="user_id::uuid",
    )

    op.alter_column(
        "forms",
        "id",
        existing_type=sa.String(length=36),
        type_=UUID,
        existing_nullable=False,
        postgresql_using="id::uuid",
        server_default=sa.text("gen_random_uuid()"),
    )
    op.alter_column(
        "forms",
        "project_id",
        existing_type=sa.String(length=36),
        type_=UUID,
        existing_nullable=False,
        postgresql_using="project_id::uuid",
    )

    # submissions.id must be UUID before thankyoutokens is created.
    op.alter_column(
        "submissions",
        "id",
        existing_type=sa.String(length=36),
        type_=UUID,
        existing_nullable=False,
        postgresql_using="id::uuid",
        server_default=sa.text("gen_random_uuid()"),
    )
    op.alter_column(
        "submissions",
        "form_id",
        existing_type=sa.String(length=36),
        type_=UUID,
        existing_nullable=False,
        postgresql_using="form_id::uuid",
    )

    op.alter_column(
        "integrations",
        "id",
        existing_type=sa.String(length=36),
        type_=UUID,
        existing_nullable=False,
        postgresql_using="id::uuid",
        server_default=sa.text("gen_random_uuid()"),
    )
    op.alter_column(
        "integrations",
        "user_id",
        existing_type=sa.String(length=36),
        type_=UUID,
        existing_nullable=False,
        postgresql_using="user_id::uuid",
    )

    op.alter_column(
        "form_integrations",
        "id",
        existing_type=sa.String(length=36),
        type_=UUID,
        existing_nullable=False,
        postgresql_using="id::uuid",
        server_default=sa.text("gen_random_uuid()"),
    )
    op.alter_column(
        "form_integrations",
        "form_id",
        existing_type=sa.String(length=36),
        type_=UUID,
        existing_nullable=False,
        postgresql_using="form_id::uuid",
    )
    op.alter_column(
        "form_integrations",
        "integration_id",
        existing_type=sa.String(length=36),
        type_=UUID,
        existing_nullable=False,
        postgresql_using="integration_id::uuid",
    )

    op.alter_column(
        "auth_tokens",
        "user_id",
        existing_type=sa.String(),
        type_=UUID,
        existing_nullable=False,
        postgresql_using="user_id::uuid",
    )

    # overage_charges is empty. Replace its SERIAL/INTEGER primary key instead
    # of attempting an invalid INTEGER-to-UUID cast.
    op.drop_constraint(
        "overage_charges_pkey",
        "overage_charges",
        type_="primary",
    )
    op.drop_column("overage_charges", "id")
    op.add_column(
        "overage_charges",
        sa.Column(
            "id",
            UUID,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
    )
    op.create_primary_key(
        "overage_charges_pkey",
        "overage_charges",
        ["id"],
    )
    op.alter_column(
        "overage_charges",
        "subscription_id",
        existing_type=sa.String(),
        type_=UUID,
        existing_nullable=False,
        postgresql_using="subscription_id::uuid",
    )
    op.execute("DROP SEQUENCE IF EXISTS overage_charges_id_seq")

    # Recreate all UUID-compatible foreign keys.
    op.create_foreign_key(
        "subscriptions_user_id_fkey",
        "subscriptions",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "projects_user_id_fkey",
        "projects",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "forms_project_id_fkey",
        "forms",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "submissions_form_id_fkey",
        "submissions",
        "forms",
        ["form_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "integrations_user_id_fkey",
        "integrations",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "form_integrations_form_id_fkey",
        "form_integrations",
        "forms",
        ["form_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "form_integrations_integration_id_fkey",
        "form_integrations",
        "integrations",
        ["integration_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "overage_charges_subscription_id_fkey",
        "overage_charges",
        "subscriptions",
        ["subscription_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # New indexes and uniqueness rule introduced by the updated models.
    op.create_index("ix_projects_user_id", "projects", ["user_id"], unique=False)
    op.create_index("ix_forms_project_id", "forms", ["project_id"], unique=False)
    op.create_index("ix_submissions_form_id", "submissions", ["form_id"], unique=False)
    op.create_index(
        "ix_form_integrations_form_id",
        "form_integrations",
        ["form_id"],
        unique=False,
    )
    op.create_index(
        "ix_form_integrations_integration_id",
        "form_integrations",
        ["integration_id"],
        unique=False,
    )
    op.create_index(
        "ix_overage_charges_subscription_id",
        "overage_charges",
        ["subscription_id"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_form_integrations_form_integration",
        "form_integrations",
        ["form_id", "integration_id"],
    )

    # Create this table last so its UUID FK references the already-converted
    # submissions.id UUID column.
    op.create_table(
        "thankyoutokens",
        sa.Column(
            "id",
            UUID,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("submission_id", UUID, nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("used_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["submissions.id"],
            name="thankyoutokens_submission_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="thankyoutokens_pkey"),
        sa.UniqueConstraint(
            "token_hash",
            name="uq_thankyoutokens_token_hash",
        ),
    )
    op.create_index(
        "ix_thankyoutokens_submission_id",
        "thankyoutokens",
        ["submission_id"],
        unique=False,
    )


def downgrade() -> None:
    """Restore the previous VARCHAR identifier schema."""

    # Remove the newly introduced table and schema objects first.
    op.drop_index(
        "ix_thankyoutokens_submission_id",
        table_name="thankyoutokens",
    )
    op.drop_table("thankyoutokens")

    op.drop_constraint(
        "uq_form_integrations_form_integration",
        "form_integrations",
        type_="unique",
    )
    op.drop_index(
        "ix_overage_charges_subscription_id",
        table_name="overage_charges",
    )
    op.drop_index(
        "ix_form_integrations_integration_id",
        table_name="form_integrations",
    )
    op.drop_index(
        "ix_form_integrations_form_id",
        table_name="form_integrations",
    )
    op.drop_index("ix_submissions_form_id", table_name="submissions")
    op.drop_index("ix_forms_project_id", table_name="forms")
    op.drop_index("ix_projects_user_id", table_name="projects")

    # Remove UUID foreign keys before changing either side back to VARCHAR.
    for table_name, constraint_name in (
        ("overage_charges", "overage_charges_subscription_id_fkey"),
        ("form_integrations", "form_integrations_integration_id_fkey"),
        ("form_integrations", "form_integrations_form_id_fkey"),
        ("integrations", "integrations_user_id_fkey"),
        ("submissions", "submissions_form_id_fkey"),
        ("forms", "forms_project_id_fkey"),
        ("projects", "projects_user_id_fkey"),
        ("subscriptions", "subscriptions_user_id_fkey"),
    ):
        op.drop_constraint(constraint_name, table_name, type_="foreignkey")

    op.alter_column(
        "auth_tokens",
        "user_id",
        existing_type=UUID,
        type_=sa.String(),
        existing_nullable=False,
        postgresql_using="user_id::text",
    )

    op.alter_column(
        "form_integrations",
        "integration_id",
        existing_type=UUID,
        type_=sa.String(length=36),
        existing_nullable=False,
        postgresql_using="integration_id::text",
    )
    op.alter_column(
        "form_integrations",
        "form_id",
        existing_type=UUID,
        type_=sa.String(length=36),
        existing_nullable=False,
        postgresql_using="form_id::text",
    )
    op.alter_column(
        "form_integrations",
        "id",
        existing_type=UUID,
        type_=sa.String(length=36),
        existing_nullable=False,
        postgresql_using="id::text",
        server_default=None,
    )

    op.alter_column(
        "integrations",
        "user_id",
        existing_type=UUID,
        type_=sa.String(length=36),
        existing_nullable=False,
        postgresql_using="user_id::text",
    )
    op.alter_column(
        "integrations",
        "id",
        existing_type=UUID,
        type_=sa.String(length=36),
        existing_nullable=False,
        postgresql_using="id::text",
        server_default=None,
    )

    op.alter_column(
        "submissions",
        "form_id",
        existing_type=UUID,
        type_=sa.String(length=36),
        existing_nullable=False,
        postgresql_using="form_id::text",
    )
    op.alter_column(
        "submissions",
        "id",
        existing_type=UUID,
        type_=sa.String(length=36),
        existing_nullable=False,
        postgresql_using="id::text",
        server_default=None,
    )

    op.alter_column(
        "forms",
        "project_id",
        existing_type=UUID,
        type_=sa.String(length=36),
        existing_nullable=False,
        postgresql_using="project_id::text",
    )
    op.alter_column(
        "forms",
        "id",
        existing_type=UUID,
        type_=sa.String(length=36),
        existing_nullable=False,
        postgresql_using="id::text",
        server_default=None,
    )

    op.alter_column(
        "subscriptions",
        "user_id",
        existing_type=UUID,
        type_=sa.String(length=36),
        existing_nullable=False,
        postgresql_using="user_id::text",
    )
    op.alter_column(
        "subscriptions",
        "id",
        existing_type=UUID,
        type_=sa.String(),
        existing_nullable=False,
        postgresql_using="id::text",
        server_default=None,
    )

    op.alter_column(
        "projects",
        "user_id",
        existing_type=UUID,
        type_=sa.String(length=36),
        existing_nullable=False,
        postgresql_using="user_id::text",
    )
    op.alter_column(
        "projects",
        "id",
        existing_type=UUID,
        type_=sa.String(length=36),
        existing_nullable=False,
        postgresql_using="id::text",
        server_default=None,
    )

    op.alter_column(
        "users",
        "id",
        existing_type=UUID,
        type_=sa.String(length=36),
        existing_nullable=False,
        postgresql_using="id::text",
        server_default=None,
    )

    # Restore overage_charges.id to an INTEGER/SERIAL-style primary key. This
    # downgrade assigns sequential integers if rows were created after upgrade.
    op.drop_constraint(
        "overage_charges_pkey",
        "overage_charges",
        type_="primary",
    )
    op.drop_column("overage_charges", "id")
    op.add_column(
        "overage_charges",
        sa.Column("id", sa.Integer(), nullable=True),
    )
    op.execute(
        """
        WITH numbered AS (
            SELECT ctid, row_number() OVER (ORDER BY billed_at, ctid)::integer AS new_id
            FROM overage_charges
        )
        UPDATE overage_charges AS charge
        SET id = numbered.new_id
        FROM numbered
        WHERE charge.ctid = numbered.ctid
        """
    )
    op.alter_column(
        "overage_charges",
        "id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.create_primary_key(
        "overage_charges_pkey",
        "overage_charges",
        ["id"],
    )
    op.execute(
        "CREATE SEQUENCE IF NOT EXISTS overage_charges_id_seq "
        "OWNED BY overage_charges.id"
    )
    op.execute(
        """
        SELECT setval(
            'overage_charges_id_seq',
            COALESCE((SELECT MAX(id) FROM overage_charges), 0) + 1,
            false
        )
        """
    )
    op.alter_column(
        "overage_charges",
        "id",
        existing_type=sa.Integer(),
        existing_nullable=False,
        server_default=sa.text("nextval('overage_charges_id_seq'::regclass)"),
    )
    op.alter_column(
        "overage_charges",
        "subscription_id",
        existing_type=UUID,
        type_=sa.String(),
        existing_nullable=False,
        postgresql_using="subscription_id::text",
    )

    # Restore the original foreign-key relationships using VARCHAR columns.
    op.create_foreign_key(
        "subscriptions_user_id_fkey",
        "subscriptions",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "projects_user_id_fkey",
        "projects",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "forms_project_id_fkey",
        "forms",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "submissions_form_id_fkey",
        "submissions",
        "forms",
        ["form_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "integrations_user_id_fkey",
        "integrations",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "form_integrations_form_id_fkey",
        "form_integrations",
        "forms",
        ["form_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "form_integrations_integration_id_fkey",
        "form_integrations",
        "integrations",
        ["integration_id"],
        ["id"],
        ondelete="CASCADE",
    )
