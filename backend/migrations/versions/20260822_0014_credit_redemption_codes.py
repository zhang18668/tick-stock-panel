"""Add one-time credit redemption codes.

Revision ID: 20260822_0014
Revises: 20260822_0013
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260822_0014"
down_revision: str | None = "20260822_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "credit_redemption_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("code_prefix", sa.String(length=14), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("redeemed_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("amount_cents > 0", name="ck_credit_redemption_codes_amount_positive"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["redeemed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash"),
    )
    op.create_index("ix_credit_redemption_codes_status_expires", "credit_redemption_codes", ["status", "expires_at"])
    op.create_index("ix_credit_redemption_codes_created", "credit_redemption_codes", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_credit_redemption_codes_created", table_name="credit_redemption_codes")
    op.drop_index("ix_credit_redemption_codes_status_expires", table_name="credit_redemption_codes")
    op.drop_table("credit_redemption_codes")
