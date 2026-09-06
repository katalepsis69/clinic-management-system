"""AI & FAQ Bot Engine for Clinic Assistant."""

from app.config import get_settings

FAQ_RULES = [
    (["emergency", "urgent", "ambulance", "severe", "critical", "911"], "For severe life-threatening emergencies, please call 911 or proceed immediately to the nearest hospital Emergency Room."),
    (["hours", "opening", "open", "time", "schedule"], "Our clinic is open Monday to Saturday from 8:00 AM to 6:00 PM. Emergency walk-ins are accepted anytime during open hours."),
    (["book", "appointment", "reserve", "slot"], "You can book an appointment in the Patient Portal under 'Book Appointment'. Choose your doctor and preferred time slot!"),
    (["location", "address", "where", "directions"], "We are located at 123 Healthcare Blvd, Suite 400, Medical Arts Tower. Parking is available on Level B1."),
    (["doctor", "specialist", "cardiologist", "physician"], "We have specialists in Cardiology, Pediatrics, General Medicine, and Orthopedics. View their profiles in the booking tab.")
]

SYSTEM_PROMPT = """You are the AI Front Desk Assistant for MediFlow Clinic.
- Opening Hours: Monday to Saturday, 8:00 AM to 6:00 PM.
- Location: 123 Healthcare Blvd, Suite 400, Medical Arts Tower.
- Specialties: Cardiology, Pediatrics, General Medicine, and Orthopedics.
- Appointments: Bookable in the Patient Portal under 'Book Appointment'.
- Medical Safety: Never prescribe medicines or diagnose severe illnesses. For emergencies, tell patient to call 911 or visit ER immediately.
- Tone: Polite, empathetic, concise (1-3 sentences)."""


def _get_faq_response(message: str) -> str:
    msg_lower = str(message).lower()
    for keywords, response in FAQ_RULES:
        if any(k in msg_lower for k in keywords):
            return response
    return "Thank you for messaging. A clinic receptionist has received your inquiry and will reply shortly. If urgent, please call our front desk at 555-0100."


def get_bot_response(message: str) -> str:
    """Return intelligent Gemini AI response with fallback to FAQ rules."""
    if not message or not str(message).strip():
        return "Thank you for messaging. A clinic receptionist has received your inquiry and will reply shortly. If urgent, please call our front desk at 555-0100."

    # Fast-path for critical emergency keywords
    msg_lower = str(message).lower()
    if any(k in msg_lower for k in ["911", "ambulance", "emergency", "severe chest pain", "can't breathe"]):
        return "For severe life-threatening emergencies, please call 911 or proceed immediately to the nearest hospital Emergency Room."

    settings = get_settings()
    api_key = settings.GEMINI_API_KEY.strip() if settings.GEMINI_API_KEY else ""

    if api_key:
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key)
            chat = client.chats.create(
                model="gemini-2.5-flash",
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.7,
                    max_output_tokens=300,
                ),
            )
            response = chat.send_message(str(message).strip())
            if response.text and response.text.strip():
                return response.text.strip()
        except Exception:
            # ponytail: fallback to static FAQ when offline, quota exceeded, or key invalid
            pass

    return _get_faq_response(message)
