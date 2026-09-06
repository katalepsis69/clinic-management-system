import json
import uuid
import pytest
from unittest.mock import AsyncMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.models import Base, ChatMessage, User, UserRole
from app.auth import create_access_token
from app.chat_bot import get_bot_response, FAQ_RULES
from app.routers.chat import router as chat_router, chat_hub, ChatConnectionHub


def _auth_cookie(user):
    """Cookie header for WS handshake / explicit headers, mirroring the login cookie."""
    token = create_access_token({"sub": user.email, "role": user.role.value})
    return {"Authorization": f"Bearer {token}"}


def _ws_cookie_headers(user):
    token = create_access_token({"sub": user.email, "role": user.role.value})
    return {"cookie": f"access_token=Bearer {token}"}


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
    app.include_router(chat_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_hub():
    chat_hub.rooms.clear()
    yield
    chat_hub.rooms.clear()


# ==========================================
# 1. Bot FAQ Response Tests (Step 1 from brief)
# ==========================================

def test_bot_faq_response():
    assert "8:00 AM" in get_bot_response("what are your clinic hours?")
    assert "appointment" in get_bot_response("how do I book an appointment?").lower()
    assert "911" in get_bot_response("is this an emergency?")


def test_bot_faq_all_rules_and_keywords():
    # Hours
    assert "8:00 AM" in get_bot_response("what time are you open?")
    assert "8:00 AM" in get_bot_response("clinic schedule please")
    assert "8:00 AM" in get_bot_response("OPENING HOURS")

    # Booking
    assert "Book Appointment" in get_bot_response("can I reserve a slot?")
    assert "Book Appointment" in get_bot_response("I want to book a visit")

    # Location
    assert "123 Healthcare Blvd" in get_bot_response("where is the clinic?")
    assert "123 Healthcare Blvd" in get_bot_response("what is your address and directions?")

    # Emergency
    assert "911" in get_bot_response("This is severe and urgent, need ambulance!")

    # Specialists / Doctors
    assert "Cardiology" in get_bot_response("Do you have a pediatrician or cardiologist?")
    assert "Cardiology" in get_bot_response("Which physician or doctor is available?")


def test_bot_fallback_and_edge_cases():
    fallback_substr = "A clinic receptionist has received your inquiry"
    assert fallback_substr in get_bot_response("Tell me a funny joke")
    assert fallback_substr in get_bot_response("Can I buy groceries?")
    assert fallback_substr in get_bot_response("")
    assert fallback_substr in get_bot_response("   ")


# ==========================================
# 2. ChatConnectionHub Unit Tests
# ==========================================

@pytest.mark.asyncio
async def test_chat_connection_hub_unit():
    hub = ChatConnectionHub()
    mock_ws1 = AsyncMock()
    mock_ws2 = AsyncMock()

    # Connect ws1 to room "room-1"
    await hub.connect("room-1", mock_ws1)
    assert "room-1" in hub.rooms
    assert mock_ws1 in hub.rooms["room-1"]
    mock_ws1.accept.assert_awaited_once()

    # Connect ws2 to room "room-1"
    await hub.connect("room-1", mock_ws2)
    assert len(hub.rooms["room-1"]) == 2

    # Send payload to room
    payload = {"sender": "Test", "message": "Hello"}
    await hub.send_to_room("room-1", payload)
    mock_ws1.send_json.assert_awaited_once_with(payload)
    mock_ws2.send_json.assert_awaited_once_with(payload)

    # Disconnect ws1
    hub.disconnect("room-1", mock_ws1)
    assert mock_ws1 not in hub.rooms["room-1"]
    assert len(hub.rooms["room-1"]) == 1

    # Disconnect ws2 -> room cleaned up
    hub.disconnect("room-1", mock_ws2)
    assert "room-1" not in hub.rooms


@pytest.mark.asyncio
async def test_chat_hub_send_error_handling():
    hub = ChatConnectionHub()
    bad_ws = AsyncMock()
    bad_ws.send_json.side_effect = RuntimeError("WebSocket connection dropped")

    await hub.connect("test-room", bad_ws)
    # Sending to room should not raise exception even if websocket fails
    await hub.send_to_room("test-room", {"msg": "test"})


# ==========================================
# 3. WebSocket Integration Tests
# ==========================================

def test_websocket_patient_message_and_bot_reply(client, db_session):
    session_id = f"sess-{uuid.uuid4().hex[:8]}"

    u_pat = User(email="alice@chat.test", hashed_password="pw", full_name="Alice Smith", role=UserRole.PATIENT)
    db_session.add(u_pat)
    db_session.commit()

    # Unauthenticated WS connections are rejected
    with pytest.raises(Exception):
        with client.websocket_connect(f"/api/chat/ws/{session_id}"):
            pass

    with client.websocket_connect(
        f"/api/chat/ws/{session_id}", headers=_ws_cookie_headers(u_pat)
    ) as ws:
        # Patient sends a question about clinic hours (identity is server-derived)
        ws.send_json({"message": "What are your clinic hours?"})

        # 1st broadcast received: Alice's own message
        msg1 = ws.receive_json()
        assert msg1["sender"] == "Alice Smith"
        assert msg1["message"] == "What are your clinic hours?"
        assert msg1["role"] == "patient"

        # 2nd broadcast received: Automated bot reply
        msg2 = ws.receive_json()
        assert msg2["sender"] == "Clinic Assistant Bot"
        assert "8:00 AM" in msg2["message"]
        assert msg2["role"] == "bot"

    # Verify messages are persisted in chat_messages table
    db_msgs = (
        db_session.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id.asc())
        .all()
    )
    assert len(db_msgs) == 2
    assert db_msgs[0].sender_name == "Alice Smith"
    assert db_msgs[0].sender_role == "patient"
    assert db_msgs[0].message_text == "What are your clinic hours?"
    assert db_msgs[0].is_bot_reply is False

    assert db_msgs[1].sender_name == "Clinic Assistant Bot"
    assert db_msgs[1].sender_role == "bot"
    assert "8:00 AM" in db_msgs[1].message_text
    assert db_msgs[1].is_bot_reply is True


def test_websocket_multi_client_relay_and_staff_message(client, db_session):
    session_id = f"sess-{uuid.uuid4().hex[:8]}"

    u_bob = User(email="bob@chat.test", hashed_password="pw", full_name="Bob Patient", role=UserRole.PATIENT)
    u_sarah = User(email="sarah@chat.test", hashed_password="pw", full_name="Nurse Sarah", role=UserRole.STAFF)
    db_session.add_all([u_bob, u_sarah])
    db_session.commit()

    with client.websocket_connect(
        f"/api/chat/ws/{session_id}", headers=_ws_cookie_headers(u_bob)
    ) as ws_patient:
        with client.websocket_connect(
            f"/api/chat/ws/{session_id}", headers=_ws_cookie_headers(u_sarah)
        ) as ws_staff:
            # Patient sends inquiry (identity comes from the authenticated user)
            ws_patient.send_json({"message": "Where is the clinic located?"})

            # Patient receives broadcast & bot reply
            p_msg1 = ws_patient.receive_json()
            assert p_msg1["sender"] == "Bob Patient"
            p_msg2 = ws_patient.receive_json()
            assert "123 Healthcare Blvd" in p_msg2["message"]

            # Staff also receives both
            s_msg1 = ws_staff.receive_json()
            assert s_msg1["sender"] == "Bob Patient"
            s_msg2 = ws_staff.receive_json()
            assert "123 Healthcare Blvd" in s_msg2["message"]

            # Staff sends a reply to the patient (server stamps Nurse Sarah identity)
            ws_staff.send_json({
                "message": "Hello Bob! We also offer valet parking on Level B1.",
                "sender_name": "Imposter Name",
                "role": "doctor",
            })

            # Both patient and staff receive staff's message
            staff_echo = ws_staff.receive_json()
            assert staff_echo["sender"] == "Nurse Sarah"
            assert staff_echo["role"] == "staff"

            patient_received = ws_patient.receive_json()
            assert patient_received["sender"] == "Nurse Sarah"
            assert patient_received["message"] == "Hello Bob! We also offer valet parking on Level B1."

            # Ensure staff message did NOT trigger automated bot reply in DB
            db_msgs = (
                db_session.query(ChatMessage)
                .filter(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.id.asc())
                .all()
            )
            # Total should be: 1 patient msg + 1 bot msg + 1 staff msg = 3 msgs
            assert len(db_msgs) == 3
            assert db_msgs[2].sender_name == "Nurse Sarah"
            assert db_msgs[2].sender_role == "staff"


def test_websocket_disconnect_cleanup(client, db_session):
    session_id = f"sess-{uuid.uuid4().hex[:8]}"

    u_pat = User(email="cleanup@chat.test", hashed_password="pw", full_name="Cleanup Pat", role=UserRole.PATIENT)
    db_session.add(u_pat)
    db_session.commit()

    with client.websocket_connect(
        f"/api/chat/ws/{session_id}", headers=_ws_cookie_headers(u_pat)
    ) as ws:
        assert session_id in chat_hub.rooms
        assert len(chat_hub.rooms[session_id]) == 1

    # After exiting context manager, client is disconnected
    assert session_id not in chat_hub.rooms or len(chat_hub.rooms[session_id]) == 0


# ==========================================
# 4. REST History and Fallback Endpoints Tests
# ==========================================

def test_chat_history_endpoint(client, db_session):
    session_id = f"sess-{uuid.uuid4().hex[:8]}"

    u_viewer = User(email="viewer@chat.test", hashed_password="pw", full_name="History Viewer", role=UserRole.STAFF)
    db_session.add(u_viewer)
    db_session.commit()
    headers = _auth_cookie(u_viewer)

    # Anonymous history access is rejected
    res_anon = client.get(f"/api/chat/history/{session_id}")
    assert res_anon.status_code == 401

    # Initially empty history
    res_empty = client.get(f"/api/chat/history/{session_id}", headers=headers)
    assert res_empty.status_code == 200
    assert res_empty.json() == []

    # Insert messages into DB
    m1 = ChatMessage(
        session_id=session_id,
        sender_name="Patient Jane",
        sender_role="patient",
        message_text="Hello!",
        is_bot_reply=False,
    )
    m2 = ChatMessage(
        session_id=session_id,
        sender_name="Clinic Assistant Bot",
        sender_role="bot",
        message_text="How can I help you?",
        is_bot_reply=True,
    )
    db_session.add_all([m1, m2])
    db_session.commit()

    # Query history
    res = client.get(f"/api/chat/history/{session_id}", headers=headers)
    assert res.status_code == 200
    history = res.json()
    assert len(history) == 2
    assert history[0]["sender_name"] == "Patient Jane"
    assert history[0]["message"] == "Hello!"
    assert history[0]["is_bot_reply"] is False
    assert history[1]["sender_name"] == "Clinic Assistant Bot"
    assert history[1]["is_bot_reply"] is True


def test_chat_sessions_endpoint(client, db_session):
    s1 = f"sess-{uuid.uuid4().hex[:8]}"
    s2 = f"sess-{uuid.uuid4().hex[:8]}"

    u_staff = User(email="inbox@chat.test", hashed_password="pw", full_name="Inbox Staff", role=UserRole.STAFF)
    db_session.add(u_staff)
    db_session.commit()

    # Anonymous session enumeration is rejected
    res_anon = client.get("/api/chat/sessions")
    assert res_anon.status_code == 401

    m1 = ChatMessage(session_id=s1, sender_name="P1", sender_role="patient", message_text="Hi 1")
    m2 = ChatMessage(session_id=s2, sender_name="P2", sender_role="patient", message_text="Hi 2")
    db_session.add_all([m1, m2])
    db_session.commit()

    res = client.get("/api/chat/sessions", headers=_auth_cookie(u_staff))
    assert res.status_code == 200
    sessions = res.json()
    assert s1 in sessions
    assert s2 in sessions


def test_chat_rest_send_fallback(client, db_session):
    session_id = f"sess-{uuid.uuid4().hex[:8]}"

    u_charlie = User(email="charlie@chat.test", hashed_password="pw", full_name="Charlie", role=UserRole.PATIENT)
    db_session.add(u_charlie)
    db_session.commit()

    # Anonymous sends are rejected
    res_anon = client.post("/api/chat/send", json={
        "session_id": session_id,
        "message": "how do I book an appointment?",
    })
    assert res_anon.status_code == 401

    # Patient posts message via REST (claimed staff identity must be ignored)
    res = client.post("/api/chat/send", headers=_auth_cookie(u_charlie), json={
        "session_id": session_id,
        "sender_name": "Fake Staff Name",
        "role": "staff",
        "message": "how do I book an appointment?",
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["user_message"]["sender"] == "Charlie"
    assert data["user_message"]["role"] == "patient"
    assert "Book Appointment" in data["bot_reply"]["message"]

    # History contains both
    res_hist = client.get(f"/api/chat/history/{session_id}", headers=_auth_cookie(u_charlie))
    assert res_hist.status_code == 200
    assert len(res_hist.json()) == 2
