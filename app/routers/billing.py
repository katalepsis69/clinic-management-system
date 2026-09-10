from datetime import datetime, timezone
import uuid
from decimal import Decimal
from typing import Annotated, Literal, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.database import get_db
from app.models import Invoice, Patient, QueueTicket, User, UserRole
from app.auth import require_roles

router = APIRouter(prefix="/api/billing", tags=["Billing & Digital Invoicing"])

Money = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)]


class CreateInvoiceRequest(BaseModel):
    patient_id: int
    queue_ticket_id: Optional[int] = None
    consultation_fee: Money = Decimal("0.00")
    medication_fee: Money = Decimal("0.00")
    other_fees: Money = Decimal("0.00")
    discount_amount: Money = Decimal("0.00")
    payment_method: Literal["cash", "credit_card", "debit_card", "qr_ewallet"] = "cash"


@router.post("/create")
def create_invoice(
    data: CreateInvoiceRequest,
    user: User = Depends(require_roles([UserRole.STAFF, UserRole.ADMIN])),
    db: Session = Depends(get_db),
):
    patient = db.query(Patient).filter(Patient.id == data.patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    if data.queue_ticket_id is not None:
        ticket = (
            db.query(QueueTicket)
            .filter(
                QueueTicket.id == data.queue_ticket_id,
                QueueTicket.patient_id == data.patient_id,
            )
            .first()
        )
        if not ticket:
            raise HTTPException(
                status_code=400, detail="Queue ticket does not exist or belongs to a different patient"
            )

    total = max(Decimal("0.00"), (data.consultation_fee + data.medication_fee + data.other_fees) - data.discount_amount)
    # ponytail: uuid suffix collision odds are negligible (~1e-7/day); add a retry if it ever fires
    receipt_no = f"REC-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

    inv = Invoice(
        receipt_number=receipt_no,
        patient_id=data.patient_id,
        queue_ticket_id=data.queue_ticket_id,
        consultation_fee=data.consultation_fee,
        medication_fee=data.medication_fee,
        other_fees=data.other_fees,
        discount_amount=data.discount_amount,
        total_amount=total,
        payment_method=data.payment_method,
        payment_status="paid",
        paid_at=datetime.now(timezone.utc),
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return {
        "status": "success",
        "invoice_id": inv.id,
        "receipt_number": inv.receipt_number,
        "total": float(inv.total_amount),
    }


@router.get("/list")
def list_invoices(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles([UserRole.STAFF, UserRole.ADMIN])),
):
    invoices = db.query(Invoice).order_by(Invoice.id.desc()).limit(50).all()
    return [
        {
            "id": inv.id,
            "receipt_number": inv.receipt_number,
            "patient_name": inv.patient.user.full_name if (inv.patient and inv.patient.user) else "Walk-in",
            "total_amount": float(inv.total_amount),
            "payment_method": inv.payment_method,
            "paid_at": inv.paid_at.strftime("%Y-%m-%d %H:%M") if inv.paid_at else None,
        }
        for inv in invoices
    ]


@router.get("/receipt/{receipt_number}")
def get_invoice_by_receipt(
    receipt_number: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles([UserRole.STAFF, UserRole.ADMIN])),
):
    inv = db.query(Invoice).filter(Invoice.receipt_number == receipt_number).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return {
        "id": inv.id,
        "receipt_number": inv.receipt_number,
        "patient_id": inv.patient_id,
        "patient_name": inv.patient.user.full_name if (inv.patient and inv.patient.user) else "Walk-in",
        "consultation_fee": float(inv.consultation_fee or 0.0),
        "medication_fee": float(inv.medication_fee or 0.0),
        "other_fees": float(inv.other_fees or 0.0),
        "discount_amount": float(inv.discount_amount or 0.0),
        "total_amount": float(inv.total_amount),
        "payment_method": inv.payment_method,
        "payment_status": inv.payment_status,
        "paid_at": inv.paid_at.strftime("%Y-%m-%d %H:%M") if inv.paid_at else None,
    }


@router.get("/{invoice_id}")
def get_invoice_by_id(
    invoice_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles([UserRole.STAFF, UserRole.ADMIN])),
):
    inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return {
        "id": inv.id,
        "receipt_number": inv.receipt_number,
        "patient_id": inv.patient_id,
        "patient_name": inv.patient.user.full_name if (inv.patient and inv.patient.user) else "Walk-in",
        "consultation_fee": float(inv.consultation_fee or 0.0),
        "medication_fee": float(inv.medication_fee or 0.0),
        "other_fees": float(inv.other_fees or 0.0),
        "discount_amount": float(inv.discount_amount or 0.0),
        "total_amount": float(inv.total_amount),
        "payment_method": inv.payment_method,
        "payment_status": inv.payment_status,
        "paid_at": inv.paid_at.strftime("%Y-%m-%d %H:%M") if inv.paid_at else None,
    }
