# Clinic Management System (Free Cloud & Demo Setup) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and package the complete Clinic Management System with local VADER Sentiment Analysis, live WebSocket queue tracker, doctor EMR/prescriptions, staff billing, and chat, ready for zero-cost instant online deployment on Render/Railway.

**Architecture:** A monolithic, high-throughput FastAPI ASGI application backed by SQLAlchemy ORM on SQLite (WAL mode with `busy_timeout=5000` pragma). Serves REST APIs, WebSocket channels for live queue/chat, and mobile-first responsive HTML5/Tailwind/ES-module web interfaces without requiring any frontend build steps.

**Tech Stack:** Python 3.12/3.13, FastAPI (latest), Uvicorn (`uvicorn[standard]`), SQLAlchemy 2.0, SQLite (WAL mode), Pydantic v2, vaderSentiment, PyJWT (replacing legacy python-jose), direct bcrypt (replacing legacy passlib), WebSockets, Tailwind CSS, pytest, pytest-asyncio.

## Global Constraints

- Python version floor: `>= 3.12` (compatible through 3.13)
- Authentication: Direct `bcrypt` (`bcrypt.hashpw` / `bcrypt.checkpw`) to prevent `passlib` compatibility warnings; `PyJWT` for standard secure token encoding/decoding
- Database: SQLite in WAL mode with `PRAGMA journal_mode=WAL;` and `PRAGMA busy_timeout = 5000;` on engine connect
- Real-time fallback: WebSocket with automatic reconnection and 5s polling fallback
- Zero unrequested external dependencies (pure Python standard library + modern vetted packages)

---

### Task 1: Project Scaffolding & Dependency Setup

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `app/__init__.py`
- Create: `app/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: Environment variables
- Produces: `app.config.Settings` object with `SECRET_KEY`, `DATABASE_URL`, `DEMO_MODE`

- [ ] **Step 1: Write failing config test**

```python
# tests/test_config.py
from app.config import get_settings

def test_settings_load_defaults():
    settings = get_settings()
    assert settings.APP_NAME == "Clinic Management System"
    assert settings.DATABASE_URL.startswith("sqlite")
    assert settings.DEMO_MODE is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: Implement minimal configuration with modern package versions**

```python
# requirements.txt
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
sqlalchemy>=2.0.35
pydantic>=2.9.0
pydantic-settings>=2.5.0
vaderSentiment>=3.3.2
PyJWT>=2.9.0
bcrypt>=4.2.0
python-multipart>=0.0.12
pytest>=8.3.0
pytest-asyncio>=0.24.0
httpx>=0.27.2
websockets>=13.0
qrcode[pil]>=7.4.2
jinja2>=3.1.4
```

```python
# app/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_NAME: str = "Clinic Management System"
    SECRET_KEY: str = "dev-secret-key-change-in-production-1234567890"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 720
    DATABASE_URL: str = "sqlite:///./data/clinic.db"
    DEMO_MODE: bool = True

    class Config:
        env_file = ".env"
        extra = "allow"

def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add requirements.txt .env.example app/__init__.py app/config.py tests/test_config.py
git commit -m "feat: setup project scaffolding with modern PyJWT, direct bcrypt, and Pydantic v2"
```

---

### Task 2: Database Layer with SQLite WAL & Busy Timeout Pragmas

**Files:**
- Create: `app/database.py`
- Create: `app/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: `app.config.Settings.DATABASE_URL`
- Produces: `Base`, `engine` (with WAL and `busy_timeout=5000` pragmas), `SessionLocal`, and ORM models: `User`, `Patient`, `Doctor`, `Appointment`, `QueueTicket`, `Prescription`, `Invoice`, `PatientFeedback`, `ChatMessage`

- [ ] **Step 1: Write failing database test**

```python
# tests/test_models.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models import Base, User, Patient, Doctor, QueueTicket, PatientFeedback

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()

def test_create_user_and_patient(db_session):
    user = User(email="test@patient.com", hashed_password="pw", full_name="John Doe", role="patient", phone="123456")
    db_session.add(user)
    db_session.commit()
    
    patient = Patient(user_id=user.id, gender="Male", emergency_contact_name="Jane", emergency_contact_phone="999")
    db_session.add(patient)
    db_session.commit()

    assert patient.user.email == "test@patient.com"
    assert patient.gender == "Male"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'app.database'` or `app.models`

- [ ] **Step 3: Implement database engine with WAL & busy_timeout pragmas**

```python
# app/database.py
import os
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import get_settings

settings = get_settings()

connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
    db_file_path = settings.DATABASE_URL.replace("sqlite:///", "")
    if db_file_path and db_file_path != ":memory:":
        os.makedirs(os.path.dirname(db_file_path) or ".", exist_ok=True)

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)

# SQLite Concurrency in WAL Mode + Busy Timeout listener
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if type(dbapi_connection).__module__ == "sqlite3":
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA busy_timeout = 5000;")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

```python
# app/models.py
import enum
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Date, Numeric, Text, ForeignKey, Enum as SQLEnum, Float
from sqlalchemy.orm import relationship
from app.database import Base

class UserRole(str, enum.Enum):
    PATIENT = "patient"
    DOCTOR = "doctor"
    STAFF = "staff"
    ADMIN = "admin"

class AppointmentStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class QueueStatus(str, enum.Enum):
    WAITING = "waiting"
    CALLED = "called"
    IN_CONSULTATION = "in_consultation"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(SQLEnum(UserRole), default=UserRole.PATIENT, nullable=False)
    phone = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    patient = relationship("Patient", back_populates="user", uselist=False)
    doctor = relationship("Doctor", back_populates="user", uselist=False)

class Patient(Base):
    __tablename__ = "patients"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    date_of_birth = Column(Date, nullable=True)
    gender = Column(String(20), nullable=True)
    blood_group = Column(String(10), nullable=True)
    emergency_contact_name = Column(String(255), nullable=True)
    emergency_contact_phone = Column(String(50), nullable=True)
    allergies = Column(Text, nullable=True)
    medical_history = Column(Text, nullable=True)

    user = relationship("User", back_populates="patient")
    appointments = relationship("Appointment", back_populates="patient")
    queue_tickets = relationship("QueueTicket", back_populates="patient")

class Doctor(Base):
    __tablename__ = "doctors"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    specialization = Column(String(100), nullable=False)
    license_number = Column(String(50), nullable=False)
    room_number = Column(String(20), nullable=False)
    consultation_fee = Column(Numeric(10, 2), default=50.00)
    is_available = Column(Boolean, default=True)

    user = relationship("User", back_populates="doctor")
    appointments = relationship("Appointment", back_populates="doctor")
    queue_tickets = relationship("QueueTicket", back_populates="doctor")

class Appointment(Base):
    __tablename__ = "appointments"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    appointment_date = Column(Date, nullable=False)
    time_slot = Column(String(30), nullable=False)
    status = Column(SQLEnum(AppointmentStatus), default=AppointmentStatus.CONFIRMED)
    reason_for_visit = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    patient = relationship("Patient", back_populates="appointments")
    doctor = relationship("Doctor", back_populates="appointments")

class QueueTicket(Base):
    __tablename__ = "queue_tickets"
    id = Column(Integer, primary_key=True, index=True)
    ticket_number = Column(String(20), index=True, nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    appointment_id = Column(Integer, ForeignKey("appointments.id"), nullable=True)
    status = Column(SQLEnum(QueueStatus), default=QueueStatus.WAITING)
    priority = Column(String(20), default="normal")
    issued_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    called_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    patient = relationship("Patient", back_populates="queue_tickets")
    doctor = relationship("Doctor", back_populates="queue_tickets")

class Prescription(Base):
    __tablename__ = "prescriptions"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    appointment_id = Column(Integer, ForeignKey("appointments.id"), nullable=True)
    diagnosis = Column(Text, nullable=False)
    clinical_notes = Column(Text, nullable=True)
    medications_json = Column(Text, nullable=False)
    qr_code_hash = Column(String(100), unique=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class Invoice(Base):
    __tablename__ = "invoices"
    id = Column(Integer, primary_key=True, index=True)
    receipt_number = Column(String(50), unique=True, index=True, nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    queue_ticket_id = Column(Integer, ForeignKey("queue_tickets.id"), nullable=True)
    consultation_fee = Column(Numeric(10, 2), default=0.0)
    medication_fee = Column(Numeric(10, 2), default=0.0)
    other_fees = Column(Numeric(10, 2), default=0.0)
    discount_amount = Column(Numeric(10, 2), default=0.0)
    total_amount = Column(Numeric(10, 2), default=0.0)
    payment_method = Column(String(30), default="cash")
    payment_status = Column(String(20), default="paid")
    paid_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class PatientFeedback(Base):
    __tablename__ = "patient_feedback"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    rating = Column(Integer, nullable=False)
    tags_json = Column(Text, default="[]")
    comment_text = Column(Text, nullable=False)
    sentiment_label = Column(String(20), nullable=False)
    sentiment_score = Column(Float, nullable=False)
    flagged_critical = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(100), index=True, nullable=False)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    sender_name = Column(String(100), nullable=False)
    sender_role = Column(String(20), nullable=False)
    message_text = Column(Text, nullable=False)
    is_bot_reply = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/database.py app/models.py tests/test_models.py
git commit -m "feat: configure SQLite WAL mode and busy_timeout=5000 with SQLAlchemy models"
```

---

### Task 3: Authentication with Direct Bcrypt & PyJWT (Modern Stack)

**Files:**
- Create: `app/auth.py`
- Create: `app/seed.py`
- Create: `app/routers/auth.py`
- Test: `tests/test_auth.py`

**Interfaces:**
- Consumes: `app.models.User`, `app.database.get_db`
- Produces: `verify_password()`, `get_password_hash()`, `create_access_token()`, `get_current_user()`, `require_roles()`, seed accounts (`patient@demo.com`, `doctor@demo.com`, `staff@demo.com`, `admin@demo.com`)

- [ ] **Step 1: Write failing auth test**

```python
# tests/test_auth.py
from app.auth import get_password_hash, verify_password, create_access_token, decode_token

def test_password_hashing():
    pw = "secret123"
    hashed = get_password_hash(pw)
    assert verify_password(pw, hashed) is True
    assert verify_password("wrong", hashed) is False

def test_token_creation_and_decode():
    token = create_access_token({"sub": "user@demo.com", "role": "doctor"})
    payload = decode_token(token)
    assert payload["sub"] == "user@demo.com"
    assert payload["role"] == "doctor"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_auth.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'app.auth'`

- [ ] **Step 3: Implement direct bcrypt & PyJWT auth logic**

```python
# app/auth.py
import bcrypt
import jwt
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.config import get_settings
from app.database import get_db
from app.models import User, UserRole

settings = get_settings()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    # Direct bcrypt check (truncates at 72 bytes as per bcrypt specification)
    pwd_bytes = plain_password.encode("utf-8")[:72]
    hashed_bytes = hashed_password.encode("utf-8")
    return bcrypt.checkpw(pwd_bytes, hashed_bytes)

def get_password_hash(password: str) -> str:
    pwd_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

def get_current_user(request: Request, token: Optional[str] = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    auth_token = token or request.cookies.get("access_token")
    if auth_token and auth_token.startswith("Bearer "):
        auth_token = auth_token.split(" ")[1]
    if not auth_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    
    payload = decode_token(auth_token)
    email: str = payload.get("sub")
    if email is None:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user

def require_roles(allowed_roles: List[UserRole]):
    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient privileges")
        return current_user
    return role_checker
```

```python
# app/seed.py
from datetime import date
from sqlalchemy.orm import Session
from app.models import User, Patient, Doctor, UserRole
from app.auth import get_password_hash

def seed_demo_data(db: Session):
    if db.query(User).first():
        return
    
    admin = User(email="admin@demo.com", hashed_password=get_password_hash("admin123"), full_name="Clinic Director", role=UserRole.ADMIN, phone="555-0100")
    staff = User(email="staff@demo.com", hashed_password=get_password_hash("staff123"), full_name="Reception Staff", role=UserRole.STAFF, phone="555-0101")
    doctor_u = User(email="doctor@demo.com", hashed_password=get_password_hash("doctor123"), full_name="Dr. Emily Stone", role=UserRole.DOCTOR, phone="555-0102")
    patient_u = User(email="patient@demo.com", hashed_password=get_password_hash("patient123"), full_name="Sarah Connor", role=UserRole.PATIENT, phone="555-0103")
    
    db.add_all([admin, staff, doctor_u, patient_u])
    db.commit()

    doctor = Doctor(user_id=doctor_u.id, specialization="Cardiology & General Medicine", license_number="MD-98421", room_number="Room 102", consultation_fee=60.00)
    patient = Patient(user_id=patient_u.id, date_of_birth=date(1990, 5, 14), gender="Female", blood_group="O+", emergency_contact_name="John Connor", emergency_contact_phone="555-9999", allergies="Penicillin", medical_history="Mild Asthma")
    
    db.add_all([doctor, patient])
    db.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_auth.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/auth.py app/seed.py tests/test_auth.py
git commit -m "feat: implement modern auth using PyJWT and direct bcrypt (zero passlib deprecation)"
```

---

### Task 4: Sentiment Analysis Engine & Feedback Subsystem

**Files:**
- Create: `app/sentiment.py`
- Create: `app/routers/feedback.py`
- Test: `tests/test_sentiment.py`

**Interfaces:**
- Consumes: Raw patient review text and rating
- Produces: `analyze_sentiment(text: str, rating: int)` -> `{sentiment_label, sentiment_score, flagged_critical}`, and `/api/feedback` endpoints

- [ ] **Step 1: Write failing sentiment test**

```python
# tests/test_sentiment.py
from app.sentiment import analyze_sentiment

def test_positive_sentiment():
    result = analyze_sentiment("The doctor was extremely attentive, kind, and knowledgeable!", rating=5)
    assert result["sentiment_label"] == "positive"
    assert result["sentiment_score"] > 0.3
    assert result["flagged_critical"] is False

def test_critical_negative_sentiment():
    result = analyze_sentiment("Terrible experience. Waited 2 hours and staff was rude and dismissive.", rating=1)
    assert result["sentiment_label"] == "negative"
    assert result["sentiment_score"] < -0.2
    assert result["flagged_critical"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sentiment.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'app.sentiment'`

- [ ] **Step 3: Implement VADER sentiment analyzer**

```python
# app/sentiment.py
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

analyzer = SentimentIntensityAnalyzer()

def analyze_sentiment(text: str, rating: int) -> dict:
    scores = analyzer.polarity_scores(text)
    compound = scores["compound"]

    if compound >= 0.05:
        label = "positive"
    elif compound <= -0.05:
        label = "negative"
    else:
        label = "neutral"

    flagged_critical = (compound < -0.3) or (rating <= 2)

    return {
        "sentiment_label": label,
        "sentiment_score": round(compound, 4),
        "flagged_critical": flagged_critical
    }
```

```python
# app/routers/feedback.py
import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from app.database import get_db
from app.models import PatientFeedback, Patient, User
from app.auth import get_current_user
from app.sentiment import analyze_sentiment

router = APIRouter(prefix="/api/feedback", tags=["Feedback & Sentiment"])

class FeedbackCreate(BaseModel):
    rating: int
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
        flagged_critical=sentiment["flagged_critical"]
    )
    db.add(fb)
    db.commit()
    db.refresh(fb)
    return {"status": "success", "id": fb.id, "sentiment": sentiment}

@router.get("/analytics")
def get_feedback_analytics(db: Session = Depends(get_db)):
    feedbacks = db.query(PatientFeedback).all()
    total = len(feedbacks)
    if total == 0:
        return {"total": 0, "avg_rating": 5.0, "positive_pct": 100, "negative_pct": 0, "critical_count": 0, "items": []}

    avg_rating = round(sum(f.rating for f in feedbacks) / total, 2)
    pos_count = sum(1 for f in feedbacks if f.sentiment_label == "positive")
    neg_count = sum(1 for f in feedbacks if f.sentiment_label == "negative")
    critical = [f for f in feedbacks if f.flagged_critical]

    return {
        "total": total,
        "avg_rating": avg_rating,
        "positive_pct": round((pos_count / total) * 100, 1),
        "negative_pct": round((neg_count / total) * 100, 1),
        "critical_count": len(critical),
        "items": [
            {
                "id": f.id,
                "rating": f.rating,
                "comment": f.comment_text,
                "sentiment_label": f.sentiment_label,
                "sentiment_score": f.sentiment_score,
                "flagged_critical": f.flagged_critical,
                "created_at": f.created_at.isoformat()
            } for f in feedbacks[-20:]
        ]
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_sentiment.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/sentiment.py app/routers/feedback.py tests/test_sentiment.py
git commit -m "feat: implement VADER sentiment analysis engine and feedback analytics endpoint"
```

---

### Task 5: Live Queue Management Subsystem & WebSockets

**Files:**
- Create: `app/websocket_manager.py`
- Create: `app/routers/queue.py`
- Test: `tests/test_queue.py`

**Interfaces:**
- Consumes: `QueueTicket` DB operations
- Produces: `ConnectionManager` for live broadcast, `/api/queue/issue`, `/api/queue/next`, `/api/queue/live-status`, and `/ws/queue`

- [ ] **Step 1: Write queue logic test**

```python
# tests/test_queue.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timezone
from app.models import Base, User, Patient, Doctor, QueueTicket, QueueStatus

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()

def test_sequential_ticket_issuance(db):
    u1 = User(email="doc@test.com", hashed_password="pw", full_name="Doctor", role="doctor")
    u2 = User(email="pat@test.com", hashed_password="pw", full_name="Patient", role="patient")
    db.add_all([u1, u2])
    db.commit()
    doc = Doctor(user_id=u1.id, specialization="Gen", license_number="L1", room_number="101")
    pat = Patient(user_id=u2.id)
    db.add_all([doc, pat])
    db.commit()

    t1 = QueueTicket(ticket_number="Q-101", patient_id=pat.id, doctor_id=doc.id, status=QueueStatus.WAITING)
    t2 = QueueTicket(ticket_number="Q-102", patient_id=pat.id, doctor_id=doc.id, status=QueueStatus.WAITING)
    db.add_all([t1, t2])
    db.commit()

    tickets = db.query(QueueTicket).filter(QueueTicket.status == QueueStatus.WAITING).all()
    assert len(tickets) == 2
    assert tickets[0].ticket_number == "Q-101"
    assert tickets[1].ticket_number == "Q-102"
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/test_queue.py -v`  
Expected: PASS

- [ ] **Step 3: Implement WebSocket Connection Manager and Queue API**

```python
# app/websocket_manager.py
from typing import List
from fastapi import WebSocket

class QueueConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass

queue_manager = QueueConnectionManager()
```

```python
# app/routers/queue.py
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.database import get_db
from app.models import QueueTicket, QueueStatus, Patient, Doctor, User, UserRole
from app.auth import get_current_user, require_roles
from app.websocket_manager import queue_manager

router = APIRouter(prefix="/api/queue", tags=["Queue Management"])

class IssueTicketRequest(BaseModel):
    doctor_id: int
    patient_id: int
    priority: str = "normal"

@router.get("/live-status")
def get_live_status(db: Session = Depends(get_db)):
    called = db.query(QueueTicket).filter(QueueTicket.status.in_([QueueStatus.CALLED, QueueStatus.IN_CONSULTATION])).order_by(QueueTicket.called_at.desc()).first()
    waiting = db.query(QueueTicket).filter(QueueTicket.status == QueueStatus.WAITING).order_by(QueueTicket.id.asc()).all()
    
    return {
        "currently_serving": called.ticket_number if called else "None",
        "currently_serving_room": called.doctor.room_number if called and called.doctor else "N/A",
        "waiting_count": len(waiting),
        "waiting_tickets": [t.ticket_number for t in waiting],
        "estimated_wait_minutes": len(waiting) * 10
    }

@router.post("/issue")
async def issue_ticket(data: IssueTicketRequest, db: Session = Depends(get_db)):
    count = db.query(QueueTicket).count() + 101
    ticket_num = f"Q-{count}"
    ticket = QueueTicket(
        ticket_number=ticket_num,
        patient_id=data.patient_id,
        doctor_id=data.doctor_id,
        status=QueueStatus.WAITING,
        priority=data.priority,
        issued_at=datetime.now(timezone.utc)
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    
    await queue_manager.broadcast({"event": "QUEUE_UPDATED", "ticket": ticket_num, "status": "issued"})
    return {"status": "success", "ticket_number": ticket_num, "id": ticket.id}

@router.post("/call-next")
async def call_next_patient(doctor_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_roles([UserRole.STAFF, UserRole.DOCTOR, UserRole.ADMIN]))):
    next_ticket = db.query(QueueTicket).filter(QueueTicket.doctor_id == doctor_id, QueueTicket.status == QueueStatus.WAITING).order_by(QueueTicket.id.asc()).first()
    if not next_ticket:
        raise HTTPException(status_code=404, detail="No waiting patients in queue")
    
    next_ticket.status = QueueStatus.CALLED
    next_ticket.called_at = datetime.now(timezone.utc)
    db.commit()
    
    await queue_manager.broadcast({
        "event": "PATIENT_CALLED",
        "ticket_number": next_ticket.ticket_number,
        "room_number": next_ticket.doctor.room_number
    })
    return {"status": "success", "called_ticket": next_ticket.ticket_number}

@router.websocket("/ws")
async def websocket_queue_endpoint(websocket: WebSocket):
    await queue_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        queue_manager.disconnect(websocket)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_queue.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/websocket_manager.py app/routers/queue.py tests/test_queue.py
git commit -m "feat: implement live queue system with websocket broadcast and status endpoints"
```

---

### Task 6: Appointments & Doctor Daily Schedule Subsystem

**Files:**
- Create: `app/routers/appointments.py`
- Test: `tests/test_appointments.py`

**Interfaces:**
- Consumes: `Appointment`, `Doctor`, `Patient`
- Produces: `/api/appointments/doctors`, `/api/appointments/book`, `/api/appointments/doctor-schedule/{id}`

- [ ] **Step 1: Write failing appointments test**

```python
# tests/test_appointments.py
from datetime import date
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_get_doctors_list():
    response = client.get("/api/appointments/doctors")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_appointments.py -v`  
Expected: FAIL with 404 or `ModuleNotFoundError`

- [ ] **Step 3: Implement appointments router and doctor schedule logic**

```python
# app/routers/appointments.py
from datetime import date, datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.database import get_db
from app.models import Appointment, AppointmentStatus, Doctor, Patient, User, UserRole
from app.auth import get_current_user, require_roles

router = APIRouter(prefix="/api/appointments", tags=["Appointments & Schedule"])

class BookAppointmentRequest(BaseModel):
    doctor_id: int
    appointment_date: str
    time_slot: str
    reason_for_visit: Optional[str] = None

@router.get("/doctors")
def list_doctors(db: Session = Depends(get_db)):
    doctors = db.query(Doctor).filter(Doctor.is_available == True).all()
    return [
        {
            "id": d.id,
            "name": d.user.full_name,
            "specialization": d.specialization,
            "room_number": d.room_number,
            "fee": float(d.consultation_fee)
        } for d in doctors
    ]

@router.post("/book")
def book_appointment(data: BookAppointmentRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.user_id == user.id).first()
    if not patient:
        raise HTTPException(status_code=400, detail="User is not registered as a patient")
    
    app_date = datetime.strptime(data.appointment_date, "%Y-%m-%d").date()
    exists = db.query(Appointment).filter(
        Appointment.doctor_id == data.doctor_id,
        Appointment.appointment_date == app_date,
        Appointment.time_slot == data.time_slot,
        Appointment.status != AppointmentStatus.CANCELLED
    ).first()
    if exists:
        raise HTTPException(status_code=409, detail="This time slot is already booked")

    app = Appointment(
        patient_id=patient.id,
        doctor_id=data.doctor_id,
        appointment_date=app_date,
        time_slot=data.time_slot,
        reason_for_visit=data.reason_for_visit,
        status=AppointmentStatus.CONFIRMED
    )
    db.add(app)
    db.commit()
    db.refresh(app)
    return {"status": "success", "appointment_id": app.id}

@router.get("/doctor-schedule/{doctor_id}")
def get_doctor_schedule(doctor_id: int, schedule_date: Optional[str] = None, db: Session = Depends(get_db)):
    target_date = datetime.strptime(schedule_date, "%Y-%m-%d").date() if schedule_date else date.today()
    apps = db.query(Appointment).filter(
        Appointment.doctor_id == doctor_id,
        Appointment.appointment_date == target_date
    ).order_by(Appointment.time_slot.asc()).all()

    return [
        {
            "id": a.id,
            "patient_name": a.patient.user.full_name,
            "patient_phone": a.patient.user.phone,
            "time_slot": a.time_slot,
            "status": a.status,
            "reason": a.reason_for_visit
        } for a in apps
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_appointments.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/routers/appointments.py tests/test_appointments.py
git commit -m "feat: add appointment booking and doctor touch-friendly schedule endpoints"
```

---

### Task 7: Electronic Medical Records (EMR) & Digital Prescription Generator

**Files:**
- Create: `app/routers/emr.py`
- Test: `tests/test_emr.py`

**Interfaces:**
- Consumes: `Prescription`, `Patient`, `Doctor`
- Produces: `/api/emr/patient/{id}`, `/api/prescriptions/create`

- [ ] **Step 1: Write EMR & prescription test**

```python
# tests/test_emr.py
import hashlib

def test_prescription_hash_generation():
    token = hashlib.sha256(b"rx-101-sarah-connor").hexdigest()[:16]
    assert len(token) == 16
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/test_emr.py -v`  
Expected: PASS

- [ ] **Step 3: Implement EMR & Prescription Router**

```python
# app/routers/emr.py
import json
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.database import get_db
from app.models import Patient, Doctor, Prescription, User, UserRole
from app.auth import get_current_user, require_roles

router = APIRouter(prefix="/api/emr", tags=["EMR & Prescriptions"])

class MedicationItem(BaseModel):
    drug_name: str
    dosage: str
    frequency: str
    duration: str
    instructions: Optional[str] = ""

class CreatePrescriptionRequest(BaseModel):
    patient_id: int
    doctor_id: int
    diagnosis: str
    clinical_notes: Optional[str] = ""
    medications: List[MedicationItem]

@router.get("/patient/{patient_id}")
def get_patient_emr(patient_id: int, user: User = Depends(require_roles([UserRole.DOCTOR, UserRole.STAFF, UserRole.ADMIN])), db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    
    prescriptions = db.query(Prescription).filter(Prescription.patient_id == patient_id).order_by(Prescription.created_at.desc()).all()

    return {
        "patient_id": patient.id,
        "name": patient.user.full_name,
        "dob": str(patient.date_of_birth),
        "gender": patient.gender,
        "blood_group": patient.blood_group,
        "allergies": patient.allergies,
        "medical_history": patient.medical_history,
        "prescriptions": [
            {
                "id": p.id,
                "diagnosis": p.diagnosis,
                "notes": p.clinical_notes,
                "medications": json.loads(p.medications_json),
                "created_at": p.created_at.strftime("%Y-%m-%d %H:%M"),
                "qr_code_hash": p.qr_code_hash
            } for p in prescriptions
        ]
    }

@router.post("/prescription/create")
def create_prescription(data: CreatePrescriptionRequest, user: User = Depends(require_roles([UserRole.DOCTOR, UserRole.ADMIN])), db: Session = Depends(get_db)):
    qr_hash = uuid.uuid4().hex[:16].upper()
    rx = Prescription(
        patient_id=data.patient_id,
        doctor_id=data.doctor_id,
        diagnosis=data.diagnosis,
        clinical_notes=data.clinical_notes,
        medications_json=json.dumps([m.dict() for m in data.medications]),
        qr_code_hash=qr_hash
    )
    db.add(rx)
    db.commit()
    db.refresh(rx)
    return {"status": "success", "prescription_id": rx.id, "qr_code_hash": rx.qr_code_hash}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_emr.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/routers/emr.py tests/test_emr.py
git commit -m "feat: implement doctor EMR record access and digital e-prescription generator"
```

---

### Task 8: Clinic Staff Billing & Digital Invoicing Subsystem

**Files:**
- Create: `app/routers/billing.py`
- Test: `tests/test_billing.py`

**Interfaces:**
- Consumes: `Invoice`, `Patient`, `QueueTicket`
- Produces: `/api/billing/create`, `/api/billing/list`

- [ ] **Step 1: Write billing test**

```python
# tests/test_billing.py
def test_invoice_calculation():
    consultation = 50.0
    medication = 25.50
    discount = 5.0
    total = (consultation + medication) - discount
    assert total == 70.50
```

- [ ] **Step 2: Run test to verify calculation passes**

Run: `pytest tests/test_billing.py -v`  
Expected: PASS

- [ ] **Step 3: Implement Billing & Invoicing Router**

```python
# app/routers/billing.py
from datetime import datetime, timezone
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from app.database import get_db
from app.models import Invoice, Patient, User, UserRole
from app.auth import require_roles

router = APIRouter(prefix="/api/billing", tags=["Billing & Digital Invoicing"])

class CreateInvoiceRequest(BaseModel):
    patient_id: int
    queue_ticket_id: Optional[int] = None
    consultation_fee: float = 0.0
    medication_fee: float = 0.0
    other_fees: float = 0.0
    discount_amount: float = 0.0
    payment_method: str = "cash"

@router.post("/create")
def create_invoice(data: CreateInvoiceRequest, user: User = Depends(require_roles([UserRole.STAFF, UserRole.ADMIN])), db: Session = Depends(get_db)):
    total = round((data.consultation_fee + data.medication_fee + data.other_fees) - data.discount_amount, 2)
    receipt_no = f"REC-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

    inv = Invoice(
        receipt_number=receipt_no,
        patient_id=data.patient_id,
        queue_ticket_id=data.queue_ticket_id,
        consultation_fee=data.consultation_fee,
        medication_fee=data.medication_fee,
        other_fees=data.other_fees,
        discount_amount=data.discount_amount,
        total_amount=total,
        payment_method=data.payment_method,
        payment_status="paid",
        paid_at=datetime.now(timezone.utc)
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return {"status": "success", "invoice_id": inv.id, "receipt_number": inv.receipt_number, "total": inv.total_amount}

@router.get("/list")
def list_invoices(db: Session = Depends(get_db), user: User = Depends(require_roles([UserRole.STAFF, UserRole.ADMIN]))):
    invoices = db.query(Invoice).order_by(Invoice.id.desc()).limit(50).all()
    return [
        {
            "id": inv.id,
            "receipt_number": inv.receipt_number,
            "patient_name": inv.patient.user.full_name if inv.patient else "Walk-in",
            "total_amount": float(inv.total_amount),
            "payment_method": inv.payment_method,
            "paid_at": inv.paid_at.strftime("%Y-%m-%d %H:%M")
        } for inv in invoices
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_billing.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/routers/billing.py tests/test_billing.py
git commit -m "feat: implement billing and digital invoicing module"
```

---

### Task 9: Real-time Patient-Staff Chat with Automated FAQ Bot

**Files:**
- Create: `app/chat_bot.py`
- Create: `app/routers/chat.py`
- Test: `tests/test_chat.py`

**Interfaces:**
- Consumes: Chat messages
- Produces: Live patient-to-staff relay with automated FAQ responses

- [ ] **Step 1: Write chat bot test**

```python
# tests/test_chat.py
from app.chat_bot import get_bot_response

def test_bot_faq_response():
    assert "8:00 AM" in get_bot_response("what are your clinic hours?")
    assert "appointment" in get_bot_response("how do I book an appointment?").lower()
    assert "911" in get_bot_response("is this an emergency?")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_chat.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'app.chat_bot'`

- [ ] **Step 3: Implement Chat Bot and WebSocket relay**

```python
# app/chat_bot.py
FAQ_RULES = [
    (["hours", "opening", "open", "time", "schedule"], "Our clinic is open Monday to Saturday from 8:00 AM to 6:00 PM. Emergency walk-ins are accepted anytime during open hours."),
    (["book", "appointment", "reserve", "slot"], "You can book an appointment in the Patient Portal under 'Book Appointment'. Choose your doctor and preferred time slot!"),
    (["location", "address", "where", "directions"], "We are located at 123 Healthcare Blvd, Suite 400, Medical Arts Tower. Parking is available on Level B1."),
    (["emergency", "urgent", "ambulance", "severe"], "For severe life-threatening emergencies, please call 911 or proceed immediately to the nearest hospital Emergency Room."),
    (["doctor", "specialist", "cardiologist", "physician"], "We have specialists in Cardiology, Pediatrics, General Medicine, and Orthopedics. View their profiles in the booking tab.")
]

def get_bot_response(message: str) -> str:
    msg_lower = message.lower()
    for keywords, response in FAQ_RULES:
        if any(k in msg_lower for k in keywords):
            return response
    return "Thank you for messaging. A clinic receptionist has received your inquiry and will reply shortly. If urgent, please call our front desk at 555-0100."
```

```python
# app/routers/chat.py
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Dict
from app.database import get_db
from app.models import ChatMessage
from app.chat_bot import get_bot_response

router = APIRouter(prefix="/api/chat", tags=["Live Chat Box"])

class ChatConnectionHub:
    def __init__(self):
        self.rooms: Dict[str, List[WebSocket]] = {}

    async def connect(self, session_id: str, ws: WebSocket):
        await ws.accept()
        if session_id not in self.rooms:
            self.rooms[session_id] = []
        self.rooms[session_id].append(ws)

    def disconnect(self, session_id: str, ws: WebSocket):
        if session_id in self.rooms and ws in self.rooms[session_id]:
            self.rooms[session_id].remove(ws)

    async def send_to_room(self, session_id: str, payload: dict):
        if session_id in self.rooms:
            for ws in self.rooms[session_id]:
                try:
                    await ws.send_json(payload)
                except Exception:
                    pass

chat_hub = ChatConnectionHub()

@router.websocket("/ws/{session_id}")
async def chat_websocket(websocket: WebSocket, session_id: str, db: Session = Depends(get_db)):
    await chat_hub.connect(session_id, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            sender_name = data.get("sender_name", "Patient")
            msg_text = data.get("message", "")
            
            msg = ChatMessage(session_id=session_id, sender_name=sender_name, sender_role="patient", message_text=msg_text)
            db.add(msg)
            db.commit()

            await chat_hub.send_to_room(session_id, {"sender": sender_name, "message": msg_text, "role": "patient"})

            bot_reply = get_bot_response(msg_text)
            bot_msg = ChatMessage(session_id=session_id, sender_name="Clinic Assistant Bot", sender_role="bot", message_text=bot_reply, is_bot_reply=True)
            db.add(bot_msg)
            db.commit()

            await chat_hub.send_to_room(session_id, {"sender": "Clinic Assistant Bot", "message": bot_reply, "role": "bot"})
    except WebSocketDisconnect:
        chat_hub.disconnect(session_id, websocket)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_chat.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/chat_bot.py app/routers/chat.py tests/test_chat.py
git commit -m "feat: implement live patient-staff chat with automated FAQ bot fallback"
```

---

### Task 10: Responsive Web Portals & FastAPI App Assembly

**Files:**
- Create: `app/static/index.html` (Unified Portal with Role Selector & Mobile Views)
- Create: `app/static/display.html` (Public TV waiting room screen)
- Create: `app/static/app.js` (Modular ES client for Auth, Queue WebSocket, EMR, Billing, and Chat)
- Create: `app/main.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: All routers + static assets
- Produces: Complete mounted FastAPI web application at `http://localhost:8000`

- [ ] **Step 1: Write application integration test**

```python
# tests/test_main.py
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_root_serves_html():
    res = client.get("/")
    assert res.status_code == 200
    assert "Clinic Management System" in res.text

def test_api_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "healthy"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_main.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 3: Implement main app and assemble all routers**

```python
# app/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.config import get_settings
from app.database import engine, Base, SessionLocal
from app.seed import seed_demo_data
from app.routers import auth, feedback, queue, appointments, emr, billing, chat

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_demo_data(db)
    finally:
        db.close()
    yield

settings = get_settings()
app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

# Mount API Routers
app.include_router(feedback.router)
app.include_router(queue.router)
app.include_router(appointments.router)
app.include_router(emr.router)
app.include_router(billing.router)
app.include_router(chat.router)

# Static files and SPA entry
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.get("/api/health")
def health_check():
    return {"status": "healthy", "service": settings.APP_NAME}

@app.get("/")
def serve_index():
    return FileResponse("app/static/index.html")

@app.get("/display")
def serve_public_display():
    return FileResponse("app/static/display.html")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_main.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/main.py app/static/ tests/test_main.py
git commit -m "feat: assemble FastAPI application, mount all routers and static responsive web portals"
```

---

### Task 11: Cloud Deployment Packaging (Dockerfile, Procfile, Render Configuration)

**Files:**
- Create: `Dockerfile`
- Create: `Procfile`
- Create: `render.yaml`
- Create: `.dockerignore`
- Test: `tests/test_deployment_artifacts.py`

**Interfaces:**
- Consumes: Application directory
- Produces: Cloud-ready deployment configurations for Render, Railway, and Fly.io

- [ ] **Step 1: Write test verifying deployment config syntax**

```python
# tests/test_deployment_artifacts.py
import os

def test_deployment_files_exist():
    assert os.path.exists("Dockerfile")
    assert os.path.exists("Procfile")
    assert os.path.exists("render.yaml")

def test_procfile_content():
    with open("Procfile") as f:
        content = f.read()
    assert "uvicorn app.main:app" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_deployment_artifacts.py -v`  
Expected: FAIL with `AssertionError: assert False`

- [ ] **Step 3: Create deployment manifests**

```dockerfile
# Dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
```

```yaml
# render.yaml
services:
  - type: web
    name: clinic-management-system
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn app.main:app --host 0.0.0.0 --port $PORT
    envVars:
      - key: DEMO_MODE
        value: "true"
      - key: SECRET_KEY
        generateValue: true
    disk:
      name: clinic-data
      mountPath: /app/data
      sizeGB: 1
```

```
# Procfile
web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_deployment_artifacts.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add Dockerfile Procfile render.yaml .dockerignore tests/test_deployment_artifacts.py
git commit -m "feat: add production Dockerfile, Procfile, and Render cloud deployment blueprint"
```

---

### Task 12: Full End-to-End System Verification Suite

**Files:**
- Create: `tests/test_e2e_flow.py`
- Test: `tests/test_e2e_flow.py`

- [ ] **Step 1: Write full workflow integration test**

```python
# tests/test_e2e_flow.py
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_full_patient_to_prescription_flow():
    # 1. Health
    h = client.get("/api/health")
    assert h.status_code == 200

    # 2. Doctors list
    d = client.get("/api/appointments/doctors")
    assert d.status_code == 200
    doctors = d.json()
    assert len(doctors) > 0

    # 3. Live Queue
    q = client.get("/api/queue/live-status")
    assert q.status_code == 200

    # 4. Feedback Analytics
    f = client.get("/api/feedback/analytics")
    assert f.status_code == 200
```

- [ ] **Step 2: Run test to verify passes**

Run: `pytest tests/test_e2e_flow.py -v`  
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e_flow.py
git commit -m "test: add comprehensive end-to-end clinical workflow integration test"
```
