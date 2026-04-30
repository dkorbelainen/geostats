"""add avatar_url column to accounts

Revision ID: 005
Revises: 004
Create Date: 2026-04-30
"""

import sqlalchemy as sa
from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("avatar_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("accounts", "avatar_url")
