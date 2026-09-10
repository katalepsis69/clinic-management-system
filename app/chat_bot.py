"""AI & FAQ Bot Engine for Clinic Assistant with Multi-Key Rotation and Bilingual Support."""

import logging
from app.config import get_settings

logger = logging.getLogger(__name__)

FAQ_RULES = [
    (
        ["emergency", "urgent", "ambulance", "severe", "critical", "911", "sakuna", "malubha", "ospital", "delikado"],
        "For severe life-threatening emergencies, please call 911 or proceed immediately to the nearest hospital Emergency Room. / Para sa malulubhang emergency, tumawag agad sa 911 o pumunta sa pinakamalapit na Emergency Room."
    ),
    (
        ["hours", "opening", "open", "time", "schedule", "close", "closing", "oras", "bukas", "sarado", "kailan bukas", "anong oras"],
        "Our clinic is open Monday to Saturday from 8:00 AM to 6:00 PM. Emergency walk-ins are accepted anytime during open hours. (Bukas po kami Lunes hanggang Sabado, 8:00 AM - 6:00 PM)."
    ),
    (
        ["book", "appointment", "reserve", "slot", "checkup", "magpa-book", "magpa-checkup", "magpa-doktor", "magpa-sched"],
        "You can book an appointment in the Patient Portal under 'Book Appointment'. Choose your doctor and preferred time slot! (Maaari po kayong mag-book sa Patient Portal sa ilalim ng 'Book Appointment'.)"
    ),
    (
        ["location", "address", "where", "directions", "find", "map", "saan", "lugar", "direksyon", "nasaan", "paano pumunta"],
        "We are located at 123 Healthcare Blvd, Suite 400, Medical Arts Tower. Parking is available on Level B1. (Matatagpuan po kami sa 123 Healthcare Blvd, Suite 400, Medical Arts Tower.)"
    ),
    (
        ["doctor", "specialist", "cardiologist", "physician", "doktor", "espesyalista", "manggagamot", "pediatrician"],
        "We have specialists in Cardiology, Pediatrics, General Medicine, and Orthopedics. View their profiles in the booking tab. (May mga espesyalista po kami sa Cardiology, Pediatrics, General Medicine, at Orthopedics.)"
    ),
]

SYSTEM_PROMPT = """You are the AI Front Desk & Healthcare Assistant for MediFlow Clinic.
- Opening Hours: Monday to Saturday, 8:00 AM to 6:00 PM.
- Location: 123 Healthcare Blvd, Suite 400, Medical Arts Tower. Parking on Level B1.
- Specialties: Cardiology, Pediatrics, General Medicine, and Orthopedics.
- Appointments: Bookable online in the Patient Portal under 'Book Appointment'.
- Medical Knowledge: You can explain general medical concepts, wellness guidance, anatomy, common symptoms, and preventive health tips clearly and empathetically.
- Medical Safety & Ethical Boundaries: Never prescribe medications, suggest exact pharmaceutical dosages, or provide definitive diagnostic verdicts. Always include a brief reminder that this is educational and the patient should consult a clinic doctor for personalized medical evaluation.
- Emergencies: For life-threatening symptoms (chest pain, severe breathlessness, profuse bleeding, stroke signs), urgently instruct calling 911 or proceeding to the nearest emergency room.
- Language & Tone: Match the patient's language dynamically. If the patient writes in Tagalog or Taglish, reply in warm, respectful Filipino/Taglish using polite honorifics ('po' / 'opo'). If in English, reply in polite, empathetic English. Keep responses concise (2 to 4 sentences)."""


class KeyRotationPool:
    """Manages rotation across multiple free Gemini API keys upon quota/rate limit exhaustion."""

    def __init__(self):
        self._current_index = 0

    def get_keys(self) -> list[str]:
        return get_settings().get_gemini_keys()

    def get_current_key(self) -> str:
        keys = self.get_keys()
        if not keys:
            return ""
        self._current_index = self._current_index % len(keys)
        return keys[self._current_index]

    def rotate_key(self) -> str:
        keys = self.get_keys()
        if not keys:
            return ""
        self._current_index = (self._current_index + 1) % len(keys)
        logger.info("Rotated to Gemini API key index %d of %d", self._current_index + 1, len(keys))
        return keys[self._current_index]


key_pool = KeyRotationPool()


def _get_matching_faq(message: str):
    msg_lower = str(message).lower()
    for keywords, response in FAQ_RULES:
        if any(k in msg_lower for k in keywords):
            return response
    return None


def _get_faq_response(message: str) -> str:
    match = _get_matching_faq(message)
    if match:
        return match
    # Ponytail: polite fallback if query neither matches FAQ nor succeeds with LLM
    msg_lower = str(message).lower()
    if any(k in msg_lower for k in ["salamat", "kamusta", "ano", "paano", "saan", "bakit"]):
        return "Salamat po sa inyong mensahe. Natanggap na po ng aming front desk receptionist ang inyong inquiry at tutugon po kami agad. Kung emergency po, tumawag sa 555-0100 o 911."
    return "Thank you for messaging. A clinic receptionist has received your inquiry and will reply shortly. If urgent, please call our front desk at 555-0100."


def get_bot_response(message: str) -> str:
    """Return intelligent Gemini AI response with key rotation pool and fallback to FAQ rules."""
    if not message or not str(message).strip():
        return _get_faq_response(message)

    # Fast-path deterministic clinic FAQ before external LLM call to save quota & latency
    faq_match = _get_matching_faq(message)
    if faq_match:
        return faq_match

    keys = key_pool.get_keys()
    if not keys:
        return _get_faq_response(message)

    settings = get_settings()
    model_name = settings.GEMINI_MODEL or "gemini-2.5-flash"

    # Try keys in rotation pool (up to number of configured keys)
    attempts = 0
    max_attempts = len(keys)

    while attempts < max_attempts:
        active_key = key_pool.get_current_key()
        if not active_key:
            break

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=active_key)
            chat = client.chats.create(
                model=model_name,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.7,
                    max_output_tokens=350,
                ),
            )
            response = chat.send_message(str(message).strip())
            if response.text and response.text.strip():
                return response.text.strip()
            break
        except Exception as exc:
            err_str = str(exc).lower()
            # If rate limited (429 / RESOURCE_EXHAUSTED / quota exceeded), rotate key immediately and retry
            if any(q in err_str for q in ["429", "resource_exhausted", "quota", "ratelimit", "exhausted"]):
                logger.warning("Gemini API key exhausted/rate limited. Rotating key pool: %s", exc)
                key_pool.rotate_key()
                attempts += 1
            else:
                logger.exception("Gemini API error with model %s: %s", model_name, exc)
                # Rotate for next request and fall back
                key_pool.rotate_key()
                break

    return _get_faq_response(message)
