import os
import tempfile
import pytest
from datetime import date, datetime, timezone
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.models import (
    Base,
    User,
    Patient,
    Doctor,
    Appointment,
    QueueTicket,
    Prescription,
    Invoice,
    PatientFeedback,
    ChatMessage,
    UserRole,
    AppointmentStatus,
    QueueStatus,
)
from app.database import engine as app_engine, SessionLocal, get_db


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_create_user_and_patient(db_session):
    user = User(
        email="test@patient.com",
        hashed_password="pw",
        full_name="John Doe",
        role="patient",
        phone="123456",
    )
    db_session.add(user)
    db_session.commit()

    patient = Patient(
        user_id=user.id,
        gender="Male",
        emergency_contact_name="Jane",
        emergency_contact_phone="999",
    )
    db_session.add(patient)
    db_session.commit()

    assert patient.user.email == "test@patient.com"
    assert patient.gender == "Male"
    assert user.patient.id == patient.id


def test_create_doctor_and_appointment(db_session):
    doc_user = User(
        email="doctor@clinic.com",
        hashed_password="pw",
        full_name="Dr. Smith",
        role=UserRole.DOCTOR,
    )
    pat_user = User(
        email="pat2@clinic.com",
        hashed_password="pw",
        full_name="Patient Two",
        role=UserRole.PATIENT,
    )
    db_session.add_all([doc_user, pat_user])
    db_session.commit()

    doctor = Doctor(
        user_id=doc_user.id,
        specialization="Cardiology",
        license_number="LIC-12345",
        room_number="Room 101",
        consultation_fee=75.50,
    )
    patient = Patient(user_id=pat_user.id, gender="Female")
    db_session.add_all([doctor, patient])
    db_session.commit()

    appt = Appointment(
        patient_id=patient.id,
        doctor_id=doctor.id,
        appointment_date=date(2026, 9, 10),
        time_slot="09:00 - 09:30",
        status=AppointmentStatus.CONFIRMED,
        reason_for_visit="Routine checkup",
    )
    db_session.add(appt)
    db_session.commit()

    assert appt.id is not None
    assert appt.patient.id == patient.id
    assert appt.doctor.specialization == "Cardiology"
    assert len(doctor.appointments) == 1
    assert len(patient.appointments) == 1


def test_queue_ticket_prescription_invoice(db_session):
    doc_user = User(
        email="doc3@clinic.com",
        hashed_password="pw",
        full_name="Dr. House",
        role=UserRole.DOCTOR,
    )
    pat_user = User(
        email="pat3@clinic.com",
        hashed_password="pw",
        full_name="Patient Three",
        role=UserRole.PATIENT,
    )
    db_session.add_all([doc_user, pat_user])
    db_session.commit()

    doctor = Doctor(
        user_id=doc_user.id,
        specialization="Diagnostics",
        license_number="LIC-999",
        room_number="Room 303",
    )
    patient = Patient(user_id=pat_user.id, gender="Male")
    db_session.add_all([doctor, patient])
    db_session.commit()

    ticket = QueueTicket(
        ticket_number="A001",
        patient_id=patient.id,
        doctor_id=doctor.id,
        status=QueueStatus.WAITING,
        priority="high",
    )
    db_session.add(ticket)
    db_session.commit()

    prescription = Prescription(
        patient_id=patient.id,
        doctor_id=doctor.id,
        diagnosis="Hypertension",
        clinical_notes="Monitor BP daily",
        medications_json='[{"name": "Lisinopril", "dosage": "10mg"}]',
        qr_code_hash="qr-hash-12345",
    )
    db_session.add(prescription)

    invoice = Invoice(
        receipt_number="INV-20260905-001",
        patient_id=patient.id,
        queue_ticket_id=ticket.id,
        consultation_fee=50.00,
        medication_fee=25.00,
        total_amount=75.00,
        payment_method="cash",
        payment_status="paid",
    )
    db_session.add(invoice)
    db_session.commit()

    assert ticket.id is not None
    assert ticket.patient.id == patient.id
    assert prescription.qr_code_hash == "qr-hash-12345"
    assert invoice.total_amount == 75.00


def test_patient_feedback_and_chat_message(db_session):
    user = User(
        email="pat4@clinic.com",
        hashed_password="pw",
        full_name="Patient Four",
        role=UserRole.PATIENT,
    )
    db_session.add(user)
    db_session.commit()

    patient = Patient(user_id=user.id)
    db_session.add(patient)
    db_session.commit()

    feedback = PatientFeedback(
        patient_id=patient.id,
        rating=5,
        tags_json='["friendly", "fast"]',
        comment_text="Great clinic service!",
        sentiment_label="positive",
        sentiment_score=0.98,
        flagged_critical=False,
    )
    db_session.add(feedback)

    chat = ChatMessage(
        session_id="session-123",
        sender_id=user.id,
        sender_name="Patient Four",
        sender_role="patient",
        message_text="Hello, what are your operating hours?",
        is_bot_reply=False,
    )
    db_session.add(chat)
    db_session.commit()

    assert feedback.id is not None
    assert feedback.sentiment_score == 0.98
    assert chat.id is not None
    assert chat.session_id == "session-123"


def test_sqlite_wal_and_busy_timeout_pragmas():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_path = tmp.name

    test_engine = None
    try:
        db_url = f"sqlite:///{tmp_path.replace(chr(92), '/')}"
        test_engine = create_engine(db_url)
        with test_engine.connect() as conn:
            journal_mode = conn.execute(text("PRAGMA journal_mode;")).scalar()
            busy_timeout = conn.execute(text("PRAGMA busy_timeout;")).scalar()
            assert journal_mode.lower() == "wal"
            assert busy_timeout == 5000
    finally:
        if test_engine is not None:
            test_engine.dispose()
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def test_get_db_generator():
    db_gen = get_db()
    session = next(db_gen)
    assert session is not None
    try:
        next(db_gen)
    except StopIteration:
        pass
