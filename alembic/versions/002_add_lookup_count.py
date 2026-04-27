"""add lookup_count to accounts

Revision ID: 002
Revises: 001
Create Date: 2026-04-27
"""

import sqlalchemy as sa
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("lookup_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("accounts", "lookup_count")
