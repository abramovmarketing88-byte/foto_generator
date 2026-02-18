"""initial

Revision ID: 0001_initial
Revises: 
Create Date: 2026-01-01 00:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_table(
        "workspaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("plan", sa.Enum("FREE", "PRO", name="planenum"), nullable=False),
        sa.Column("credits_balance", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_foreign_key("fk_users_workspace", "users", "workspaces", ["workspace_id"], ["id"])

    op.create_table(
        "identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("status", sa.Enum("ENROLLING", "READY", "FAILED", name="identitystatus"), nullable=False),
        sa.Column("identity_id", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(128), unique=True, nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("preview_storage_key", sa.String(512), nullable=True),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("num_outputs", sa.Integer(), nullable=False),
        sa.Column("cost_credits", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("identity_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("identities.id"), nullable=True),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("templates.id"), nullable=True),
        sa.Column("type", sa.Enum("ENROLL", "GENERATE", name="jobtype"), nullable=False),
        sa.Column("status", sa.Enum("QUEUED", "RUNNING", "DONE", "FAILED", "CANCELED", name="jobstatus"), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "result_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "subscription_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(64), unique=True, nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("monthly_credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "purchases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("amount_credits", sa.Integer(), nullable=False),
        sa.Column("metadata", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("purchases")
    op.drop_table("subscription_plans")
    op.drop_table("result_assets")
    op.drop_table("jobs")
    op.drop_table("templates")
    op.drop_table("identities")
    op.drop_constraint("fk_users_workspace", "users", type_="foreignkey")
    op.drop_table("workspaces")
    op.drop_table("users")
    sa.Enum(name="jobstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="jobtype").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="identitystatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="planenum").drop(op.get_bind(), checkfirst=True)
