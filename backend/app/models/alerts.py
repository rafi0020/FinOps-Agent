from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class AlertRule(Base):
    __tablename__ = "alert_rules"
    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    org_id: Mapped[UUID] = mapped_column(ForeignKey("orgs.id"))
    metric: Mapped[str]
    comparison: Mapped[str]
    threshold: Mapped[Decimal]
    window: Mapped[str]
    region: Mapped[str | None]
    rationale: Mapped[str] = mapped_column(default="")
    status: Mapped[str] = mapped_column(default="active")
    run_id: Mapped[UUID | None] = mapped_column(ForeignKey("runs.id"))
    step_idx: Mapped[int | None]
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AlertEvent(Base):
    __tablename__ = "alert_events"
    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    org_id: Mapped[UUID] = mapped_column(ForeignKey("orgs.id"))
    rule_id: Mapped[UUID] = mapped_column(ForeignKey("alert_rules.id"))
    period: Mapped[str]
    value: Mapped[Decimal]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    acknowledged_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    acknowledged_at: Mapped[datetime | None]
