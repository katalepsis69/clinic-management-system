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
