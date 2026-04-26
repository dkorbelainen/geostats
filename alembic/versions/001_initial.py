"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-04-26
"""

from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("nick", sa.Text(), nullable=False),
        sa.Column("country_code", sa.Text(), nullable=True),
        sa.Column("level", sa.Integer(), nullable=True),
        sa.Column("is_pro", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("pin_url", sa.Text(), nullable=True),
        sa.Column("tracked", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.create_table(
        "rating_snapshots",
        sa.Column(
            "account_id",
            sa.Text(),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("captured_at", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("division_number", sa.Integer(), nullable=True),
        sa.Column("division_name", sa.Text(), nullable=True),
        sa.Column("rating_moving", sa.Integer(), nullable=True),
        sa.Column("rating_nomove", sa.Integer(), nullable=True),
        sa.Column("rating_nmpz", sa.Integer(), nullable=True),
        sa.Column("win_streak", sa.Integer(), nullable=True),
        sa.Column("guessed_first_rate", sa.Float(), nullable=True),
        sa.Column("games_played", sa.Integer(), nullable=True),
        sa.Column("games_won", sa.Integer(), nullable=True),
        sa.Column("avg_guess_distance_km", sa.Float(), nullable=True),
        sa.Column("position_overall", sa.Integer(), nullable=True),
        sa.Column("position_moving", sa.Integer(), nullable=True),
        sa.Column("position_nomove", sa.Integer(), nullable=True),
        sa.Column("position_nmpz", sa.Integer(), nullable=True),
        sa.Column("position_country", sa.Integer(), nullable=True),
    )
    # Creates TimescaleDB hypertable; silently skips if extension not installed (plain Postgres in tests)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
                PERFORM create_hypertable('rating_snapshots', 'captured_at', if_not_exists => TRUE);
            END IF;
        END
        $$;
    """)


def downgrade() -> None:
    op.drop_table("rating_snapshots")
    op.drop_table("accounts")
