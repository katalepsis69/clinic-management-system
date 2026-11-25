from datetime import datetime, timedelta, timezone
from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, Field
from app.config import get_settings
from app.database import get_db
from app.models import Appointment, AppointmentStatus, Doctor, Patient, QueueTicket, User, UserRole
from app.auth import get_current_user, require_roles

router = APIRouter(prefix="/api/appointments", tags=["Appointments & Schedule"])
settings = get_settings()


class BookAppointmentRequest(BaseModel):
    doctor_id: int
    appointment_date: str
    time_slot: str = Field(min_length=1, max_length=30)
    reason_for_visit: Optional[str] = Field(default=None, max_length=500)


@router.get("/doctors")
def list_doctors(db: Session = Depends(get_db)):
    doctors = (
        db.query(Doctor)
        .join(User)
        .filter(Doctor.is_available == True, User.is_approved == True)
        .all()
    )
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
    if app_date < settings.clinic_today():
        raise HTTPException(status_code=400, detail="Appointment date cannot be in the past")

    doctor = (
        db.query(Doctor)
        .join(User)
        .filter(Doctor.id == data.doctor_id, User.is_approved == True)
        .first()
    )
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


@router.get("/my")
def get_my_appointments(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.PATIENT])),
):
    patient = db.query(Patient).filter(Patient.user_id == current_user.id).first()
    if not patient:
        return []
    apps = (
        db.query(Appointment)
        .filter(Appointment.patient_id == patient.id)
        .order_by(Appointment.appointment_date.desc(), Appointment.id.desc())
        .limit(20)
        .all()
    )
    return [
        {
            "id": a.id,
            "doctor_name": a.doctor.user.full_name if a.doctor and a.doctor.user else "Clinic Physician",
            "specialization": a.doctor.specialization if a.doctor else "",
            "room_number": a.doctor.room_number if a.doctor else "N/A",
            "appointment_date": str(a.appointment_date),
            "time_slot": a.time_slot,
            "status": a.status.value if hasattr(a.status, "value") else str(a.status),
            "reason": a.reason_for_visit,
        }
        for a in apps
    ]


class UpdateAppointmentStatusRequest(BaseModel):
    status: Literal["confirmed", "completed", "cancelled"]


@router.get("/daily")
def get_daily_appointments(
    schedule_date: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.STAFF, UserRole.ADMIN])),
):
    if schedule_date:
        try:
            target_date = datetime.strptime(schedule_date, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD")
    else:
        target_date = settings.clinic_today()

    apps = (
        db.query(Appointment)
        .filter(Appointment.appointment_date == target_date)
        .order_by(Appointment.time_slot.asc(), Appointment.id.asc())
        .all()
    )
    return [
        {
            "id": a.id,
            "patient_id": a.patient_id,
            "patient_name": a.patient.user.full_name if a.patient and a.patient.user else "Unknown",
            "doctor_id": a.doctor_id,
            "doctor_name": a.doctor.user.full_name if a.doctor and a.doctor.user else "Clinic Physician",
            "room_number": a.doctor.room_number if a.doctor else "N/A",
            "appointment_date": str(a.appointment_date),
            "time_slot": a.time_slot,
            "status": a.status.value if hasattr(a.status, "value") else str(a.status),
            "reason": a.reason_for_visit,
        }
        for a in apps
    ]


@router.post("/{appointment_id}/status")
def update_appointment_status(
    appointment_id: int,
    data: UpdateAppointmentStatusRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.STAFF, UserRole.DOCTOR, UserRole.ADMIN])),
):
    appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if current_user.role == UserRole.DOCTOR:
        own = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
        if not own or appointment.doctor_id != own.id:
            raise HTTPException(status_code=403, detail="Doctors can only update their own appointments")

    appointment.status = AppointmentStatus(data.status)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Time slot is already booked by another appointment",
        )
    return {"status": "success", "appointment_id": appointment.id, "appointment_status": data.status}


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
        target_date = settings.clinic_today()

    apps = (
        db.query(Appointment)
        .filter(
            Appointment.doctor_id == doctor_id,
            Appointment.appointment_date == target_date,
        )
        .order_by(Appointment.time_slot.asc())
        .all()
    )

    items = [
        {
            "id": a.id,
            "entry_type": "appointment",
            "patient_id": a.patient_id,
            "patient_name": a.patient.user.full_name if a.patient and a.patient.user else "Unknown",
            "patient_phone": a.patient.user.phone if a.patient and a.patient.user else None,
            "time_slot": a.time_slot,
            "status": a.status.value if hasattr(a.status, "value") else str(a.status),
            "reason": a.reason_for_visit,
        }
        for a in apps
    ]

    # Include walk-in queue tickets issued on target_date in clinic timezone
    offset = timedelta(hours=settings.CLINIC_UTC_OFFSET)
    day_start_utc = datetime.combine(target_date, datetime.min.time()) - offset
    day_end_utc = day_start_utc + timedelta(days=1)
    walkins = (
        db.query(QueueTicket)
        .filter(
            QueueTicket.doctor_id == doctor_id,
            QueueTicket.issued_at >= day_start_utc,
            QueueTicket.issued_at < day_end_utc,
        )
        .order_by(QueueTicket.id.asc())
        .all()
    )
    for t in walkins:
        items.append({
            "id": t.id,
            "entry_type": "walk_in",
            "ticket_number": t.ticket_number,
            "patient_id": t.patient_id,
            "patient_name": t.patient.user.full_name if t.patient and t.patient.user else "Walk-in",
            "patient_phone": t.patient.user.phone if t.patient and t.patient.user else None,
            "time_slot": f"Walk-in ({t.ticket_number})",
            "status": t.status.value if hasattr(t.status, "value") else str(t.status),
            "reason": f"Priority: {t.priority or 'normal'}",
        })

    return items


@router.post("/{appointment_id}/cancel")
def cancel_appointment(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cancel an appointment. The owning patient, the appointment's doctor, or
    staff/admin may cancel. Reschedule = cancel + book again (the freed slot is
    immediately bookable thanks to the partial unique index)."""
    appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")

    allowed = False
    if current_user.role in (UserRole.STAFF, UserRole.ADMIN):
        allowed = True
    elif current_user.role == UserRole.PATIENT:
        patient = db.query(Patient).filter(Patient.user_id == current_user.id).first()
        allowed = patient is not None and appointment.patient_id == patient.id
    elif current_user.role == UserRole.DOCTOR:
        doctor = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
        allowed = doctor is not None and appointment.doctor_id == doctor.id
    if not allowed:
        raise HTTPException(status_code=403, detail="Not allowed to cancel this appointment")

    if appointment.status == AppointmentStatus.CANCELLED:
        raise HTTPException(status_code=409, detail="Appointment is already cancelled")

    appointment.status = AppointmentStatus.CANCELLED
    db.commit()
    return {"status": "success", "appointment_id": appointment.id, "appointment_status": "cancelled"}
