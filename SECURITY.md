# Security Documentation

## API Key Storage Security

This bot implements industry-standard best practices for storing user API keys securely. This document outlines the security mechanisms in place.

### Overview

User API keys (Pterodactyl panel tokens) are stored encrypted in the database using a multi-layered security approach:

1. **Per-User Key Derivation** using Argon2id
2. **AES-256-GCM Authenticated Encryption**
3. **Additional Authenticated Data (AAD)** binding
4. **Random salts** per credential
5. **Key versioning** for rotation support

### Security Architecture

#### 1. Key Derivation with Argon2id

Each user's API keys are encrypted with a unique encryption key derived specifically for that user:

```
User-Specific Key = Argon2id(
    secret = SHA-256(master_key + discord_user_id),
    salt = random_16_bytes,
    time_cost = 3,
    memory_cost = 64MB,
    parallelism = 4
)
```

**Why Argon2id?**
- **OWASP recommended** for key derivation
- **Memory-hard**: Resistant to GPU/ASIC attacks
- **Side-channel resistant**: Hybrid design (Argon2i + Argon2d)
- **Configurable cost**: Can increase security as hardware improves

**Benefits:**
- Each user has a unique encryption key
- Compromising one user's key doesn't affect others
- Prevents rainbow table attacks via random salts
- Makes brute-force attacks computationally infeasible

#### 2. AES-256-GCM Encryption

After key derivation, tokens are encrypted using AES-256-GCM:

```
Ciphertext = AES-256-GCM.encrypt(
    key = user_specific_key,
    nonce = random_12_bytes,
    plaintext = api_token,
    aad = discord_user_id|panel_url|key_version
)
```

**Why AES-256-GCM?**
- **NIST approved** encryption standard
- **Authenticated encryption**: Detects tampering
- **Industry standard**: Used by TLS, Signal, WhatsApp
- **256-bit key**: Maximum security level

**Benefits:**
- Data confidentiality (encryption)
- Data integrity (authentication)
- Prevents tampering detection
- Random nonce prevents replay attacks

#### 3. Additional Authenticated Data (AAD)

The AAD binds the encrypted token to specific context:

```
AAD = discord_user_id|panel_url|key_version
```

**Benefits:**
- Prevents moving encrypted tokens between users
- Prevents using tokens for different panels
- Detects unauthorized modifications
- Enables key version tracking

#### 4. Token Fingerprinting

Instead of showing actual tokens, we display a fingerprint:

```
Fingerprint = SHA-256(token)[-10:]
```

This allows users to identify their keys without exposing sensitive data.

### Security Properties

The implemented system provides:

1. **Confidentiality**: Tokens are encrypted, unreadable without the master key
2. **Integrity**: Tampering is detected via authenticated encryption
3. **Per-user isolation**: Each user has unique encryption keys
4. **Forward secrecy**: Old tokens remain secure if master key is rotated
5. **Defense in depth**: Multiple layers of security
6. **Resistance to attacks**:
   - Brute-force: Argon2id is computationally expensive
   - Rainbow tables: Random salts prevent pre-computation
   - Side-channel: Argon2id hybrid mode resists timing attacks
   - Replay: Random nonces prevent reuse
   - Tampering: AEAD detects modifications

### Key Management

#### Master Encryption Key

The master key must be:
- **256-bit (32 bytes)** exactly
- **Cryptographically random** (generated with `openssl rand -hex 32`)
- **Stored securely** in environment variables (never in code)
- **Base64 encoded** for safe storage

Generate a secure key:
```bash
openssl rand -hex 32
```

Add to `.env`:
```
ENCRYPTION_KEY=your_64_character_hex_key_here
```

#### Key Rotation

The system supports key versioning for rotation:

1. Generate a new master key
2. Update `DATA_KEY_VERSION` in config
3. Run migration command to re-encrypt existing credentials
4. Old key versions remain readable during transition

### Backward Compatibility

The system supports both legacy and enhanced encryption:

- **Legacy credentials** (no salt): Use simple AES-GCM with master key
- **New credentials** (with salt): Use Argon2id key derivation
- **Migration**: Admin command available to upgrade legacy credentials

### Database Schema

```sql
CREATE TABLE user_credentials (
    id INTEGER PRIMARY KEY,
    discord_user_id BIGINT NOT NULL,
    panel_url VARCHAR NOT NULL,
    label VARCHAR(8),
    ciphertext_b64 VARCHAR NOT NULL,      -- Encrypted token
    salt_b64 VARCHAR,                     -- Salt for key derivation
    key_version INTEGER DEFAULT 1,        -- For key rotation
    token_fingerprint VARCHAR(64),        -- SHA-256 fingerprint
    is_default BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP,
    last_verified_at TIMESTAMP,
    last_used_at TIMESTAMP,
    revoked BOOLEAN DEFAULT FALSE
);
```

### Security Best Practices for Deployment

1. **Environment Security**
   - Never commit `.env` files
   - Use secure secret management (e.g., Docker secrets, Kubernetes secrets)
   - Rotate encryption keys periodically
   - Monitor for unauthorized access

2. **Database Security**
   - Use encrypted connections (SSL/TLS)
   - Restrict database access
   - Regular backups with encryption
   - Monitor for suspicious queries

3. **Access Control**
   - Limit admin role assignments
   - Audit admin actions
   - Use ephemeral responses for sensitive data
   - Implement rate limiting

4. **Monitoring**
   - Log failed decryption attempts
   - Alert on unusual access patterns
   - Track credential age and usage
   - Automatic purging of old credentials

### Threat Model

**What this protects against:**
- ✅ Database compromise (tokens are encrypted)
- ✅ Insider threats (per-user keys prevent bulk decryption)
- ✅ Brute-force attacks (Argon2id is expensive to compute)
- ✅ Rainbow tables (random salts per credential)
- ✅ Data tampering (authenticated encryption detects changes)
- ✅ Replay attacks (random nonces per encryption)
- ✅ Side-channel attacks (Argon2id is resistant)

**What this does NOT protect against:**
- ❌ Compromised master encryption key (rotate immediately if suspected)
- ❌ Compromised bot process memory (tokens are decrypted in memory when used)
- ❌ Stolen Discord accounts (users should enable 2FA)
- ❌ Compromised panel (users should use limited-scope API keys)

### Compliance

This implementation follows:
- **OWASP** cryptographic storage guidelines
- **NIST** approved algorithms (AES-256, SHA-256)
- **Industry standards** for key derivation (Argon2)
- **Best practices** for secret management

### References

- [OWASP Cryptographic Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html)
- [Argon2 RFC 9106](https://www.rfc-editor.org/rfc/rfc9106.html)
- [NIST SP 800-38D (GCM)](https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication800-38d.pdf)
- [NIST SP 800-132 (Password-Based Key Derivation)](https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication800-132.pdf)

### Security Contact

If you discover a security vulnerability, please report it responsibly:
- Do not open a public issue
- Contact the repository maintainers directly
- Allow time for patching before disclosure

---

**Last Updated**: 2026-01-20  
**Security Version**: 2.0 (Enhanced Argon2id-based encryption)
