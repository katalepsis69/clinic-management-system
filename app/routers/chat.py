"""Real-time Patient-Staff Chat with Automated FAQ Bot router."""

import logging
from typing import Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Path, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.database import get_db
from app.models import ChatMessage, User, UserRole
from app.auth import decode_token, get_current_user, require_roles
from app.chat_bot import get_bot_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["Live Chat Box"])


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
    # Identity comes from the auth cookie, never from the client payload.
    user = _user_from_websocket(websocket, db)
    if user is None:
        await websocket.close(code=1008)
        return
    sender_name = user.full_name
    sender_role = user.role.value if hasattr(user.role, "value") else str(user.role)

    await chat_hub.connect(session_id, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            if isinstance(data, str):
                data = {"message": data}
            elif not isinstance(data, dict):
                data = {"message": str(data)}

            msg_text = str(data.get("message") or data.get("text") or "")[:2000]

            # 1. Persist user message
            user_msg = ChatMessage(
                session_id=session_id,
                sender_id=user.id,
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

                bot_payload = {
                    "sender": "Clinic Assistant Bot",
                    "sender_name": "Clinic Assistant Bot",
                    "message": bot_reply,
                    "message_text": bot_reply,
                    "role": "bot",
                    "sender_role": "bot",
                    "is_bot_reply": True,
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
    current_user: User = Depends(get_current_user),
):
    """REST fallback for sending a chat message with automated bot reply.

    Identity is taken from the authenticated user, never from the request body.
    """
    sender_name = current_user.full_name
    sender_role = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)

    # Persist user message
    user_msg = ChatMessage(
        session_id=data.session_id,
        sender_id=current_user.id,
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

        bot_payload = {
            "sender": "Clinic Assistant Bot",
            "sender_name": "Clinic Assistant Bot",
            "message": bot_reply,
            "message_text": bot_reply,
            "role": "bot",
            "sender_role": "bot",
            "is_bot_reply": True,
        }
        await chat_hub.send_to_room(data.session_id, bot_payload)

    return {
        "status": "success",
        "message_id": user_msg.id,
        "user_message": user_payload,
        "bot_reply": bot_payload,
    }
