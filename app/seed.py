from datetime import date
from sqlalchemy.orm import Session
from app.models import User, Patient, Doctor, UserRole
from app.auth import get_password_hash


def seed_demo_data(db: Session):
    if db.query(User).first():
        return

    admin = User(
        email="admin@demo.com",
        hashed_password=get_password_hash("admin123"),
        full_name="Clinic Director",
        role=UserRole.ADMIN,
        phone="555-0100",
    )
    staff = User(
        email="staff@demo.com",
        hashed_password=get_password_hash("staff123"),
        full_name="Reception Staff",
        role=UserRole.STAFF,
        phone="555-0101",
    )
    doctor_u = User(
        email="doctor@demo.com",
        hashed_password=get_password_hash("doctor123"),
        full_name="Dr. Emily Stone",
        role=UserRole.DOCTOR,
        phone="555-0102",
    )
    patient_u = User(
        email="patient@demo.com",
        hashed_password=get_password_hash("patient123"),
        full_name="Sarah Connor",
        role=UserRole.PATIENT,
        phone="555-0103",
    )

    db.add_all([admin, staff, doctor_u, patient_u])
    db.commit()

    doctor = Doctor(
        user_id=doctor_u.id,
        specialization="Cardiology & General Medicine",
        license_number="MD-98421",
        room_number="Room 102",
        consultation_fee=60.00,
    )
    patient = Patient(
        user_id=patient_u.id,
        date_of_birth=date(1990, 5, 14),
        gender="Female",
        blood_group="O+",
        emergency_contact_name="John Connor",
        emergency_contact_phone="555-9999",
        allergies="Penicillin",
        medical_history="Mild Asthma",
    )

    db.add_all([doctor, patient])
    db.commit()
