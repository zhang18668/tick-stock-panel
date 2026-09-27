"""Add referral relationships and an immutable credit ledger."""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260812_0010"
down_revision: str | None = "20260811_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("referral_code", sa.String(16)))
    op.add_column("users", sa.Column("referred_by_user_id", postgresql.UUID(as_uuid=True)))
    op.create_unique_constraint("uq_users_referral_code", "users", ["referral_code"])
    op.create_foreign_key("fk_users_referrer", "users", "users", ["referred_by_user_id"], ["id"], ondelete="SET NULL")
    op.create_table(
        "credit_accounts",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("balance_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("earned_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("spent_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "credit_ledger_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("balance_after_cents", sa.BigInteger(), nullable=False),
        sa.Column("entry_type", sa.String(40), nullable=False),
        sa.Column("business_key", sa.String(160), nullable=False),
        sa.Column("description", sa.String(240), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("business_key"),
    )
    op.create_index("ix_credit_ledger_user_created", "credit_ledger_entries", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_credit_ledger_user_created", table_name="credit_ledger_entries")
    op.drop_table("credit_ledger_entries")
    op.drop_table("credit_accounts")
    op.drop_constraint("fk_users_referrer", "users", type_="foreignkey")
    op.drop_constraint("uq_users_referral_code", "users", type_="unique")
    op.drop_column("users", "referred_by_user_id")
    op.drop_column("users", "referral_code")
