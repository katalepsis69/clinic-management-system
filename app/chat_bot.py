"""AI & FAQ Bot Engine for Clinic Assistant with Multi-Key Rotation and Bilingual Support."""

import logging
import re
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

SYSTEM_PROMPT = """You are the AI Front Desk & Healthcare Assistant for Clinic Management System.
- Opening Hours: Monday to Saturday, 8:00 AM to 6:00 PM.
- Location: 123 Healthcare Blvd, Suite 400, Medical Arts Tower. Parking on Level B1.
- Specialties: Cardiology, Pediatrics, General Medicine, and Orthopedics.
- Appointments: Bookable online in the Patient Portal under 'Book Appointment'.
- General Medical Care & Symptoms: You can explain general medical concepts, wellness guidance, anatomy, common symptoms, and preventive health tips clearly and empathetically.
- Over-The-Counter (OTC) & General Knowledge Medications: You ARE PERMITTED to suggest widely recognized, safe over-the-counter (OTC) medicines and home care remedies that do not require a doctor's prescription (such as topical antifungal creams like clotrimazole, terbinafine, or miconazole for ringworm/buni; paracetamol or ibuprofen for mild fever/headaches; antacids for heartburn; oral rehydration salts for mild dehydration; saline nasal spray or antihistamines like cetirizine/loratadine for mild allergic rhinitis). Mention common generic names and popular recognized OTC examples (such as Canesten, Biogesic, etc.).
- Precautions & Safety Boundaries: Always remind the user to read and follow the product packaging and dosage instructions. Explicitly warn against using topical steroid creams (such as hydrocortisone, betamethasone, or generic 'BL cream') on fungal infections like ringworm/buni, as steroids worsen fungal conditions.
- Emergencies: For life-threatening symptoms (chest pain, severe breathlessness, profuse bleeding, stroke signs), urgently instruct calling 911 or proceeding to the nearest emergency room.
- STRICT FORMATTING RULE: NEVER output headings, labels, or bullet sections like '*Clinic Advice/Appointment:*', '*Appointment:*', '*Clinic Advice:*', or artificial promotional appointment callouts. Do NOT mechanically push clinic booking unless the user explicitly asks how to book or visit. Keep your advice completely natural, helpful, conversational, and direct.
- Language & Tone: Match the patient's language dynamically. If the patient writes in Tagalog or Taglish, reply in warm, respectful Filipino/Taglish using polite honorifics ('po' / 'opo'). If in English, reply in polite, empathetic English. Keep responses concise and easy to read (3 to 5 sentences or structured bullet points)."""


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


def classify_query_intent(message: str) -> str:
    """Classify user query into CLINIC_FAQ, WEB_SEARCH, or INTERNAL_LLM.

    - CLINIC_FAQ: Direct match with preset clinic operational rules (hours, location, doctors, booking).
    - WEB_SEARCH: Queries asking about local retail pharmacies (Mercury Drug, Watsons, etc.),
      current pricing/costs, retail availability, or recent health news/outbreaks.
    - INTERNAL_LLM: Medical concepts, pathology, symptoms, safe OTC drug classes, anatomy, home care.
    """
    if not message or not str(message).strip():
        return "CLINIC_FAQ"

    msg_lower = str(message).lower()

    # 1. Clinic operational FAQ rules (Deterministic Fast-Path)
    if _get_matching_faq(msg_lower) is not None:
        return "CLINIC_FAQ"

    # 2. Indicators requiring live Web Search grounding (Philippine pharmacies, pricing, availability)
    web_search_triggers = [
        "mercury drug", "watsons", "southstar", "rose pharmacy", "the generics pharmacy", "tgp",
        "botika", "parmasya", "pharmacy", "drugstore", "convenience store",
        "magkano", "presyo", "price", "pricing", "cost", "magkano po", "piso", "pesos",
        "mabibili ba", "saan mabibili", "available ba", "out of stock", "meron ba sa", "may tinda",
        "outbreak", "doh advisory", "epidemic", "balita ngayon", "alert", "fda warning", "recall"
    ]
    if any(trigger in msg_lower for trigger in web_search_triggers):
        return "WEB_SEARCH"

    # 3. Default for medical definitions, pathology, symptoms, OTC recommendations & home remedies
    return "INTERNAL_LLM"


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
    """Return intelligent Gemini AI response with category-based smart routing,
    multi-model fallback, key rotation, and FAQ fallback."""
    if not message or not str(message).strip():
        return _get_faq_response(message)

    category = classify_query_intent(message)

    # Category 1: Deterministic clinic FAQ fast-path (instant, free, 100% precision)
    if category == "CLINIC_FAQ":
        faq_match = _get_matching_faq(message)
        if faq_match:
            return faq_match

    keys = key_pool.get_keys()
    if not keys:
        return _get_faq_response(message)

    settings = get_settings()
    configured_model = settings.GEMINI_MODEL or "gemini-3-flash-preview"
    model_candidates = [configured_model, "gemini-3-flash-preview", "gemini-flash-latest", "gemini-3.6-flash"]
    seen = set()
    models = [m for m in model_candidates if not (m in seen or seen.add(m))]

    enable_search = getattr(settings, "ENABLE_WEB_SEARCH", True)

    # Category 2 vs 3 Routing:
    # - WEB_SEARCH queries prioritize live Google Search grounding (with fallback to internal if quota exhausted)
    # - INTERNAL_LLM queries bypass web search directly for ~400ms speed, quota saving, and clean clinical focus
    if category == "WEB_SEARCH" and enable_search:
        search_options = [True, False]
    else:
        search_options = [False]

    attempts = 0
    max_attempts = len(keys)

    while attempts < max_attempts:
        active_key = key_pool.get_current_key()
        if not active_key:
            break

        for model_name in models:
            for use_search in search_options:
                try:
                    from google import genai
                    from google.genai import types

                    client = genai.Client(api_key=active_key)
                    tools = [types.Tool(google_search=types.GoogleSearch())] if use_search else None

                    # Disable thinking budget (budget=0) to cut latency from ~10s to ~1.8s and prevent
                    # invisible thought tokens from exhausting max_output_tokens and cutting off answers.
                    try:
                        cfg = types.GenerateContentConfig(
                            system_instruction=SYSTEM_PROMPT,
                            tools=tools,
                            temperature=0.7,
                            thinking_config=types.ThinkingConfig(thinking_budget=0),
                            max_output_tokens=1024,
                        )
                        chat = client.chats.create(model=model_name, config=cfg)
                        response = chat.send_message(str(message).strip())
                    except Exception as cfg_exc:
                        if "400" in str(cfg_exc) and "invalid_argument" in str(cfg_exc).lower():
                            cfg = types.GenerateContentConfig(
                                system_instruction=SYSTEM_PROMPT,
                                tools=tools,
                                temperature=0.7,
                                max_output_tokens=1024,
                            )
                            chat = client.chats.create(model=model_name, config=cfg)
                            response = chat.send_message(str(message).strip())
                        else:
                            raise cfg_exc

                    if response.text and response.text.strip():
                        cleaned_text = response.text.strip()
                        # Defensive sanitize: strip any robotic clinic advice headers
                        cleaned_text = re.sub(r'(?i)^\s*\*?\*?Clinic Advice/Appointment:?\*?\*?\s*', '', cleaned_text, flags=re.MULTILINE)
                        cleaned_text = re.sub(r'(?i)\n\s*\*?\*?Clinic Advice/Appointment:?\*?\*?\s*', '\n', cleaned_text).strip()
                        return cleaned_text
                except Exception as exc:
                    err_str = str(exc).lower()
                    # If web search grounding specifically threw 429/quota error, let loop retry without search
                    if use_search and any(q in err_str for q in ["429", "resource_exhausted", "quota"]):
                        logger.info(
                            "Web search grounding quota unavailable on model %s for category %s, falling back to internal knowledge: %s",
                            model_name, category, exc
                        )
                        continue
                    # If model failed with rate limit or demand spike, step to next candidate model
                    if any(q in err_str for q in ["429", "resource_exhausted", "quota", "ratelimit", "503", "unavailable", "404", "not_found"]):
                        logger.warning("Model %s failed (%s); trying fallback model...", model_name, exc)
                        break
                    logger.exception("Gemini API error on model %s: %s", model_name, exc)
                    break

        key_pool.rotate_key()
        attempts += 1

    return _get_faq_response(message)
