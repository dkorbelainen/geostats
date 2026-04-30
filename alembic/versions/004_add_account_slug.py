"""add slug column to accounts

Revision ID: 004
Revises: 003
Create Date: 2026-04-30
"""

import sqlalchemy as sa
from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("slug", sa.Text(), nullable=True))
    op.execute("""
        WITH ranked AS (
            SELECT id,
                   lower(nick) AS base_slug,
                   ROW_NUMBER() OVER (PARTITION BY lower(nick) ORDER BY created_at) AS rn
            FROM accounts
        )
        UPDATE accounts
        SET slug = CASE WHEN ranked.rn = 1 THEN ranked.base_slug
                        ELSE ranked.base_slug || ranked.rn::text END
        FROM ranked
        WHERE accounts.id = ranked.id
    """)
    op.create_unique_constraint("uq_accounts_slug", "accounts", ["slug"])


def downgrade() -> None:
    op.drop_constraint("uq_accounts_slug", "accounts", type_="unique")
    op.drop_column("accounts", "slug")
