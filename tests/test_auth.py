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

    # 5. Patient Registration with clinical profiling
    reg_payload = {
        "email": "newpatient@clinic.test",
        "password": "strongPassword123",
        "full_name": "Alexander Hayes",
        "phone": "+1-555-4321",
        "date_of_birth": "1994-08-22",
        "gender": "Male",
        "blood_group": "B+",
        "emergency_contact_name": "Elena Hayes",
        "emergency_contact_phone": "+1-555-8888",
        "allergies": "Sulfa drugs, Aspirin",
        "medical_history": "Childhood asthma",
    }
    reg_res = client.post("/api/auth/register", json=reg_payload)
    assert reg_res.status_code == 201
    reg_data = reg_res.json()
    assert reg_data["user"]["email"] == "newpatient@clinic.test"
    assert reg_data["user"]["role"] == "patient"
    assert reg_data["user"]["patient_id"] is not None
    assert reg_data["user"]["patient_profile"]["blood_group"] == "B+"
    assert reg_data["user"]["patient_profile"]["allergies"] == "Sulfa drugs, Aspirin"
    assert reg_data["user"]["patient_profile"]["emergency_contact_name"] == "Elena Hayes"

    new_token = reg_data["access_token"]

    # 6. Update patient medical profile
    update_res = client.put(
        "/api/auth/profile",
        headers={"Authorization": f"Bearer {new_token}"},
        json={"allergies": "Sulfa drugs, Aspirin, Shellfish", "phone": "+1-555-9999"},
    )
    assert update_res.status_code == 200
    updated_data = update_res.json()
    assert updated_data["patient_profile"]["allergies"] == "Sulfa drugs, Aspirin, Shellfish"
    assert updated_data["phone"] == "+1-555-9999"

    # 7. Duplicate email rejection
    dup_res = client.post("/api/auth/register", json=reg_payload)
    assert dup_res.status_code == 400
    assert "already exists" in dup_res.json()["detail"]

    # 8. Doctor, staff, and admin self-registrations require admin approval
    doc_res = client.post("/api/auth/register", json={
        "email": "dr.house@clinic.test",
        "password": "password123",
        "full_name": "Dr. Gregory House",
        "role": "doctor",
        "phone": "555-4321",
        "specialization": "Nephrology & Diagnostics",
        "license_number": "MD-44910",
        "room_number": "Room 304",
        "consultation_fee": 120.00,
    })
    assert doc_res.status_code == 201
    doc_data = doc_res.json()
    assert doc_data["pending_approval"] is True
    assert "access_token" not in doc_data
    assert doc_data["user"]["role"] == "doctor"
    assert doc_data["user"]["is_approved"] is False
    assert doc_data["user"]["doctor_id"] is not None

    staff_res = client.post("/api/auth/register", json={
        "email": "nurse.jackie@clinic.test",
        "password": "password123",
        "full_name": "Jackie Peyton",
        "role": "staff",
        "phone": "555-8888",
    })
    assert staff_res.status_code == 201
    assert staff_res.json()["pending_approval"] is True
    assert staff_res.json()["user"]["is_approved"] is False

    admin_res = client.post("/api/auth/register", json={
        "email": "head.admin@clinic.test",
        "password": "password123",
        "full_name": "Dr. Cuddy",
        "role": "admin",
        "phone": "555-9999",
    })
    assert admin_res.status_code == 201
    assert admin_res.json()["pending_approval"] is True
    assert admin_res.json()["user"]["is_approved"] is False

    # Pending accounts cannot log in until approved
    assert client.post("/api/auth/login", json={
        "email": "head.admin@clinic.test", "password": "password123",
    }).status_code == 403


def _client_with_routers(db_session, include_admin=False):
    test_app = FastAPI()
    test_app.include_router(auth_router)
    if include_admin:
        from app.routers.admin import router as admin_router
        test_app.include_router(admin_router)

    from app.database import get_db

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    test_app.dependency_overrides[get_db] = override_get_db
    return TestClient(test_app)


def test_setup_admin_first_run_flow(db_session):
    client = _client_with_routers(db_session)

    res = client.get("/api/auth/setup-status")
    assert res.status_code == 200
    assert res.json()["initialized"] is False
    assert res.json()["demo_mode"] is True

    payload = {
        "full_name": "Clinic Director",
        "email": "director@clinic.test",
        "password": "strongPassword123",
        "phone": "555-0100",
    }
    res = client.post("/api/auth/setup-admin", json=payload)
    assert res.status_code == 200
    assert res.json()["user"]["role"] == "admin"
    assert "access_token" in res.cookies

    # Second attempt is permanently locked
    res2 = client.post("/api/auth/setup-admin", json=payload)
    assert res2.status_code == 403

    res3 = client.get("/api/auth/setup-status")
    assert res3.json()["initialized"] is True

    # Weak password rejected before the lock check creates anything else
    db_session.delete(db_session.query(User).filter(User.role == UserRole.ADMIN).first())
    db_session.commit()
    res4 = client.post("/api/auth/setup-admin", json={
        "full_name": "Weak", "email": "weak@clinic.test", "password": "123",
    })
    assert res4.status_code == 400


def test_admin_user_management_endpoints(db_session):
    seed_demo_data(db_session)
    client = _client_with_routers(db_session, include_admin=True)

    # Anonymous -> 401
    assert client.get("/api/admin/users").status_code == 401
    assert client.post("/api/admin/users", json={
        "full_name": "X", "email": "x@clinic.test", "password": "password123", "role": "staff",
    }).status_code == 401

    # Patient -> 403
    pat_token = create_access_token({"sub": "patient@demo.com", "role": "patient"})
    pat_headers = {"Authorization": f"Bearer {pat_token}"}
    assert client.get("/api/admin/users", headers=pat_headers).status_code == 403

    # Admin creates a staff member
    admin_token = create_access_token({"sub": "admin@demo.com", "role": "admin"})
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    res_staff = client.post("/api/admin/users", headers=admin_headers, json={
        "full_name": "Jackie Peyton", "email": "nurse.jackie@clinic.test",
        "password": "password123", "phone": "555-8888", "role": "staff",
    })
    assert res_staff.status_code == 201
    assert res_staff.json()["user"]["role"] == "staff"

    # Admin creates a doctor with credentials
    res_doc = client.post("/api/admin/users", headers=admin_headers, json={
        "full_name": "Dr. Marcus Vance", "email": "vance@clinic.test",
        "password": "password123", "role": "doctor",
        "specialization": "Pediatrics", "license_number": "MD-55421",
        "room_number": "Room 204", "consultation_fee": 75.00,
    })
    assert res_doc.status_code == 201
    assert res_doc.json()["user"]["role"] == "doctor"
    assert res_doc.json()["user"]["doctor_id"] is not None

    # Duplicate email rejected
    assert client.post("/api/admin/users", headers=admin_headers, json={
        "full_name": "Dup", "email": "vance@clinic.test", "password": "password123", "role": "staff",
    }).status_code == 400

    # List shows the provisioned accounts
    res_list = client.get("/api/admin/users", headers=admin_headers)
    assert res_list.status_code == 200
    emails = [u["email"] for u in res_list.json()]
    assert "nurse.jackie@clinic.test" in emails
    assert "vance@clinic.test" in emails

    # Admin can create another admin directly and approve/reject pending requests
    res_new_admin = client.post("/api/admin/users", headers=admin_headers, json={
        "full_name": "Deputy Admin", "email": "deputy@clinic.test",
        "password": "password123", "role": "admin",
    })
    assert res_new_admin.status_code == 201
    assert res_new_admin.json()["user"]["role"] == "admin"
    assert res_new_admin.json()["user"]["is_approved"] is True

    pend_res = client.post("/api/auth/register", json={
        "full_name": "Pending Staff", "email": "pending.staff@clinic.test",
        "password": "password123", "role": "staff",
    })
    pend_id = pend_res.json()["user"]["id"]
    assert client.post("/api/auth/login", json={
        "email": "pending.staff@clinic.test", "password": "password123",
    }).status_code == 403

    app_res = client.post(f"/api/admin/users/{pend_id}/approve", headers=admin_headers)
    assert app_res.status_code == 200
    assert app_res.json()["user"]["is_approved"] is True
    assert client.post("/api/auth/login", json={
        "email": "pending.staff@clinic.test", "password": "password123",
    }).status_code == 200

    rej_res = client.post("/api/auth/register", json={
        "full_name": "Reject Me", "email": "reject@clinic.test",
        "password": "password123", "role": "admin",
    })
    rej_id = rej_res.json()["user"]["id"]
    assert client.delete(f"/api/admin/users/{rej_id}", headers=admin_headers).status_code == 200


def test_auth_cookie_secure_flag_matches_request_scheme(db_session, monkeypatch):
    import app.routers.auth as auth_module

    monkeypatch.setattr(auth_module.settings, "DEMO_MODE", False)
    client = _client_with_routers(db_session)

    # Local HTTP (e.g., http://localhost:8000): cookie must NOT set Secure even when DEMO_MODE=false
    setup_res = client.post("/api/auth/setup-admin", json={
        "full_name": "Local Admin",
        "email": "localadmin@clinic.test",
        "password": "password123",
    })
    assert setup_res.status_code == 200
    set_cookie_http = setup_res.headers.get("set-cookie", "")
    assert "access_token=" in set_cookie_http
    assert "Secure" not in set_cookie_http

    # Behind HTTPS reverse proxy (X-Forwarded-Proto: https): cookie MUST set Secure
    login_https_proxy = client.post(
        "/api/auth/login",
        headers={"X-Forwarded-Proto": "https"},
        json={"email": "localadmin@clinic.test", "password": "password123"},
    )
    assert login_https_proxy.status_code == 200
    assert "Secure" in login_https_proxy.headers.get("set-cookie", "")

    # Direct HTTPS request URL scheme: cookie MUST set Secure
    https_client = TestClient(_client_with_routers(db_session).app, base_url="https://testserver")
    reg_https = https_client.post("/api/auth/register", json={
        "full_name": "HTTPS Patient",
        "email": "https.patient@clinic.test",
        "password": "password123",
    })
    assert reg_https.status_code == 201
    assert "Secure" in reg_https.headers.get("set-cookie", "")


def test_login_normalizes_email_and_profile_rejects_bad_dob(db_session):
    seed_demo_data(db_session)
    client = _client_with_routers(db_session, include_admin=True)

    # Case-insensitive + whitespace-trimmed login succeeds
    res = client.post("/api/auth/login", json={"email": "  Patient@Demo.COM ", "password": "patient123"})
    assert res.status_code == 200
    pat_token = res.json()["access_token"]

    # Invalid DOB returns 400 instead of 500
    bad_dob = client.put(
        "/api/auth/profile",
        headers={"Authorization": f"Bearer {pat_token}"},
        json={"date_of_birth": "not-a-date"},
    )
    assert bad_dob.status_code == 400

    # Invalid role on registration returns 400
    bad_role = client.post("/api/auth/register", json={
        "email": "badrole@clinic.test",
        "password": "password123",
        "full_name": "Bad Role",
        "role": "superuser",
    })
    assert bad_role.status_code == 400

    # Doctor can update own doctor profile fields (availability, room, fee)
    doc_login = client.post("/api/auth/login", json={"email": "doctor@demo.com", "password": "doctor123"})
    assert doc_login.status_code == 200
    doc_token = doc_login.json()["access_token"]
    doc_upd = client.put(
        "/api/auth/profile",
        headers={"Authorization": f"Bearer {doc_token}"},
        json={"room_number": "Room 305", "consultation_fee": 750.00, "is_available": False},
    )
    assert doc_upd.status_code == 200
    assert doc_upd.json()["doctor_profile"]["room_number"] == "Room 305"
    assert doc_upd.json()["doctor_profile"]["is_available"] is False

    # Admin can deactivate and reactivate another approved user, but not self
    admin_token = create_access_token({"sub": "admin@demo.com", "role": "admin"})
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    staff_u = db_session.query(User).filter(User.email == "staff@demo.com").first()
    admin_u = db_session.query(User).filter(User.email == "admin@demo.com").first()

    assert client.post(f"/api/admin/users/{admin_u.id}/toggle-active", headers=admin_headers).status_code == 400
    tog_off = client.post(f"/api/admin/users/{staff_u.id}/toggle-active", headers=admin_headers)
    assert tog_off.status_code == 200
    assert tog_off.json()["user"]["is_approved"] is False
    assert client.post("/api/auth/login", json={"email": "staff@demo.com", "password": "staff123"}).status_code == 403
    tog_on = client.post(f"/api/admin/users/{staff_u.id}/toggle-active", headers=admin_headers)
    assert tog_on.status_code == 200
    assert tog_on.json()["user"]["is_approved"] is True
