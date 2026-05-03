"""add account_anomalies table

Revision ID: 007
Revises: 006
Create Date: 2026-05-03
"""

import sqlalchemy as sa
from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_anomalies",
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("confidence_pct", sa.SmallInteger(), nullable=False),
        sa.Column("driver_1_feature", sa.Text(), nullable=False),
        sa.Column("driver_1_z", sa.Float(), nullable=False),
        sa.Column("driver_2_feature", sa.Text(), nullable=True),
        sa.Column("driver_2_z", sa.Float(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("account_id"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_account_anomalies_confidence_pct",
        "account_anomalies",
        ["confidence_pct"],
        postgresql_using="btree",
    )


def downgrade() -> None:
    op.drop_index("ix_account_anomalies_confidence_pct", table_name="account_anomalies")
    op.drop_table("account_anomalies")
