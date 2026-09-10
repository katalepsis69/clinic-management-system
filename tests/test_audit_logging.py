from app.models_audit import log_audit_event, AuditLog
from app.database import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

def test_audit_event_logged():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    entry = log_audit_event(
        db=db,
        user_id=1,
        patient_id=2,
        action="VIEW_EMR",
        resource="prescriptions",
        ip_address="192.168.1.100",
        user_agent="Mozilla/5.0"
    )
    assert entry.id is not None
    assert entry.action == "VIEW_EMR"
    assert entry.resource == "prescriptions"
    assert entry.user_id == 1
    assert entry.patient_id == 2
    assert entry.ip_address == "192.168.1.100"
    db.close()
