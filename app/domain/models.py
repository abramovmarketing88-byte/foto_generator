import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class PlanEnum(str, enum.Enum):
    FREE = "FREE"
    PRO = "PRO"


class ModeEnum(str, enum.Enum):
    reports = "reports"
    ai_seller = "ai_seller"


class GptModelEnum(str, enum.Enum):
    gpt_mini = "gpt-mini"
    gpt_mid = "gpt-mid"
    gpt_optimal = "gpt-optimal"
    gpt_pro = "gpt-pro"


class PromptScopeEnum(str, enum.Enum):
    system = "system"
    followup = "followup"
    summary = "summary"


class DialogRoleEnum(str, enum.Enum):
    user = "user"
    assistant = "assistant"
    system = "system"


class FollowupStartEventEnum(str, enum.Enum):
    dialog_started = "dialog_started"
    no_reply = "no_reply"
    manual = "manual"


class FollowupSendModeEnum(str, enum.Enum):
    always = "always"
    if_not_converted = "if_not_converted"
    if_not_converted_and_no_negative = "if_not_converted_and_no_negative"


class FollowupContentTypeEnum(str, enum.Enum):
    fixed = "fixed"
    llm = "llm"


class FollowupTargetChannelEnum(str, enum.Enum):
    telegram_user = "telegram_user"
    avito_dialog = "avito_dialog"
    telegram_manager = "telegram_manager"


class ScheduledFollowupStatusEnum(str, enum.Enum):
    pending = "pending"
    sent = "sent"
    canceled = "canceled"
    failed = "failed"


class IdentityStatus(str, enum.Enum):
    ENROLLING = "ENROLLING"
    READY = "READY"
    FAILED = "FAILED"


class JobType(str, enum.Enum):
    ENROLL = "ENROLL"
    GENERATE = "GENERATE"


class JobStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=True)
    current_mode: Mapped[ModeEnum] = mapped_column(Enum(ModeEnum), default=ModeEnum.reports, nullable=False)
    current_branch_id: Mapped[int | None] = mapped_column(ForeignKey("ai_branches.id"), nullable=True)

    workspace: Mapped["Workspace"] = relationship(foreign_keys=[workspace_id], post_update=True)


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    plan: Mapped[PlanEnum] = mapped_column(Enum(PlanEnum), default=PlanEnum.FREE, nullable=False)
    credits_balance: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Identity(Base):
    __tablename__ = "identities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    status: Mapped[IdentityStatus] = mapped_column(Enum(IdentityStatus), nullable=False)
    identity_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Template(Base):
    __tablename__ = "templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    preview_storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    num_outputs: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_credits: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.tg_user_id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    scope: Mapped[PromptScopeEnum] = mapped_column(Enum(PromptScopeEnum), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class AIBranch(Base):
    __tablename__ = "ai_branches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.tg_user_id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    avito_profile_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    gpt_model: Mapped[GptModelEnum] = mapped_column(Enum(GptModelEnum), nullable=False)
    system_prompt_id: Mapped[int | None] = mapped_column(ForeignKey("prompt_templates.id"), nullable=True)
    context_retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_messages_in_context: Mapped[int | None] = mapped_column(Integer, nullable=True)
    followup_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class AIDialogMessage(Base):
    __tablename__ = "ai_dialog_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.tg_user_id"), nullable=False)
    branch_id: Mapped[int] = mapped_column(ForeignKey("ai_branches.id"), nullable=False)
    dialog_id: Mapped[str] = mapped_column(String(255), nullable=False, default="default")
    role: Mapped[DialogRoleEnum] = mapped_column(Enum(DialogRoleEnum), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AIDialogState(Base):
    __tablename__ = "ai_dialog_state"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.tg_user_id"), primary_key=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("ai_branches.id"), primary_key=True)
    dialog_id: Mapped[str] = mapped_column(String(255), primary_key=True, default="default")
    is_converted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_negative: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    phone_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_client_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FollowupChain(Base):
    __tablename__ = "followup_chains"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("ai_branches.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    start_event: Mapped[FollowupStartEventEnum] = mapped_column(Enum(FollowupStartEventEnum), nullable=False)
    stop_on_conversion: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class FollowupStep(Base):
    __tablename__ = "followup_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chain_id: Mapped[int] = mapped_column(ForeignKey("followup_chains.id", ondelete="CASCADE"), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    delay_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    send_mode: Mapped[FollowupSendModeEnum] = mapped_column(Enum(FollowupSendModeEnum), nullable=False)
    content_type: Mapped[FollowupContentTypeEnum] = mapped_column(Enum(FollowupContentTypeEnum), nullable=False)
    fixed_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_template_id: Mapped[int | None] = mapped_column(ForeignKey("prompt_templates.id"), nullable=True)
    target_channel: Mapped[FollowupTargetChannelEnum] = mapped_column(Enum(FollowupTargetChannelEnum), nullable=False)


class ScheduledFollowup(Base):
    __tablename__ = "scheduled_followups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.tg_user_id"), nullable=False)
    branch_id: Mapped[int] = mapped_column(ForeignKey("ai_branches.id"), nullable=False)
    chain_id: Mapped[int] = mapped_column(ForeignKey("followup_chains.id"), nullable=False)
    step_id: Mapped[int] = mapped_column(ForeignKey("followup_steps.id"), nullable=False)
    dialog_id: Mapped[str] = mapped_column(String(255), nullable=False)
    execute_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[ScheduledFollowupStatusEnum] = mapped_column(Enum(ScheduledFollowupStatusEnum), nullable=False, default=ScheduledFollowupStatusEnum.pending)
    converted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    negative_detected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    identity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("identities.id"), nullable=True)
    template_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("templates.id"), nullable=True)
    type: Mapped[JobType] = mapped_column(Enum(JobType), nullable=False)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class ResultAsset(Base):
    __tablename__ = "result_assets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    monthly_credits: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Purchase(Base):
    __tablename__ = "purchases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    amount_credits: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
