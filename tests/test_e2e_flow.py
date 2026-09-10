"""End-to-End System Verification Suite for Clinic Management System.

Validates the complete clinical lifecycle across all subsystems:
1. API health check (/api/health)
2. Doctor listing (/api/appointments/doctors)
3. Patient appointment booking (/api/appointments/book)
4. Live queue ticket issuance (/api/queue/issue) and live status query (/api/queue/live-status)
5. Front-desk ticket calling (/api/queue/call-next)
6. Doctor EMR consultation note & digital prescription generation (/api/emr/prescription/create)
7. Staff billing invoice generation and receipt creation (/api/billing/create)
8. Patient feedback submission with VADER sentiment scoring and analytics verification (/api/feedback & /api/feedback/analytics)
9. Reception chat relay and FAQ bot inquiry verification (/api/chat/ws/{session_id} and /api/chat/send)
"""

import uuid
from datetime import date
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import engine, Base, SessionLocal
from app.models import QueueTicket, QueueStatus, Appointment
from app.seed import seed_demo_data

# Ensure database tables and seed data are initialized
Base.metadata.create_all(bind=engine)
_init_db = SessionLocal()
try:
    seed_demo_data(_init_db)
finally:
    _init_db.close()

client = TestClient(app)


# ---------------------------------------------------------------------------
# 1. Baseline Flow from Task Brief
# ---------------------------------------------------------------------------

def test_full_patient_to_prescription_flow():
    """Baseline integration test from task brief verifying read endpoints."""
    # 1. Health
    h = client.get("/api/health")
    assert h.status_code == 200
    assert h.json()["status"] == "healthy"

    # 2. Doctors list
    d = client.get("/api/appointments/doctors")
    assert d.status_code == 200
    doctors = d.json()
    assert len(doctors) > 0
    assert "name" in doctors[0]
    assert "specialization" in doctors[0]

    # 3. Live Queue
    q = client.get("/api/queue/live-status")
    assert q.status_code == 200
    queue_data = q.json()
    assert "waiting_count" in queue_data
    assert "currently_serving" in queue_data

    # 4. Feedback Analytics (staff-only endpoint — anonymous access must be rejected)
    f = client.get("/api/feedback/analytics")
    assert f.status_code == 401
    s_login = client.post("/api/auth/login", json={"email": "staff@demo.com", "password": "staff123"})
    assert s_login.status_code == 200
    f = client.get(
        "/api/feedback/analytics",
        headers={"Authorization": f"Bearer {s_login.json()['access_token']}"},
    )
    assert f.status_code == 200
    analytics = f.json()
    assert "avg_rating" in analytics
    assert "positive_pct" in analytics


# ---------------------------------------------------------------------------
# 2. Full Comprehensive End-to-End Clinical Lifecycle (Steps 1 - 9)
# ---------------------------------------------------------------------------

def test_complete_e2e_clinical_workflow():
    """Exhaustive end-to-end clinical workflow simulating full patient experience:
    Health -> Doctor Directory -> Patient Booking -> Queue Ticket -> Ticket Call ->
    Doctor EMR & Prescription -> Staff Billing -> Patient VADER Feedback -> Chat & Bot FAQ.
    """
    # Clean slate for the queue and the fixed e2e booking date: close any waiting
    # tickets and drop stale bookings left by earlier runs
    _cleanup = SessionLocal()
    try:
        _cleanup.query(QueueTicket).filter(QueueTicket.status == QueueStatus.WAITING).update(
            {"status": QueueStatus.COMPLETED}
        )
        _cleanup.query(Appointment).filter(Appointment.appointment_date == "2026-11-20").delete()
        _cleanup.commit()
    finally:
        _cleanup.close()

    # -----------------------------------------------------------------------
    # Step 1: API Health Check
    # -----------------------------------------------------------------------
    health_res = client.get("/api/health")
    assert health_res.status_code == 200
    health_json = health_res.json()
    assert health_json["status"] == "healthy"
    assert "Clinic Management System" in health_json["service"]

    # -----------------------------------------------------------------------
    # Step 2: Doctor Directory Listing
    # -----------------------------------------------------------------------
    doctors_res = client.get("/api/appointments/doctors")
    assert doctors_res.status_code == 200
    doctors = doctors_res.json()
    assert len(doctors) >= 1
    selected_doctor = doctors[0]
    doctor_id = selected_doctor["id"]
    doctor_room = selected_doctor.get("room_number", "Room 102")
    assert doctor_id > 0

    # -----------------------------------------------------------------------
    # Step 3: Patient Authentication & Appointment Booking
    # -----------------------------------------------------------------------
    # Login as demo patient
    p_login_res = client.post(
        "/api/auth/login",
        json={"email": "patient@demo.com", "password": "patient123"},
    )
    assert p_login_res.status_code == 200
    patient_auth = p_login_res.json()
    patient_token = patient_auth["access_token"]
    patient_user_id = patient_auth["user"]["id"]
    patient_headers = {"Authorization": f"Bearer {patient_token}"}

    # Verify patient identity via /api/auth/me
    me_res = client.get("/api/auth/me", headers=patient_headers)
    assert me_res.status_code == 200
    assert me_res.json()["role"] == "patient"

    # Book an appointment with a unique time slot to prevent conflicts across test runs
    unique_suffix = uuid.uuid4().hex[:4]
    booking_payload = {
        "doctor_id": doctor_id,
        "appointment_date": "2026-11-20",
        "time_slot": f"09:{unique_suffix[:2]} - 10:00",
        "reason_for_visit": "Annual health checkup and hypertension review",
    }
    book_res = client.post(
        "/api/appointments/book",
        headers=patient_headers,
        json=booking_payload,
    )
    assert book_res.status_code == 200
    booking_data = book_res.json()
    assert booking_data["status"] == "success"
    appointment_id = booking_data["appointment_id"]
    assert appointment_id > 0

    # Verify the schedule endpoint is protected (anonymous -> 401, patient cookie -> 403)
    schedule_anon = client.get(
        f"/api/appointments/doctor-schedule/{doctor_id}?schedule_date=2026-11-20"
    )
    assert schedule_anon.status_code in (401, 403)

    # -----------------------------------------------------------------------
    # Step 4: Live Queue Ticket Issuance & Status Query
    # -----------------------------------------------------------------------
    # Patient arrives at the clinic; patient self-issues their own ticket
    issue_payload = {
        "doctor_id": doctor_id,
        "patient_id": 1,
        "priority": "normal",
    }
    issue_res = client.post("/api/queue/issue", json=issue_payload, headers=patient_headers)
    assert issue_res.status_code == 200
    ticket_data = issue_res.json()
    assert ticket_data["status"] == "success"
    ticket_number = ticket_data["ticket_number"]
    ticket_id = ticket_data["id"]
    assert ticket_number.startswith("Q-")

    # Verify live queue status reflects the newly waiting ticket
    q_live_res = client.get("/api/queue/live-status")
    assert q_live_res.status_code == 200
    q_live_data = q_live_res.json()
    assert ticket_number in q_live_data["waiting_tickets"]
    assert q_live_data["waiting_count"] >= 1

    # -----------------------------------------------------------------------
    # Step 5: Front-Desk Ticket Calling (Next Patient)
    # -----------------------------------------------------------------------
    # Authenticate as front-desk staff
    staff_login_res = client.post(
        "/api/auth/login",
        json={"email": "staff@demo.com", "password": "staff123"},
    )
    assert staff_login_res.status_code == 200
    staff_token = staff_login_res.json()["access_token"]
    staff_headers = {"Authorization": f"Bearer {staff_token}"}

    # Staff views the doctor schedule (staff-only endpoint) and sees the new booking
    schedule_res = client.get(
        f"/api/appointments/doctor-schedule/{doctor_id}?schedule_date=2026-11-20",
        headers=staff_headers,
    )
    assert schedule_res.status_code == 200
    schedule_items = schedule_res.json()
    assert any(item["id"] == appointment_id for item in schedule_items)

    # Staff calls the next patient for this doctor
    call_res = client.post(
        f"/api/queue/call-next?doctor_id={doctor_id}",
        headers=staff_headers,
    )
    assert call_res.status_code == 200
    call_data = call_res.json()
    assert call_data["status"] == "success"
    called_ticket = call_data["called_ticket"]
    assert called_ticket.startswith("Q-")

    # Verify live status updates with currently serving ticket
    q_called_res = client.get("/api/queue/live-status")
    assert q_called_res.status_code == 200
    q_called_data = q_called_res.json()
    assert q_called_data["currently_serving"] == called_ticket

    # -----------------------------------------------------------------------
    # Step 6: Doctor EMR Consultation Note & Digital Prescription Generation
    # -----------------------------------------------------------------------
    # Authenticate as Doctor
    doc_login_res = client.post(
        "/api/auth/login",
        json={"email": "doctor@demo.com", "password": "doctor123"},
    )
    assert doc_login_res.status_code == 200
    doctor_token = doc_login_res.json()["access_token"]
    doc_headers = {"Authorization": f"Bearer {doctor_token}"}

    # Doctor views patient EMR history
    emr_history_res = client.get("/api/emr/patient/1", headers=doc_headers)
    assert emr_history_res.status_code == 200
    patient_emr = emr_history_res.json()
    assert patient_emr["name"] == "Sarah Connor"
    assert patient_emr["blood_group"] == "O+"

    # Doctor generates a digital prescription with clinical notes
    prescription_payload = {
        "patient_id": 1,
        "doctor_id": doctor_id,
        "diagnosis": "Stage 1 Essential Hypertension & Allergic Rhinitis",
        "clinical_notes": "BP: 138/88 mmHg. Advised low-sodium DASH diet. Regular aerobic exercise.",
        "medications": [
            {
                "drug_name": "Amlodipine Besylate",
                "dosage": "5mg",
                "frequency": "Once daily (Morning)",
                "duration": "30 days",
                "instructions": "Take with water after breakfast",
            },
            {
                "drug_name": "Cetirizine HCl",
                "dosage": "10mg",
                "frequency": "Once daily (Night)",
                "duration": "7 days",
                "instructions": "Take before sleep for seasonal allergies",
            },
        ],
    }
    rx_res = client.post(
        "/api/emr/prescription/create",
        headers=doc_headers,
        json=prescription_payload,
    )
    assert rx_res.status_code == 200
    rx_data = rx_res.json()
    assert rx_data["status"] == "success"
    prescription_id = rx_data["prescription_id"]
    qr_code_hash = rx_data["qr_code_hash"]
    assert len(qr_code_hash) == 16

    # Verify new prescription is reflected in patient's EMR
    emr_updated_res = client.get("/api/emr/patient/1", headers=doc_headers)
    assert emr_updated_res.status_code == 200
    all_rx = emr_updated_res.json()["prescriptions"]
    assert any(rx["id"] == prescription_id for rx in all_rx)

    # -----------------------------------------------------------------------
    # Step 7: Staff Billing Invoice Generation & Receipt Verification
    # -----------------------------------------------------------------------
    billing_payload = {
        "patient_id": 1,
        "queue_ticket_id": ticket_id,
        "consultation_fee": 60.00,
        "medication_fee": 35.50,
        "other_fees": 10.00,
        "discount_amount": 5.50,
        "payment_method": "credit_card",
    }
    invoice_res = client.post(
        "/api/billing/create",
        headers=staff_headers,
        json=billing_payload,
    )
    assert invoice_res.status_code == 200
    invoice_data = invoice_res.json()
    assert invoice_data["status"] == "success"
    invoice_id = invoice_data["invoice_id"]
    receipt_number = invoice_data["receipt_number"]
    assert receipt_number.startswith("REC-")
    expected_total = round((60.00 + 35.50 + 10.00) - 5.50, 2)
    assert invoice_data["total"] == expected_total

    # Verify invoice appears in staff billing list
    list_inv_res = client.get("/api/billing/list", headers=staff_headers)
    assert list_inv_res.status_code == 200
    invoices_list = list_inv_res.json()
    assert any(inv["receipt_number"] == receipt_number for inv in invoices_list)

    # Retrieve full receipt details
    receipt_res = client.get(
        f"/api/billing/receipt/{receipt_number}",
        headers=staff_headers,
    )
    assert receipt_res.status_code == 200
    receipt_data = receipt_res.json()
    assert receipt_data["receipt_number"] == receipt_number
    assert receipt_data["patient_name"] == "Sarah Connor"
    assert receipt_data["total_amount"] == expected_total
    assert receipt_data["payment_method"] == "credit_card"

    # -----------------------------------------------------------------------
    # Step 8: Patient Feedback Submission with VADER Sentiment Scoring
    # -----------------------------------------------------------------------
    feedback_payload = {
        "doctor_id": doctor_id,
        "rating": 5,
        "tags": ["Attentive Doctor", "Painless Service", "Modern Clinic"],
        "comment_text": "Dr. Emily Stone provided phenomenal, deeply caring treatment! The queue display and prescription QR code were super efficient.",
    }
    fb_res = client.post(
        "/api/feedback",
        headers=patient_headers,
        json=feedback_payload,
    )
    assert fb_res.status_code == 200
    fb_data = fb_res.json()
    assert fb_data["status"] == "success"
    sentiment_result = fb_data["sentiment"]
    assert sentiment_result["sentiment_label"] == "positive"
    assert sentiment_result["sentiment_score"] > 0.05
    assert sentiment_result["flagged_critical"] is False

    # Verify analytics update (staff-only endpoint)
    analytics_res = client.get("/api/feedback/analytics", headers=staff_headers)
    assert analytics_res.status_code == 200
    analytics_data = analytics_res.json()
    assert analytics_data["total"] >= 1
    assert analytics_data["positive_pct"] > 0
    assert any(item["id"] == fb_data["id"] for item in analytics_data["items"])

    # -----------------------------------------------------------------------
    # Step 9: Reception Live Chat Relay & Automated FAQ Bot Verification
    # -----------------------------------------------------------------------
    chat_session_id = f"e2e-session-{uuid.uuid4().hex[:8]}"

    # 9a. Real-time WebSocket Inquiry & Automated Bot Response
    # Re-login as patient so the WS handshake cookie carries patient identity
    # (identity is derived from the authenticated user, not the WS payload)
    client.post("/api/auth/login", json={"email": "patient@demo.com", "password": "patient123"})
    with client.websocket_connect(f"/api/chat/ws/{chat_session_id}") as ws:
        # Patient sends inquiry about clinic opening hours
        ws.send_json({
            "sender_name": "Sarah Connor",
            "message": "What are your operating hours and clinic schedule?",
            "role": "patient",
        })

        # Echoed patient broadcast
        echo_msg = ws.receive_json()
        assert echo_msg["sender"] == "Sarah Connor"
        assert echo_msg["role"] == "patient"
        assert "operating hours" in echo_msg["message"]

        # Automated FAQ Bot reply
        bot_msg = ws.receive_json()
        assert bot_msg["sender"] == "Clinic Assistant Bot"
        assert bot_msg["role"] == "bot"
        assert bot_msg["is_bot_reply"] is True
        assert "8:00 AM" in bot_msg["message"]

    # 9b. REST Fallback & Staff Relay Verification
    rest_chat_payload = {
        "session_id": chat_session_id,
        "sender_name": "Reception Staff",
        "role": "staff",
        "message": "Hello Sarah, your receipt REC is ready and your prescription has been sent.",
    }
    rest_res = client.post("/api/chat/send", json=rest_chat_payload, headers=staff_headers)
    assert rest_res.status_code == 200
    rest_data = rest_res.json()
    assert rest_data["status"] == "success"
    # Staff message should not trigger bot response
    assert rest_data["bot_reply"] is None

    # Verify complete chat history for session
    hist_res = client.get(f"/api/chat/history/{chat_session_id}", headers=staff_headers)
    assert hist_res.status_code == 200
    history = hist_res.json()
    assert len(history) >= 3  # Patient question, Bot reply, Staff message
    roles_in_history = [m["role"] for m in history]
    assert "patient" in roles_in_history
    assert "bot" in roles_in_history
    assert "staff" in roles_in_history


# ---------------------------------------------------------------------------
# 3. Security, RBAC & Boundary Verification
# ---------------------------------------------------------------------------

def test_e2e_rbac_and_boundary_checks():
    """Validates role-based access control, unauthenticated rejection, and boundary handling."""
    # Ensure client cookies are cleared to simulate anonymous visitor
    client.cookies.clear()

    # 1. Unauthenticated attempts to book or write clinical data must be rejected
    unauth_rx = client.post(
        "/api/emr/prescription/create",
        json={
            "patient_id": 1,
            "doctor_id": 1,
            "diagnosis": "Test",
            "medications": [],
        },
    )
    assert unauth_rx.status_code == 401

    unauth_bill = client.post(
        "/api/billing/create",
        json={"patient_id": 1, "consultation_fee": 50.0},
    )
    assert unauth_bill.status_code == 401

    # 2. Patients cannot issue prescriptions (Role-Based Access Control)
    p_login = client.post(
        "/api/auth/login",
        json={"email": "patient@demo.com", "password": "patient123"},
    )
    patient_headers = {"Authorization": f"Bearer {p_login.json()['access_token']}"}

    forbidden_rx = client.post(
        "/api/emr/prescription/create",
        headers=patient_headers,
        json={
            "patient_id": 1,
            "doctor_id": 1,
            "diagnosis": "Unauthorized diagnosis",
            "medications": [],
        },
    )
    assert forbidden_rx.status_code == 403

    # 3. Staff cannot submit feedback as patient
    s_login = client.post(
        "/api/auth/login",
        json={"email": "staff@demo.com", "password": "staff123"},
    )
    staff_headers = {"Authorization": f"Bearer {s_login.json()['access_token']}"}
    invalid_fb = client.post(
        "/api/feedback",
        headers=staff_headers,
        json={"rating": 5, "comment_text": "Staff attempting patient feedback"},
    )
    assert invalid_fb.status_code == 400

    # 4. Calling next patient when queue has no waiting patients for a non-existent doctor returns 404
    no_queue_call = client.post(
        "/api/queue/call-next?doctor_id=99999",
        headers=staff_headers,
    )
    assert no_queue_call.status_code == 404
