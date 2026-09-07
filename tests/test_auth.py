import pytest
from datetime import timedelta
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.auth import (
    get_password_hash,
    verify_password,
    create_access_token,
    decode_token,
    get_current_user,
    require_roles,
)
from app.models import Base, User, UserRole
from app.seed import seed_demo_data
from app.routers.auth import router as auth_router


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_password_hashing():
    pw = "secret123"
    hashed = get_password_hash(pw)
    assert verify_password(pw, hashed) is True
    assert verify_password("wrong", hashed) is False


def test_password_hashing_truncates_72_bytes():
    # Passwords longer than 72 bytes should not raise ValueError from direct bcrypt
    long_pw = "a" * 100
    hashed = get_password_hash(long_pw)
    # The first 72 bytes match
    assert verify_password(long_pw, hashed) is True
    assert verify_password("a" * 72, hashed) is True
    assert verify_password("a" * 71, hashed) is False


def test_token_creation_and_decode():
    token = create_access_token({"sub": "user@demo.com", "role": "doctor"})
    payload = decode_token(token)
    assert payload["sub"] == "user@demo.com"
    assert payload["role"] == "doctor"


def test_token_decode_invalid():
    with pytest.raises(HTTPException) as exc_info:
        decode_token("invalid.jwt.token")
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid token"


def test_token_decode_expired():
    token = create_access_token(
        {"sub": "expired@demo.com"}, expires_delta=timedelta(seconds=-10)
    )
    with pytest.raises(HTTPException) as exc_info:
        decode_token(token)
    assert exc_info.value.status_code == 401


def test_get_current_user_bearer_token(db_session):
    user = User(
        email="doctor@demo.com",
        hashed_password=get_password_hash("doc123"),
        full_name="Dr. Test",
        role=UserRole.DOCTOR,
    )
    db_session.add(user)
    db_session.commit()

    token = create_access_token({"sub": user.email, "role": user.role.value})
    mock_request = Request(
        scope={
            "type": "http",
            "headers": [(b"authorization", f"Bearer {token}".encode("utf-8"))],
        }
    )

    current_user = get_current_user(request=mock_request, token=token, db=db_session)
    assert current_user.email == "doctor@demo.com"
    assert current_user.role == UserRole.DOCTOR


def test_get_current_user_cookie(db_session):
    user = User(
        email="staff@demo.com",
        hashed_password=get_password_hash("staff123"),
        full_name="Staff Test",
        role=UserRole.STAFF,
    )
    db_session.add(user)
    db_session.commit()

    token = create_access_token({"sub": user.email, "role": user.role.value})
    cookie_header = f"access_token=Bearer {token}".encode("utf-8")
    mock_request = Request(
        scope={"type": "http", "headers": [(b"cookie", cookie_header)]}
    )

    current_user = get_current_user(request=mock_request, token=None, db=db_session)
    assert current_user.email == "staff@demo.com"


def test_get_current_user_unauthenticated(db_session):
    mock_request = Request(scope={"type": "http", "headers": []})
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(request=mock_request, token=None, db=db_session)
    assert exc_info.value.status_code == 401


def test_require_roles():
    admin_user = User(email="admin@test.com", role=UserRole.ADMIN)
    patient_user = User(email="patient@test.com", role=UserRole.PATIENT)

    checker = require_roles([UserRole.ADMIN, UserRole.STAFF])
    # Should pass
    assert checker(current_user=admin_user) == admin_user

    # Should fail with 403 Forbidden
    with pytest.raises(HTTPException) as exc_info:
        checker(current_user=patient_user)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Insufficient privileges"


def test_seed_demo_data(db_session):
    seed_demo_data(db_session)

    users = db_session.query(User).all()
    assert len(users) == 4

    admin = db_session.query(User).filter_by(email="admin@demo.com").first()
    assert admin is not None
    assert admin.role == UserRole.ADMIN
    assert verify_password("admin123", admin.hashed_password) is True

    doctor = db_session.query(User).filter_by(email="doctor@demo.com").first()
    assert doctor is not None
    assert doctor.doctor is not None
    assert doctor.doctor.license_number == "MD-98421"

    patient = db_session.query(User).filter_by(email="patient@demo.com").first()
    assert patient is not None
    assert patient.patient is not None
    assert patient.patient.emergency_contact_name == "John Connor"

    # Test idempotency (calling seed again does not duplicate)
    seed_demo_data(db_session)
    assert db_session.query(User).count() == 4


def test_auth_router_endpoints(db_session):
    seed_demo_data(db_session)

    test_app = FastAPI()
    test_app.include_router(auth_router)

    from app.database import get_db

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    test_app.dependency_overrides[get_db] = override_get_db

    client = TestClient(test_app)

    # 1. Login success (JSON)
    res = client.post(
        "/api/auth/login",
        json={"email": "admin@demo.com", "password": "admin123"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert data["user"]["email"] == "admin@demo.com"
    assert "access_token" in res.cookies

    token = data["access_token"]

    # 2. Get me endpoint with Bearer token
    me_res = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me_res.status_code == 200
    assert me_res.json()["email"] == "admin@demo.com"
    assert me_res.json()["role"] == "admin"

    # 3. Login failure
    bad_res = client.post(
        "/api/auth/login",
        json={"email": "admin@demo.com", "password": "wrongpassword"},
    )
    assert bad_res.status_code == 401

    # 4. Logout endpoint clears cookie
    logout_res = client.post("/api/auth/logout")
    assert logout_res.status_code == 200
    assert (
        "access_token" not in logout_res.cookies
        or logout_res.cookies["access_token"] == '""'
        or logout_res.cookies["access_token"] == ""
    )
