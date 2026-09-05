"""Automated FAQ Rule-Based Bot Engine."""

FAQ_RULES = [
    (["emergency", "urgent", "ambulance", "severe", "critical", "911"], "For severe life-threatening emergencies, please call 911 or proceed immediately to the nearest hospital Emergency Room."),
    (["hours", "opening", "open", "time", "schedule"], "Our clinic is open Monday to Saturday from 8:00 AM to 6:00 PM. Emergency walk-ins are accepted anytime during open hours."),
    (["book", "appointment", "reserve", "slot"], "You can book an appointment in the Patient Portal under 'Book Appointment'. Choose your doctor and preferred time slot!"),
    (["location", "address", "where", "directions"], "We are located at 123 Healthcare Blvd, Suite 400, Medical Arts Tower. Parking is available on Level B1."),
    (["doctor", "specialist", "cardiologist", "physician"], "We have specialists in Cardiology, Pediatrics, General Medicine, and Orthopedics. View their profiles in the booking tab.")
]


def get_bot_response(message: str) -> str:
    """Analyze incoming message and return rule-based FAQ answer or default receptionist notice."""
    if not message or not str(message).strip():
        return "Thank you for messaging. A clinic receptionist has received your inquiry and will reply shortly. If urgent, please call our front desk at 555-0100."

    msg_lower = str(message).lower()
    for keywords, response in FAQ_RULES:
        if any(k in msg_lower for k in keywords):
            return response
    return "Thank you for messaging. A clinic receptionist has received your inquiry and will reply shortly. If urgent, please call our front desk at 555-0100."
