from __future__ import annotations
import os, base64, hashlib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from .config import settings

def _aad(discord_user_id: int, panel_url: str) -> bytes:
    return f"{discord_user_id}|{panel_url}".encode("utf-8")

def encrypt_token(discord_user_id: int, panel_url: str, token: str) -> str:
    key = settings.bot_data_key
    aes = AESGCM(key)
    nonce = os.urandom(12)
    ct = aes.encrypt(nonce, token.encode("utf-8"), _aad(discord_user_id, panel_url))
    blob = nonce + ct
    return base64.b64encode(blob).decode("utf-8")

def decrypt_token(discord_user_id: int, panel_url: str, ciphertext_b64: str) -> str:
    key = settings.bot_data_key
    data = base64.b64decode(ciphertext_b64)
    nonce, ct = data[:12], data[12:]
    aes = AESGCM(key)
    pt = aes.decrypt(nonce, ct, _aad(discord_user_id, panel_url))
    return pt.decode("utf-8")

def fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[-10:]
