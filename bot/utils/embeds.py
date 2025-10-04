import discord

def status_embed(*, name: str, uuid: str, node: str | None, allocation: str | None, power: str | None, stats: dict | None) -> discord.Embed:
    e = discord.Embed(title=f"{name}", description=f"`{uuid}`")
    if power:
        e.add_field(name="Power", value=power, inline=True)
    if stats:
        cpu_abs = stats.get('cpu_absolute', 0)
        mem_b = stats.get('memory_bytes', 0)
        disk_b = stats.get('disk_bytes', 0)
        net = stats.get('network', {}) or {}
        e.add_field(name="CPU", value=f"{cpu_abs:.1f}%", inline=True)
        e.add_field(name="Memory", value=f"{mem_b/1024/1024:.1f} MiB", inline=True)
        e.add_field(name="Disk", value=f"{disk_b/1024/1024:.1f} MiB", inline=True)
        e.add_field(name="Net In/Out", value=f"{(net.get('rx_bytes',0))/1024/1024:.1f} / {(net.get('tx_bytes',0))/1024/1024:.1f} MiB", inline=True)
    if node:
        e.add_field(name="Node", value=node, inline=True)
    if allocation:
        e.add_field(name="Allocation", value=allocation, inline=True)
    return e
