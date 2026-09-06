import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.models import Base, User, UserRole, Patient, Doctor, PatientFeedback
from app.auth import create_access_token
from app.sentiment import analyze_sentiment
from app.routers.feedback import router as feedback_router


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
    app.include_router(feedback_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


# --- Unit tests for analyze_sentiment ---

def test_positive_sentiment():
    result = analyze_sentiment("The doctor was extremely attentive, kind, and knowledgeable!", rating=5)
    assert result["sentiment_label"] == "positive"
    assert result["sentiment_score"] > 0.3
    assert result["flagged_critical"] is False


def test_critical_negative_sentiment():
    result = analyze_sentiment("Terrible experience. Waited 2 hours and staff was rude and dismissive.", rating=1)
    assert result["sentiment_label"] == "negative"
    assert result["sentiment_score"] < -0.2
    assert result["flagged_critical"] is True


def test_neutral_sentiment():
    result = analyze_sentiment("The clinic is located on the second floor.", rating=3)
    assert result["sentiment_label"] == "neutral"
    assert -0.05 < result["sentiment_score"] < 0.05
    assert result["flagged_critical"] is False


def test_critical_due_to_low_rating():
    # Even if text is neutral or mildly positive, rating <= 2 flags critical
    result = analyze_sentiment("Appointment was fine.", rating=2)
    assert result["flagged_critical"] is True


def test_critical_due_to_strongly_negative_compound():
    # Even if rating is 3, severe negative text (compound < -0.3) flags critical
    result = analyze_sentiment("Horrible, terrible, painful and dreadful experience.", rating=3)
    assert result["sentiment_score"] < -0.3
    assert result["flagged_critical"] is True


# --- Integration tests for /api/feedback endpoints ---

def test_feedback_analytics_empty(client, db_session):
    u_staff = User(email="analytics1@demo.com", full_name="Analytics Staff", role=UserRole.STAFF, hashed_password="pw")
    db_session.add(u_staff)
    db_session.commit()
    staff_headers = {"Authorization": f"Bearer {create_access_token({'sub': u_staff.email, 'role': u_staff.role.value})}"}

    # Anonymous access is rejected (staff-only endpoint)
    res_anon = client.get("/api/feedback/analytics")
    assert res_anon.status_code == 401

    res = client.get("/api/feedback/analytics", headers=staff_headers)
    assert res.status_code == 200
    data = res.json()
    assert data == {
        "total": 0,
        "avg_rating": 5.0,
        "positive_pct": 100,
        "negative_pct": 0,
        "critical_count": 0,
        "items": [],
    }


def test_submit_feedback_patient_success(client, db_session):
    # Setup patient user and patient profile
    user = User(
        email="patient1@demo.com",
        full_name="Patient One",
        role=UserRole.PATIENT,
        hashed_password="hashedpassword",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    patient = Patient(user_id=user.id, emergency_contact_name="Family", emergency_contact_phone="123456")
    db_session.add(patient)
    db_session.commit()

    token = create_access_token({"sub": "patient1@demo.com", "role": "patient"})

    payload = {
        "rating": 5,
        "tags": ["friendly", "clean"],
        "comment_text": "Excellent care and friendly staff!",
        "doctor_id": None,
    }
    res = client.post(
        "/api/feedback",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    res_data = res.json()
    assert res_data["status"] == "success"
    assert "id" in res_data
    assert res_data["sentiment"]["sentiment_label"] == "positive"
    assert res_data["sentiment"]["flagged_critical"] is False

    # Check DB record
    fb = db_session.query(PatientFeedback).filter_by(id=res_data["id"]).first()
    assert fb is not None
    assert fb.patient_id == patient.id
    assert fb.rating == 5
    assert json.loads(fb.tags_json) == ["friendly", "clean"]
    assert fb.comment_text == "Excellent care and friendly staff!"
    assert fb.sentiment_label == "positive"
    assert fb.flagged_critical is False


def test_submit_feedback_non_patient_forbidden(client, db_session):
    # Doctor tries to submit feedback (no Patient record for this user)
    user = User(
        email="doctor1@demo.com",
        full_name="Dr. Smith",
        role=UserRole.DOCTOR,
        hashed_password="hashedpassword",
    )
    db_session.add(user)
    db_session.commit()

    token = create_access_token({"sub": "doctor1@demo.com", "role": "doctor"})

    payload = {
        "rating": 4,
        "tags": ["doctor-note"],
        "comment_text": "Trying to submit as a doctor",
    }
    res = client.post(
        "/api/feedback",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 400
    assert res.json()["detail"] == "Only patients can submit feedback"


def test_submit_feedback_unauthenticated(client):
    payload = {
        "rating": 4,
        "comment_text": "No auth token provided",
    }
    res = client.post("/api/feedback", json=payload)
    assert res.status_code == 401


def test_feedback_analytics_with_data(client, db_session):
    user = User(
        email="patient2@demo.com",
        full_name="Patient Two",
        role=UserRole.PATIENT,
        hashed_password="hashedpassword",
    )
    db_session.add(user)
    db_session.commit()
    patient = Patient(user_id=user.id, emergency_contact_name="Family", emergency_contact_phone="123456")
    db_session.add(patient)
    db_session.commit()

    token = create_access_token({"sub": "patient2@demo.com", "role": "patient"})

    # Submit 1 positive review
    client.post(
        "/api/feedback",
        json={"rating": 5, "tags": ["great"], "comment_text": "Great doctor and wonderful staff!"},
        headers={"Authorization": f"Bearer {token}"},
    )
    # Submit 1 critical negative review
    client.post(
        "/api/feedback",
        json={"rating": 1, "tags": ["wait"], "comment_text": "Terrible service, waited forever and doctor was rude."},
        headers={"Authorization": f"Bearer {token}"},
    )

    u_staff2 = User(email="analytics2@demo.com", full_name="Analytics Two", role=UserRole.STAFF, hashed_password="pw")
    db_session.add(u_staff2)
    db_session.commit()
    staff_headers = {"Authorization": f"Bearer {create_access_token({'sub': u_staff2.email, 'role': u_staff2.role.value})}"}

    analytics_res = client.get("/api/feedback/analytics", headers=staff_headers)
    assert analytics_res.status_code == 200
    data = analytics_res.json()
    assert data["total"] == 2
    assert data["avg_rating"] == 3.0
    assert data["positive_pct"] == 50.0
    assert data["negative_pct"] == 50.0
    assert data["critical_count"] == 1
    assert len(data["items"]) == 2
    assert data["items"][0]["rating"] in [1, 5]
    assert "created_at" in data["items"][0]
