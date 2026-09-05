from datetime import date, datetime
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.models import (
    Base,
    User,
    UserRole,
    Patient,
    Doctor,
    Appointment,
    AppointmentStatus,
)
from app.auth import create_access_token
from app.routers.appointments import router as appointments_router, doctors_router


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


app = FastAPI()
app.include_router(appointments_router)
app.include_router(doctors_router)

client = TestClient(app)


@pytest.fixture(autouse=True)
def override_db(db_session):
    def _override():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    yield
    app.dependency_overrides.clear()


# --- Brief Step 1 Baseline Test ---

def test_get_doctors_list():
    response = client.get("/api/appointments/doctors")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


# --- Comprehensive Doctor Listing Tests ---

def test_list_doctors_with_availability(db_session):
    u_doc1 = User(
        email="dr.alice@clinic.test",
        hashed_password="pw",
        full_name="Dr. Alice Smith",
        role=UserRole.DOCTOR,
        phone="555-0101",
    )
    u_doc2 = User(
        email="dr.bob@clinic.test",
        hashed_password="pw",
        full_name="Dr. Bob Jones",
        role=UserRole.DOCTOR,
        phone="555-0102",
    )
    db_session.add_all([u_doc1, u_doc2])
    db_session.commit()

    doc1 = Doctor(
        user_id=u_doc1.id,
        specialization="Cardiology",
        license_number="LIC-101",
        room_number="Room 201",
        consultation_fee=75.50,
        is_available=True,
    )
    doc2 = Doctor(
        user_id=u_doc2.id,
        specialization="Dermatology",
        license_number="LIC-102",
        room_number="Room 202",
        consultation_fee=60.00,
        is_available=False,
    )
    db_session.add_all([doc1, doc2])
    db_session.commit()

    # Available doctors should return doc1 only
    response = client.get("/api/appointments/doctors")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == doc1.id
    assert data[0]["name"] == "Dr. Alice Smith"
    assert data[0]["specialization"] == "Cardiology"
    assert data[0]["room_number"] == "Room 201"
    assert data[0]["fee"] == 75.50

    # Also test the alias endpoint /api/doctors/list
    alias_resp = client.get("/api/doctors/list")
    assert alias_resp.status_code == 200
    alias_data = alias_resp.json()
    assert len(alias_data) == 1
    assert alias_data[0]["id"] == doc1.id


# --- Appointment Booking Tests ---

def test_book_appointment_unauthenticated():
    payload = {
        "doctor_id": 1,
        "appointment_date": "2026-09-10",
        "time_slot": "09:00 - 09:30",
        "reason_for_visit": "Routine check",
    }
    response = client.post("/api/appointments/book", json=payload)
    assert response.status_code == 401


def test_book_appointment_non_patient(db_session):
    u_staff = User(
        email="staff1@clinic.test",
        hashed_password="pw",
        full_name="Staff Member",
        role=UserRole.STAFF,
    )
    db_session.add(u_staff)
    db_session.commit()

    token = create_access_token({"sub": u_staff.email, "role": u_staff.role.value})
    payload = {
        "doctor_id": 1,
        "appointment_date": "2026-09-10",
        "time_slot": "09:00 - 09:30",
    }
    response = client.post(
        "/api/appointments/book",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "User is not registered as a patient"


def test_book_appointment_success(db_session):
    u_doc = User(
        email="dr.clara@clinic.test",
        hashed_password="pw",
        full_name="Dr. Clara Oswald",
        role=UserRole.DOCTOR,
    )
    u_pat = User(
        email="patient.john@clinic.test",
        hashed_password="pw",
        full_name="John Doe",
        role=UserRole.PATIENT,
        phone="555-1234",
    )
    db_session.add_all([u_doc, u_pat])
    db_session.commit()

    doc = Doctor(
        user_id=u_doc.id,
        specialization="Pediatrics",
        license_number="LIC-103",
        room_number="Room 105",
        consultation_fee=50.00,
        is_available=True,
    )
    pat = Patient(user_id=u_pat.id)
    db_session.add_all([doc, pat])
    db_session.commit()

    token = create_access_token({"sub": u_pat.email, "role": u_pat.role.value})
    payload = {
        "doctor_id": doc.id,
        "appointment_date": "2026-09-10",
        "time_slot": "10:00 - 10:30",
        "reason_for_visit": "Fever and cough",
    }
    response = client.post(
        "/api/appointments/book",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["status"] == "success"
    assert "appointment_id" in res_data

    # Verify DB persistence
    appt = db_session.query(Appointment).filter(Appointment.id == res_data["appointment_id"]).first()
    assert appt is not None
    assert appt.patient_id == pat.id
    assert appt.doctor_id == doc.id
    assert appt.appointment_date == date(2026, 9, 10)
    assert appt.time_slot == "10:00 - 10:30"
    assert appt.reason_for_visit == "Fever and cough"
    assert appt.status == AppointmentStatus.CONFIRMED


def test_book_appointment_slot_conflict(db_session):
    u_doc = User(
        email="dr.dan@clinic.test",
        hashed_password="pw",
        full_name="Dr. Dan",
        role=UserRole.DOCTOR,
    )
    u_pat1 = User(
        email="pat1@clinic.test",
        hashed_password="pw",
        full_name="Pat One",
        role=UserRole.PATIENT,
    )
    u_pat2 = User(
        email="pat2@clinic.test",
        hashed_password="pw",
        full_name="Pat Two",
        role=UserRole.PATIENT,
    )
    db_session.add_all([u_doc, u_pat1, u_pat2])
    db_session.commit()

    doc = Doctor(
        user_id=u_doc.id,
        specialization="General",
        license_number="LIC-104",
        room_number="Room 101",
    )
    pat1 = Patient(user_id=u_pat1.id)
    pat2 = Patient(user_id=u_pat2.id)
    db_session.add_all([doc, pat1, pat2])
    db_session.commit()

    token1 = create_access_token({"sub": u_pat1.email, "role": u_pat1.role.value})
    token2 = create_access_token({"sub": u_pat2.email, "role": u_pat2.role.value})

    payload = {
        "doctor_id": doc.id,
        "appointment_date": "2026-09-12",
        "time_slot": "14:00 - 14:30",
        "reason_for_visit": "First booking",
    }
    resp1 = client.post(
        "/api/appointments/book",
        json=payload,
        headers={"Authorization": f"Bearer {token1}"},
    )
    assert resp1.status_code == 200

    # Second patient attempts the exact same slot -> 409
    resp2 = client.post(
        "/api/appointments/book",
        json=payload,
        headers={"Authorization": f"Bearer {token2}"},
    )
    assert resp2.status_code == 409
    assert resp2.json()["detail"] == "This time slot is already booked"


def test_book_appointment_rebooking_after_cancellation(db_session):
    u_doc = User(
        email="dr.evan@clinic.test",
        hashed_password="pw",
        full_name="Dr. Evan",
        role=UserRole.DOCTOR,
    )
    u_pat1 = User(
        email="pat3@clinic.test",
        hashed_password="pw",
        full_name="Pat Three",
        role=UserRole.PATIENT,
    )
    u_pat2 = User(
        email="pat4@clinic.test",
        hashed_password="pw",
        full_name="Pat Four",
        role=UserRole.PATIENT,
    )
    db_session.add_all([u_doc, u_pat1, u_pat2])
    db_session.commit()

    doc = Doctor(
        user_id=u_doc.id,
        specialization="Orthopedics",
        license_number="LIC-105",
        room_number="Room 102",
    )
    pat1 = Patient(user_id=u_pat1.id)
    pat2 = Patient(user_id=u_pat2.id)
    db_session.add_all([doc, pat1, pat2])
    db_session.commit()

    # Cancelled appointment exists on this slot
    cancelled_appt = Appointment(
        patient_id=pat1.id,
        doctor_id=doc.id,
        appointment_date=date(2026, 9, 14),
        time_slot="11:00 - 11:30",
        status=AppointmentStatus.CANCELLED,
    )
    db_session.add(cancelled_appt)
    db_session.commit()

    token2 = create_access_token({"sub": u_pat2.email, "role": u_pat2.role.value})
    payload = {
        "doctor_id": doc.id,
        "appointment_date": "2026-09-14",
        "time_slot": "11:00 - 11:30",
        "reason_for_visit": "Rebooking slot",
    }
    resp = client.post(
        "/api/appointments/book",
        json=payload,
        headers={"Authorization": f"Bearer {token2}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"


def test_book_appointment_different_slots_and_doctors(db_session):
    u_doc1 = User(
        email="dr.frank@clinic.test",
        hashed_password="pw",
        full_name="Dr. Frank",
        role=UserRole.DOCTOR,
    )
    u_doc2 = User(
        email="dr.grace@clinic.test",
        hashed_password="pw",
        full_name="Dr. Grace",
        role=UserRole.DOCTOR,
    )
    u_pat = User(
        email="pat5@clinic.test",
        hashed_password="pw",
        full_name="Pat Five",
        role=UserRole.PATIENT,
    )
    db_session.add_all([u_doc1, u_doc2, u_pat])
    db_session.commit()

    doc1 = Doctor(
        user_id=u_doc1.id,
        specialization="ENT",
        license_number="LIC-106",
        room_number="Room 103",
    )
    doc2 = Doctor(
        user_id=u_doc2.id,
        specialization="Neurology",
        license_number="LIC-107",
        room_number="Room 104",
    )
    pat = Patient(user_id=u_pat.id)
    db_session.add_all([doc1, doc2, pat])
    db_session.commit()

    token = create_access_token({"sub": u_pat.email, "role": u_pat.role.value})

    # Book doc1 at 09:00
    r1 = client.post(
        "/api/appointments/book",
        json={
            "doctor_id": doc1.id,
            "appointment_date": "2026-09-16",
            "time_slot": "09:00 - 09:30",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r1.status_code == 200

    # Book doc1 at 09:30 (different slot, same doctor, same date) -> succeeds
    r2 = client.post(
        "/api/appointments/book",
        json={
            "doctor_id": doc1.id,
            "appointment_date": "2026-09-16",
            "time_slot": "09:30 - 10:00",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.status_code == 200

    # Book doc2 at 09:00 (same slot, different doctor, same date) -> succeeds
    r3 = client.post(
        "/api/appointments/book",
        json={
            "doctor_id": doc2.id,
            "appointment_date": "2026-09-16",
            "time_slot": "09:00 - 09:30",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r3.status_code == 200


def test_book_appointment_invalid_date_format(db_session):
    u_pat = User(
        email="pat6@clinic.test",
        hashed_password="pw",
        full_name="Pat Six",
        role=UserRole.PATIENT,
    )
    db_session.add(u_pat)
    db_session.commit()
    pat = Patient(user_id=u_pat.id)
    db_session.add(pat)
    db_session.commit()

    token = create_access_token({"sub": u_pat.email, "role": u_pat.role.value})
    resp = client.post(
        "/api/appointments/book",
        json={
            "doctor_id": 1,
            "appointment_date": "invalid-date-string",
            "time_slot": "09:00 - 09:30",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    assert "date format" in resp.json()["detail"].lower()


# --- Doctor Schedule Tests ---

def test_get_doctor_schedule_default_date_today(db_session):
    u_doc = User(
        email="dr.helen@clinic.test",
        hashed_password="pw",
        full_name="Dr. Helen",
        role=UserRole.DOCTOR,
    )
    u_pat = User(
        email="pat7@clinic.test",
        hashed_password="pw",
        full_name="Patient Helen Doe",
        role=UserRole.PATIENT,
        phone="555-9988",
    )
    db_session.add_all([u_doc, u_pat])
    db_session.commit()

    doc = Doctor(
        user_id=u_doc.id,
        specialization="Family Medicine",
        license_number="LIC-108",
        room_number="Room 108",
    )
    pat = Patient(user_id=u_pat.id)
    db_session.add_all([doc, pat])
    db_session.commit()

    today_date = date.today()
    appt_today = Appointment(
        patient_id=pat.id,
        doctor_id=doc.id,
        appointment_date=today_date,
        time_slot="10:00 - 10:30",
        status=AppointmentStatus.CONFIRMED,
        reason_for_visit="Headache",
    )
    appt_tomorrow = Appointment(
        patient_id=pat.id,
        doctor_id=doc.id,
        appointment_date=date(2099, 1, 1),
        time_slot="11:00 - 11:30",
        status=AppointmentStatus.CONFIRMED,
        reason_for_visit="Tomorrow visit",
    )
    db_session.add_all([appt_today, appt_tomorrow])
    db_session.commit()

    # Omit schedule_date -> should default to today
    resp = client.get(f"/api/appointments/doctor-schedule/{doc.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == appt_today.id
    assert data[0]["patient_name"] == "Patient Helen Doe"
    assert data[0]["patient_phone"] == "555-9988"
    assert data[0]["time_slot"] == "10:00 - 10:30"
    assert data[0]["status"] == AppointmentStatus.CONFIRMED.value
    assert data[0]["reason"] == "Headache"


def test_get_doctor_schedule_ordered_by_time_slot(db_session):
    u_doc = User(
        email="dr.ian@clinic.test",
        hashed_password="pw",
        full_name="Dr. Ian",
        role=UserRole.DOCTOR,
    )
    u_pat1 = User(
        email="pat8@clinic.test",
        hashed_password="pw",
        full_name="Pat Eight",
        role=UserRole.PATIENT,
        phone="555-0008",
    )
    u_pat2 = User(
        email="pat9@clinic.test",
        hashed_password="pw",
        full_name="Pat Nine",
        role=UserRole.PATIENT,
        phone="555-0009",
    )
    db_session.add_all([u_doc, u_pat1, u_pat2])
    db_session.commit()

    doc = Doctor(
        user_id=u_doc.id,
        specialization="Cardiology",
        license_number="LIC-109",
        room_number="Room 109",
    )
    pat1 = Patient(user_id=u_pat1.id)
    pat2 = Patient(user_id=u_pat2.id)
    db_session.add_all([doc, pat1, pat2])
    db_session.commit()

    target_date = "2026-09-20"
    target_d = date(2026, 9, 20)

    # Insert out of order
    appt2 = Appointment(
        patient_id=pat2.id,
        doctor_id=doc.id,
        appointment_date=target_d,
        time_slot="14:00 - 14:30",
        status=AppointmentStatus.CONFIRMED,
        reason_for_visit="Follow up",
    )
    appt1 = Appointment(
        patient_id=pat1.id,
        doctor_id=doc.id,
        appointment_date=target_d,
        time_slot="09:00 - 09:30",
        status=AppointmentStatus.CONFIRMED,
        reason_for_visit="Initial check",
    )
    db_session.add_all([appt2, appt1])
    db_session.commit()

    resp = client.get(f"/api/appointments/doctor-schedule/{doc.id}?schedule_date={target_date}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    # Check ordering by time_slot ascending
    assert data[0]["time_slot"] == "09:00 - 09:30"
    assert data[0]["patient_name"] == "Pat Eight"
    assert data[1]["time_slot"] == "14:00 - 14:30"
    assert data[1]["patient_name"] == "Pat Nine"


def test_get_doctor_schedule_invalid_date(db_session):
    resp = client.get("/api/appointments/doctor-schedule/1?schedule_date=invalid-date")
    assert resp.status_code == 400
    assert "date format" in resp.json()["detail"].lower()
