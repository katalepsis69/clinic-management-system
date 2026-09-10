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
        # ponytail: log-based simulator in dev/staging; real Twilio REST dispatch when credentials configured
        if self.account_sid and self.auth_token:
            try:
                from twilio.rest import Client
                client = Client(self.account_sid, self.auth_token)
                client.messages.create(body=message_body, from_=self.from_phone, to=to_phone)
                return True
            except Exception as e:
                logger.error("Failed to send SMS via Twilio: %s", e)
                return False
        else:
            logger.info("[SMS SIMULATION] To: %s | Body: %s", to_phone, message_body)
            return True

notification_service = NotificationService()
