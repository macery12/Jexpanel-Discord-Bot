from __future__ import annotations
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from ..db.models import UserCredential
from ..crypto import encrypt_token, decrypt_token, fingerprint
from ..config import settings

TZUTC = timezone.utc

def _to_naive_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(TZUTC).replace(tzinfo=None)

async def add_or_update_credential(s: AsyncSession, discord_user_id: int, panel_url: str, token: str, label: str | None = None) -> UserCredential:
    fp = fingerprint(token)
    ct = encrypt_token(discord_user_id, panel_url, token)

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
                chosen = r; break
    if not chosen:
        chosen = next((r for r in rows if r.is_default), rows[0])
    chosen.last_used_at = _to_naive_utc(datetime.utcnow())
    await s.commit()
    return decrypt_token(user_id, panel_url, chosen.ciphertext_b64)

async def purge_old_credentials(s: AsyncSession, days: int) -> int:
    cutoff = datetime.utcnow()
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
