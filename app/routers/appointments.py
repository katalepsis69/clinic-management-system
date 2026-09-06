from datetime import date, datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, Field
from app.database import get_db
from app.models import Appointment, AppointmentStatus, Doctor, Patient, User, UserRole
from app.auth import get_current_user, require_roles

router = APIRouter(prefix="/api/appointments", tags=["Appointments & Schedule"])
doctors_router = APIRouter(prefix="/api/doctors", tags=["Doctors"])


class BookAppointmentRequest(BaseModel):
    doctor_id: int
    appointment_date: str
    time_slot: str = Field(min_length=1, max_length=30)
    reason_for_visit: Optional[str] = Field(default=None, max_length=500)


@router.get("/doctors")
def list_doctors(db: Session = Depends(get_db)):
    doctors = db.query(Doctor).filter(Doctor.is_available == True).all()
    return [
        {
            "id": d.id,
            "name": d.user.full_name if d.user else "Unknown Doctor",
            "specialization": d.specialization,
            "room_number": d.room_number,
            "fee": float(d.consultation_fee) if d.consultation_fee is not None else 0.0,
        }
        for d in doctors
    ]


@doctors_router.get("/list")
def list_doctors_alias(db: Session = Depends(get_db)):
    """Alias for /api/doctors/list returning available doctors."""
    return list_doctors(db=db)


@router.post("/book")
def book_appointment(
    data: BookAppointmentRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = db.query(Patient).filter(Patient.user_id == user.id).first()
    if not patient:
        raise HTTPException(status_code=400, detail="User is not registered as a patient")

    try:
        app_date = datetime.strptime(data.appointment_date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=400, detail="Invalid date format, expected YYYY-MM-DD"
        )
    if app_date < date.today():
        raise HTTPException(status_code=400, detail="Appointment date cannot be in the past")

    doctor = db.query(Doctor).filter(Doctor.id == data.doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    exists = (
        db.query(Appointment)
        .filter(
            Appointment.doctor_id == data.doctor_id,
            Appointment.appointment_date == app_date,
            Appointment.time_slot == data.time_slot,
            Appointment.status != AppointmentStatus.CANCELLED,
        )
        .first()
    )
    if exists:
        raise HTTPException(status_code=409, detail="This time slot is already booked")

    app = Appointment(
        patient_id=patient.id,
        doctor_id=data.doctor_id,
        appointment_date=app_date,
        time_slot=data.time_slot,
        reason_for_visit=data.reason_for_visit,
        status=AppointmentStatus.CONFIRMED,
    )
    db.add(app)
    try:
        db.commit()
    except IntegrityError:
        # ux_appointment_slot lost the race with a concurrent booking
        db.rollback()
        raise HTTPException(status_code=409, detail="This time slot is already booked")
    db.refresh(app)
    return {"status": "success", "appointment_id": app.id}


@router.get("/doctor-schedule/{doctor_id}")
def get_doctor_schedule(
    doctor_id: int,
    schedule_date: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.DOCTOR, UserRole.STAFF, UserRole.ADMIN])),
):
    # Doctors may only view their own schedule; staff/admin view any.
    if current_user.role == UserRole.DOCTOR:
        own = db.query(Doctor).filter(Doctor.id == doctor_id, Doctor.user_id == current_user.id).first()
        if not own:
            raise HTTPException(status_code=403, detail="Doctors can only view their own schedule")
    if schedule_date:
        try:
            target_date = datetime.strptime(schedule_date, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=400, detail="Invalid date format, expected YYYY-MM-DD"
            )
    else:
        target_date = date.today()

    apps = (
        db.query(Appointment)
        .filter(
            Appointment.doctor_id == doctor_id,
            Appointment.appointment_date == target_date,
        )
        .order_by(Appointment.time_slot.asc())
        .all()
    )

    return [
        {
            "id": a.id,
            "patient_name": a.patient.user.full_name if a.patient and a.patient.user else "Unknown",
            "patient_phone": a.patient.user.phone if a.patient and a.patient.user else None,
            "time_slot": a.time_slot,
            "status": a.status.value if hasattr(a.status, "value") else str(a.status),
            "reason": a.reason_for_visit,
        }
        for a in apps
    ]
