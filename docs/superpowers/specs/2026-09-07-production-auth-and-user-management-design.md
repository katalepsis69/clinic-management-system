# Production Authentication, User Management, and Personalized Dashboard Design

**Date:** 2026-09-07  
**Status:** Approved  
**Author:** Antigravity Engineering  
**Scope:** Replaces legacy demo account system with production-ready authentication, first-run admin provisioning, self-service patient onboarding, admin staff management, and role-scoped personalized dashboards.

---

## 1. Executive Summary

The Clinic Management System is transitioning from an interactive demo model (with hardcoded accounts and universally visible tabs) to a secure, production-ready multi-tenant application flow.

### Key Objectives
1. **Zero Demo Clutter**: Completely eliminate mock seeds (seed_demo_data), quick-login switchers, and hardcoded profile strings (Sarah Connor, Dr. Emily Stone).
2. **First-Run Setup Wizard**: On a clean/empty database, securely prompt for the primary Administrator account setup, then permanently lock the setup endpoint.
3. **Public Self-Registration**: Allow patients to register themselves online with essential demographic and medical history details.
4. **Admin User Management**: Provide a dedicated console within the Admin portal to create, provision, and manage Doctor and Staff accounts.
5. **Strict Role-Gated Navigation & Personalized Dashboards**:
   - Guests see only public clinic information, hours, location, and the AI assistant, with "Sign In" and "Register" actions.
   - Authenticated users are automatically routed to their personalized dashboard, populated exclusively with their own records and permissions.
   - Internal tabs are strictly hidden from unauthorized roles.

---

## 2. System Architecture & Flow

`
+-------------------------------------------------------------------------+
|                              VISITOR                                    |
+-------------------------------------------------------------------------+
                                     |
                                     v
                       GET /api/auth/setup-status
                                     |
                     +---------------+---------------+
                     |                               |
              [Database Empty]               [Admin Exists]
                     |                               |
                     v                               v
          First-Run Setup Wizard             GET /api/auth/me
      (Create Primary Administrator)                 |
                     |                 +-------------+-------------+
                     v                 |                           |
         POST /api/auth/setup-admin    v                           v
             (Permanently Locks)    [Guest]                 [Authenticated]
                                       |                           |
                     +-----------------+                           |
                     |                 |                           |
                     v                 v                           v
               Public Portal      Login Modal            Role-Specific Dashboard:
              (Info, FAQ, AI)    (or Register)           - Patient: My Health Dashboard
                                                         - Doctor: My Schedule & EMR
                                                         - Staff: Queue & Billing Ops
                                                         - Admin: Analytics & Staff Mgmt
`

---

## 3. Detailed Specifications

### 3.1 First-Run Setup & Zero Seed Policy
* **Zero Seed Policy**: pp/seed.py and startup auto-seed routines are removed. No default or mock accounts are inserted into the database.
* **Setup Status API**: GET /api/auth/setup-status queries db.query(User).filter(User.role == UserRole.ADMIN).first().
  * If no admin exists: returns {"initialized": false}.
  * If admin exists: returns {"initialized": true}.
* **Setup Admin API**: POST /api/auth/setup-admin
  * Payload: { "full_name": str, "email": str, "password": str, "phone": Optional[str] }
  * Validation: Strong password (min 8 chars), valid email format.
  * Guard: If db.query(User).filter(User.role == UserRole.ADMIN).first() already exists, immediately raises HTTP 403 Forbidden ("System already initialized").
  * Success: Hashes password with bcrypt, creates User(role=UserRole.ADMIN), sets HttpOnly auth cookie, and logs the user in directly to the Admin console.

### 3.2 Public Patient Self-Registration
* **Endpoint**: POST /api/auth/register
* **Access**: Public, unauthenticated.
* **Payload**:
  `json
  {
    "full_name": "Jane Doe",
    "email": "jane@example.com",
    "password": "SecurePassword123!",
    "phone": "555-0199",
    "date_of_birth": "1992-08-20",
    "gender": "Female",
    "blood_group": "A+",
    "emergency_contact_name": "Bob Doe",
    "emergency_contact_phone": "555-0198",
    "allergies": "None",
    "medical_history": "No chronic illnesses"
  }
  `
* **Validation & Security**:
  * Rejects duplicate email addresses (HTTP 400 Bad Request).
  * Enforces minimum 8-character password.
  * Performs atomic database commit creating both User(role=UserRole.PATIENT) and Patient linked record.
* **Response**: Sets ccess_token HttpOnly cookie and returns the user profile, instantly redirecting the user into their new personalized Patient Dashboard.

### 3.3 Admin User & Staff Management
* **Endpoints**:
  * GET /api/admin/users: Returns list of all accounts with role, contact info, and associated doctor/patient metadata. Guarded by equire_roles([UserRole.ADMIN]).
  * POST /api/admin/users: Creates a new medical professional or administrative staff member.
* **Staff Creation Payload**:
  `json
  {
    "full_name": "Dr. Marcus Vance",
    "email": "vance@clinic.com",
    "password": "InitialPassword123!",
    "role": "doctor",  // "doctor" or "staff"
    "phone": "555-0144",
    // If doctor:
    "specialization": "Pediatrics",
    "license_number": "MD-55421",
    "room_number": "Room 204",
    "consultation_fee": 75.00
  }
  `
* **Validation**: Validates required fields for doctors; ensures role is strictly doctor or staff (prevents privilege escalation unless executed by an admin).

### 3.4 Personalized Dashboards & Role Scoping

#### A. Patient Dashboard
* **Profile Card**: Loaded dynamically from GET /api/patient/me/profile. Renders user's actual name, patient ID, date of birth, blood group, allergies, medical history, and emergency contact.
* **Live Queue Ticket Card**: GET /api/patient/me/queue-ticket. If the patient has a ticket issued today, renders their ticket number, current queue status (waiting, called, in_consultation), and room number. Includes a "Join Queue" button that automatically creates a ticket linked to current_user.patient.id.
* **My Appointments**: GET /api/patient/me/appointments. Renders upcoming and past appointments for this patient.
* **Appointment Booking**: Wizard pre-fills the patient's identity and submits bookings directly under their patient ID.
* **Invoices & Receipts**: GET /api/patient/me/invoices. Shows billing history with itemized line items and payment status.

#### B. Doctor Portal
* **Identity Banner**: Displays Dr. [Full Name], specialization, room number, and consultation fee loaded from current_user.doctor.
* **Daily Schedule**: GET /api/doctor/me/schedule?date=YYYY-MM-DD. Exclusively queries appointments assigned to current_user.doctor.id. Allows updating appointment status (in_consultation, completed, cancelled).
* **EMR Lookup**: Look up patient medical records and past prescriptions for registered patients.
* **Digital Prescription Generator**: Automatically locks doctor_id to current_user.doctor.id. Doctor inputs patient ID, diagnosis, clinical notes, and medications. Generates tamper-proof QR verification code.

#### C. Staff Portal (Staff & Admin)
* **Clinic Queue Management**: Front desk queue console to issue walk-in tickets, call next patient, and update room assignments.
* **Clinic Billing & Invoicing**: Create visit invoices, record payments (cash, card, QR code), and generate printable receipts.

#### D. Admin Portal (Admin Only)
* **Clinic Analytics**: Live feedback sentiment breakdown, patient volume, average wait time, and revenue totals.
* **Staff Management UI**: Interactive table of all staff and doctors with a modal to provision new accounts.

---

## 4. UI/UX Changes & Role Navigation

### 4.1 Header & Navigation Overhaul
* **Demo Bar Removal**: Remove <div class="flex items-center gap-2 border-t border-slate-100 py-2 text-xs"> (the demo accounts row) completely from index.html.
* **Navigation Bar**:
  * When logged out: Only **"Clinic Home"** (public view) is active. The right header shows **"Sign In"** and **"Register"** buttons.
  * When logged in as **Patient**: Tabs show **"My Dashboard"** and **"Clinic Info"**.
  * When logged in as **Doctor**: Tabs show **"My Schedule & EMR"**.
  * When logged in as **Staff**: Tabs show **"Queue Operations"** and **"Billing"**.
  * When logged in as **Admin**: Tabs show **"Analytics"**, **"User Management"**, and **"Queue Operations"**.
* **Header Profile Badge**: Displays real authenticated name, colored role badge, and a functional **"Sign Out"** button.

### 4.2 Auth Modals
1. **Sign In Modal**: Clean email and password inputs with "Don't have an account? Register as Patient" link.
2. **Patient Registration Modal**: Tabbed/stepped or streamlined form:
   - Account Credentials: Full Name, Email, Password, Phone.
   - Medical Profile: DOB, Gender, Blood Group, Allergies, Medical History, Emergency Contact.
3. **First-Run Setup Modal / Banner**: High-priority full-screen modal displayed when /api/auth/setup-status returns uninitialized.

---

## 5. Security & Configuration Standards

* **Cookie Security**:
  * httponly = True
  * samesite = "strict"
  * secure = True in production (controlled via DEMO_MODE = False).
  * max_age = ACCESS_TOKEN_EXPIRE_MINUTES * 60
* **Password Hashing**: crypt with salt rounds.
* **Rate Limiting**: Retain existing in-memory IP/email throttle (max 5 failed attempts per 15 minutes).
* **Configuration Defaults**:
  * DEMO_MODE: bool = False in config.py and ender.yaml.
  * Strong SECRET_KEY validation enforced in production.

---

## 6. Verification Plan

1. **First-Run Setup Verification**:
   - Initialize with clean database (m -f data/clinic.db).
   - Confirm setup screen appears.
   - Create Admin account. Verify setup endpoint returns 403 upon subsequent attempts.
2. **Patient Registration & Dashboard Verification**:
   - Register new patient patient1@test.com.
   - Verify User and Patient records created.
   - Verify immediate login to Patient Dashboard with accurate medical details.
   - Book appointment; verify it appears in "My Appointments".
3. **Admin User Management Verification**:
   - Log in as Admin.
   - Provision new Doctor (dr.test@clinic.com).
   - Log out; log in as Doctor.
   - Verify Doctor Portal loads with Dr. Test's name, room, and scoped schedule.
4. **Access Control Verification**:
   - Attempt to access /api/admin/users as a Patient -> Verify HTTP 403 Forbidden.
   - Attempt to call /api/doctor/me/schedule as a Patient -> Verify HTTP 403 Forbidden.
