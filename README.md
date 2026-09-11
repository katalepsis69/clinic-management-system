# Clinic Management System

An intelligent, real-time healthcare clinic portal built with **FastAPI**, **SQLite/PostgreSQL**, and **Google Gemini AI**. Designed for seamless clinic operations, live queue management, and 24/7 bilingual patient triage.

---

## 🌟 Key Features

### 1. 🏥 Four Dedicated Operational Portals
- **Patient Portal**: Online appointment booking, profile & medical history management, live queue position tracker, and post-visit sentiment feedback.
- **Doctor Clinical Console**: Real-time consultation queue, patient EMRs, and digital prescription issuance with **SHA-256 HMAC cryptographic signatures** to prevent tampering.
- **Staff & Billing Desk**: Walk-in patient intake, automated queue calling, itemized invoicing, and instant payment receipt generation.
- **Sentiment & Experience Analytics**: Real-time VADER Natural Language Processing (NLP) analyzing patient visit reviews with Net Sentiment Score (NSS) tracking.

### 2. 📺 Public TV Waiting Display (/display)
- Zero-latency WebSocket broadcast for clinic waiting rooms.
- Shows current ticket being served with designated consultation room and upcoming queue numbers.
- Integrated audio chime announcements on ticket calls.

### 3. 🤖 AI Virtual Assistant & Smart Router
- **Adaptive 3-Tier Routing Engine**:
  - **🏥 Clinic FAQ Rules**: Instant, deterministic responses for operating hours, clinic address, and doctor specialties.
  - **🌐 Live Web Search Grounding**: Automatically searches real-time Philippine pharmacy availability (Mercury Drug, Watsons, TGP) and current prices when asked about store stock or retail costs.
  - **🧠 Direct Medical LLM Knowledge**: Fast (~400ms) clinical explanations of symptoms, disease mechanisms, and safe Over-The-Counter (OTC) remedies (e.g. Canesten/clotrimazole, Biogesic/paracetamol).
- **Multi-Key Failover Pool**: Automatic millisecond rotation across multiple Gemini API keys on rate limits (429 RESOURCE_EXHAUSTED).
- **Multi-Model Resiliency**: Automated fallback across gemini-3.6-flash → gemini-flash-latest → gemini-3-flash-preview.
- **Guest Access**: 5 free messages for unauthenticated guests before prompting sign-in.

---

## 🚀 Quick Start (Local Development)

### 1. Clone & Install Dependencies
`ash
git clone https://github.com/katalepsis69/clinic-management-system.git
cd clinic-management-system
python -m venv venv
source venv/bin/activate  # On Windows: .\venv\Scripts\activate
pip install -r requirements.txt
`

### 2. Configure Environment Variables
Copy .env.example to .env:
`ash
cp .env.example .env
`
Edit .env with your Gemini API keys:
`env
GEMINI_API_KEY=AIzaSy...
# Or multiple keys separated by comma for auto-failover:
GEMINI_API_KEYS=key1,key2,key3
GEMINI_MODEL=gemini-3.6-flash
ENABLE_WEB_SEARCH=true
`

### 3. Run Development Server
`ash
uvicorn app.main:app --reload
`
Access the application at http://localhost:8000.

---

## 🧪 Testing

Run the full automated test suite:
`ash
python -m pytest
`

---

## ☁️ Deployment on Render

This project is pre-configured for one-click deployment on [Render](https://render.com) via 
ender.yaml.

1. Connect your GitHub repository to Render.
2. Under **Environment Variables**, set:
   - GEMINI_API_KEY: Your Gemini API key(s). Supports comma-separated keys for auto-failover!
3. Deploy!
