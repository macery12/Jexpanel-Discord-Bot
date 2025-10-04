# Pterodactyl Discord Bot

Production-ready Discord bot that integrates with **Jexpanel** Client (and optional Application) APIs.


> For production, we recommend using the **prebuilt container image** published by GitHub Actions to **GHCR**.

---

## Quick start (using prebuilt image)

### 1) Prepare `.env`
Copy `.env.example` to `.env` and fill values:
```bash
cp .env.example .env
# edit .env
```

Set **BOT_SYNC_SCOPE** and IDs:
- `BOT_SYNC_SCOPE` — set `GUILD` during development, switch to `GLOBAL` for production
- `DEV_GUILD_ID` — your test server ID (only when `BOT_SYNC_SCOPE=GUILD`)

### 2) Pull & run with Docker Compose
```bash
docker compose pull
docker compose up -d
```

### 3) Production mode
In `.env`:
```
BOT_SYNC_SCOPE=GLOBAL
DEV_GUILD_ID=
```
Then re-run:
```bash
docker compose pull && docker compose up -d
```

---

## Discord setup checklist

1. Create an application + bot in **Discord Developer Portal**.
2. Invite the bot with scopes:
   - `bot`, `applications.commands`
3. Minimal permissions in channels:
   - Send Messages, Embed Links, Attach Files, Use External Emojis
   - (Optional) Manage Messages if you want auto-delete behavior
4. Copy the **Bot Token** into `DISCORD_TOKEN` in `.env`.

---

## Jexpanel configuration

- **Per-user keys**: users link their own **Client API** keys with `/link` (keys encrypted at rest via `ENCRYPTION_KEY`).
- **Admin visibility** (`/panel_*`): set **Application API** key in `PTERO_APP_API_KEY` and your `PTERO_PANEL_URL`.
- Optional: `PTERO_CLIENT_API_KEY` as a fallback client key (per-user keys preferred).

---

## CI/CD — Multi-arch Docker builds (GHCR)

This repo includes `.github/workflows/docker-multiarch.yml` which builds **linux/amd64** and **linux/arm64** images and pushes to **GHCR** on:
- pushes to `main` → tags `latest` and `sha-<short>`
- pushes of tags `vX.Y.Z` → also tag `vX.Y.Z`

---

## Manual local run (optional)

If you want to run without GHCR:
```bash
docker build -t my-bot:dev .
docker run --env-file .env --name ptero-bot my-bot:dev
```
(For normal ops, prefer the prebuilt image flow above.)
