# app/routers/feedback.py
import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import List, Optional
from app.database import get_db
from app.models import PatientFeedback, Patient, User, UserRole
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

    sentiment = analyze_sentiment(data.comment_text, data.rating)

    fb = PatientFeedback(
        patient_id=patient.id,
        doctor_id=data.doctor_id,
        rating=data.rating,
        tags_json=json.dumps(data.tags),
        comment_text=data.comment_text,
        sentiment_label=sentiment["sentiment_label"],
        sentiment_score=sentiment["sentiment_score"],
        flagged_critical=sentiment["flagged_critical"],
    )
    db.add(fb)
    db.commit()
    db.refresh(fb)
    return {"status": "success", "id": fb.id, "sentiment": sentiment}


@router.get("/analytics")
def get_feedback_analytics(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles([UserRole.STAFF, UserRole.ADMIN, UserRole.DOCTOR])),
):
    from sqlalchemy import func

    total = db.query(func.count(PatientFeedback.id)).scalar() or 0
    if total == 0:
        return {
            "total": 0,
            "avg_rating": 5.0,
            "positive_pct": 100,
            "negative_pct": 0,
            "critical_count": 0,
            "items": [],
        }

    avg_rating = round(float(db.query(func.avg(PatientFeedback.rating)).scalar() or 0), 2)
    pos_count = (
        db.query(func.count(PatientFeedback.id))
        .filter(PatientFeedback.sentiment_label == "positive")
        .scalar() or 0
    )
    neg_count = (
        db.query(func.count(PatientFeedback.id))
        .filter(PatientFeedback.sentiment_label == "negative")
        .scalar() or 0
    )
    critical_count = (
        db.query(func.count(PatientFeedback.id))
        .filter(PatientFeedback.flagged_critical == True)  # noqa: E712
        .scalar() or 0
    )
    recent = (
        db.query(PatientFeedback)
        .order_by(PatientFeedback.id.desc())
        .limit(20)
        .all()
    )

    return {
        "total": total,
        "avg_rating": avg_rating,
        "positive_pct": round((pos_count / total) * 100, 1),
        "negative_pct": round((neg_count / total) * 100, 1),
        "critical_count": critical_count,
        "items": [
            {
                "id": f.id,
                "rating": f.rating,
                "comment": f.comment_text,
                "sentiment_label": f.sentiment_label,
                "sentiment_score": f.sentiment_score,
                "flagged_critical": f.flagged_critical,
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in recent
        ],
    }
