from sqlalchemy import Column, String, Numeric, Integer, ForeignKey, DateTime, Text, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, relationship
import uuid

class Base(DeclarativeBase):
    pass

class ScoringResult(Base):
    __tablename__ = 'scoring_results'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id = Column(UUID(as_uuid=True), ForeignKey('applications.id'), nullable=False)
    kind = Column(String, nullable=False)
    
    monthly_payment_rub = Column(Numeric(15, 2), nullable=False)
    dscr = Column(Numeric, nullable=False) 
    limit_rub = Column(Numeric(15, 2), nullable=True)
    
    score = Column(Integer, nullable=False)
    risk_level = Column(String, nullable=False)
    inputs_hash = Column(String, nullable=False)
    
    created_at = Column(DateTime(timezone=True), nullable=False)