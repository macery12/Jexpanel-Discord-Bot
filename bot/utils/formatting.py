"""Formatting utilities for displaying server information."""
from __future__ import annotations


def format_bytes(n: int | None) -> str:
    """Format bytes into human-readable string (B, KiB, MiB, GiB, TiB)."""
    if not n:
        return "0 B"
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    i = 0
    f = float(n)
    while f >= 1024.0 and i < len(units) - 1:
        f /= 1024.0
        i += 1
    if i >= 2:
        return f"{f:.2f} {units[i]}"
    return f"{f:.1f} {units[i]}"


def format_memory_usage(used_bytes: int, limit_mib: int | None) -> tuple[str, float | None]:
    """Format memory usage as 'used / limit (percentage)' and return the percentage."""
    used_s = format_bytes(int(used_bytes or 0))
    if not limit_mib or limit_mib <= 0:
        return f"{used_s} / ∞", None
    limit_bytes = int(limit_mib) * 1024 * 1024
    lim_s = format_bytes(limit_bytes)
    pct = (used_bytes / limit_bytes * 100.0) if limit_bytes > 0 else None
    return f"{used_s} / {lim_s} ({pct:.0f}%)", pct


def format_progress_bar(percentage: float | None, length: int = 10) -> str:
    """Create a visual progress bar using Unicode block characters."""
    if percentage is None:
        return "▱" * length
    pct = max(0.0, min(100.0, percentage))
    filled = int((pct / 100.0) * length)
    empty = length - filled
    return "▰" * filled + "▱" * empty


def get_status_color(power: str, suspended: bool) -> int:
    """Return embed color based on server status."""
    if suspended:
        return 0x95A5A6  # Gray for suspended
    power_lower = power.lower()
    if power_lower in ("running", "online"):
        return 0x2ECC71  # Green for running
    elif power_lower in ("starting", "stopping"):
        return 0xF39C12  # Orange for transitioning
    elif power_lower in ("offline", "stopped"):
        return 0xE74C3C  # Red for offline
    else:
        return 0x3498DB  # Blue for unknown


def format_uptime(ms: int | None) -> str:
    """Format uptime in milliseconds to a human-readable string."""
    if not ms or ms <= 0:
        return "—"
    s = int(ms // 1000)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    if not parts: parts.append(f"{s}s")
    return " ".join(parts)
