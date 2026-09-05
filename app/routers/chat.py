"""Real-time Patient-Staff Chat with Automated FAQ Bot router."""

import json
from typing import Dict, List, Optional
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models import ChatMessage
from app.chat_bot import get_bot_response

router = APIRouter(prefix="/api/chat", tags=["Live Chat Box"])


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
    session_id: str
    sender_name: Optional[str] = "Patient"
    role: Optional[str] = "patient"
    message: str


@router.websocket("/ws/{session_id}")
async def chat_websocket(
    websocket: WebSocket,
    session_id: str,
    db: Session = Depends(get_db),
):
    await chat_hub.connect(session_id, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            if isinstance(data, str):
                data = {"message": data}
            elif not isinstance(data, dict):
                data = {"message": str(data)}

            sender_name = data.get("sender_name") or data.get("sender") or "Patient"
            msg_text = data.get("message") or data.get("text") or ""
            sender_role = data.get("sender_role") or data.get("role") or "patient"

            # 1. Persist user message
            user_msg = ChatMessage(
                session_id=session_id,
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
        pass
    finally:
        chat_hub.disconnect(session_id, websocket)


@router.get("/history/{session_id}")
def get_chat_history(session_id: str, db: Session = Depends(get_db)):
    """Retrieve chat history for a given session."""
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
def list_chat_sessions(db: Session = Depends(get_db)):
    """Retrieve all unique active chat session IDs."""
    sessions = db.query(ChatMessage.session_id).distinct().all()
    return [s[0] for s in sessions]


@router.post("/send")
async def send_rest_message(data: SendMessageRequest, db: Session = Depends(get_db)):
    """REST fallback for sending a chat message with automated bot reply."""
    sender_name = data.sender_name or "Patient"
    sender_role = data.role or "patient"

    # Persist user message
    user_msg = ChatMessage(
        session_id=data.session_id,
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
