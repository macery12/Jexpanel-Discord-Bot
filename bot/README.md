# Bot Directory Structure

This directory contains the Discord bot implementation for Jexpanel integration.

## Directory Organization

```
bot/
├── main.py                 # Bot entry point and main Bot class
├── config.py              # Settings and configuration management
├── client/                # Pterodactyl Panel API clients
│   ├── ptero_rest.py     # REST API client for client endpoints
│   ├── ptero_ws.py       # WebSocket client for console/logs
│   └── ptero_app.py      # Application API client (admin features)
├── cogs/                  # Discord command handlers (slash commands)
│   ├── credentials.py    # User API key management (/link, /unlink, etc.)
│   ├── server.py         # Server operations (/list, /status, /console, etc.)
│   ├── admin.py          # Admin commands (/alias_set, etc.)
│   ├── app_admin.py      # Application API admin commands (/panel_nodes, etc.)
│   └── monitor.py        # Monitoring features (placeholder)
├── db/                    # Database models and session management
│   ├── models.py         # SQLAlchemy models (UserCredential, ServerAlias, etc.)
│   └── __init__.py       # Database engine and session factory
├── services/              # Business logic layer
│   └── credentials.py    # Credential management operations
└── utils/                 # Utility modules
    ├── crypto.py         # Encryption/decryption for API keys
    ├── permissions.py    # Permission checking utilities
    ├── formatting.py     # Display formatting helpers (bytes, uptime, etc.)
    ├── server_helpers.py # Server resolution and lookup helpers
    └── embeds.py         # Discord embed builders (legacy)
```

## Key Design Patterns

### Separation of Concerns

- **client/**: Low-level API communication with Pterodactyl panel
- **cogs/**: Discord command handlers that orchestrate features
- **services/**: Business logic independent of Discord
- **utils/**: Shared utility functions used across modules

### Database Access

- All database operations use async SQLAlchemy sessions
- Sessions created via `SessionLocal()` context manager from `db/__init__.py`
- Models defined in `db/models.py`

### Security

- User API keys encrypted at rest using AES-GCM (see `utils/crypto.py`)
- Encryption key loaded from environment variable
- Admin permissions enforced via `utils/permissions.py`

### Configuration

- Centralized in `config.py` using pydantic-settings
- Environment variables loaded from `.env` file
- Type-safe settings with validation

## Adding New Features

1. **New Discord command**: Add to appropriate cog in `cogs/`
2. **New business logic**: Add to `services/` directory
3. **New utility function**: Add to appropriate module in `utils/`
4. **New API client method**: Add to relevant client in `client/`
5. **New database model**: Add to `db/models.py`

## Running the Bot

See the main repository README for deployment instructions.
