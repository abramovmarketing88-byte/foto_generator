"""add ai seller mode tables

Revision ID: 0002_ai_seller_mode
Revises: 0001_initial
Create Date: 2026-02-18 10:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_ai_seller_mode"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("current_mode", sa.Enum("reports", "ai_seller", name="modeenum"), nullable=False, server_default="reports"))
    op.add_column("users", sa.Column("current_branch_id", sa.Integer(), nullable=True))

    op.create_table(
        "prompt_templates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_id", sa.BigInteger(), sa.ForeignKey("users.tg_user_id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("scope", sa.Enum("system", "followup", "summary", name="promptscopeenum"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "ai_branches",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_id", sa.BigInteger(), sa.ForeignKey("users.tg_user_id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("avito_profile_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("gpt_model", sa.Enum("gpt-mini", "gpt-mid", "gpt-optimal", "gpt-pro", name="gptmodelenum"), nullable=False),
        sa.Column("system_prompt_id", sa.Integer(), sa.ForeignKey("prompt_templates.id"), nullable=True),
        sa.Column("context_retention_days", sa.Integer(), nullable=True),
        sa.Column("max_messages_in_context", sa.Integer(), nullable=True),
        sa.Column("followup_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_foreign_key("fk_users_current_branch", "users", "ai_branches", ["current_branch_id"], ["id"])

    op.create_table(
        "ai_dialog_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.tg_user_id"), nullable=False),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("ai_branches.id"), nullable=False),
        sa.Column("dialog_id", sa.String(length=255), nullable=False, server_default="default"),
        sa.Column("role", sa.Enum("user", "assistant", "system", name="dialogroleenum"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "ai_dialog_state",
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.tg_user_id"), primary_key=True),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("ai_branches.id"), primary_key=True),
        sa.Column("dialog_id", sa.String(length=255), primary_key=True, server_default="default"),
        sa.Column("is_converted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("has_negative", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("phone_number", sa.String(length=64), nullable=True),
        sa.Column("last_client_message_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "followup_chains",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("ai_branches.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("start_event", sa.Enum("dialog_started", "no_reply", "manual", name="followupstarteventenum"), nullable=False),
        sa.Column("stop_on_conversion", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    op.create_table(
        "followup_steps",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("chain_id", sa.Integer(), sa.ForeignKey("followup_chains.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("delay_seconds", sa.Integer(), nullable=False),
        sa.Column("send_mode", sa.Enum("always", "if_not_converted", "if_not_converted_and_no_negative", name="followupsendmodeenum"), nullable=False),
        sa.Column("content_type", sa.Enum("fixed", "llm", name="followupcontenttypeenum"), nullable=False),
        sa.Column("fixed_text", sa.Text(), nullable=True),
        sa.Column("prompt_template_id", sa.Integer(), sa.ForeignKey("prompt_templates.id"), nullable=True),
        sa.Column("target_channel", sa.Enum("telegram_user", "avito_dialog", "telegram_manager", name="followuptargetchannelenum"), nullable=False),
    )

    op.create_table(
        "scheduled_followups",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.tg_user_id"), nullable=False),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("ai_branches.id"), nullable=False),
        sa.Column("chain_id", sa.Integer(), sa.ForeignKey("followup_chains.id"), nullable=False),
        sa.Column("step_id", sa.Integer(), sa.ForeignKey("followup_steps.id"), nullable=False),
        sa.Column("dialog_id", sa.String(length=255), nullable=False),
        sa.Column("execute_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Enum("pending", "sent", "canceled", "failed", name="scheduledfollowupstatusenum"), nullable=False, server_default="pending"),
        sa.Column("converted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("negative_detected", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_index("ix_ai_dialog_messages_user_branch_created", "ai_dialog_messages", ["user_id", "branch_id", sa.text("created_at DESC")])
    op.create_index("ix_scheduled_followups_status_execute", "scheduled_followups", ["status", "execute_at"])


def downgrade() -> None:
    op.drop_index("ix_scheduled_followups_status_execute", table_name="scheduled_followups")
    op.drop_index("ix_ai_dialog_messages_user_branch_created", table_name="ai_dialog_messages")
    op.drop_table("scheduled_followups")
    op.drop_table("followup_steps")
    op.drop_table("followup_chains")
    op.drop_table("ai_dialog_state")
    op.drop_table("ai_dialog_messages")
    op.drop_constraint("fk_users_current_branch", "users", type_="foreignkey")
    op.drop_table("ai_branches")
    op.drop_table("prompt_templates")
    op.drop_column("users", "current_branch_id")
    op.drop_column("users", "current_mode")

    sa.Enum(name="scheduledfollowupstatusenum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="followuptargetchannelenum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="followupcontenttypeenum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="followupsendmodeenum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="followupstarteventenum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="dialogroleenum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="gptmodelenum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="promptscopeenum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="modeenum").drop(op.get_bind(), checkfirst=True)
