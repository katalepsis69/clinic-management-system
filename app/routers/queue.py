from datetime import datetime, timezone
from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel

from app.database import get_db
from app.models import QueueTicket, QueueStatus, Patient, Doctor, User, UserRole
from app.auth import get_current_user, require_roles
from app.websocket_manager import queue_manager

router = APIRouter(prefix="/api/queue", tags=["Queue Management"])


class IssueTicketRequest(BaseModel):
    doctor_id: int
    # ponytail: staff may issue walk-ins for another patient; patients are always self-issued
    patient_id: Optional[int] = None
    priority: Literal["normal", "urgent"] = "normal"


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
        "currently_serving_room": called.doctor.room_number if called and called.doctor else "N/A",
        "waiting_count": len(waiting),
        "waiting_tickets": [t.ticket_number for t in waiting],
        "estimated_wait_minutes": len(waiting) * 10,
    }


@router.post("/issue")
async def issue_ticket(
    data: IssueTicketRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doctor = db.query(Doctor).filter(Doctor.id == data.doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

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

    active = (
        db.query(QueueTicket)
        .filter(QueueTicket.patient_id == patient.id, QueueTicket.status == QueueStatus.WAITING)
        .first()
    )
    if active:
        raise HTTPException(
            status_code=409,
            detail=f"Patient already has an active ticket ({active.ticket_number})",
        )

    # ponytail: count+101 + unique-constraint retry; switch to a counter table/sequence if volume grows
    ticket = None
    for _ in range(5):
        ticket_num = f"Q-{db.query(QueueTicket).count() + 101}"
        candidate = QueueTicket(
            ticket_number=ticket_num,
            patient_id=patient.id,
            doctor_id=data.doctor_id,
            status=QueueStatus.WAITING,
            priority=data.priority,
            issued_at=datetime.now(timezone.utc),
        )
        db.add(candidate)
        try:
            db.commit()
            ticket = candidate
            break
        except IntegrityError:
            db.rollback()
    if ticket is None:
        raise HTTPException(status_code=503, detail="Could not allocate a ticket number, please retry")
    db.refresh(ticket)

    await queue_manager.broadcast({"event": "QUEUE_UPDATED", "ticket": ticket.ticket_number, "status": "issued"})
    return {"status": "success", "ticket_number": ticket.ticket_number, "id": ticket.id}


@router.post("/call-next")
async def call_next_patient(
    doctor_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.STAFF, UserRole.DOCTOR, UserRole.ADMIN])),
):
    first = (
        db.query(QueueTicket.id)
        .filter(QueueTicket.doctor_id == doctor_id, QueueTicket.status == QueueStatus.WAITING)
        .order_by(QueueTicket.id.asc())
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
