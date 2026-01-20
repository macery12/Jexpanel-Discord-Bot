from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..crypto import (
    decrypt_token, 
    decrypt_token_legacy, 
    encrypt_token, 
    fingerprint,
    generate_salt
)
from ..db.models import UserCredential

TZUTC = UTC

def _to_naive_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(TZUTC).replace(tzinfo=None)

async def add_or_update_credential(s: AsyncSession, discord_user_id: int, panel_url: str, token: str, label: str | None = None) -> UserCredential:
    """
    Add or update a user credential with enhanced encryption.
    
    Uses Argon2id-based per-user key derivation for maximum security.
    """
    fp = fingerprint(token)
    
    # Use new encryption method with salt
    ct, salt_b64 = encrypt_token(discord_user_id, panel_url, token)

    res = await s.execute(select(UserCredential).where(
        (UserCredential.discord_user_id == discord_user_id) &
        (UserCredential.panel_url == panel_url)
    ))
    existing_for_panel = res.scalars().all()
    is_default = len(existing_for_panel) == 0

    cred = UserCredential(
        discord_user_id=discord_user_id,
        panel_url=panel_url,
        label=str(label) if label else None,
        ciphertext_b64=ct,
        salt_b64=salt_b64,  # Store salt for key derivation
        key_version=settings.data_key_version,
        token_fingerprint=fp,
        is_default=is_default,
        revoked=False,
    )
    s.add(cred)
    await s.commit()
    return cred

async def list_user_credentials(s: AsyncSession, user_id: int):
    res = await s.execute(select(UserCredential).where(UserCredential.discord_user_id == user_id))
    return list(res.scalars().all())

async def set_default_credential(s: AsyncSession, user_id: int, panel_url: str, label: str) -> int:
    await s.execute(update(UserCredential).where(
        (UserCredential.discord_user_id == user_id) & (UserCredential.panel_url == panel_url)
    ).values(is_default=False))
    res = await s.execute(select(UserCredential).where(
        (UserCredential.discord_user_id == user_id) & (UserCredential.panel_url == panel_url) & (UserCredential.label == str(label))
    ))
    cred = res.scalar_one_or_none()
    if not cred:
        return 0
    cred.is_default = True
    await s.commit()
    return 1

async def delete_credential(s: AsyncSession, user_id: int, panel_url: str, label: str | None) -> int:
    if label is None:
        res = await s.execute(select(UserCredential).where(
            (UserCredential.discord_user_id == user_id) & (UserCredential.panel_url == panel_url) & (UserCredential.is_default == True)
        ))
        cred = res.scalar_one_or_none()
        if not cred:
            return 0
        await s.delete(cred)
        await s.commit()
        return 1
    else:
        res = await s.execute(select(UserCredential).where(
            (UserCredential.discord_user_id == user_id) & (UserCredential.panel_url == panel_url) & (UserCredential.label == str(label))
        ))
        cred = res.scalar_one_or_none()
        if not cred:
            return 0
        await s.delete(cred)
        await s.commit()
        return 1

async def wipe_user_credentials(s: AsyncSession, user_id: int) -> int:
    res = await s.execute(select(UserCredential).where(UserCredential.discord_user_id == user_id))
    creds = res.scalars().all()
    count = len(creds)
    for c in creds:
        await s.delete(c)
    await s.commit()
    return count

async def wipe_all_credentials(s: AsyncSession) -> int:
    res = await s.execute(select(UserCredential))
    creds = res.scalars().all()
    count = len(creds)
    for c in creds:
        await s.delete(c)
    await s.commit()
    return count

async def get_user_token(s: AsyncSession, user_id: int, panel_url: str, prefer_label: str | None = None) -> str | None:
    """
    Retrieve and decrypt a user's API token.
    
    Supports both new (with salt) and legacy (without salt) encryption methods
    for backward compatibility.
    """
    from sqlalchemy import select
    q = select(UserCredential).where(
        (UserCredential.discord_user_id == user_id) & (UserCredential.panel_url == panel_url)
    )
    res = await s.execute(q)
    rows = res.scalars().all()
    if not rows:
        return None
    chosen = None
    if prefer_label:
        for r in rows:
            if r.label == str(prefer_label):
                chosen = r
                break
    if not chosen:
        chosen = next((r for r in rows if r.is_default), rows[0])
    
    # Update last used timestamp
    chosen.last_used_at = _to_naive_utc(datetime.now(UTC))
    await s.commit()
    
    # Decrypt using appropriate method based on presence of salt
    if chosen.salt_b64:
        # New encryption method with per-user key derivation
        return decrypt_token(
            user_id, 
            panel_url, 
            chosen.ciphertext_b64,
            chosen.salt_b64,
            chosen.key_version
        )
    else:
        # Legacy encryption method (backward compatibility)
        return decrypt_token_legacy(
            user_id, 
            panel_url, 
            chosen.ciphertext_b64,
            chosen.key_version
        )

async def purge_old_credentials(s: AsyncSession, days: int) -> int:
    cutoff = datetime.now(UTC)
    res = await s.execute(select(UserCredential))
    rows = res.scalars().all()
    to_delete = []
    for r in rows:
        last = r.last_used_at or r.created_at
        last = _to_naive_utc(last)
        if last is None:
            continue
        delta = cutoff - last
        if r.revoked or delta.days >= days:
            to_delete.append(r)
    for r in to_delete:
        await s.delete(r)
    await s.commit()
    return len(to_delete)

async def migrate_credential_to_new_encryption(s: AsyncSession, credential_id: int) -> bool:
    """
    Migrate a legacy credential to the new Argon2id-based encryption.
    
    This re-encrypts the token with per-user key derivation for enhanced security.
    
    Args:
        s: Database session
        credential_id: ID of the credential to migrate
    
    Returns:
        True if migration was successful, False if credential not found or already migrated
    """
    res = await s.execute(
        select(UserCredential).where(UserCredential.id == credential_id)
    )
    cred = res.scalar_one_or_none()
    
    if not cred:
        return False
    
    # Skip if already using new encryption
    if cred.salt_b64:
        return False
    
    try:
        # Decrypt with legacy method
        token = decrypt_token_legacy(
            cred.discord_user_id,
            cred.panel_url,
            cred.ciphertext_b64,
            cred.key_version
        )
        
        # Re-encrypt with new method
        new_ct, new_salt = encrypt_token(
            cred.discord_user_id,
            cred.panel_url,
            token
        )
        
        # Update credential
        cred.ciphertext_b64 = new_ct
        cred.salt_b64 = new_salt
        cred.key_version = settings.data_key_version
        
        await s.commit()
        return True
    except Exception:
        # If decryption fails, leave credential as-is
        return False

async def migrate_all_user_credentials(s: AsyncSession, user_id: int) -> int:
    """
    Migrate all of a user's credentials to the new encryption method.
    
    Returns the number of credentials successfully migrated.
    """
    res = await s.execute(
        select(UserCredential).where(
            (UserCredential.discord_user_id == user_id) &
            (UserCredential.salt_b64.is_(None))
        )
    )
    legacy_creds = res.scalars().all()
    
    migrated = 0
    for cred in legacy_creds:
        if await migrate_credential_to_new_encryption(s, cred.id):
            migrated += 1
    
    return migrated
