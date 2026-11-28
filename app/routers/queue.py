from datetime import datetime, timezone
import secrets
from typing import Literal, Optional
import uuid
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, Field

from app.database import get_db
from app.models import Appointment, QueueTicket, QueueStatus, Patient, Doctor, User, UserRole
from app.auth import get_current_user, get_password_hash, require_roles
from app.websocket_manager import queue_manager

router = APIRouter(prefix="/api/queue", tags=["Queue Management"])


class IssueTicketRequest(BaseModel):
    doctor_id: int
    # ponytail: staff may issue walk-ins for another patient; patients are always self-issued
    patient_id: Optional[int] = None
    appointment_id: Optional[int] = None
    priority: Literal["normal", "urgent"] = "normal"


class WalkinRegisterRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=50)
    gender: Optional[str] = Field(default=None, max_length=20)
    allergies: Optional[str] = Field(default=None, max_length=500)
    doctor_id: int
    priority: Literal["normal", "urgent"] = "normal"


class AdvanceTicketRequest(BaseModel):
    ticket_id: int
    to: Literal["in_consultation", "completed", "cancelled"]


# Allowed status transitions for /advance; everything else 409s.
ADVANCE_FROM = {
    "in_consultation": {QueueStatus.CALLED},
    "completed": {QueueStatus.CALLED, QueueStatus.IN_CONSULTATION},
    "cancelled": {QueueStatus.WAITING, QueueStatus.CALLED},
}


@router.get("/patients")
def search_patients(
    q: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.STAFF, UserRole.DOCTOR, UserRole.ADMIN])),
):
    """Lookup approved patient IDs by name or numeric ID for front-desk check-in, billing, and EMR."""
    query = db.query(Patient).join(User).filter(User.is_approved == True)
    term = q.strip()
    if term:
        if term.isdigit():
            query = query.filter((Patient.id == int(term)) | (User.full_name.ilike(f"%{term}%")))
        else:
            query = query.filter(User.full_name.ilike(f"%{term}%"))
    patients = query.order_by(Patient.id.asc()).limit(15 if term else 100).all()
    return [
        {
            "id": p.id,
            "full_name": p.user.full_name if p.user else f"Patient #{p.id}",
            "phone": p.user.phone if p.user else None,
        }
        for p in patients
    ]


@router.get("/live-status")
def get_live_status(db: Session = Depends(get_db)):
    # ponytail: intentionally public — the TV display polls it; response carries
    # ticket numbers only, no patient-identifying data.
    called = (
        db.query(QueueTicket)
        .filter(QueueTicket.status.in_([QueueStatus.CALLED, QueueStatus.IN_CONSULTATION]))
        .order_by(QueueTicket.called_at.desc())
        .first()
    )
    waiting = (
        db.query(QueueTicket)
        .filter(QueueTicket.status == QueueStatus.WAITING)
        .order_by(QueueTicket.id.asc())
        .all()
    )

    return {
        "currently_serving": called.ticket_number if called else "None",
        "currently_serving_id": called.id if called else None,
        "currently_serving_room": called.doctor.room_number if called and called.doctor else "N/A",
        "waiting_count": len(waiting),
        "waiting_tickets": [t.ticket_number for t in waiting],
        "estimated_wait_minutes": len(waiting) * 10,
    }


def _allocate_queue_ticket(
    db: Session,
    patient_id: int,
    doctor_id: int,
    priority: str,
    appointment_id: Optional[int] = None,
) -> QueueTicket:
    active = (
        db.query(QueueTicket)
        .filter(
            QueueTicket.patient_id == patient_id,
            QueueTicket.status.in_([QueueStatus.WAITING, QueueStatus.CALLED, QueueStatus.IN_CONSULTATION]),
        )
        .first()
    )
    if active:
        raise HTTPException(
            status_code=409,
            detail=f"Patient already has an active ticket ({active.ticket_number})",
        )

    # ponytail: MAX+1 + unique-constraint retry survives restores/deletions where
    # count+101 deadlocked; switch to a counter table/sequence if contention grows
    ticket = None
    for _ in range(5):
        max_num = db.execute(
            text("SELECT COALESCE(MAX(CAST(SUBSTR(ticket_number, 3) AS INTEGER)), 100) FROM queue_tickets")
        ).scalar()
        candidate = QueueTicket(
            ticket_number=f"Q-{max_num + 1}",
            patient_id=patient_id,
            doctor_id=doctor_id,
            appointment_id=appointment_id,
            status=QueueStatus.WAITING,
            priority=priority,
            issued_at=datetime.now(timezone.utc),
        )
        db.add(candidate)
        try:
            db.commit()
            ticket = candidate
            break
        except IntegrityError:
            db.rollback()
            still_active = (
                db.query(QueueTicket)
                .filter(QueueTicket.patient_id == patient_id, QueueTicket.status == QueueStatus.WAITING)
                .first()
            )
            if still_active:
                raise HTTPException(
                    status_code=409,
                    detail=f"Patient already has an active ticket ({still_active.ticket_number})",
                )
    if ticket is None:
        raise HTTPException(status_code=503, detail="Could not allocate a ticket number, please retry")
    db.refresh(ticket)
    return ticket


@router.get("/active")
def get_active_queue(
    doctor_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.STAFF, UserRole.DOCTOR, UserRole.ADMIN])),
):
    """Authenticated active queue tickets with patient/doctor/room details for staff & doctor consoles."""
    query = (
        db.query(QueueTicket)
        .filter(QueueTicket.status.in_([QueueStatus.WAITING, QueueStatus.CALLED, QueueStatus.IN_CONSULTATION]))
    )
    if doctor_id is not None:
        query = query.filter(QueueTicket.doctor_id == doctor_id)
    tickets = query.order_by((QueueTicket.priority == "urgent").desc(), QueueTicket.id.asc()).all()
    return [
        {
            "id": t.id,
            "ticket_number": t.ticket_number,
            "status": t.status.value if hasattr(t.status, "value") else str(t.status),
            "priority": t.priority or "normal",
            "doctor_id": t.doctor_id,
            "doctor_name": t.doctor.user.full_name if t.doctor and t.doctor.user else "Clinic Physician",
            "room_number": t.doctor.room_number if t.doctor else "N/A",
            "patient_id": t.patient_id,
            "patient_name": t.patient.user.full_name if t.patient and t.patient.user else f"Patient #{t.patient_id}",
            "appointment_id": t.appointment_id,
        }
        for t in tickets
    ]


@router.post("/issue")
async def issue_ticket(
    data: IssueTicketRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doctor = db.query(Doctor).join(User).filter(Doctor.id == data.doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    if not doctor.user or not doctor.user.is_approved or not doctor.is_available:
        raise HTTPException(status_code=400, detail="Doctor is currently unavailable")

    if current_user.role == UserRole.PATIENT:
        patient = db.query(Patient).filter(Patient.user_id == current_user.id).first()
        if not patient:
            raise HTTPException(status_code=400, detail="User is not registered as a patient")
    else:
        if not data.patient_id:
            raise HTTPException(status_code=400, detail="patient_id is required for staff-issued tickets")
        patient = db.query(Patient).filter(Patient.id == data.patient_id).first()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found")

    if data.appointment_id is not None:
        appt = (
            db.query(Appointment)
            .filter(
                Appointment.id == data.appointment_id,
                Appointment.patient_id == patient.id,
                Appointment.doctor_id == doctor.id,
            )
            .first()
        )
        if not appt:
            raise HTTPException(status_code=400, detail="Appointment does not match patient and doctor")

    ticket = _allocate_queue_ticket(db, patient.id, data.doctor_id, data.priority, data.appointment_id)
    await queue_manager.broadcast({"event": "QUEUE_UPDATED", "ticket": ticket.ticket_number, "status": "issued"})
    return {"status": "success", "ticket_number": ticket.ticket_number, "id": ticket.id}


@router.post("/walkin-register")
async def register_walkin_patient(
    data: WalkinRegisterRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.STAFF, UserRole.ADMIN])),
):
    """Register an unregistered walk-in patient at the front desk and issue a queue ticket."""
    doctor = (
        db.query(Doctor)
        .join(User)
        .filter(Doctor.id == data.doctor_id, User.is_approved == True, Doctor.is_available == True)
        .first()
    )
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found or unavailable")

    name = data.full_name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Patient name is required")

    user = User(
        email=f"walkin.{uuid.uuid4().hex[:12]}@clinic.local",
        hashed_password=get_password_hash(secrets.token_urlsafe(16)),
        full_name=name,
        phone=data.phone.strip() if data.phone else None,
        role=UserRole.PATIENT,
        is_approved=True,
    )
    db.add(user)
    db.flush()

    patient = Patient(
        user_id=user.id,
        gender=data.gender.strip() if data.gender else None,
        allergies=data.allergies.strip() if data.allergies else None,
    )
    db.add(patient)
    db.commit()
    db.refresh(patient)

    try:
        ticket = _allocate_queue_ticket(db, patient.id, data.doctor_id, data.priority)
    except Exception:
        db.delete(patient)
        db.delete(user)
        db.commit()
        raise
    await queue_manager.broadcast({"event": "QUEUE_UPDATED", "ticket": ticket.ticket_number, "status": "issued"})
    return {
        "status": "success",
        "patient_id": patient.id,
        "patient_name": user.full_name,
        "ticket_number": ticket.ticket_number,
        "id": ticket.id,
    }


@router.post("/call-next")
async def call_next_patient(
    doctor_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.STAFF, UserRole.DOCTOR, UserRole.ADMIN])),
):
    first = (
        db.query(QueueTicket.id)
        .filter(QueueTicket.doctor_id == doctor_id, QueueTicket.status == QueueStatus.WAITING)
        # Urgent triage jumps the line; ties resolve in issuance order.
        .order_by((QueueTicket.priority == "urgent").desc(), QueueTicket.id.asc())
        .first()
    )
    if not first:
        raise HTTPException(status_code=404, detail="No waiting patients in queue")

    # Atomic guarded update: only one concurrent caller can flip the ticket out of WAITING.
    updated = (
        db.query(QueueTicket)
        .filter(QueueTicket.id == first.id, QueueTicket.status == QueueStatus.WAITING)
        .update(
            {"status": QueueStatus.CALLED, "called_at": datetime.now(timezone.utc)},
            synchronize_session=False,
        )
    )
    db.commit()
    if not updated:
        raise HTTPException(status_code=409, detail="Ticket was just called by another staff member")

    next_ticket = db.get(QueueTicket, first.id)
    room_num = next_ticket.doctor.room_number if next_ticket.doctor else "N/A"
    await queue_manager.broadcast({
        "event": "PATIENT_CALLED",
        "ticket_number": next_ticket.ticket_number,
        "room_number": room_num,
    })
    return {"status": "success", "called_ticket": next_ticket.ticket_number}


@router.post("/advance")
async def advance_ticket(
    data: AdvanceTicketRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.STAFF, UserRole.DOCTOR, UserRole.ADMIN])),
):
    """Move a ticket through its lifecycle: CALLED -> IN_CONSULTATION -> COMPLETED,
    or CANCELLED for no-shows/waiting cancellations."""
    target = QueueStatus(data.to)
    updates: dict = {"status": target}
    if target == QueueStatus.COMPLETED:
        updates["completed_at"] = datetime.now(timezone.utc)

    updated = (
        db.query(QueueTicket)
        .filter(QueueTicket.id == data.ticket_id, QueueTicket.status.in_(ADVANCE_FROM[data.to]))
        .update(updates, synchronize_session=False)
    )
    db.commit()
    if not updated:
        raise HTTPException(
            status_code=409,
            detail="Ticket is not in a state that allows this transition",
        )

    ticket = db.get(QueueTicket, data.ticket_id)
    room_num = ticket.doctor.room_number if ticket.doctor else "N/A"
    await queue_manager.broadcast({
        "event": "QUEUE_UPDATED",
        "ticket": ticket.ticket_number,
        "status": data.to,
    })
    return {
        "status": "success",
        "ticket_number": ticket.ticket_number,
        "ticket_status": data.to,
        "room_number": room_num,
    }


@router.get("/my-ticket")
def get_my_active_ticket(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.PATIENT])),
):
    """Return the signed-in patient's active queue ticket (if any) so UI reflects staff check-ins and prevents duplicate clicks."""
    patient = db.query(Patient).filter(Patient.user_id == current_user.id).first()
    if not patient:
        return {"active_ticket": None}
    active = (
        db.query(QueueTicket)
        .filter(
            QueueTicket.patient_id == patient.id,
            QueueTicket.status.in_([QueueStatus.WAITING, QueueStatus.CALLED, QueueStatus.IN_CONSULTATION]),
        )
        .order_by(QueueTicket.id.desc())
        .first()
    )
    if not active:
        return {"active_ticket": None}
    return {
        "active_ticket": {
            "id": active.id,
            "ticket_number": active.ticket_number,
            "status": active.status.value if hasattr(active.status, "value") else str(active.status),
            "doctor_name": active.doctor.user.full_name if active.doctor and active.doctor.user else "Clinic Physician",
            "room_number": active.doctor.room_number if active.doctor else "N/A",
        }
    }


@router.websocket("/ws")
async def websocket_queue_endpoint(websocket: WebSocket):
    await queue_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        queue_manager.disconnect(websocket)
