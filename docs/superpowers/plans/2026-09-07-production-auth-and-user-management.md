# Production Authentication, User Management, and Personalized Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate all demo accounts and seeds, introduce a secure first-run admin setup wizard, enable public patient self-registration, provide admin staff management, and direct authenticated users to role-scoped personalized dashboards.

**Architecture:** Extend FastAPI backend with dedicated endpoints for setup status, patient registration, admin staff provisioning, and patient self-service (`/api/patient/me/*`). Secure all sessions using HttpOnly SameSite=Strict JWT cookies with `DEMO_MODE=False`. Dynamically reconfigure the single-page application navigation and data views based on the authenticated user's role profile.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy 2.0, SQLite (WAL mode), Pydantic v2, bcrypt, PyJWT, Tailwind CSS, Vanilla JavaScript (ES6+).

## Global Constraints

- Zero demo seeds in production: remove `seed_demo_data()` and automatic startup database seeding.
- Password minimum length is 8 characters.
- Session tokens are stored in HttpOnly cookies with `samesite="strict"` and `secure=True` when `DEMO_MODE=False`.
- No new external runtime dependencies: leverage existing FastAPI, SQLAlchemy, and standard libraries.
- Every API route modifying or accessing medical or staff records must enforce role checks via `require_roles()`.

---

### Task 1: Zero-Seed Policy, Production Config & First-Run Admin Setup API

**Files:**
- Modify: `app/config.py:10-15`
- Modify: `render.yaml:10-15`
- Modify: `app/main.py:1-25`
- Modify: `app/routers/auth.py:1-120`
- Test: `tests/test_auth.py`

**Interfaces:**
- Produces: `GET /api/auth/setup-status` -> `{"initialized": bool}`
- Produces: `POST /api/auth/setup-admin` with `{full_name: str, email: str, password: str, phone: Optional[str]}` -> `{"status": "success", "user": dict}` (Sets auth cookie)
- Consumes: `User`, `UserRole`, `get_password_hash`, `create_access_token`

- [ ] **Step 1: Write failing tests for setup-status and setup-admin**

In `tests/test_auth.py`, append:
```python
def test_setup_status_uninitialized(db_session, client):
    res = client.get("/api/auth/setup-status")
    assert res.status_code == 200
    assert res.json() == {"initialized": False}

def test_setup_admin_success_and_locks(db_session, client):
    payload = {
        "full_name": "Clinic Admin",
        "email": "admin@clinic.com",
        "password": "StrongPassword123!",
        "phone": "555-0100"
    }
    res = client.post("/api/auth/setup-admin", json=payload)
    assert res.status_code == 200
    assert res.json()["user"]["role"] == "admin"
    assert "access_token" in res.cookies

    # Second call must be blocked with 403
    res2 = client.post("/api/auth/setup-admin", json=payload)
    assert res2.status_code == 403

    # Now setup-status should be true
    res3 = client.get("/api/auth/setup-status")
    assert res3.status_code == 200
    assert res3.json() == {"initialized": True}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_auth.py::test_setup_status_uninitialized -v`  
Expected: FAIL (404 Not Found)

- [ ] **Step 3: Implement setup endpoints, disable seed on startup, and set DEMO_MODE=False**

In `app/config.py`:
`DEMO_MODE: bool = False`

In `render.yaml`:
`DEMO_MODE: "false"`

In `app/main.py`:
Remove `seed_demo_data(db)` from `lifespan`.

In `app/routers/auth.py`:
Implement `GET /api/auth/setup-status` and `POST /api/auth/setup-admin`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_auth.py::test_setup_status_uninitialized tests/test_auth.py::test_setup_admin_success_and_locks -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/config.py render.yaml app/main.py app/routers/auth.py tests/test_auth.py
git commit -m "feat: implement first-run admin setup and remove auto-seeding"
```

---

### Task 2: Public Patient Self-Registration API

**Files:**
- Modify: `app/routers/auth.py`
- Test: `tests/test_auth.py`

**Interfaces:**
- Produces: `POST /api/auth/register` -> `{"status": "success", "user": dict}` (Sets auth cookie)
- Consumes: `User`, `Patient`, `UserRole`, `get_password_hash`, `create_access_token`

- [ ] **Step 1: Write failing test for patient self-registration**

In `tests/test_auth.py`, append:
```python
def test_patient_registration_success(db_session, client):
    payload = {
        "full_name": "Jane Doe",
        "email": "jane@example.com",
        "password": "Password123!",
        "phone": "555-0123",
        "date_of_birth": "1995-04-12",
        "gender": "Female",
        "blood_group": "A+",
        "emergency_contact_name": "John Doe",
        "emergency_contact_phone": "555-0124",
        "allergies": "Peanuts",
        "medical_history": "None",
    }
    res = client.post("/api/auth/register", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["user"]["email"] == "jane@example.com"
    assert data["user"]["role"] == "patient"
    assert data["user"]["patient_id"] is not None
    assert "access_token" in res.cookies
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_auth.py::test_patient_registration_success -v`  
Expected: FAIL (404 Not Found)

- [ ] **Step 3: Implement POST /api/auth/register in app/routers/auth.py**

Create `RegisterPatientPayload` and `register_patient()` endpoint creating both `User` and `Patient` record atomically.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_auth.py::test_patient_registration_success -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/routers/auth.py tests/test_auth.py
git commit -m "feat: add patient self-registration API"
```

---

### Task 3: Admin User & Staff Management API

**Files:**
- Create: `app/routers/admin.py`
- Modify: `app/main.py`
- Test: `tests/test_admin.py`

**Interfaces:**
- Produces: `GET /api/admin/users` -> `List[dict]`
- Produces: `POST /api/admin/users` -> `{"status": "success", "user": dict}`
- Consumes: `require_roles([UserRole.ADMIN])`, `User`, `Doctor`, `Patient`

- [ ] **Step 1: Write failing test for admin user management**

Create `tests/test_admin.py` testing creation of Doctor and Staff users with admin token, and verification that non-admins get HTTP 403.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_admin.py -v`  
Expected: FAIL (404 Not Found)

- [ ] **Step 3: Implement app/routers/admin.py and register in app/main.py**

Add `GET /api/admin/users` and `POST /api/admin/users` with support for role assignment and doctor profile metadata.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_admin.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/routers/admin.py app/main.py tests/test_admin.py
git commit -m "feat: add admin user and staff management API"
```

---

### Task 4: Patient Personalized Data APIs (/api/patient/me/*)

**Files:**
- Create: `app/routers/patient.py`
- Modify: `app/main.py`
- Test: `tests/test_patient.py`

**Interfaces:**
- Produces: `GET /api/patient/me/profile` -> Patient profile details
- Produces: `GET /api/patient/me/appointments` -> List of patient's appointments
- Produces: `GET /api/patient/me/queue-ticket` -> Active queue ticket for today
- Produces: `GET /api/patient/me/invoices` -> List of patient's invoices
- Consumes: `require_roles([UserRole.PATIENT])`, `Patient`, `Appointment`, `QueueTicket`, `Invoice`

- [ ] **Step 1: Write failing test for patient personalized data**

Create `tests/test_patient.py` verifying `/api/patient/me/profile`, `/api/patient/me/appointments`, etc.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_patient.py -v`  
Expected: FAIL (404 Not Found)

- [ ] **Step 3: Implement app/routers/patient.py and register in app/main.py**

Create endpoints scoped directly to `current_user.patient`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_patient.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/routers/patient.py app/main.py tests/test_patient.py
git commit -m "feat: add patient personalized self-service APIs"
```

---

### Task 5: Frontend UI Redesign: Remove Demo Switcher, Add First-Run Setup & Registration Modals

**Files:**
- Modify: `app/static/index.html`
- Modify: `app/static/app.js`

**Interfaces:**
- Removes: Demo buttons bar (Sarah Connor, Dr. Emily Stone, etc.)
- Adds: First-Run Setup Wizard modal `#setupModal`
- Adds: Patient Registration modal `#registerModal`
- Adds: "Register" button in header

- [ ] **Step 1: Remove demo bar and add Setup and Register modals to index.html**
- [ ] **Step 2: Add setup and register handlers to app/static/app.js**
- [ ] **Step 3: Verify in browser and check syntax**
- [ ] **Step 4: Commit**

```bash
git add app/static/index.html app/static/app.js
git commit -m "feat: add first-run setup and patient registration modals to UI"
```

---

### Task 6: Dynamic Role-Gated Navigation & Personalized Dashboards in UI

**Files:**
- Modify: `app/static/index.html`
- Modify: `app/static/app.js`

**Interfaces:**
- Dynamically hides tabs that the current role is not authorized to access.
- Renders real user name and personal medical info on the Patient Dashboard card instead of hardcoded demo values.
- Automatically populates the Doctor schedule and prescription generator using the authenticated doctor's profile.

- [ ] **Step 1: Update navigation tabs and patient profile elements in index.html**
- [ ] **Step 2: Update role gating and personalized loader in app/static/app.js**
- [ ] **Step 3: Test and verify role switching**
- [ ] **Step 4: Commit**

```bash
git add app/static/index.html app/static/app.js
git commit -m "feat: role-gated navigation and personalized patient dashboard loaders"
```

---

### Task 7: Admin Console User Management Interface

**Files:**
- Modify: `app/static/index.html`
- Modify: `app/static/app.js`

**Interfaces:**
- Adds: Admin User Management tab panel `#portal-admin-users`
- Adds: "Add Doctor / Staff" modal `#addUserModal`
- Adds: Table rendering clinic accounts with role badges

- [ ] **Step 1: Add User Management section to index.html**
- [ ] **Step 2: Add Admin User Management client logic in app/static/app.js**
- [ ] **Step 3: Commit**

```bash
git add app/static/index.html app/static/app.js
git commit -m "feat: add admin staff management interface"
```

---

### Task 8: Test Suite Updates & Complete Verification

**Files:**
- Modify: `tests/test_auth.py`
- Modify: `tests/test_e2e_flow.py`
- Modify: `app/seed.py`

**Interfaces:**
- Ensures the entire pytest test suite passes cleanly with zero reliance on automatic startup demo seeding.

- [ ] **Step 1: Update existing test fixtures that relied on seed_demo_data**
- [ ] **Step 2: Run full test suite to verify everything passes**
- [ ] **Step 3: Commit**

```bash
git add tests/ app/seed.py
git commit -m "test: update test suite for zero-seed production auth"
```
