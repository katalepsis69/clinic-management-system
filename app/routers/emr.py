import json
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.config import get_settings
from app.database import get_db
from app.models import Patient, Doctor, Prescription, User, UserRole
from app.auth import get_current_user, require_roles

router = APIRouter(prefix="/api/emr", tags=["EMR & Prescriptions"])
settings = get_settings()


class MedicationItem(BaseModel):
    drug_name: str
    dosage: str
    frequency: str
    duration: str
    instructions: Optional[str] = ""


class CreatePrescriptionRequest(BaseModel):
    patient_id: int
    # Only honored for ADMIN creating on behalf of a doctor; doctors are derived from the token.
    doctor_id: Optional[int] = None
    diagnosis: str
    clinical_notes: Optional[str] = ""
    medications: List[MedicationItem]


@router.get("/patient/{patient_id}")
def get_patient_emr(
    patient_id: int,
    user: User = Depends(require_roles([UserRole.DOCTOR, UserRole.STAFF, UserRole.ADMIN])),
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

    return {
        "patient_id": patient.id,
        "name": patient.user.full_name,
        "dob": str(patient.date_of_birth),
        "gender": patient.gender,
        "blood_group": patient.blood_group,
        "allergies": patient.allergies,
        "medical_history": patient.medical_history,
        "prescriptions": [
            {
                "id": p.id,
                "diagnosis": p.diagnosis,
                "notes": p.clinical_notes,
                "medications": json.loads(p.medications_json),
                "created_at": p.created_at.strftime("%Y-%m-%d %H:%M"),
                "qr_code_hash": p.qr_code_hash,
            }
            for p in prescriptions
        ],
    }


@router.post("/prescription/create")
def create_prescription(
    data: CreatePrescriptionRequest,
    user: User = Depends(require_roles([UserRole.DOCTOR, UserRole.ADMIN])),
    db: Session = Depends(get_db),
):
    patient = db.query(Patient).filter(Patient.id == data.patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    if user.role == UserRole.DOCTOR:
        doctor = db.query(Doctor).filter(Doctor.user_id == user.id).first()
        if not doctor:
            raise HTTPException(status_code=403, detail="Current user is not registered as a doctor")
    else:  # ADMIN creating on behalf of a named, existing doctor
        if not data.doctor_id:
            raise HTTPException(status_code=400, detail="doctor_id is required when creating on behalf of a doctor")
        doctor = db.query(Doctor).filter(Doctor.id == data.doctor_id).first()
        if not doctor:
            raise HTTPException(status_code=404, detail="Doctor not found")

    qr_hash = uuid.uuid4().hex[:16].upper()
    medications_data = [
        m.model_dump() if hasattr(m, "model_dump") else m.dict()
        for m in data.medications
    ]
    rx = Prescription(
        patient_id=patient.id,
        doctor_id=doctor.id,
        diagnosis=data.diagnosis,
        clinical_notes=data.clinical_notes,
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
        "qr_code_image": None,
    }

