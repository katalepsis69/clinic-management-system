# app/routers/feedback.py
import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import List, Optional
from app.database import get_db
from app.models import Doctor, PatientFeedback, Patient, User, UserRole
from app.auth import get_current_user, require_roles
from app.sentiment import analyze_sentiment

router = APIRouter(prefix="/api/feedback", tags=["Feedback & Sentiment"])


class FeedbackCreate(BaseModel):
    rating: int = Field(..., ge=1, le=5, description="Star rating from 1 to 5")
    tags: List[str] = []
    comment_text: str
    doctor_id: Optional[int] = None


@router.post("")
def submit_feedback(data: FeedbackCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.user_id == user.id).first()
    if not patient:
        raise HTTPException(status_code=400, detail="Only patients can submit feedback")

    comment = (data.comment_text or "").strip()
    if not comment:
        raise HTTPException(status_code=400, detail="Feedback comment is required")
    if data.doctor_id is not None:
        if not db.query(Doctor.id).filter(Doctor.id == data.doctor_id).first():
            raise HTTPException(status_code=404, detail="Doctor not found")

    sentiment = analyze_sentiment(comment, data.rating)

    fb = PatientFeedback(
        patient_id=patient.id,
        doctor_id=data.doctor_id,
        rating=data.rating,
        tags_json=json.dumps(data.tags),
        comment_text=comment,
        sentiment_label=sentiment["sentiment_label"],
        sentiment_score=sentiment["sentiment_score"],
        flagged_critical=sentiment["flagged_critical"],
    )
    db.add(fb)
    db.commit()
    db.refresh(fb)
    return {"status": "success", "id": fb.id, "sentiment": sentiment}


def _serialize_feedback_item(f: PatientFeedback, doctor_names: dict[int, str]) -> dict:
    try:
        tags = json.loads(f.tags_json or "[]")
        if not isinstance(tags, list):
            tags = []
    except (ValueError, TypeError):
        tags = []

    return {
        "id": f.id,
        "doctor_id": f.doctor_id,
        "doctor_name": doctor_names.get(f.doctor_id) if f.doctor_id else None,
        "rating": f.rating,
        "tags": tags,
        "comment": f.comment_text,
        "sentiment_label": f.sentiment_label,
        "sentiment_score": f.sentiment_score,
        "flagged_critical": f.flagged_critical,
        "created_at": f.created_at.isoformat() if f.created_at else None,
    }


@router.get("/analytics")
def get_feedback_analytics(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles([UserRole.STAFF, UserRole.ADMIN])),
):
    from sqlalchemy import func, case

    stats = db.query(
        func.count(PatientFeedback.id),
        func.avg(PatientFeedback.rating),
        func.sum(case((PatientFeedback.sentiment_label == "positive", 1), else_=0)),
        func.sum(case((PatientFeedback.sentiment_label == "negative", 1), else_=0)),
        func.sum(case((PatientFeedback.flagged_critical == True, 1), else_=0)),  # noqa: E712
    ).first()

    total = stats[0] or 0
    if total == 0:
        # Nothing submitted yet: report no numbers instead of defaults that read as real data.
        return {
            "total": 0,
            "avg_rating": None,
            "positive_pct": 0,
            "negative_pct": 0,
            "critical_count": 0,
            "items": [],
        }

    avg_rating = round(float(stats[1] or 0), 2)
    pos_count = stats[2] or 0
    neg_count = stats[3] or 0
    critical_count = stats[4] or 0

    recent = (
        db.query(PatientFeedback)
        .order_by(PatientFeedback.id.desc())
        .limit(50)
        .all()
    )
    critical_rows = (
        db.query(PatientFeedback)
        .filter(PatientFeedback.flagged_critical == True)  # noqa: E712
        .order_by(PatientFeedback.id.desc())
        .limit(50)
        .all()
    )
    doc_ids = {f.doctor_id for f in (*recent, *critical_rows) if f.doctor_id}
    doctor_names = (
        {d.id: (d.user.full_name if d.user else f"Doctor #{d.id}") for d in db.query(Doctor).filter(Doctor.id.in_(doc_ids)).all()}
        if doc_ids
        else {}
    )

    return {
        "total": total,
        "avg_rating": avg_rating,
        "positive_pct": round((pos_count / total) * 100, 1),
        "negative_pct": round((neg_count / total) * 100, 1),
        "critical_count": critical_count,
        "critical_alerts": [_serialize_feedback_item(f, doctor_names) for f in critical_rows],
        "items": [_serialize_feedback_item(f, doctor_names) for f in recent],
    }
