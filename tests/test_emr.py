import hashlib
import json
from datetime import date, datetime, timezone, timedelta
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
    Prescription,
)
from app.auth import create_access_token
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
    app.include_router(emr_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


# --- Step 1 Baseline Test from Brief ---

def test_prescription_hash_generation():
    token = hashlib.sha256(b"rx-101-sarah-connor").hexdigest()[:16]
    assert len(token) == 16


# --- EMR Retrieval Tests ---

def test_get_patient_emr_unauthenticated(client):
    response = client.get("/api/emr/patient/1")
    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


def test_get_patient_emr_forbidden_patient_role(client, db_session):
    u_patient = User(
        email="patient@clinic.test",
        hashed_password="pw",
        full_name="Patient Sarah",
        role=UserRole.PATIENT,
    )
    db_session.add(u_patient)
    db_session.commit()

    token = create_access_token({"sub": u_patient.email, "role": u_patient.role.value})
    response = client.get(
        "/api/emr/patient/1",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Insufficient privileges"


def test_get_patient_emr_not_found(client, db_session):
    u_doc = User(
        email="dr.smith@clinic.test",
        hashed_password="pw",
        full_name="Dr. John Smith",
        role=UserRole.DOCTOR,
    )
    db_session.add(u_doc)
    db_session.commit()

    token = create_access_token({"sub": u_doc.email, "role": u_doc.role.value})
    response = client.get(
        "/api/emr/patient/9999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Patient not found"


def test_get_patient_emr_success_empty_prescriptions(client, db_session):
    u_doc = User(
        email="dr.smith@clinic.test",
        hashed_password="pw",
        full_name="Dr. John Smith",
        role=UserRole.DOCTOR,
    )
    u_pat = User(
        email="patient.sarah@clinic.test",
        hashed_password="pw",
        full_name="Sarah Connor",
        role=UserRole.PATIENT,
    )
    db_session.add_all([u_doc, u_pat])
    db_session.commit()

    patient = Patient(
        user_id=u_pat.id,
        date_of_birth=date(1985, 4, 12),
        gender="Female",
        blood_group="A-",
        allergies="Penicillin, Sulfa drugs",
        medical_history="Mild asthma, fractured clavicle (2018)",
    )
    db_session.add(patient)
    db_session.commit()

    token = create_access_token({"sub": u_doc.email, "role": u_doc.role.value})
    response = client.get(
        f"/api/emr/patient/{patient.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["patient_id"] == patient.id
    assert data["name"] == "Sarah Connor"
    assert data["dob"] == "1985-04-12"
    assert data["gender"] == "Female"
    assert data["blood_group"] == "A-"
    assert data["allergies"] == "Penicillin, Sulfa drugs"
    assert data["medical_history"] == "Mild asthma, fractured clavicle (2018)"
    assert data["prescriptions"] == []


def test_get_patient_emr_roles_staff_and_admin(client, db_session):
    u_staff = User(
        email="staff.amy@clinic.test",
        hashed_password="pw",
        full_name="Staff Amy",
        role=UserRole.STAFF,
    )
    u_admin = User(
        email="admin.boss@clinic.test",
        hashed_password="pw",
        full_name="Admin Boss",
        role=UserRole.ADMIN,
    )
    u_pat = User(
        email="pat.tim@clinic.test",
        hashed_password="pw",
        full_name="Tim Green",
        role=UserRole.PATIENT,
    )
    db_session.add_all([u_staff, u_admin, u_pat])
    db_session.commit()

    patient = Patient(user_id=u_pat.id, date_of_birth=date(1995, 10, 20), gender="Male")
    db_session.add(patient)
    db_session.commit()

    staff_token = create_access_token({"sub": u_staff.email, "role": u_staff.role.value})
    resp_staff = client.get(
        f"/api/emr/patient/{patient.id}",
        headers={"Authorization": f"Bearer {staff_token}"},
    )
    assert resp_staff.status_code == 403

    admin_token = create_access_token({"sub": u_admin.email, "role": u_admin.role.value})
    resp_admin = client.get(
        f"/api/emr/patient/{patient.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp_admin.status_code == 403


def test_get_patient_emr_with_prescriptions_ordered(client, db_session):
    u_doc = User(
        email="dr.watson@clinic.test",
        hashed_password="pw",
        full_name="Dr. John Watson",
        role=UserRole.DOCTOR,
    )
    u_pat = User(
        email="pat.jane@clinic.test",
        hashed_password="pw",
        full_name="Jane Doe",
        role=UserRole.PATIENT,
    )
    db_session.add_all([u_doc, u_pat])
    db_session.commit()

    doc = Doctor(user_id=u_doc.id, specialization="General", license_number="DOC-001", room_number="101")
    pat = Patient(user_id=u_pat.id, date_of_birth=date(1992, 1, 1), gender="Female")
    db_session.add_all([doc, pat])
    db_session.commit()

    time_now = datetime.now(timezone.utc)
    time_earlier = time_now - timedelta(days=7)

    meds1 = [
        {"drug_name": "Ibuprofen", "dosage": "400mg", "frequency": "TID", "duration": "3 days", "instructions": "Take with food"}
    ]
    meds2 = [
        {"drug_name": "Amoxicillin", "dosage": "500mg", "frequency": "BID", "duration": "7 days", "instructions": "Complete course"}
    ]

    rx1 = Prescription(
        patient_id=pat.id,
        doctor_id=doc.id,
        diagnosis="Tension Headache",
        clinical_notes="Patient has stress-induced tension.",
        medications_json=json.dumps(meds1),
        qr_code_hash="1A2B3C4D5E6F7890",
        created_at=time_earlier,
    )
    rx2 = Prescription(
        patient_id=pat.id,
        doctor_id=doc.id,
        diagnosis="Bacterial Pharyngitis",
        clinical_notes="Throat erythema with exudate.",
        medications_json=json.dumps(meds2),
        qr_code_hash="9F8E7D6C5B4A3210",
        created_at=time_now,
    )
    db_session.add_all([rx1, rx2])
    db_session.commit()

    token = create_access_token({"sub": u_doc.email, "role": u_doc.role.value})
    response = client.get(
        f"/api/emr/patient/{pat.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    prescriptions = data["prescriptions"]
    assert len(prescriptions) == 2
    # rx2 should come first (descending by created_at)
    assert prescriptions[0]["id"] == rx2.id
    assert prescriptions[0]["diagnosis"] == "Bacterial Pharyngitis"
    assert prescriptions[0]["notes"] == "Throat erythema with exudate."
    assert prescriptions[0]["medications"] == meds2
    assert prescriptions[0]["qr_code_hash"] == "9F8E7D6C5B4A3210"
    assert prescriptions[0]["created_at"] == time_now.strftime("%Y-%m-%d %H:%M")

    # rx1 should be second
    assert prescriptions[1]["id"] == rx1.id
    assert prescriptions[1]["diagnosis"] == "Tension Headache"
    assert prescriptions[1]["medications"] == meds1


# --- Prescription Creation Tests ---

def test_create_prescription_unauthenticated(client):
    payload = {
        "patient_id": 1,
        "doctor_id": 1,
        "diagnosis": "Common Cold",
        "medications": [],
    }
    response = client.post("/api/emr/prescription/create", json=payload)
    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


def test_create_prescription_forbidden_patient_role(client, db_session):
    u_pat = User(
        email="patient.user@clinic.test",
        hashed_password="pw",
        full_name="Patient User",
        role=UserRole.PATIENT,
    )
    db_session.add(u_pat)
    db_session.commit()

    token = create_access_token({"sub": u_pat.email, "role": u_pat.role.value})
    payload = {
        "patient_id": 1,
        "doctor_id": 1,
        "diagnosis": "Self Prescribed",
        "medications": [],
    }
    response = client.post(
        "/api/emr/prescription/create",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Insufficient privileges"


def test_create_prescription_forbidden_staff_role(client, db_session):
    u_staff = User(
        email="staff.user@clinic.test",
        hashed_password="pw",
        full_name="Staff User",
        role=UserRole.STAFF,
    )
    db_session.add(u_staff)
    db_session.commit()

    token = create_access_token({"sub": u_staff.email, "role": u_staff.role.value})
    payload = {
        "patient_id": 1,
        "doctor_id": 1,
        "diagnosis": "Staff Prescribed",
        "medications": [],
    }
    response = client.post(
        "/api/emr/prescription/create",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Insufficient privileges"


def test_create_prescription_success_doctor(client, db_session):
    u_doc = User(
        email="dr.house@clinic.test",
        hashed_password="pw",
        full_name="Dr. Gregory House",
        role=UserRole.DOCTOR,
    )
    u_pat = User(
        email="pat.cameron@clinic.test",
        hashed_password="pw",
        full_name="Allison Cameron",
        role=UserRole.PATIENT,
    )
    db_session.add_all([u_doc, u_pat])
    db_session.commit()

    doc = Doctor(user_id=u_doc.id, specialization="Diagnostics", license_number="DOC-999", room_number="404")
    pat = Patient(user_id=u_pat.id)
    db_session.add_all([doc, pat])
    db_session.commit()

    token = create_access_token({"sub": u_doc.email, "role": u_doc.role.value})
    payload = {
        "patient_id": pat.id,
        "doctor_id": doc.id,
        "diagnosis": "Acute Bronchitis",
        "clinical_notes": "Patient presents with persistent dry cough and mild fever.",
        "medications": [
            {
                "drug_name": "Amoxicillin",
                "dosage": "500mg",
                "frequency": "Three times daily",
                "duration": "7 days",
                "instructions": "Take after meals",
            },
            {
                "drug_name": "Guaifenesin",
                "dosage": "200mg",
                "frequency": "Every 4 hours",
                "duration": "5 days",
                "instructions": "Drink plenty of water",
            },
        ],
    }

    response = client.post(
        "/api/emr/prescription/create",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["status"] == "success"
    assert "prescription_id" in res_data
    assert "qr_code_hash" in res_data

    qr_hash = res_data["qr_code_hash"]
    assert len(qr_hash) == 16
    assert qr_hash.isupper()
    # Hex validation
    int(qr_hash, 16)

    # Verify DB persistence
    rx = db_session.query(Prescription).filter(Prescription.id == res_data["prescription_id"]).first()
    assert rx is not None
    assert rx.patient_id == pat.id
    assert rx.doctor_id == doc.id
    assert rx.diagnosis == "Acute Bronchitis"
    assert rx.clinical_notes == "Patient presents with persistent dry cough and mild fever."
    assert rx.qr_code_hash == qr_hash

    meds_saved = json.loads(rx.medications_json)
    assert len(meds_saved) == 2
    assert meds_saved[0]["drug_name"] == "Amoxicillin"
    assert meds_saved[1]["drug_name"] == "Guaifenesin"


def test_create_prescription_forbidden_for_admin(client, db_session):
    u_admin = User(
        email="admin.emr@clinic.test",
        hashed_password="pw",
        full_name="Admin Director",
        role=UserRole.ADMIN,
    )
    u_doc = User(
        email="dr.doc2@clinic.test",
        hashed_password="pw",
        full_name="Dr. Doc Two",
        role=UserRole.DOCTOR,
    )
    u_pat = User(
        email="pat.pat2@clinic.test",
        hashed_password="pw",
        full_name="Pat Two",
        role=UserRole.PATIENT,
    )
    db_session.add_all([u_admin, u_doc, u_pat])
    db_session.commit()

    doc = Doctor(user_id=u_doc.id, specialization="Family Medicine", license_number="DOC-888", room_number="102")
    pat = Patient(user_id=u_pat.id)
    db_session.add_all([doc, pat])
    db_session.commit()

    admin_token = create_access_token({"sub": u_admin.email, "role": u_admin.role.value})
    payload = {
        "patient_id": pat.id,
        "doctor_id": doc.id,
        "diagnosis": "Seasonal Allergic Rhinitis",
        "clinical_notes": "Prescription entered by Admin on behalf of doctor.",
        "medications": [
            {
                "drug_name": "Cetirizine",
                "dosage": "10mg",
                "frequency": "Once daily at bedtime",
                "duration": "14 days",
                "instructions": "May cause drowsiness",
            }
        ],
    }

    response = client.post(
        "/api/emr/prescription/create",
        json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 403


def test_emr_full_flow_create_and_view(client, db_session):
    u_doc = User(
        email="dr.strange@clinic.test",
        hashed_password="pw",
        full_name="Dr. Stephen Strange",
        role=UserRole.DOCTOR,
    )
    u_pat = User(
        email="pat.peter@clinic.test",
        hashed_password="pw",
        full_name="Peter Parker",
        role=UserRole.PATIENT,
    )
    db_session.add_all([u_doc, u_pat])
    db_session.commit()

    doc = Doctor(user_id=u_doc.id, specialization="Neurology", license_number="DOC-007", room_number="301")
    pat = Patient(
        user_id=u_pat.id,
        date_of_birth=date(2001, 8, 10),
        gender="Male",
        blood_group="B+",
        allergies="None",
        medical_history="Spider bite reaction",
    )
    db_session.add_all([doc, pat])
    db_session.commit()

    token = create_access_token({"sub": u_doc.email, "role": u_doc.role.value})

    # Step A: Create prescription
    create_payload = {
        "patient_id": pat.id,
        "doctor_id": doc.id,
        "diagnosis": "Spider Bite Observation",
        "clinical_notes": "Monitor vitals and sensory perception changes.",
        "medications": [
            {
                "drug_name": "Antihistamine Syrup",
                "dosage": "10ml",
                "frequency": "Twice daily",
                "duration": "3 days",
                "instructions": "Shake well before use",
            }
        ],
    }
    create_resp = client.post(
        "/api/emr/prescription/create",
        json=create_payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create_resp.status_code == 200
    rx_id = create_resp.json()["prescription_id"]
    qr_hash = create_resp.json()["qr_code_hash"]

    # Step B: Retrieve EMR for patient
    emr_resp = client.get(
        f"/api/emr/patient/{pat.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert emr_resp.status_code == 200
    emr_data = emr_resp.json()
    assert emr_data["name"] == "Peter Parker"
    assert emr_data["allergies"] == "None"
    assert len(emr_data["prescriptions"]) == 1
    rx_item = emr_data["prescriptions"][0]
    assert rx_item["id"] == rx_id
    assert rx_item["diagnosis"] == "Spider Bite Observation"
    assert rx_item["notes"] == "Monitor vitals and sensory perception changes."
    assert rx_item["qr_code_hash"] == qr_hash
    assert len(rx_item["medications"]) == 1
    assert rx_item["medications"][0]["drug_name"] == "Antihistamine Syrup"
