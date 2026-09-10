import enum
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Date, Numeric, Text, ForeignKey, Enum as SQLEnum, Float, Index, CheckConstraint, text
from sqlalchemy.orm import relationship
from app.database import Base

class UserRole(str, enum.Enum):
    PATIENT = "patient"
    DOCTOR = "doctor"
    STAFF = "staff"
    ADMIN = "admin"

class AppointmentStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class QueueStatus(str, enum.Enum):
    WAITING = "waiting"
    CALLED = "called"
    IN_CONSULTATION = "in_consultation"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(SQLEnum(UserRole), default=UserRole.PATIENT, nullable=False)
    phone = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    patient = relationship("Patient", back_populates="user", uselist=False)
    doctor = relationship("Doctor", back_populates="user", uselist=False)

class Patient(Base):
    __tablename__ = "patients"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    date_of_birth = Column(Date, nullable=True)
    gender = Column(String(20), nullable=True)
    blood_group = Column(String(10), nullable=True)
    emergency_contact_name = Column(String(255), nullable=True)
    emergency_contact_phone = Column(String(50), nullable=True)
    allergies = Column(Text, nullable=True)
    medical_history = Column(Text, nullable=True)

    user = relationship("User", back_populates="patient")
    appointments = relationship("Appointment", back_populates="patient")
    queue_tickets = relationship("QueueTicket", back_populates="patient")
    invoices = relationship("Invoice", back_populates="patient")

class Doctor(Base):
    __tablename__ = "doctors"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    specialization = Column(String(100), nullable=False)
    license_number = Column(String(50), nullable=False)
    room_number = Column(String(20), nullable=False)
    consultation_fee = Column(Numeric(10, 2), default=50.00)
    is_available = Column(Boolean, default=True)

    user = relationship("User", back_populates="doctor")
    appointments = relationship("Appointment", back_populates="doctor")
    queue_tickets = relationship("QueueTicket", back_populates="doctor")

class Appointment(Base):
    __tablename__ = "appointments"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    appointment_date = Column(Date, nullable=False)
    time_slot = Column(String(30), nullable=False)
    status = Column(SQLEnum(AppointmentStatus), default=AppointmentStatus.CONFIRMED)
    reason_for_visit = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Atomic slot guard: one live appointment per doctor/date/slot (cancelled slots free to rebook).
    __table_args__ = (
        Index(
            "ux_appointment_slot",
            "doctor_id", "appointment_date", "time_slot",
            unique=True,
            sqlite_where=text("status != 'CANCELLED'"),
            postgresql_where=text("status != 'CANCELLED'"),
        ),
    )

    patient = relationship("Patient", back_populates="appointments")
    doctor = relationship("Doctor", back_populates="appointments")

class QueueTicket(Base):
    __tablename__ = "queue_tickets"
    id = Column(Integer, primary_key=True, index=True)
    ticket_number = Column(String(20), unique=True, index=True, nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    appointment_id = Column(Integer, ForeignKey("appointments.id"), nullable=True)
    status = Column(SQLEnum(QueueStatus), default=QueueStatus.WAITING)
    priority = Column(String(20), default="normal")
    issued_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    called_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    patient = relationship("Patient", back_populates="queue_tickets")
    doctor = relationship("Doctor", back_populates="queue_tickets")

class Prescription(Base):
    __tablename__ = "prescriptions"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    appointment_id = Column(Integer, ForeignKey("appointments.id"), nullable=True)
    diagnosis = Column(Text, nullable=False)
    clinical_notes = Column(Text, nullable=True)
    medications_json = Column(Text, nullable=False)
    qr_code_hash = Column(String(100), unique=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class Invoice(Base):
    __tablename__ = "invoices"
    id = Column(Integer, primary_key=True, index=True)
    receipt_number = Column(String(50), unique=True, index=True, nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    queue_ticket_id = Column(Integer, ForeignKey("queue_tickets.id"), nullable=True)
    consultation_fee = Column(Numeric(10, 2), default=0.0)
    medication_fee = Column(Numeric(10, 2), default=0.0)
    other_fees = Column(Numeric(10, 2), default=0.0)
    discount_amount = Column(Numeric(10, 2), default=0.0)
    total_amount = Column(Numeric(10, 2), default=0.0)
    payment_method = Column(String(30), default="cash")
    payment_status = Column(String(20), default="paid")
    paid_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    patient = relationship("Patient", back_populates="invoices")
    queue_ticket = relationship("QueueTicket")

class PatientFeedback(Base):
    __tablename__ = "patient_feedback"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    rating = Column(Integer, nullable=False)
    tags_json = Column(Text, default="[]")
    comment_text = Column(Text, nullable=False)
    sentiment_label = Column(String(20), nullable=False)
    sentiment_score = Column(Float, nullable=False)
    flagged_critical = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_feedback_rating"),
    )

class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(100), index=True, nullable=False)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    sender_name = Column(String(100), nullable=False)
    sender_role = Column(String(20), nullable=False)
    message_text = Column(Text, nullable=False)
    is_bot_reply = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
