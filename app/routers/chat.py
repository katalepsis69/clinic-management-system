"""Real-time Patient-Staff Chat with Automated FAQ Bot router."""

import logging
from typing import Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Path, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.database import get_db
from app.models import ChatMessage, User, UserRole
from app.auth import decode_token, get_current_user, get_optional_current_user, require_roles
from app.chat_bot import get_bot_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["Live Chat Box"])

GUEST_CHAT_LIMIT = 5


def _user_from_websocket(websocket: WebSocket, db: Session) -> Optional[User]:
    """Resolve the authenticated user from the access_token cookie set at WS handshake."""
    raw = websocket.cookies.get("access_token")
    if not raw:
        return None
    if raw.startswith("Bearer "):
        raw = raw[7:].strip()
    try:
        payload = decode_token(raw)
    except HTTPException:
        return None
    email = payload.get("sub")
    if not email:
        return None
    return db.query(User).filter(User.email == email).first()


class ChatConnectionHub:
    """Manages multi-client WebSocket connections organized by session_id rooms."""

    def __init__(self):
        self.rooms: Dict[str, List[WebSocket]] = {}

    async def connect(self, session_id: str, ws: WebSocket):
        await ws.accept()
        if session_id not in self.rooms:
            self.rooms[session_id] = []
        self.rooms[session_id].append(ws)

    def disconnect(self, session_id: str, ws: WebSocket):
        if session_id in self.rooms:
            if ws in self.rooms[session_id]:
                self.rooms[session_id].remove(ws)
            if not self.rooms[session_id]:
                del self.rooms[session_id]

    async def send_to_room(self, session_id: str, payload: dict):
        if session_id in self.rooms:
            for ws in list(self.rooms[session_id]):
                try:
                    await ws.send_json(payload)
                except Exception:
                    self.disconnect(session_id, ws)


chat_hub = ChatConnectionHub()


class SendMessageRequest(BaseModel):
    session_id: str = Field(min_length=8, max_length=128)
    message: str = Field(min_length=1, max_length=2000)


@router.websocket("/ws/{session_id}")
async def chat_websocket(
    websocket: WebSocket,
    session_id: str = Path(min_length=8, max_length=128),
    db: Session = Depends(get_db),  # ponytail: session pinned per socket; per-message SessionLocal if chat volume grows
):
    # Identity comes from the auth cookie if authenticated, otherwise Guest.
    user = _user_from_websocket(websocket, db)
    is_guest = (user is None)
    sender_name = user.full_name if user else "Guest"
    sender_role = (user.role.value if hasattr(user.role, "value") else str(user.role)) if user else "patient"
    sender_id = user.id if user else None

    await chat_hub.connect(session_id, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            if isinstance(data, str):
                data = {"message": data}
            elif not isinstance(data, dict):
                data = {"message": str(data)}

            msg_text = str(data.get("message") or data.get("text") or "")[:2000]
            if not msg_text.strip():
                continue

            if is_guest:
                guest_count = (
                    db.query(ChatMessage)
                    .filter(ChatMessage.session_id == session_id, ChatMessage.is_bot_reply == False)
                    .count()
                )
                if guest_count >= GUEST_CHAT_LIMIT:
                    limit_payload = {
                        "sender": "Clinic Assistant Bot",
                        "sender_name": "Clinic Assistant Bot",
                        "message": f"You have reached the guest limit of {GUEST_CHAT_LIMIT} messages. Please sign in or create an account to continue chatting!",
                        "role": "bot",
                        "sender_role": "bot",
                        "is_bot_reply": True,
                        "limit_reached": True,
                        "guest_remaining": 0,
                    }
                    await websocket.send_json(limit_payload)
                    continue
            else:
                guest_count = 0

            # 1. Persist user message
            user_msg = ChatMessage(
                session_id=session_id,
                sender_id=sender_id,
                sender_name=sender_name,
                sender_role=sender_role,
                message_text=msg_text,
                is_bot_reply=False,
            )
            db.add(user_msg)
            db.commit()

            # 2. Broadcast user message to room
            user_payload = {
                "sender": sender_name,
                "sender_name": sender_name,
                "message": msg_text,
                "message_text": msg_text,
                "role": sender_role,
                "sender_role": sender_role,
                "is_bot_reply": False,
            }
            await chat_hub.send_to_room(session_id, user_payload)

            # 3. If patient inquiry, trigger automated FAQ bot reply
            if sender_role.lower() not in ("staff", "doctor", "admin", "bot"):
                bot_reply = get_bot_response(msg_text)
                bot_msg = ChatMessage(
                    session_id=session_id,
                    sender_name="Clinic Assistant Bot",
                    sender_role="bot",
                    message_text=bot_reply,
                    is_bot_reply=True,
                )
                db.add(bot_msg)
                db.commit()

                guest_count_after = (guest_count + 1) if is_guest else 0
                guest_remaining = max(0, GUEST_CHAT_LIMIT - guest_count_after) if is_guest else None

                bot_payload = {
                    "sender": "Clinic Assistant Bot",
                    "sender_name": "Clinic Assistant Bot",
                    "message": bot_reply,
                    "message_text": bot_reply,
                    "role": "bot",
                    "sender_role": "bot",
                    "is_bot_reply": True,
                    "guest_remaining": guest_remaining,
                    "limit_reached": (guest_remaining == 0) if is_guest else False,
                }
                await chat_hub.send_to_room(session_id, bot_payload)

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Chat websocket failed for session %s", session_id)
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        chat_hub.disconnect(session_id, websocket)


@router.get("/history/{session_id}")
def get_chat_history(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve chat history for a given session (any authenticated user)."""
    # ponytail: sessions are not yet bound to a user in the schema; add a session-owner
    # column and filter on it if chat history becomes sensitive beyond staff/patient use.
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id.asc())
        .all()
    )
    return [
        {
            "id": m.id,
            "session_id": m.session_id,
            "sender": m.sender_name,
            "sender_name": m.sender_name,
            "role": m.sender_role,
            "sender_role": m.sender_role,
            "message": m.message_text,
            "message_text": m.message_text,
            "is_bot_reply": m.is_bot_reply,
            "created_at": m.created_at.strftime("%Y-%m-%d %H:%M:%S") if m.created_at else None,
        }
        for m in messages
    ]


@router.get("/sessions")
def list_chat_sessions(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRole.STAFF, UserRole.ADMIN])),
):
    """Retrieve all unique active chat session IDs (staff inbox only)."""
    sessions = db.query(ChatMessage.session_id).distinct().all()
    return [s[0] for s in sessions]


@router.post("/send")
async def send_rest_message(
    data: SendMessageRequest,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user),
):
    """REST fallback for sending a chat message with automated bot reply.

    Identity is taken from authenticated user if available, otherwise Guest.
    Guests are limited to GUEST_CHAT_LIMIT (5) messages per session.
    """
    is_guest = (current_user is None)
    if is_guest:
        guest_count = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == data.session_id, ChatMessage.is_bot_reply == False)
            .count()
        )
        if guest_count >= GUEST_CHAT_LIMIT:
            raise HTTPException(
                status_code=429,
                detail=f"Guest chat limit reached ({GUEST_CHAT_LIMIT}/{GUEST_CHAT_LIMIT} messages). Please sign in or create an account to continue chatting.",
            )
        sender_name = "Guest"
        sender_role = "patient"
        sender_id = None
    else:
        guest_count = 0
        sender_name = current_user.full_name
        sender_role = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
        sender_id = current_user.id

    # Persist user message
    user_msg = ChatMessage(
        session_id=data.session_id,
        sender_id=sender_id,
        sender_name=sender_name,
        sender_role=sender_role,
        message_text=data.message,
        is_bot_reply=False,
    )
    db.add(user_msg)
    db.commit()
    db.refresh(user_msg)

    user_payload = {
        "sender": sender_name,
        "sender_name": sender_name,
        "message": data.message,
        "message_text": data.message,
        "role": sender_role,
        "sender_role": sender_role,
        "is_bot_reply": False,
    }
    await chat_hub.send_to_room(data.session_id, user_payload)

    bot_payload = None
    if sender_role.lower() not in ("staff", "doctor", "admin", "bot"):
        bot_reply = get_bot_response(data.message)
        bot_msg = ChatMessage(
            session_id=data.session_id,
            sender_name="Clinic Assistant Bot",
            sender_role="bot",
            message_text=bot_reply,
            is_bot_reply=True,
        )
        db.add(bot_msg)
        db.commit()
        db.refresh(bot_msg)

        guest_count_after = (guest_count + 1) if is_guest else 0
        guest_remaining = max(0, GUEST_CHAT_LIMIT - guest_count_after) if is_guest else None

        bot_payload = {
            "sender": "Clinic Assistant Bot",
            "sender_name": "Clinic Assistant Bot",
            "message": bot_reply,
            "message_text": bot_reply,
            "role": "bot",
            "sender_role": "bot",
            "is_bot_reply": True,
            "guest_remaining": guest_remaining,
            "limit_reached": (guest_remaining == 0) if is_guest else False,
        }
        await chat_hub.send_to_room(data.session_id, bot_payload)

    return {
        "status": "success",
        "message_id": user_msg.id,
        "user_message": user_payload,
        "bot_reply": bot_payload,
        "guest_remaining": (max(0, GUEST_CHAT_LIMIT - (guest_count + 1))) if is_guest else None,
        "limit_reached": ((guest_count + 1) >= GUEST_CHAT_LIMIT) if is_guest else False,
    }


@router.get("/status/{session_id}")
def get_chat_status(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user),
):
    """Check whether current session is guest and how many messages remain."""
    if current_user:
        return {
            "is_guest": False,
            "limit": None,
            "remaining": None,
            "limit_reached": False,
        }
    guest_count = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id, ChatMessage.is_bot_reply == False)
        .count()
    )
    remaining = max(0, GUEST_CHAT_LIMIT - guest_count)
    return {
        "is_guest": True,
        "limit": GUEST_CHAT_LIMIT,
        "used": guest_count,
        "remaining": remaining,
        "limit_reached": remaining <= 0,
    }
