from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Doctor, User, UserRole
from app.auth import get_password_hash, require_roles
from app.routers.auth import _user_profile

router = APIRouter(prefix="/api/admin", tags=["Admin & User Management"])


class AdminCreateUserRequest(BaseModel):
    full_name: str
    email: str
    password: str = Field(min_length=6)
    phone: Optional[str] = None
    role: Literal["doctor", "staff", "admin"]
    specialization: Optional[str] = None
    license_number: Optional[str] = None
    room_number: Optional[str] = None
    consultation_fee: Optional[float] = 500.00


@router.get("/users")
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.ADMIN])),
):
    users = db.query(User).order_by(User.is_approved.asc(), User.id.asc()).all()
    return [
        {
            "id": u.id,
            "email": u.email,
            "full_name": u.full_name,
            "role": u.role.value if hasattr(u.role, "value") else str(u.role),
            "is_approved": bool(u.is_approved),
            "phone": u.phone,
            "doctor_id": u.doctor.id if u.doctor else None,
            "patient_id": u.patient.id if u.patient else None,
        }
        for u in users
    ]


@router.post("/users", status_code=201)
def create_user(
    payload: AdminCreateUserRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.ADMIN])),
):
    email = payload.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email address is required")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="An account with this email already exists")

    role_map = {
        "doctor": UserRole.DOCTOR,
        "staff": UserRole.STAFF,
        "admin": UserRole.ADMIN,
    }
    role = role_map[payload.role]
    user = User(
        email=email,
        hashed_password=get_password_hash(payload.password),
        full_name=payload.full_name.strip(),
        phone=payload.phone.strip() if payload.phone else None,
        role=role,
        is_approved=True,
    )
    db.add(user)
    db.flush()
    if role == UserRole.DOCTOR:
        db.add(Doctor(
            user_id=user.id,
            specialization=(payload.specialization or "").strip() or "General Medicine",
            license_number=(payload.license_number or "").strip() or f"MD-{user.id:04d}",
            room_number=(payload.room_number or "").strip() or f"Room {100 + user.id}",
            consultation_fee=payload.consultation_fee if payload.consultation_fee is not None else 500.00,
            is_available=True,
        ))
    db.commit()
    db.refresh(user)
    return {"status": "success", "user": _user_profile(user)}


@router.post("/users/{user_id}/approve")
def approve_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.ADMIN])),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_approved = True
    db.commit()
    db.refresh(user)
    return {"status": "success", "user": _user_profile(user)}


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.ADMIN])),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_approved:
        raise HTTPException(status_code=400, detail="Only pending accounts can be rejected here")
    if user.doctor:
        db.delete(user.doctor)
    if user.patient:
        db.delete(user.patient)
    db.delete(user)
    db.commit()
    return {"status": "success"}
