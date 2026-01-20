from __future__ import annotations

import base64
import hashlib
import os
import secrets
from typing import Tuple

from argon2 import PasswordHasher
from argon2.low_level import Type, hash_secret_raw
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import settings


# Argon2 parameters for key derivation (OWASP recommended)
# These provide strong protection against brute-force attacks
ARGON2_TIME_COST = 3      # Number of iterations
ARGON2_MEMORY_COST = 65536  # Memory in KiB (64 MB)
ARGON2_PARALLELISM = 4    # Number of parallel threads
ARGON2_HASH_LEN = 32      # Output length in bytes (256 bits)
ARGON2_SALT_LEN = 16      # Salt length in bytes (128 bits)


def _aad(discord_user_id: int, panel_url: str, key_version: int = 1) -> bytes:
    """
    Create Additional Authenticated Data for AES-GCM encryption.
    Includes user ID, panel URL, and key version for enhanced security.
    """
    return f"{discord_user_id}|{panel_url}|v{key_version}".encode("utf-8")


def _aad_legacy(discord_user_id: int, panel_url: str) -> bytes:
    """
    Legacy AAD format without key version.
    Used only for backward compatibility with old encrypted credentials.
    """
    return f"{discord_user_id}|{panel_url}".encode("utf-8")


def generate_salt() -> bytes:
    """
    Generate a cryptographically secure random salt for key derivation.
    Returns 16 bytes (128 bits) of randomness.
    """
    return secrets.token_bytes(ARGON2_SALT_LEN)


def derive_user_key(discord_user_id: int, master_key: bytes, salt: bytes) -> bytes:
    """
    Derive a user-specific encryption key using Argon2id.
    
    This creates a unique encryption key for each user by combining:
    - Master encryption key (from environment)
    - Discord user ID (unique per user)
    - Random salt (stored per credential)
    
    Argon2id is recommended by OWASP for key derivation as it's resistant to:
    - GPU cracking attacks
    - Side-channel attacks
    - Memory-hard (expensive to crack)
    
    Args:
        discord_user_id: The Discord user's unique ID
        master_key: The master encryption key from settings
        salt: Random salt (should be stored with the credential)
    
    Returns:
        32-byte derived key suitable for AES-256-GCM
    """
    # Combine master key with user ID to create a per-user secret
    user_secret = hashlib.sha256(
        master_key + str(discord_user_id).encode("utf-8")
    ).digest()
    
    # Use Argon2id to derive the final encryption key
    # This is computationally expensive, making brute-force attacks infeasible
    derived_key = hash_secret_raw(
        secret=user_secret,
        salt=salt,
        time_cost=ARGON2_TIME_COST,
        memory_cost=ARGON2_MEMORY_COST,
        parallelism=ARGON2_PARALLELISM,
        hash_len=ARGON2_HASH_LEN,
        type=Type.ID  # Argon2id (hybrid mode - best for most use cases)
    )
    
    return derived_key


def encrypt_token(discord_user_id: int, panel_url: str, token: str, salt: bytes | None = None) -> Tuple[str, str]:
    """
    Encrypt an API token using AES-256-GCM with per-user key derivation.
    
    Security features:
    - Per-user encryption key derived using Argon2id
    - Random nonce for each encryption (prevents replay attacks)
    - Authenticated encryption with additional data (AEAD)
    - Salt-based key derivation (prevents rainbow table attacks)
    
    Args:
        discord_user_id: The Discord user's unique ID
        panel_url: The panel URL (included in AAD for binding)
        token: The API token to encrypt
        salt: Optional salt (if None, generates new one)
    
    Returns:
        Tuple of (encrypted_token_b64, salt_b64)
    """
    # Generate or use provided salt
    if salt is None:
        salt = generate_salt()
    
    # Derive user-specific encryption key
    master_key = settings.bot_data_key
    user_key = derive_user_key(discord_user_id, master_key, salt)
    
    # Encrypt with AES-256-GCM
    aes = AESGCM(user_key)
    nonce = os.urandom(12)  # 96-bit nonce (recommended for GCM)
    
    # Include key version in AAD
    key_version = settings.data_key_version
    ct = aes.encrypt(
        nonce,
        token.encode("utf-8"),
        _aad(discord_user_id, panel_url, key_version)
    )
    
    # Combine nonce + ciphertext
    blob = nonce + ct
    encrypted_b64 = base64.b64encode(blob).decode("utf-8")
    salt_b64 = base64.b64encode(salt).decode("utf-8")
    
    return encrypted_b64, salt_b64


def decrypt_token(discord_user_id: int, panel_url: str, ciphertext_b64: str, salt_b64: str, key_version: int = 1) -> str:
    """
    Decrypt an API token using AES-256-GCM with per-user key derivation.
    
    Args:
        discord_user_id: The Discord user's unique ID
        panel_url: The panel URL (must match encryption)
        ciphertext_b64: Base64-encoded encrypted token
        salt_b64: Base64-encoded salt used during encryption
        key_version: The key version used during encryption
    
    Returns:
        Decrypted API token
    
    Raises:
        cryptography.exceptions.InvalidTag: If decryption fails (wrong key, tampered data, etc.)
    """
    # Decode inputs
    data = base64.b64decode(ciphertext_b64)
    salt = base64.b64decode(salt_b64)
    
    # Derive the same user-specific encryption key
    master_key = settings.bot_data_key
    user_key = derive_user_key(discord_user_id, master_key, salt)
    
    # Split nonce and ciphertext
    nonce, ct = data[:12], data[12:]
    
    # Decrypt with AES-256-GCM
    aes = AESGCM(user_key)
    pt = aes.decrypt(nonce, ct, _aad(discord_user_id, panel_url, key_version))
    
    return pt.decode("utf-8")


def fingerprint(token: str) -> str:
    """
    Create a non-reversible fingerprint of a token for display purposes.
    
    Uses SHA-256 and returns the last 10 characters for user identification
    without exposing the actual token.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[-10:]


# Legacy functions for backward compatibility with old encrypted credentials
def encrypt_token_legacy(discord_user_id: int, panel_url: str, token: str) -> str:
    """Legacy encryption without per-user key derivation. For backward compatibility only."""
    key = settings.bot_data_key
    aes = AESGCM(key)
    nonce = os.urandom(12)
    ct = aes.encrypt(nonce, token.encode("utf-8"), _aad_legacy(discord_user_id, panel_url))
    blob = nonce + ct
    return base64.b64encode(blob).decode("utf-8")


def decrypt_token_legacy(discord_user_id: int, panel_url: str, ciphertext_b64: str, key_version: int = 1) -> str:
    """Legacy decryption without per-user key derivation. For backward compatibility only."""
    key = settings.bot_data_key
    data = base64.b64decode(ciphertext_b64)
    nonce, ct = data[:12], data[12:]
    aes = AESGCM(key)
    pt = aes.decrypt(nonce, ct, _aad_legacy(discord_user_id, panel_url))
    return pt.decode("utf-8")
