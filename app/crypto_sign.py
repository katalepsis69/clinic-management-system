import base64
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes, serialization

def generate_keypair():
    # ponytail: 2048-bit RSA + PSS standard for digital signatures; bump to 4096-bit if compliance mandates
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
