import json
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.database import get_db
from app.models import Appointment, Patient, Doctor, Prescription, User, UserRole
from app.auth import require_roles
from app.qr import make_qr_data_uri

router = APIRouter(prefix="/api/emr", tags=["EMR & Prescriptions"])


class MedicationItem(BaseModel):
    drug_name: str
    dosage: str
    frequency: str
    duration: str
    instructions: Optional[str] = ""


class CreatePrescriptionRequest(BaseModel):
    patient_id: int
    doctor_id: Optional[int] = None
    appointment_id: Optional[int] = None
    diagnosis: str
    clinical_notes: Optional[str] = ""
    medications: List[MedicationItem]


@router.get("/patient/{patient_id}")
def get_patient_emr(
    patient_id: int,
    user: User = Depends(require_roles([UserRole.DOCTOR])),
    db: Session = Depends(get_db),
):
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    prescriptions = (
        db.query(Prescription)
        .filter(Prescription.patient_id == patient_id)
        .order_by(Prescription.created_at.desc())
        .all()
    )

    rx_items = []
    for p in prescriptions:
        # ponytail: a hand-edited/imported row must not 500 the whole chart view
        try:
            meds = json.loads(p.medications_json)
            if not isinstance(meds, list):
                meds = []
        except (ValueError, TypeError):
            meds = []
        rx_items.append({
            "id": p.id,
            "diagnosis": p.diagnosis,
            "notes": p.clinical_notes,
            "medications": meds,
            "created_at": p.created_at.strftime("%Y-%m-%d %H:%M"),
            "qr_code_hash": p.qr_code_hash,
        })

    return {
        "patient_id": patient.id,
        "name": patient.user.full_name,
        "dob": str(patient.date_of_birth) if patient.date_of_birth else None,
        "gender": patient.gender,
        "blood_group": patient.blood_group,
        "allergies": patient.allergies,
        "medical_history": patient.medical_history,
        "prescriptions": rx_items,
    }


@router.post("/prescription/create")
def create_prescription(
    data: CreatePrescriptionRequest,
    user: User = Depends(require_roles([UserRole.DOCTOR])),
    db: Session = Depends(get_db),
):
    patient = db.query(Patient).filter(Patient.id == data.patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    doctor = db.query(Doctor).filter(Doctor.user_id == user.id).first()
    if not doctor:
        raise HTTPException(status_code=403, detail="Current user is not registered as a doctor")

    diagnosis = (data.diagnosis or "").strip()
    if not diagnosis:
        raise HTTPException(status_code=400, detail="Diagnosis is required")
    if not data.medications:
        raise HTTPException(status_code=400, detail="At least one medication is required")
    if any(not (m.drug_name or "").strip() or not (m.dosage or "").strip() for m in data.medications):
        raise HTTPException(status_code=400, detail="Medication drug name and dosage are required")

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

    qr_hash = uuid.uuid4().hex[:16].upper()
    medications_data = [m.model_dump() for m in data.medications]
    rx = Prescription(
        patient_id=patient.id,
        doctor_id=doctor.id,
        appointment_id=data.appointment_id,
        diagnosis=diagnosis,
        clinical_notes=(data.clinical_notes or "").strip(),
        medications_json=json.dumps(medications_data),
        qr_code_hash=qr_hash,
    )
    db.add(rx)
    db.commit()
    db.refresh(rx)

    return {
        "status": "success",
        "prescription_id": rx.id,
        "qr_code_hash": rx.qr_code_hash,
        "qr_code_image": make_qr_data_uri(f"RX:{rx.qr_code_hash}"),
    }


@router.get("/my-prescriptions")
def get_my_prescriptions(
    user: User = Depends(require_roles([UserRole.PATIENT])),
    db: Session = Depends(get_db),
):
    patient = db.query(Patient).filter(Patient.user_id == user.id).first()
    if not patient:
        return []
    prescriptions = (
        db.query(Prescription)
        .filter(Prescription.patient_id == patient.id)
        .order_by(Prescription.created_at.desc(), Prescription.id.desc())
        .limit(20)
        .all()
    )
    doctor_ids = {p.doctor_id for p in prescriptions if p.doctor_id}
    doctors = (
        {d.id: d for d in db.query(Doctor).filter(Doctor.id.in_(doctor_ids)).all()}
        if doctor_ids
        else {}
    )
    items = []
    for p in prescriptions:
        doc = doctors.get(p.doctor_id)
        try:
            meds = json.loads(p.medications_json)
            if not isinstance(meds, list):
                meds = []
        except (ValueError, TypeError):
            meds = []
        items.append({
            "id": p.id,
            "doctor_name": doc.user.full_name if doc and doc.user else "Clinic Physician",
            "specialization": doc.specialization if doc else "",
            "diagnosis": p.diagnosis,
            "notes": p.clinical_notes,
            "medications": meds,
            "created_at": p.created_at.strftime("%Y-%m-%d %H:%M"),
            "qr_code_hash": p.qr_code_hash,
            "qr_code_image": make_qr_data_uri(f"RX:{p.qr_code_hash}"),
        })
    return items

