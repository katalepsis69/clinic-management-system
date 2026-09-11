from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.auth import (
    create_access_token,
    get_current_user,
    get_password_hash,
    verify_password,
)
from app.config import get_settings
from app.database import get_db
from app.models import Doctor, Patient, User, UserRole

router = APIRouter(prefix="/api/auth", tags=["Authentication"])
settings = get_settings()

# ponytail: in-memory throttle, single process only — swap for slowapi/redis if multi-worker
_FAILED_LOGINS: dict = {}


class LoginPayload(BaseModel):
    email: Optional[str] = None
    username: Optional[str] = None
    password: str


def _rate_limited(email: str) -> bool:
    import time

    now = time.monotonic()
    attempts = [t for t in _FAILED_LOGINS.get(email, []) if now - t < 900]
    _FAILED_LOGINS[email] = attempts
    return len(attempts) >= 5


def _record_failure(email: str):
    import time

    _FAILED_LOGINS.setdefault(email, []).append(time.monotonic())


def _user_profile(user: User) -> dict:
    role_val = user.role.value if hasattr(user.role, "value") else str(user.role)
    data = {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": role_val,
        "phone": user.phone,
        "patient_id": user.patient.id if user.patient else None,
        "doctor_id": user.doctor.id if user.doctor else None,
    }
    if user.patient:
        data["patient_profile"] = {
            "date_of_birth": str(user.patient.date_of_birth) if user.patient.date_of_birth else None,
            "gender": user.patient.gender,
            "blood_group": user.patient.blood_group,
            "emergency_contact_name": user.patient.emergency_contact_name,
            "emergency_contact_phone": user.patient.emergency_contact_phone,
            "allergies": user.patient.allergies,
            "medical_history": user.patient.medical_history,
        }
    return data


def _set_auth_cookie(response: Response, token: str):
    response.set_cookie(
        key="access_token",
        value=f"Bearer {token}",
        httponly=True,
        secure=not settings.DEMO_MODE,
        samesite="strict",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/login")
async def login(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        email = body.get("email") or body.get("username")
        password = body.get("password")
    else:
        form = await request.form()
        email = form.get("username") or form.get("email")
        password = form.get("password")

    if not email or not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email/username and password are required",
        )

    if _rate_limited(email):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts, try again later",
        )

    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.hashed_password):
        _record_failure(email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    _FAILED_LOGINS.pop(email, None)
    role_val = user.role.value if hasattr(user.role, "value") else str(user.role)
    token = create_access_token({"sub": user.email, "role": role_val})
    _set_auth_cookie(response, token)

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": _user_profile(user),
    }


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(key="access_token")
    return {"status": "success", "message": "Logged out successfully"}


@router.get("/me")
def get_me(current_user: User = Depends(get_current_user)):
    return _user_profile(current_user)


class RegisterUserPayload(BaseModel):
    email: str
    password: str
    full_name: str
    phone: Optional[str] = None
    role: Optional[str] = "patient"
    # Patient fields
    date_of_birth: Optional[str] = None
    gender: Optional[str] = None
    blood_group: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    allergies: Optional[str] = None
    medical_history: Optional[str] = None
    # Doctor fields
    specialization: Optional[str] = None
    license_number: Optional[str] = None
    room_number: Optional[str] = None
    consultation_fee: Optional[float] = 60.00


# Backwards compatibility alias
RegisterPatientPayload = RegisterUserPayload


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register_user(
    payload: RegisterUserPayload,
    response: Response,
    db: Session = Depends(get_db),
):
    email = payload.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email address is required")
    if not payload.password or len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    if not payload.full_name or not payload.full_name.strip():
        raise HTTPException(status_code=400, detail="Full name is required")

    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="An account with this email already exists")

    target_role_str = (payload.role or "patient").strip().lower()
    role_map = {
        "patient": UserRole.PATIENT,
        "doctor": UserRole.DOCTOR,
        "staff": UserRole.STAFF,
        "admin": UserRole.ADMIN,
    }
    user_role = role_map.get(target_role_str, UserRole.PATIENT)

    user = User(
        email=email,
        hashed_password=get_password_hash(payload.password),
        full_name=payload.full_name.strip(),
        phone=payload.phone.strip() if payload.phone else None,
        role=user_role,
    )
    db.add(user)
    db.flush()

    if user_role == UserRole.PATIENT:
        dob = None
        if payload.date_of_birth:
            try:
                dob = date.fromisoformat(payload.date_of_birth)
            except Exception:
                raise HTTPException(status_code=400, detail="Date of birth must be in YYYY-MM-DD format")

        patient = Patient(
            user_id=user.id,
            date_of_birth=dob,
            gender=payload.gender.strip() if payload.gender else None,
            blood_group=payload.blood_group.strip() if payload.blood_group else None,
            emergency_contact_name=payload.emergency_contact_name.strip() if payload.emergency_contact_name else None,
            emergency_contact_phone=payload.emergency_contact_phone.strip() if payload.emergency_contact_phone else None,
            allergies=payload.allergies.strip() if payload.allergies else None,
            medical_history=payload.medical_history.strip() if payload.medical_history else None,
        )
        db.add(patient)

    elif user_role == UserRole.DOCTOR:
        spec = (payload.specialization or "").strip() or "General Medicine"
        lic = (payload.license_number or "").strip() or f"MD-{user.id:04d}"
        room = (payload.room_number or "").strip() or f"Room {100 + user.id}"
        fee = payload.consultation_fee if payload.consultation_fee is not None else 60.00

        doctor = Doctor(
            user_id=user.id,
            specialization=spec,
            license_number=lic,
            room_number=room,
            consultation_fee=fee,
            is_available=True,
        )
        db.add(doctor)

    db.commit()
    db.refresh(user)

    role_val = user.role.value if hasattr(user.role, "value") else str(user.role)
    token = create_access_token({"sub": user.email, "role": role_val})
    _set_auth_cookie(response, token)

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": _user_profile(user),
    }


class UpdatePatientProfilePayload(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    date_of_birth: Optional[str] = None
    gender: Optional[str] = None
    blood_group: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    allergies: Optional[str] = None
    medical_history: Optional[str] = None


@router.put("/profile")
def update_profile(
    payload: UpdatePatientProfilePayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.full_name is not None and payload.full_name.strip():
        current_user.full_name = payload.full_name.strip()
    if payload.phone is not None:
        current_user.phone = payload.phone.strip() if payload.phone else None

    if current_user.patient:
        patient = current_user.patient
        if payload.date_of_birth is not None:
            if payload.date_of_birth:
                patient.date_of_birth = date.fromisoformat(payload.date_of_birth)
            else:
                patient.date_of_birth = None
        if payload.gender is not None:
            patient.gender = payload.gender
        if payload.blood_group is not None:
            patient.blood_group = payload.blood_group
        if payload.emergency_contact_name is not None:
            patient.emergency_contact_name = payload.emergency_contact_name
        if payload.emergency_contact_phone is not None:
            patient.emergency_contact_phone = payload.emergency_contact_phone
        if payload.allergies is not None:
            patient.allergies = payload.allergies
        if payload.medical_history is not None:
            patient.medical_history = payload.medical_history

    db.commit()
    db.refresh(current_user)
    return _user_profile(current_user)
