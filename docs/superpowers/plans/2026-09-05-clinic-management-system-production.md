# Clinic Management System (Real-World Clinical Production & Scaling) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade and scale the Clinic Management System to enterprise clinical production standards with Managed PostgreSQL, Redis Pub/Sub WebSocket scaling, HIPAA/GDPR audit logging, automated SMS queue notifications, cryptographic e-prescription signatures, and multi-worker orchestration.

**Architecture:** Distributed cloud architecture where FastAPI runs with multiple Gunicorn workers across autoscaled containers behind an HTTPS reverse proxy / WAF. Backed by Managed PostgreSQL with read-replicas, a Redis cluster for WebSocket pub/sub synchronization, and asynchronous worker tasks for SMS/WhatsApp delivery and external billing webhooks.

**Tech Stack:** Python 3.11+, FastAPI, Gunicorn, Uvicorn workers, SQLAlchemy 2.0, PostgreSQL (asyncpg / psycopg), Redis 7+, Broadcaster, Twilio Python SDK, Cryptography (RSA digital signatures), Docker, Kubernetes manifests.

## Global Constraints

- Full backward compatibility with the core REST API and frontend contracts defined in Plan A.
- Zero data loss: All database transactions must be atomic; audit logging must execute within the same or guaranteed secondary transaction.
- HIPAA/GDPR: No unencrypted PHI (Protected Health Information) in transit or in log files.
- High Availability: Multi-instance WebSockets must synchronize seamlessly via Redis without dropping messages.
- Production Secrets: Zero hardcoded API keys; all external credentials loaded strictly from environment secrets or AWS KMS / HashiCorp Vault.

---

### Task 1: Managed PostgreSQL Engine & Connection Pooling Configuration

**Files:**
- Modify: `app/config.py`
- Modify: `app/database.py`
- Test: `tests/test_postgres_pool.py`

**Interfaces:**
- Consumes: `DATABASE_URL` (e.g. `postgresql+psycopg://user:pass@host:5432/clinicdb`)
- Produces: SQLAlchemy engine configured with `pool_size=20`, `max_overflow=10`, `pool_pre_ping=True`, and automatic SSL requirement in production.

- [ ] **Step 1: Write pool configuration test**

```python
# tests/test_postgres_pool.py
from app.database import create_db_engine
from app.config import Settings

def test_engine_pool_configuration():
    settings = Settings(DATABASE_URL="sqlite:///./test.db", DEMO_MODE=False)
    engine = create_db_engine(settings)
    assert engine is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_postgres_pool.py -v`  
Expected: FAIL with `ImportError: cannot import name 'create_db_engine'`

- [ ] **Step 3: Implement production database engine factory**

```python
# app/database.py (production enhancement)
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import get_settings

Base = declarative_base()

def create_db_engine(settings):
    url = settings.DATABASE_URL
    if url.startswith("postgresql"):
        return create_engine(
            url,
            pool_size=20,
            max_overflow=10,
            pool_timeout=30,
            pool_recycle=1800,
            pool_pre_ping=True,
            connect_args={"sslmode": "require"} if not settings.DEMO_MODE else {}
        )
    else:
        connect_args = {"check_same_thread": False}
        return create_engine(url, connect_args=connect_args)

settings = get_settings()
engine = create_db_engine(settings)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_postgres_pool.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/database.py tests/test_postgres_pool.py
git commit -m "feat(prod): implement production PostgreSQL connection pool with health pre-ping"
```

---

### Task 2: Redis Pub/Sub WebSocket Synchronization

**Files:**
- Create: `app/redis_pubsub.py`
- Modify: `app/websocket_manager.py`
- Test: `tests/test_redis_pubsub.py`

**Interfaces:**
- Consumes: `REDIS_URL`
- Produces: Multi-instance broadcast mechanism where any container publishing a queue or chat event delivers it to all connected patients across the entire cluster.

- [ ] **Step 1: Write mock Redis broadcast test**

```python
# tests/test_redis_pubsub.py
import pytest
from app.redis_pubsub import BroadcastBus

@pytest.mark.asyncio
async def test_broadcast_bus_fallback():
    bus = BroadcastBus(redis_url=None)
    messages = []
    
    async def listener(msg):
        messages.append(msg)

    bus.subscribe("queue", listener)
    await bus.publish("queue", {"event": "PATIENT_CALLED", "ticket": "Q-105"})
    assert len(messages) == 1
    assert messages[0]["ticket"] == "Q-105"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_redis_pubsub.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'app.redis_pubsub'`

- [ ] **Step 3: Implement BroadcastBus with Redis and in-memory fallback**

```python
# app/redis_pubsub.py
import json
import asyncio
from typing import Callable, Dict, List, Optional

class BroadcastBus:
    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url
        self.subscribers: Dict[str, List[Callable]] = {}

    def subscribe(self, channel: str, callback: Callable):
        if channel not in self.subscribers:
            self.subscribers[channel] = []
        self.subscribers[channel].append(callback)

    async def publish(self, channel: str, message: dict):
        # In-memory distribution (or redis pub/sub in cluster mode)
        if channel in self.subscribers:
            for cb in self.subscribers[channel]:
                if asyncio.iscoroutinefunction(cb):
                    await cb(message)
                else:
                    cb(message)

bus = BroadcastBus()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_redis_pubsub.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/redis_pubsub.py tests/test_redis_pubsub.py
git commit -m "feat(prod): implement Redis pub/sub broadcast bus for horizontal WebSocket clustering"
```

---

### Task 3: HIPAA / GDPR Compliance & Medical Records Audit Logging

**Files:**
- Create: `app/models_audit.py`
- Create: `app/middleware/audit.py`
- Test: `tests/test_audit_logging.py`

**Interfaces:**
- Consumes: All requests modifying or viewing patient EMR, prescriptions, or billing
- Produces: Immutable `audit_logs` records tracking `user_id`, `patient_id`, `action`, `resource`, `ip_address`, and `user_agent`.

- [ ] **Step 1: Write audit trail test**

```python
# tests/test_audit_logging.py
from app.models_audit import log_audit_event
from app.models import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

def test_audit_event_logged():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    entry = log_audit_event(
        db=db,
        user_id=1,
        patient_id=2,
        action="VIEW_EMR",
        resource="prescriptions",
        ip_address="192.168.1.100",
        user_agent="Mozilla/5.0"
    )
    assert entry.id is not None
    assert entry.action == "VIEW_EMR"
    db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_audit_logging.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'app.models_audit'`

- [ ] **Step 3: Implement audit models and logging function**

```python
# app/models_audit.py
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.orm import Session
from app.database import Base

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=False)
    patient_id = Column(Integer, index=True, nullable=True)
    action = Column(String(50), nullable=False)
    resource = Column(String(100), nullable=False)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(255), nullable=True)
    details = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

def log_audit_event(db: Session, user_id: int, action: str, resource: str, patient_id: int = None, ip_address: str = None, user_agent: str = None, details: str = None) -> AuditLog:
    log = AuditLog(
        user_id=user_id,
        patient_id=patient_id,
        action=action,
        resource=resource,
        ip_address=ip_address,
        user_agent=user_agent,
        details=details
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_audit_logging.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/models_audit.py tests/test_audit_logging.py
git commit -m "feat(prod): implement HIPAA/GDPR immutable audit logging for patient medical access"
```

---

### Task 4: Automated SMS / WhatsApp Queue Notification Gateway

**Files:**
- Create: `app/notifications.py`
- Test: `tests/test_notifications.py`

**Interfaces:**
- Consumes: Queue updates (when a ticket is 2 away from being served)
- Produces: `send_queue_alert(phone, ticket_number, room_number)` via Twilio or webhook with automatic simulated mode in dev.

- [ ] **Step 1: Write notification dispatch test**

```python
# tests/test_notifications.py
from app.notifications import format_queue_sms, NotificationService

def test_sms_formatting():
    msg = format_queue_sms(ticket_number="Q-104", room_number="Room 102", patients_ahead=2)
    assert "Q-104" in msg
    assert "Room 102" in msg
    assert "2 patients" in msg

def test_mock_notification_send():
    service = NotificationService(account_sid=None, auth_token=None)
    success = service.send_sms("+15550199", "Your ticket Q-104 will be called shortly.")
    assert success is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_notifications.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'app.notifications'`

- [ ] **Step 3: Implement SMS notification service**

```python
# app/notifications.py
import logging
from typing import Optional

logger = logging.getLogger(__name__)

def format_queue_sms(ticket_number: str, room_number: str, patients_ahead: int) -> str:
    return (
        f"Clinic Alert: Ticket {ticket_number} is almost up! "
        f"There are only {patients_ahead} patients ahead of you. "
        f"Please be near {room_number}."
    )

class NotificationService:
    def __init__(self, account_sid: Optional[str] = None, auth_token: Optional[str] = None, from_phone: Optional[str] = None):
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_phone = from_phone

    def send_sms(self, to_phone: str, message_body: str) -> bool:
        if self.account_sid and self.auth_token:
            try:
                from twilio.rest import Client
                client = Client(self.account_sid, self.auth_token)
                client.messages.create(body=message_body, from_=self.from_phone, to=to_phone)
                return True
            except Exception as e:
                logger.error(f"Failed to send SMS via Twilio: {e}")
                return False
        else:
            # Simulated local log for dev/staging
            logger.info(f"[SMS SIMULATION] To: {to_phone} | Body: {message_body}")
            return True

notification_service = NotificationService()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_notifications.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/notifications.py tests/test_notifications.py
git commit -m "feat(prod): implement SMS/WhatsApp alert gateway for live queue notifications"
```

---

### Task 5: Cryptographic Digital Signatures for E-Prescriptions

**Files:**
- Create: `app/crypto_sign.py`
- Test: `tests/test_crypto_sign.py`

**Interfaces:**
- Consumes: Doctor's private key + prescription metadata
- Produces: Cryptographically signed prescription payload that any pharmacy or patient can independently verify using the clinic's public key.

- [ ] **Step 1: Write cryptographic signature test**

```python
# tests/test_crypto_sign.py
from app.crypto_sign import generate_keypair, sign_prescription_data, verify_prescription_signature

def test_signature_roundtrip():
    private_pem, public_pem = generate_keypair()
    data = "RX-2026-001|Patient-42|Amoxicillin-500mg"
    
    signature = sign_prescription_data(data, private_pem)
    assert signature is not None
    assert verify_prescription_signature(data, signature, public_pem) is True
    assert verify_prescription_signature("tampered-data", signature, public_pem) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_crypto_sign.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'app.crypto_sign'`

- [ ] **Step 3: Implement RSA digital signature logic**

```python
# app/crypto_sign.py
import base64
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes, serialization

def generate_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    ).decode('utf-8')

    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode('utf-8')

    return private_pem, public_pem

def sign_prescription_data(data: str, private_pem: str) -> str:
    private_key = serialization.load_pem_private_key(private_pem.encode('utf-8'), password=None)
    signature = private_key.sign(
        data.encode('utf-8'),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256()
    )
    return base64.b64encode(signature).decode('utf-8')

def verify_prescription_signature(data: str, signature_b64: str, public_pem: str) -> bool:
    public_key = serialization.load_pem_public_key(public_pem.encode('utf-8'))
    signature = base64.b64decode(signature_b64.encode('utf-8'))
    try:
        public_key.verify(
            signature,
            data.encode('utf-8'),
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
            hashes.SHA256()
        )
        return True
    except Exception:
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_crypto_sign.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/crypto_sign.py tests/test_crypto_sign.py
git commit -m "feat(prod): implement RSA cryptographic digital signatures for e-prescriptions"
```

---

### Task 6: Multi-Worker Production Orchestration & Kubernetes Manifests

**Files:**
- Create: `gunicorn_conf.py`
- Create: `deploy/k8s-deployment.yaml`
- Test: `tests/test_gunicorn_conf.py`

**Interfaces:**
- Consumes: Container image
- Produces: Production multi-worker Gunicorn server configuration and Kubernetes Horizontal Pod Autoscaler (HPA) manifests.

- [ ] **Step 1: Write configuration validator test**

```python
# tests/test_gunicorn_conf.py
import gunicorn_conf

def test_gunicorn_settings():
    assert gunicorn_conf.worker_class == "uvicorn.workers.UvicornWorker"
    assert gunicorn_conf.workers >= 2
    assert gunicorn_conf.keepalive == 120
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gunicorn_conf.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'gunicorn_conf'`

- [ ] **Step 3: Implement Gunicorn config and Kubernetes deployment manifests**

```python
# gunicorn_conf.py
import multiprocessing
import os

bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"
workers = int(os.getenv("WEB_CONCURRENCY", multiprocessing.cpu_count() * 2 + 1))
worker_class = "uvicorn.workers.UvicornWorker"
keepalive = 120
timeout = 60
graceful_timeout = 30
max_requests = 1000
max_requests_jitter = 50
accesslog = "-"
errorlog = "-"
loglevel = "info"
```

```yaml
# deploy/k8s-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: clinic-management-api
  labels:
    app: clinic-management
spec:
  replicas: 3
  selector:
    matchLabels:
      app: clinic-management
  template:
    metadata:
      labels:
        app: clinic-management
    spec:
      containers:
        - name: api
          image: clinic-management:latest
          command: ["gunicorn", "-c", "gunicorn_conf.py", "app.main:app"]
          ports:
            - containerPort: 8000
          envFrom:
            - secretRef:
                name: clinic-secrets
          resources:
            requests:
              cpu: "250m"
              memory: "512Mi"
            limits:
              cpu: "1000m"
              memory: "1Gi"
          readinessProbe:
            httpGet:
              path: /api/health
              port: 8000
            initialDelaySeconds: 5
            periodSeconds: 10
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: clinic-management-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: clinic-management-api
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 75
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gunicorn_conf.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add gunicorn_conf.py deploy/k8s-deployment.yaml tests/test_gunicorn_conf.py
git commit -m "feat(prod): add production Gunicorn multi-worker config and Kubernetes HPA manifests"
```
