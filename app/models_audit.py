from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.orm import Session
from app.database import Base

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=False)
    patient_id = Column(Integer, index=True, nullable=True)
    action = Column(String(50), nullable=False)
    resource = Column(String(100), nullable=False)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(255), nullable=True)
    details = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

def log_audit_event(
    db: Session,
    user_id: int,
    action: str,
    resource: str,
    patient_id: int = None,
    ip_address: str = None,
    user_agent: str = None,
    details: str = None
) -> AuditLog:
    # ponytail: direct sync audit write; offload to background task/queue if audit volume exceeds 1k eps
    log = AuditLog(
        user_id=user_id,
        patient_id=patient_id,
        action=action,
        resource=resource,
        ip_address=ip_address,
        user_agent=user_agent,
        details=details
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log
