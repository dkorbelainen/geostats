"""clear invalid unicode/slash slugs

Revision ID: 008
Revises: 007
Create Date: 2026-05-05
"""

from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE accounts SET slug = NULL
        WHERE slug IS NOT NULL
          AND slug !~ '^[a-z0-9_а-яё-]+$'
    """)


def downgrade() -> None:
    pass
