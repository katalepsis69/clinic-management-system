from app.crypto_sign import generate_keypair, sign_prescription_data, verify_prescription_signature

def test_signature_roundtrip():
    private_pem, public_pem = generate_keypair()
    data = "RX-2026-001|Patient-42|Amoxicillin-500mg"
    
    signature = sign_prescription_data(data, private_pem)
    assert signature is not None
    assert verify_prescription_signature(data, signature, public_pem) is True
    assert verify_prescription_signature("tampered-data", signature, public_pem) is False
