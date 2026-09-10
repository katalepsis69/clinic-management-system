# Clinic Management System with Sentiment Analysis: System Design Document

**Date:** 2026-09-05  
**Status:** Approved  
**Author:** Antigravity Engineering  

---

## 1. Executive Summary & Goals

The **Clinic Management System (CMS)** is a responsive, web-based healthcare clinic management platform that unifies patient registration, queue management, appointment scheduling, doctor electronic medical records (EMR), digital prescriptions, billing/invoicing, live reception chat, and real-time patient sentiment analysis into a cohesive, high-performance application.

The design specifically accommodates two deployment pathways:
1. **Plan A: Free Cloud / Interactive Online Demo**: Fully functional single-container application using FastAPI, SQLite (WAL mode), WebSockets, and local VADER NLP, deployable on free cloud tiers (Render, Railway, Fly.io) with zero setup cost.
2. **Plan B: Real-World Clinical Production**: Scalable multi-container architecture using Managed PostgreSQL, Redis Pub/Sub for WebSockets, HIPAA/GDPR-compliant security, audit logging, SMS/WhatsApp notifications, and digital signature workflows.

---

## 2. Technology Stack & Architecture

### 2.1 Backend & NLP
* **Framework**: Python 3.11+ with **FastAPI** (asynchronous ASGI, high throughput, automatic OpenAPI documentation).
* **ASGI Server**: **Uvicorn** (local/demo) and **Gunicorn with Uvicorn workers** (production).
* **Sentiment Analysis Engine**: **VADER Sentiment Analysis** (`vaderSentiment`). Lightweight, rule-based NLP tuned for customer feedback and reviews. Operates locally with zero external API fees or external latency.
* **Database Access**: **SQLAlchemy 2.0 ORM** (abstracts database operations, allowing identical application code on SQLite and PostgreSQL).

### 2.2 Real-time Engine
* **WebSockets**: Native FastAPI WebSockets for bi-directional live queue updates and patient-to-staff live chat.
* **Resilience Mechanism**: Client-side automatic reconnection (exponential backoff: 1s, 2s, 5s) with a 5-second polling fallback if WebSockets are interrupted or blocked.

### 2.3 Frontend & User Experience
* **Framework**: Mobile-first responsive UI built with **HTML5, Tailwind CSS, and Modern Vanilla JavaScript (ES Modules)**.
* **Design Philosophy**: High readability, touch-optimized button hitboxes (minimum 44x44px for mobile/tablet doctor and patient use), zero client-side compilation required (no npm build step needed for instant cloud deployment).

---

## 3. Database Schema & Data Models

The database models are designed with SQLAlchemy to support SQLite for development/demo and PostgreSQL for production.

### 3.1 Core Tables
* **`users`**:
  * `id` (Integer / UUID, PK)
  * `email` (String, unique, indexed)
  * `hashed_password` (String)
  * `full_name` (String)
  * `role` (Enum: `patient`, `doctor`, `staff`, `admin`)
  * `phone` (String, indexed)
  * `created_at` (DateTime, UTC)

* **`patients`**:
  * `id` (Integer / UUID, PK)
  * `user_id` (FK -> `users.id`, unique)
  * `date_of_birth` (Date)
  * `gender` (String)
  * `blood_group` (String, nullable)
  * `emergency_contact_name` (String)
  * `emergency_contact_phone` (String)
  * `allergies` (Text)
  * `medical_history` (Text)

* **`doctors`**:
  * `id` (Integer / UUID, PK)
  * `user_id` (FK -> `users.id`, unique)
  * `specialization` (String)
  * `license_number` (String)
  * `room_number` (String)
  * `consultation_fee` (Numeric(10, 2))
  * `is_available` (Boolean, default True)

* **`appointments`**:
  * `id` (Integer / UUID, PK)
  * `patient_id` (FK -> `patients.id`)
  * `doctor_id` (FK -> `doctors.id`)
  * `appointment_date` (Date)
  * `time_slot` (String, e.g. "09:30 AM")
  * `status` (Enum: `pending`, `confirmed`, `completed`, `cancelled`, `no_show`)
  * `reason_for_visit` (Text)
  * `created_at` (DateTime, UTC)

* **`queue_tickets`**:
  * `id` (Integer / UUID, PK)
  * `ticket_number` (String, e.g. "Q-101", indexed)
  * `patient_id` (FK -> `patients.id`)
  * `doctor_id` (FK -> `doctors.id`)
  * `appointment_id` (FK -> `appointments.id`, nullable for walk-in patients)
  * `status` (Enum: `waiting`, `called`, `in_consultation`, `completed`, `cancelled`)
  * `priority` (Enum: `normal`, `priority_senior_pwd`, `emergency`)
  * `issued_at` (DateTime, UTC)
  * `called_at` (DateTime, nullable)
  * `completed_at` (DateTime, nullable)

* **`prescriptions`**:
  * `id` (Integer / UUID, PK)
  * `patient_id` (FK -> `patients.id`)
  * `doctor_id` (FK -> `doctors.id`)
  * `appointment_id` (FK -> `appointments.id`, nullable)
  * `diagnosis` (Text)
  * `clinical_notes` (Text)
  * `medications` (JSON array: `[{"drug_name": "Amoxicillin", "dosage": "500mg", "frequency": "TID", "duration": "7 days", "instructions": "After meals"}]`)
  * `qr_code_hash` (String, unique verification token)
  * `created_at` (DateTime, UTC)

* **`invoices`**:
  * `id` (Integer / UUID, PK)
  * `receipt_number` (String, unique, indexed, e.g. "REC-2026-001")
  * `patient_id` (FK -> `patients.id`)
  * `queue_ticket_id` (FK -> `queue_tickets.id`, nullable)
  * `consultation_fee` (Numeric(10, 2))
  * `medication_fee` (Numeric(10, 2))
  * `other_fees` (Numeric(10, 2))
  * `discount_amount` (Numeric(10, 2))
  * `total_amount` (Numeric(10, 2))
  * `payment_method` (Enum: `cash`, `credit_card`, `debit_card`, `qr_ewallet`)
  * `payment_status` (Enum: `unpaid`, `paid`, `refunded`)
  * `paid_at` (DateTime, nullable)
  * `created_at` (DateTime, UTC)

* **`patient_feedback`**:
  * `id` (Integer / UUID, PK)
  * `patient_id` (FK -> `patients.id`)
  * `doctor_id` (FK -> `doctors.id`, nullable)
  * `rating` (Integer, 1 to 5)
  * `tags` (JSON array of selected badges: e.g. `["Wait Time", "Doctor Care"]`)
  * `comment_text` (Text)
  * `sentiment_label` (Enum: `positive`, `neutral`, `negative`)
  * `sentiment_score` (Float, range -1.0 to +1.0)
  * `flagged_critical` (Boolean, default False; true if score < -0.3 or rating <= 2)
  * `created_at` (DateTime, UTC)

* **`chat_messages`**:
  * `id` (Integer / UUID, PK)
  * `session_id` (String, indexed)
  * `sender_id` (FK -> `users.id`, nullable for guest inquiries)
  * `sender_name` (String)
  * `sender_role` (Enum: `patient`, `staff`, `bot`)
  * `message_text` (Text)
  * `is_bot_reply` (Boolean, default False)
  * `created_at` (DateTime, UTC)

---

## 4. Subsystems & User Role Portals

### 4.1 Patient Experience (Mobile-First)
* **Registration & Profile**: Self-registration with phone/email and essential health background.
* **Appointment Booking**: Wizard interface selecting clinic specialty, doctor, date, available time slot, and reason for consultation.
* **Live Queue Tracker**:
  * Shows assigned ticket, currently called ticket, count of patients ahead, and estimated wait calculation.
  * Real-time WebSocket connection rings an audio/visual chime when called to consultation room.
* **Feedback Form**: Star rating, feedback categories, text review, with instant sentiment feedback preview upon submission.

### 4.2 Doctor Portal (Tablet & Mobile Optimized)
* **Daily Schedule Viewer**:
  * Interactive touch timeline displaying today's appointments, walk-ins, cancellations, and completed visits.
* **Electronic Medical Records (EMR)**:
  * Patient history summary, past visit chronology, current allergies, and diagnosis entry form.
* **Digital Prescription Generator**:
  * Quick-add medication selector with dosage, route, frequency, and instructions.
  * Instant generation of digital e-prescription with QR verification code and printable format.

### 4.3 Clinic Staff Console
* **Queue Management Console**:
  * Front-desk controls to "Call Ticket", "Mark In-Consultation", "Complete", or "Mark No-Show".
  * Public TV Waiting Room display view at `/display`.
* **Walk-in Registration**:
  * High-speed intake modal for non-booked patients, auto-issuing the next sequential queue ticket.
* **Billing & Invoicing**:
  * Aggregates consultation fees and prescription medicines into an itemized bill.
  * Records payment type (Cash, Card, QR Code) and generates printable/scannable receipt.

### 4.4 Live Chat Box & Automated FAQ Fallback
* Floating widget available across all patient screens.
* Two-way real-time messaging between patient and reception staff.
* Automatic canned answers for clinic hours, location, emergency instructions, and appointment policies when staff is offline.

### 4.5 Sentiment Analysis & Analytics Dashboard
* **VADER NLP Engine**: Scores all feedback text into Polarity (-1.0 to 1.0) and Sentiment Class.
* **Clinic Dashboard**:
  * Net Sentiment Score (NSS), average ratings, sentiment breakdown percentages.
  * Highlighted "Urgent Service Recovery" queue for negative reviews.

---

## 5. Deployment Plan A: Free Cloud / Interactive Online Demo

**Target**: Instant public online URL on free tier hosting (Render, Railway, or Fly.io) with zero infrastructure expense.

### Components
1. **Containerized Packaging**:
   * Single lightweight Docker image (`python:3.11-slim`).
   * No node/npm runtime required in deployment.
2. **Storage**:
   * SQLite with WAL (`PRAGMA journal_mode=WAL;`) stored in `/data/clinic.db` on a mounted persistent volume.
3. **WebSockets**:
   * Direct in-memory connection manager handling active patient and staff WebSocket connections.
4. **Auto-Seeding**:
   * Automatic database initialization on startup with demo doctors, staff, upcoming appointments, and sample queue tickets.
   * One-click demo login buttons for rapid reviewer evaluation.
5. **Configuration Files Provided**:
   * `Dockerfile`: Container definition.
   * `Procfile`: Web process definition (`web: uvicorn main:app --host 0.0.0.0 --port $PORT`).
   * `render.yaml`: Infrastructure-as-code for Render blueprint deployment.

---

## 6. Deployment Plan B: Real-World Clinical Production & Scaling

**Target**: Enterprise-grade, HIPAA/GDPR-compliant clinical production deployment for high-volume multi-location clinics.

### Architecture & Components
1. **Database Layer**:
   * Managed **PostgreSQL 16+** (AWS RDS Aurora or Supabase) with Multi-AZ redundancy and automated point-in-time recovery.
   * Read-replicas for heavy analytical queries (e.g. sentiment reporting and billing reconciliation).
2. **Real-Time Scaling with Redis Pub/Sub**:
   * Redis 7+ cluster backing FastAPI WebSocket connections via `broadcaster` or `redis-py`.
   * Enables horizontal scaling across multiple container instances (AWS ECS or Kubernetes) while ensuring queue announcements and chat messages reach connected patients regardless of which server instance handles their socket.
3. **Security & Regulatory Compliance**:
   * **TLS 1.3** end-to-end encryption with HSTS and Cloudflare WAF.
   * **Database Encryption**: AES-256 encryption at rest for patient records and EMR notes.
   * **Audit Logging Table**: Immutable log recording `user_id`, `patient_id`, `action` (`VIEW_EMR`, `UPDATE_DIAGNOSIS`, `ISSUE_PRESCRIPTION`), `ip_address`, and `timestamp`.
   * **Role-Based Token Authentication**: 15-minute access tokens with rotating refresh tokens in secure HTTP-only cookies and optional 2FA for medical staff.
4. **External Healthcare Integrations**:
   * **SMS / WhatsApp Gateway**: Twilio or Sinch for automatic queue notifications (*"Your turn is coming up in 2 tickets. Please proceed to Room 3"*).
   * **Payment Processing**: Stripe or local QR payment gateway webhook integration for instant invoice payment reconciliation.
   * **Pharmacy Integration**: HL7 / FHIR standard export for digital prescriptions.

---

## 7. Verification & Quality Gates

* **Unit Tests**:
  * Role authentication and RBAC boundary enforcement.
  * Appointment scheduling conflict prevention.
  * Queue numbering sequencing and state transitions.
  * Sentiment score classification thresholds.
* **Integration Tests**:
  * End-to-end patient booking -> queue check-in -> doctor consultation -> prescription -> billing flow.
  * WebSocket broadcast delivery.
* **Performance Benchmark**:
  * Sub-50ms API response times for queue status polling/websocket messages under 500 concurrent connections.
