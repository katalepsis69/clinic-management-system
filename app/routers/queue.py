from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models import QueueTicket, QueueStatus, Patient, Doctor, User, UserRole
from app.auth import get_current_user, require_roles
from app.websocket_manager import queue_manager

router = APIRouter(prefix="/api/queue", tags=["Queue Management"])


class IssueTicketRequest(BaseModel):
    doctor_id: int
    patient_id: int
    priority: str = "normal"


@router.get("/live-status")
def get_live_status(db: Session = Depends(get_db)):
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
async def issue_ticket(data: IssueTicketRequest, db: Session = Depends(get_db)):
    count = db.query(QueueTicket).count() + 101
    ticket_num = f"Q-{count}"
    ticket = QueueTicket(
        ticket_number=ticket_num,
        patient_id=data.patient_id,
        doctor_id=data.doctor_id,
        status=QueueStatus.WAITING,
        priority=data.priority,
        issued_at=datetime.now(timezone.utc),
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    await queue_manager.broadcast({"event": "QUEUE_UPDATED", "ticket": ticket_num, "status": "issued"})
    return {"status": "success", "ticket_number": ticket_num, "id": ticket.id}


@router.post("/call-next")
async def call_next_patient(
    doctor_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.STAFF, UserRole.DOCTOR, UserRole.ADMIN])),
):
    next_ticket = (
        db.query(QueueTicket)
        .filter(QueueTicket.doctor_id == doctor_id, QueueTicket.status == QueueStatus.WAITING)
        .order_by(QueueTicket.id.asc())
        .first()
    )
    if not next_ticket:
        raise HTTPException(status_code=404, detail="No waiting patients in queue")

    next_ticket.status = QueueStatus.CALLED
    next_ticket.called_at = datetime.now(timezone.utc)
    db.commit()

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
        queue_manager.disconnect(websocket)
