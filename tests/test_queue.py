import pytest
from unittest.mock import AsyncMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.models import Base, User, Patient, Doctor, QueueTicket, QueueStatus, UserRole
from app.auth import create_access_token
from app.websocket_manager import QueueConnectionManager, queue_manager
from app.routers.queue import router as queue_router


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


@pytest.fixture
def client(db_session):
    app = FastAPI()
    app.include_router(queue_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


# --- Step 1 Test from Brief: Sequential ticket issuance in database ---

def test_sequential_ticket_issuance(db_session):
    u1 = User(email="doc@test.com", hashed_password="pw", full_name="Doctor", role="doctor")
    u2 = User(email="pat@test.com", hashed_password="pw", full_name="Patient", role="patient")
    u3 = User(email="pat2@test.com", hashed_password="pw", full_name="Patient Two", role="patient")
    db_session.add_all([u1, u2, u3])
    db_session.commit()
    doc = Doctor(user_id=u1.id, specialization="Gen", license_number="L1", room_number="101")
    pat = Patient(user_id=u2.id)
    pat2 = Patient(user_id=u3.id)
    db_session.add_all([doc, pat, pat2])
    db_session.commit()

    t1 = QueueTicket(ticket_number="Q-101", patient_id=pat.id, doctor_id=doc.id, status=QueueStatus.WAITING)
    # Second patient holds the next ticket: a patient can hold only one WAITING ticket
    t2 = QueueTicket(ticket_number="Q-102", patient_id=pat2.id, doctor_id=doc.id, status=QueueStatus.WAITING)
    db_session.add_all([t1, t2])
    db_session.commit()

    tickets = db_session.query(QueueTicket).filter(QueueTicket.status == QueueStatus.WAITING).all()
    assert len(tickets) == 2
    assert tickets[0].ticket_number == "Q-101"
    assert tickets[1].ticket_number == "Q-102"


# --- Unit tests for QueueConnectionManager ---

@pytest.mark.asyncio
async def test_queue_connection_manager_connect_and_disconnect():
    manager = QueueConnectionManager()
    ws_mock = AsyncMock()

    await manager.connect(ws_mock)
    assert ws_mock in manager.active_connections
    ws_mock.accept.assert_awaited_once()

    manager.disconnect(ws_mock)
    assert ws_mock not in manager.active_connections

    # Disconnecting an already removed websocket should not raise
    manager.disconnect(ws_mock)


@pytest.mark.asyncio
async def test_queue_connection_manager_broadcast():
    manager = QueueConnectionManager()
    ws1 = AsyncMock()
    ws2 = AsyncMock()
    # Simulate ws2 failing to verify graceful failure handling
    ws2.send_json.side_effect = Exception("Connection lost")

    manager.active_connections = [ws1, ws2]
    message = {"event": "QUEUE_UPDATED", "ticket": "Q-101"}
    await manager.broadcast(message)

    ws1.send_json.assert_awaited_once_with(message)
    ws2.send_json.assert_awaited_once_with(message)


# --- Integration tests for /api/queue endpoints ---

def test_get_live_status_empty(client):
    res = client.get("/api/queue/live-status")
    assert res.status_code == 200
    data = res.json()
    assert data == {
        "currently_serving": "None",
        "currently_serving_room": "N/A",
        "waiting_count": 0,
        "waiting_tickets": [],
        "estimated_wait_minutes": 0,
    }


def test_issue_ticket_endpoint(client, db_session):
    u_staff = User(email="staff1@demo.com", hashed_password="pw", full_name="Front Desk", role=UserRole.STAFF)
    u_doc = User(email="doc1@demo.com", hashed_password="pw", full_name="Dr. Sarah", role=UserRole.DOCTOR)
    u_pat = User(email="pat1@demo.com", hashed_password="pw", full_name="John Doe", role=UserRole.PATIENT)
    u_pat2 = User(email="pat1b@demo.com", hashed_password="pw", full_name="Jane Doe", role=UserRole.PATIENT)
    db_session.add_all([u_staff, u_doc, u_pat, u_pat2])
    db_session.commit()

    doc = Doctor(user_id=u_doc.id, specialization="Cardiology", license_number="DOC-123", room_number="Room 204")
    pat = Patient(user_id=u_pat.id)
    pat2 = Patient(user_id=u_pat2.id)
    db_session.add_all([doc, pat, pat2])
    db_session.commit()

    staff_headers = {"Authorization": f"Bearer {create_access_token({'sub': u_staff.email, 'role': u_staff.role.value})}"}

    # Unauthenticated issue is rejected
    res_anon = client.post("/api/queue/issue", json={"doctor_id": doc.id, "patient_id": pat.id, "priority": "normal"})
    assert res_anon.status_code == 401

    # Issue first ticket (staff walk-in for pat)
    res1 = client.post(
        "/api/queue/issue",
        json={"doctor_id": doc.id, "patient_id": pat.id, "priority": "normal"},
        headers=staff_headers,
    )
    assert res1.status_code == 200
    d1 = res1.json()
    assert d1["status"] == "success"
    assert d1["ticket_number"] == "Q-101"
    assert "id" in d1

    # Same patient cannot hold two waiting tickets
    res_dup = client.post(
        "/api/queue/issue",
        json={"doctor_id": doc.id, "patient_id": pat.id, "priority": "urgent"},
        headers=staff_headers,
    )
    assert res_dup.status_code == 409

    # Issue second ticket for another patient
    res2 = client.post(
        "/api/queue/issue",
        json={"doctor_id": doc.id, "patient_id": pat2.id, "priority": "urgent"},
        headers=staff_headers,
    )
    assert res2.status_code == 200
    d2 = res2.json()
    assert d2["status"] == "success"
    assert d2["ticket_number"] == "Q-102"

    # Verify live status reflects waiting tickets
    live_res = client.get("/api/queue/live-status")
    assert live_res.status_code == 200
    live_data = live_res.json()
    assert live_data["waiting_count"] == 2
    assert live_data["waiting_tickets"] == ["Q-101", "Q-102"]
    assert live_data["estimated_wait_minutes"] == 20
    assert live_data["currently_serving"] == "None"


def test_call_next_patient_flow(client, db_session):
    u_doc = User(email="doc2@demo.com", hashed_password="pw", full_name="Dr. Jones", role=UserRole.DOCTOR)
    u_pat1 = User(email="pat2@demo.com", hashed_password="pw", full_name="Patient Two", role=UserRole.PATIENT)
    u_pat2 = User(email="pat3@demo.com", hashed_password="pw", full_name="Patient Three", role=UserRole.PATIENT)
    db_session.add_all([u_doc, u_pat1, u_pat2])
    db_session.commit()

    doc = Doctor(user_id=u_doc.id, specialization="Pediatrics", license_number="PED-456", room_number="Room 105")
    pat1 = Patient(user_id=u_pat1.id)
    pat2 = Patient(user_id=u_pat2.id)
    db_session.add_all([doc, pat1, pat2])
    db_session.commit()

    # Create tokens
    doctor_token = create_access_token({"sub": "doc2@demo.com", "role": "doctor"})
    patient_token = create_access_token({"sub": "pat2@demo.com", "role": "patient"})

    # Issue two tickets (requires staff auth)
    staff_headers = {"Authorization": f"Bearer {create_access_token({'sub': 'staff2@demo.com', 'role': 'staff'})}"}
    u_staff = User(email="staff2@demo.com", hashed_password="pw", full_name="Desk Two", role=UserRole.STAFF)
    db_session.add(u_staff)
    db_session.commit()
    client.post("/api/queue/issue", json={"doctor_id": doc.id, "patient_id": pat1.id}, headers=staff_headers)
    client.post("/api/queue/issue", json={"doctor_id": doc.id, "patient_id": pat2.id}, headers=staff_headers)

    # Call-next unauthenticated -> 401
    res_unauth = client.post(f"/api/queue/call-next?doctor_id={doc.id}")
    assert res_unauth.status_code == 401

    # Call-next unauthorized role (patient) -> 403
    res_forbidden = client.post(
        f"/api/queue/call-next?doctor_id={doc.id}",
        headers={"Authorization": f"Bearer {patient_token}"},
    )
    assert res_forbidden.status_code == 403

    # Call-next with doctor role -> 200
    res_call1 = client.post(
        f"/api/queue/call-next?doctor_id={doc.id}",
        headers={"Authorization": f"Bearer {doctor_token}"},
    )
    assert res_call1.status_code == 200
    assert res_call1.json() == {"status": "success", "called_ticket": "Q-101"}

    # Verify live-status updated
    live_res1 = client.get("/api/queue/live-status")
    live_data1 = live_res1.json()
    assert live_data1["currently_serving"] == "Q-101"
    assert live_data1["currently_serving_room"] == "Room 105"
    assert live_data1["waiting_count"] == 1
    assert live_data1["waiting_tickets"] == ["Q-102"]
    assert live_data1["estimated_wait_minutes"] == 10

    # Call next patient (Q-102)
    res_call2 = client.post(
        f"/api/queue/call-next?doctor_id={doc.id}",
        headers={"Authorization": f"Bearer {doctor_token}"},
    )
    assert res_call2.status_code == 200
    assert res_call2.json() == {"status": "success", "called_ticket": "Q-102"}

    # No more waiting patients -> 404
    res_call3 = client.post(
        f"/api/queue/call-next?doctor_id={doc.id}",
        headers={"Authorization": f"Bearer {doctor_token}"},
    )
    assert res_call3.status_code == 404
    assert res_call3.json()["detail"] == "No waiting patients in queue"


def test_queue_websocket_endpoint(client):
    # Test WebSocket connection lifecycle
    with client.websocket_connect("/api/queue/ws") as websocket:
        websocket.send_text("ping")
        # Connection was accepted and registered in queue_manager
        assert len(queue_manager.active_connections) >= 1

    # After exiting context manager, disconnect should have cleaned it up
    assert websocket not in queue_manager.active_connections


# --- Remediation verification tests ---

def _make_doctor_and_patients(db, n_patients=2, tag="rem"):
    u_doc = User(email=f"doc-{tag}@t.com", hashed_password="pw", full_name="Doc Rem", role=UserRole.DOCTOR)
    db.add(u_doc)
    db.commit()
    doc = Doctor(user_id=u_doc.id, specialization="Gen", license_number="L", room_number="R1")
    db.add(doc)
    db.commit()
    pats = []
    for i in range(n_patients):
        u = User(email=f"pat-{tag}-{i}@t.com", hashed_password="pw", full_name=f"Pat {i}", role=UserRole.PATIENT)
        db.add(u)
        db.commit()
        p = Patient(user_id=u.id)
        db.add(p)
        db.commit()
        pats.append(p)
    return doc, pats


def _staff_headers(db):
    u = User(email=f"staff-rem-{db.query(User).count()}@t.com", hashed_password="pw", full_name="Desk", role=UserRole.STAFF)
    db.add(u)
    db.commit()
    return {"Authorization": f"Bearer {create_access_token({'sub': u.email, 'role': 'staff'})}"}


def test_call_next_urgent_jumps_queue(client, db_session):
    doc, (pat1, pat2) = _make_doctor_and_patients(db_session)
    headers = _staff_headers(db_session)
    r1 = client.post("/api/queue/issue", json={"doctor_id": doc.id, "patient_id": pat1.id, "priority": "normal"}, headers=headers)
    r2 = client.post("/api/queue/issue", json={"doctor_id": doc.id, "patient_id": pat2.id, "priority": "urgent"}, headers=headers)
    normal_ticket = r1.json()["ticket_number"]
    urgent_ticket = r2.json()["ticket_number"]

    res = client.post(f"/api/queue/call-next?doctor_id={doc.id}", headers=headers)
    assert res.status_code == 200
    # The urgent ticket (issued second) must be called before the normal one
    assert res.json()["called_ticket"] == urgent_ticket
    assert normal_ticket != urgent_ticket


def test_advance_ticket_lifecycle(client, db_session):
    doc, (pat1, _) = _make_doctor_and_patients(db_session, n_patients=2)
    headers = _staff_headers(db_session)
    issued = client.post("/api/queue/issue", json={"doctor_id": doc.id, "patient_id": pat1.id}, headers=headers).json()
    ticket_id = issued["id"]

    # Waiting -> in_consultation is invalid (must be CALLED first)
    res_bad = client.post("/api/queue/advance", headers=headers, json={"ticket_id": ticket_id, "to": "in_consultation"})
    assert res_bad.status_code == 409

    client.post(f"/api/queue/call-next?doctor_id={doc.id}", headers=headers)
    res1 = client.post("/api/queue/advance", headers=headers, json={"ticket_id": ticket_id, "to": "in_consultation"})
    assert res1.status_code == 200
    assert db_session.query(QueueTicket).filter(QueueTicket.id == ticket_id).first().status == QueueStatus.IN_CONSULTATION

    res2 = client.post("/api/queue/advance", headers=headers, json={"ticket_id": ticket_id, "to": "completed"})
    assert res2.status_code == 200
    done = db_session.query(QueueTicket).filter(QueueTicket.id == ticket_id).first()
    assert done.status == QueueStatus.COMPLETED
    assert done.completed_at is not None

    # With the ticket completed and nothing else waiting, the board goes idle
    live = client.get("/api/queue/live-status").json()
    assert live["currently_serving"] == "None"

    # Patients can re-queue after completion
    res3 = client.post("/api/queue/issue", json={"doctor_id": doc.id, "patient_id": pat1.id}, headers=headers)
    assert res3.status_code == 200


def test_patient_cannot_reissue_while_called(client, db_session):
    doc, (pat1, _) = _make_doctor_and_patients(db_session, n_patients=2, tag="reissue")
    headers = _staff_headers(db_session)
    client.post("/api/queue/issue", json={"doctor_id": doc.id, "patient_id": pat1.id}, headers=headers)
    client.post(f"/api/queue/call-next?doctor_id={doc.id}", headers=headers)

    res = client.post("/api/queue/issue", json={"doctor_id": doc.id, "patient_id": pat1.id}, headers=headers)
    assert res.status_code == 409


def test_ticket_allocation_survives_restore_gap(client, db_session):
    """After a restore that leaves a gap (e.g. only Q-102 exists), allocation
    must use MAX+1, not count+101 which would deadlock on the collision."""
    doc, (pat1, pat2) = _make_doctor_and_patients(db_session, n_patients=2, tag="restore")
    db_session.add(QueueTicket(ticket_number="Q-102", patient_id=pat1.id, doctor_id=doc.id, status=QueueStatus.CALLED))
    db_session.commit()

    headers = _staff_headers(db_session)
    res = client.post("/api/queue/issue", json={"doctor_id": doc.id, "patient_id": pat2.id}, headers=headers)
    assert res.status_code == 200
    assert res.json()["ticket_number"] == "Q-103"
