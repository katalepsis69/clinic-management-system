from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.auth import (
    create_access_token,
    get_current_user,
    verify_password,
)
from app.config import get_settings
from app.database import get_db
from app.models import User

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
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": role_val,
        "phone": user.phone,
        "patient_id": user.patient.id if user.patient else None,
        "doctor_id": user.doctor.id if user.doctor else None,
    }


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

    response.set_cookie(
        key="access_token",
        value=f"Bearer {token}",
        httponly=True,
        secure=not settings.DEMO_MODE,
        samesite="strict",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )

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
