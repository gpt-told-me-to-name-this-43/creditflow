import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class ScoringResult(Base):
    __tablename__ = "scoring_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id = Column(UUID(as_uuid=True), ForeignKey("applications.id"), nullable=False)
    kind = Column(String, nullable=False)

    monthly_payment_rub = Column(Numeric(15, 2), nullable=False)
    dscr = Column(Numeric, nullable=False)
    limit_rub = Column(Numeric(15, 2), nullable=True)

    score = Column(Integer, nullable=False)
    risk_level = Column(String, nullable=False)
    inputs_hash = Column(String, nullable=False)

    created_at = Column(DateTime(timezone=True), nullable=False)
