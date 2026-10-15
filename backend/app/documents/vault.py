from cryptography.fernet import Fernet


def encrypt_value(value: str, key: str) -> bytes:
    return Fernet(key.encode()).encrypt(value.encode())


def decrypt_value(blob: bytes, key: str) -> str:
    return Fernet(key.encode()).decrypt(blob).decode()
