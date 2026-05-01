"""add player_matches table

Revision ID: 006
Revises: 005
Create Date: 2026-05-01
"""

import sqlalchemy as sa
from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "player_matches",
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("global_match_id", sa.Text(), nullable=True),
        sa.Column("global_similarity", sa.SmallInteger(), nullable=True),
        sa.Column("country_match_id", sa.Text(), nullable=True),
        sa.Column("country_similarity", sa.SmallInteger(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("account_id"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["global_match_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["country_match_id"], ["accounts.id"], ondelete="SET NULL"),
    )


def downgrade() -> None:
    op.drop_table("player_matches")
