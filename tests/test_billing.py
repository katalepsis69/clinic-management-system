import re
from datetime import datetime, timezone
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
    QueueTicket,
    Invoice,
)
from app.auth import create_access_token
from app.routers.billing import router as billing_router


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
    app.include_router(billing_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


# --- Step 1 Baseline Calculation Test from Brief ---

def test_invoice_calculation():
    consultation = 50.0
    medication = 25.50
    discount = 5.0
    total = (consultation + medication) - discount
    assert total == 70.50


# --- Authentication and Authorization Tests ---

def test_create_invoice_unauthenticated(client):
    payload = {
        "patient_id": 1,
        "consultation_fee": 50.0,
        "medication_fee": 25.0,
    }
    response = client.post("/api/billing/create", json=payload)
    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


def test_create_invoice_forbidden_patient_role(client, db_session):
    u_patient = User(
        email="patient@clinic.test",
        hashed_password="pw",
        full_name="Patient User",
        role=UserRole.PATIENT,
    )
    db_session.add(u_patient)
    db_session.commit()

    token = create_access_token({"sub": u_patient.email, "role": u_patient.role.value})
    payload = {
        "patient_id": 1,
        "consultation_fee": 50.0,
    }
    response = client.post(
        "/api/billing/create",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Insufficient privileges"


def test_create_invoice_forbidden_doctor_role(client, db_session):
    u_doctor = User(
        email="doctor@clinic.test",
        hashed_password="pw",
        full_name="Dr. Doctor",
        role=UserRole.DOCTOR,
    )
    db_session.add(u_doctor)
    db_session.commit()

    token = create_access_token({"sub": u_doctor.email, "role": u_doctor.role.value})
    payload = {
        "patient_id": 1,
        "consultation_fee": 50.0,
    }
    response = client.post(
        "/api/billing/create",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Insufficient privileges"


# --- Invoice Creation Tests ---

def test_create_invoice_success_staff(client, db_session):
    u_staff = User(
        email="staff@clinic.test",
        hashed_password="pw",
        full_name="Receptionist Sarah",
        role=UserRole.STAFF,
    )
    u_pat = User(
        email="patient.john@clinic.test",
        hashed_password="pw",
        full_name="John Doe",
        role=UserRole.PATIENT,
    )
    db_session.add_all([u_staff, u_pat])
    db_session.commit()

    patient = Patient(user_id=u_pat.id, gender="Male")
    db_session.add(patient)
    db_session.commit()

    staff_token = create_access_token({"sub": u_staff.email, "role": u_staff.role.value})
    payload = {
        "patient_id": patient.id,
        "consultation_fee": 60.0,
        "medication_fee": 35.50,
        "other_fees": 10.0,
        "discount_amount": 5.50,
        "payment_method": "credit_card",
    }

    response = client.post(
        "/api/billing/create",
        json=payload,
        headers={"Authorization": f"Bearer {staff_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "invoice_id" in data
    assert "receipt_number" in data
    assert data["total"] == 100.0  # (60.0 + 35.50 + 10.0) - 5.50 = 100.00

    # Validate receipt number format REC-YYYYMMDD-XXXXXX
    receipt_pattern = r"^REC-\d{8}-[A-F0-9]{6}$"
    assert re.match(receipt_pattern, data["receipt_number"]) is not None

    # Verify DB persistence
    inv = db_session.query(Invoice).filter(Invoice.id == data["invoice_id"]).first()
    assert inv is not None
    assert inv.patient_id == patient.id
    assert inv.receipt_number == data["receipt_number"]
    assert float(inv.consultation_fee) == 60.0
    assert float(inv.medication_fee) == 35.50
    assert float(inv.other_fees) == 10.0
    assert float(inv.discount_amount) == 5.50
    assert float(inv.total_amount) == 100.0
    assert inv.payment_method == "credit_card"
    assert inv.payment_status == "paid"
    assert inv.paid_at is not None


def test_create_invoice_success_admin_with_queue_ticket(client, db_session):
    u_admin = User(
        email="admin@clinic.test",
        hashed_password="pw",
        full_name="Admin Director",
        role=UserRole.ADMIN,
    )
    u_pat = User(
        email="patient.jane@clinic.test",
        hashed_password="pw",
        full_name="Jane Smith",
        role=UserRole.PATIENT,
    )
    u_doc = User(
        email="dr.doc@clinic.test",
        hashed_password="pw",
        full_name="Dr. House",
        role=UserRole.DOCTOR,
    )
    db_session.add_all([u_admin, u_pat, u_doc])
    db_session.commit()

    patient = Patient(user_id=u_pat.id, gender="Female")
    db_session.add(patient)
    db_session.commit()

    ticket = QueueTicket(
        ticket_number="A010",
        patient_id=patient.id,
        doctor_id=u_doc.id,
    )
    db_session.add(ticket)
    db_session.commit()

    admin_token = create_access_token({"sub": u_admin.email, "role": u_admin.role.value})
    payload = {
        "patient_id": patient.id,
        "queue_ticket_id": ticket.id,
        "consultation_fee": 50.0,
        "medication_fee": 20.0,
        "other_fees": 0.0,
        "discount_amount": 0.0,
        "payment_method": "cash",
    }

    response = client.post(
        "/api/billing/create",
        json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["total"] == 70.0

    inv = db_session.query(Invoice).filter(Invoice.id == data["invoice_id"]).first()
    assert inv is not None
    assert inv.queue_ticket_id == ticket.id
    assert inv.payment_method == "cash"


def test_create_invoice_defaults(client, db_session):
    u_staff = User(
        email="staff2@clinic.test",
        hashed_password="pw",
        full_name="Staff Worker",
        role=UserRole.STAFF,
    )
    u_pat = User(
        email="patient.bob@clinic.test",
        hashed_password="pw",
        full_name="Bob Vance",
        role=UserRole.PATIENT,
    )
    db_session.add_all([u_staff, u_pat])
    db_session.commit()

    patient = Patient(user_id=u_pat.id)
    db_session.add(patient)
    db_session.commit()

    staff_token = create_access_token({"sub": u_staff.email, "role": u_staff.role.value})
    payload = {"patient_id": patient.id}

    response = client.post(
        "/api/billing/create",
        json=payload,
        headers={"Authorization": f"Bearer {staff_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["total"] == 0.0

    inv = db_session.query(Invoice).filter(Invoice.id == data["invoice_id"]).first()
    assert float(inv.total_amount) == 0.0
    assert inv.payment_method == "cash"
    assert inv.queue_ticket_id is None


# --- Invoice List Tests ---

def test_list_invoices_unauthenticated(client):
    response = client.get("/api/billing/list")
    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


def test_list_invoices_forbidden_patient_role(client, db_session):
    u_pat = User(
        email="pat.forbidden@clinic.test",
        hashed_password="pw",
        full_name="Forbidden Patient",
        role=UserRole.PATIENT,
    )
    db_session.add(u_pat)
    db_session.commit()

    token = create_access_token({"sub": u_pat.email, "role": u_pat.role.value})
    response = client.get(
        "/api/billing/list",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Insufficient privileges"


def test_list_invoices_empty(client, db_session):
    u_staff = User(
        email="staff3@clinic.test",
        hashed_password="pw",
        full_name="Staff Person",
        role=UserRole.STAFF,
    )
    db_session.add(u_staff)
    db_session.commit()

    token = create_access_token({"sub": u_staff.email, "role": u_staff.role.value})
    response = client.get(
        "/api/billing/list",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json() == []


def test_list_invoices_multiple_and_ordering(client, db_session):
    u_staff = User(
        email="staff4@clinic.test",
        hashed_password="pw",
        full_name="Billing Clerk",
        role=UserRole.STAFF,
    )
    u_pat1 = User(
        email="pat1@clinic.test",
        hashed_password="pw",
        full_name="Patient One",
        role=UserRole.PATIENT,
    )
    u_pat2 = User(
        email="pat2@clinic.test",
        hashed_password="pw",
        full_name="Patient Two",
        role=UserRole.PATIENT,
    )
    db_session.add_all([u_staff, u_pat1, u_pat2])
    db_session.commit()

    patient1 = Patient(user_id=u_pat1.id)
    patient2 = Patient(user_id=u_pat2.id)
    db_session.add_all([patient1, patient2])
    db_session.commit()

    inv1 = Invoice(
        receipt_number="REC-20260905-AAAAAA",
        patient_id=patient1.id,
        consultation_fee=40.0,
        medication_fee=10.0,
        total_amount=50.0,
        payment_method="cash",
        payment_status="paid",
        paid_at=datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc),
    )
    inv2 = Invoice(
        receipt_number="REC-20260905-BBBBBB",
        patient_id=patient2.id,
        consultation_fee=60.0,
        medication_fee=30.0,
        total_amount=90.0,
        payment_method="card",
        payment_status="paid",
        paid_at=datetime(2026, 9, 5, 11, 30, tzinfo=timezone.utc),
    )
    db_session.add_all([inv1, inv2])
    db_session.commit()

    token = create_access_token({"sub": u_staff.email, "role": u_staff.role.value})
    response = client.get(
        "/api/billing/list",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 2

    # Descending ID order: inv2 first, then inv1
    assert items[0]["id"] == inv2.id
    assert items[0]["receipt_number"] == "REC-20260905-BBBBBB"
    assert items[0]["patient_name"] == "Patient Two"
    assert items[0]["total_amount"] == 90.0
    assert items[0]["payment_method"] == "card"
    assert items[0]["paid_at"] == "2026-09-05 11:30"

    assert items[1]["id"] == inv1.id
    assert items[1]["receipt_number"] == "REC-20260905-AAAAAA"
    assert items[1]["patient_name"] == "Patient One"
    assert items[1]["total_amount"] == 50.0
    assert items[1]["payment_method"] == "cash"
    assert items[1]["paid_at"] == "2026-09-05 10:00"


# --- Receipt and Invoice Lookup Tests ---

def test_get_receipt_by_number(client, db_session):
    u_admin = User(
        email="admin2@clinic.test",
        hashed_password="pw",
        full_name="Admin Boss",
        role=UserRole.ADMIN,
    )
    u_pat = User(
        email="pat3@clinic.test",
        hashed_password="pw",
        full_name="Alice Cooper",
        role=UserRole.PATIENT,
    )
    db_session.add_all([u_admin, u_pat])
    db_session.commit()

    patient = Patient(user_id=u_pat.id)
    db_session.add(patient)
    db_session.commit()

    inv = Invoice(
        receipt_number="REC-20260905-LKP123",
        patient_id=patient.id,
        consultation_fee=50.0,
        medication_fee=25.0,
        other_fees=5.0,
        discount_amount=10.0,
        total_amount=70.0,
        payment_method="insurance",
        payment_status="paid",
        paid_at=datetime(2026, 9, 5, 14, 0, tzinfo=timezone.utc),
    )
    db_session.add(inv)
    db_session.commit()

    token = create_access_token({"sub": u_admin.email, "role": u_admin.role.value})

    # Found
    resp = client.get(
        "/api/billing/receipt/REC-20260905-LKP123",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    receipt_data = resp.json()
    assert receipt_data["receipt_number"] == "REC-20260905-LKP123"
    assert receipt_data["patient_name"] == "Alice Cooper"
    assert receipt_data["consultation_fee"] == 50.0
    assert receipt_data["medication_fee"] == 25.0
    assert receipt_data["other_fees"] == 5.0
    assert receipt_data["discount_amount"] == 10.0
    assert receipt_data["total_amount"] == 70.0
    assert receipt_data["payment_method"] == "insurance"

    # Not found
    resp_404 = client.get(
        "/api/billing/receipt/REC-NONEXISTENT",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_404.status_code == 404
    assert resp_404.json()["detail"] == "Invoice not found"


def test_get_invoice_by_id(client, db_session):
    u_staff = User(
        email="staff5@clinic.test",
        hashed_password="pw",
        full_name="Staff Inspector",
        role=UserRole.STAFF,
    )
    u_pat = User(
        email="pat4@clinic.test",
        hashed_password="pw",
        full_name="Charlie Brown",
        role=UserRole.PATIENT,
    )
    db_session.add_all([u_staff, u_pat])
    db_session.commit()

    patient = Patient(user_id=u_pat.id)
    db_session.add(patient)
    db_session.commit()

    inv = Invoice(
        receipt_number="REC-20260905-ID001",
        patient_id=patient.id,
        consultation_fee=75.0,
        total_amount=75.0,
        payment_method="cash",
        payment_status="paid",
    )
    db_session.add(inv)
    db_session.commit()

    token = create_access_token({"sub": u_staff.email, "role": u_staff.role.value})

    # Found
    resp = client.get(
        f"/api/billing/{inv.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == inv.id
    assert resp.json()["patient_name"] == "Charlie Brown"

    # Not found
    resp_404 = client.get(
        "/api/billing/99999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_404.status_code == 404
    assert resp_404.json()["detail"] == "Invoice not found"
