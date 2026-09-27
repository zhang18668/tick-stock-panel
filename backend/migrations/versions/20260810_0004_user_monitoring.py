"""Add user-scoped monitor rules and alert events."""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260810_0004"
down_revision: str | None = "20260810_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_monitor_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rule_id", sa.String(length=120), nullable=False),
        sa.Column("rule", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rule_id", name="uq_monitor_rule_runtime_id"),
        sa.UniqueConstraint("user_id", "rule_id", name="uq_user_monitor_rule"),
    )
    op.create_index(
        "ix_user_monitor_rules_user_enabled", "user_monitor_rules", ["user_id", "enabled"]
    )
    op.create_table(
        "user_alert_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_ts", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("rule_id", sa.String(length=120)),
        sa.Column("event", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_user_alert_events_user_ts", "user_alert_events", ["user_id", "event_ts"]
    )
    op.create_index(
        "ix_user_alert_events_user_source", "user_alert_events", ["user_id", "source"]
    )


def downgrade() -> None:
    op.drop_index("ix_user_alert_events_user_source", table_name="user_alert_events")
    op.drop_index("ix_user_alert_events_user_ts", table_name="user_alert_events")
    op.drop_table("user_alert_events")
    op.drop_index("ix_user_monitor_rules_user_enabled", table_name="user_monitor_rules")
    op.drop_table("user_monitor_rules")
