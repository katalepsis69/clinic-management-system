"""Access-control regression tests for the security hardening pass."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.models import Base, User, UserRole
from app.auth import create_access_token
from app.config import Settings
from app.routers.appointments import router as appointments_router
from app.routers.feedback import router as feedback_router
from app.routers.chat import router as chat_router
from app.routers.emr import router as emr_router


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def client(db_session):
    app = FastAPI()
    app.include_router(appointments_router)
    app.include_router(feedback_router)
    app.include_router(chat_router)
    app.include_router(emr_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _token(user):
    return {"Authorization": f"Bearer {create_access_token({'sub': user.email, 'role': user.role.value})}"}


def test_doctor_cannot_view_other_doctors_schedule(client, db_session):
    u_doc1 = User(email="d1@sec.test", hashed_password="pw", full_name="Doc One", role=UserRole.DOCTOR)
    u_doc2 = User(email="d2@sec.test", hashed_password="pw", full_name="Doc Two", role=UserRole.DOCTOR)
    db_session.add_all([u_doc1, u_doc2])
    db_session.commit()

    # doctor_id 999 does not belong to u_doc1
    res = client.get("/api/appointments/doctor-schedule/999", headers=_token(u_doc1))
    assert res.status_code == 403
    # Patient role is rejected outright
    u_pat = User(email="p1@sec.test", hashed_password="pw", full_name="Pat One", role=UserRole.PATIENT)
    db_session.add(u_pat)
    db_session.commit()
    res = client.get("/api/appointments/doctor-schedule/999", headers=_token(u_pat))
    assert res.status_code == 403


def test_feedback_analytics_requires_staff_role(client, db_session):
    u_pat = User(email="p2@sec.test", hashed_password="pw", full_name="Pat Two", role=UserRole.PATIENT)
    db_session.add(u_pat)
    db_session.commit()

    res = client.get("/api/feedback/analytics", headers=_token(u_pat))
    assert res.status_code == 403


def test_patient_cannot_impersonate_staff_in_chat(client, db_session):
    u_pat = User(email="p3@sec.test", hashed_password="pw", full_name="Just A Patient", role=UserRole.PATIENT)
    db_session.add(u_pat)
    db_session.commit()

    res = client.post("/api/chat/send", headers=_token(u_pat), json={
        "session_id": "sess-security-01",
        "sender_name": "Fake Reception",
        "role": "staff",
        "message": "hello",
    })
    assert res.status_code == 200
    body = res.json()["user_message"]
    assert body["sender_name"] == "Just A Patient"
    assert body["sender_role"] == "patient"
    # Patients get the bot; staff would not
    assert res.json()["bot_reply"] is not None


def test_production_settings_reject_dev_secret():
    with pytest.raises(RuntimeError):
        Settings(DEMO_MODE=False, SECRET_KEY="dev-secret-key-change-in-production-1234567890")


def test_production_settings_accept_strong_secret():
    s = Settings(DEMO_MODE=False, SECRET_KEY="x" * 48)
    assert s.ACCESS_TOKEN_EXPIRE_MINUTES == 60


def test_admin_and_staff_forbidden_from_viewing_patient_emr(client, db_session):
    u_admin = User(email="admin@sec.test", hashed_password="pw", full_name="Admin Boss", role=UserRole.ADMIN)
    u_staff = User(email="staff@sec.test", hashed_password="pw", full_name="Staff Front", role=UserRole.STAFF)
    u_doc = User(email="doc@sec.test", hashed_password="pw", full_name="Doctor House", role=UserRole.DOCTOR)
    db_session.add_all([u_admin, u_staff, u_doc])
    db_session.commit()

    # Admin access must return 403 Forbidden
    res_admin = client.get("/api/emr/patient/1", headers=_token(u_admin))
    assert res_admin.status_code == 403

    # Staff access must return 403 Forbidden
    res_staff = client.get("/api/emr/patient/1", headers=_token(u_staff))
    assert res_staff.status_code == 403

    # Doctor access is allowed (404 because patient id 1 does not exist in db, but NOT 403)
    res_doc = client.get("/api/emr/patient/1", headers=_token(u_doc))
    assert res_doc.status_code == 404


def test_admin_forbidden_from_creating_prescription(client, db_session):
    u_admin = User(email="admin2@sec.test", hashed_password="pw", full_name="Admin Pharma", role=UserRole.ADMIN)
    db_session.add(u_admin)
    db_session.commit()

    payload = {
        "patient_id": 1,
        "items": [
            {
                "medication_name": "Amoxicillin",
                "dosage": "500mg",
                "frequency": "TID",
                "duration": "7 days",
                "instructions": "After food",
            }
        ],
        "notes": "Admin testing rx",
    }
    res = client.post("/api/emr/prescription/create", headers=_token(u_admin), json=payload)
    assert res.status_code == 403