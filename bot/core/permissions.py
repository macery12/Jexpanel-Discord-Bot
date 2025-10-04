import re
import discord
from ..config import settings

SERVER_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

def has_admin_role(inter: discord.Interaction) -> bool:
    if not inter.guild or not isinstance(inter.user, discord.Member):
        return False
    member: discord.Member = inter.user
    if inter.guild.owner_id == member.id:
        return True
    if getattr(member.guild_permissions, "administrator", False):
        return True
    allowed = set(settings.admin_role_ids)
    if not allowed:
        return False
    return any(role.id in allowed for role in member.roles)
