# Picasso Auto-Login System — Architecture Reference

**Created:** Build #121+ (2026-02-12)
**Status:** COMPLETE AND WORKING
**Last verified:** 118 fares returned via auto-obtained token

---

## Overview

The Picasso/Redbox flight search API uses session-based auth via a `redbox-session-token` cookie.
Previously this required manually logging into `cockpit.thegoodconsolidator.com`, running
`document.cookie` in the browser console, and pasting the token into `.env`. The auto-login system
eliminates this entirely — credentials go in `.env` once and the app manages token lifecycle forever.

---

## File Map

| File | Role |
|------|------|
| `picasso_auth.py` | **Core** — Token manager singleton, auth strategies, persistence |
| `picasso_client.py` | **Consumer** — Uses `token_manager.get_token()`, retry-on-401 |
| `search.py` | **Upstream** — Calls `search_with_picasso()` as priority path |
| `config.py` | Config class with `PICASSO_*` env var mappings |
| `.env` | Credentials (username, password, TOTP secret, Gmail IMAP) |
| `.picasso_token.json` | Persisted token (gitignored, auto-created) |
| `.gitignore` | Includes `.picasso_token.json` |
| `requirements.txt` | Includes `pyotp>=2.9.0` |

---

## Auth Strategy Chain

Strategies are tried in order; first success wins.

### Strategy A: Playwright + TOTP (Primary — ~15s)
```
1. Launch headless Chromium via Playwright
2. Navigate to cockpit.thegoodconsolidator.com
3. Keycloak redirects to login page (account.picassotravel.com)
4. Fill username + password, submit
5. Keycloak shows TOTP challenge ("enter code from authenticator app")
6. pyotp generates 6-digit TOTP code from PICASSO_TOTP_SECRET
7. Fill TOTP code, submit
8. Cockpit loads at /home/#/flight
9. Extract "redbox-session-token" cookie
10. Persist to .picasso_token.json
```

### Strategy B: Playwright + Email OTP via IMAP (Fallback — ~30s)
```
1. Same Playwright flow as Strategy A through step 4
2. Keycloak shows email OTP challenge (sends code to account email)
3. IMAP connects to Gmail (serenity22is@gmail.com) with App Password
4. Uses UIDNEXT snapshot to only check emails arriving AFTER login submit
5. Polls every 3s for up to 60s, filters by Keycloak sender address
6. Extracts 6-digit code from email body
7. Fills OTP code, submits
8. Same cookie extraction as Strategy A
```

### Fallback: Manual Token
```
Uses PICASSO_SESSION_TOKEN from .env (current behavior, no auto-refresh)
```

---

## Environment Variables

### Required (auto-login)
```bash
PICASSO_USERNAME=mysteskyrion@gmail.com      # Cockpit login email
PICASSO_PASSWORD=<password>                   # Cockpit password
PICASSO_TOTP_SECRET=MNVHOUDZMRVDANLJPFAWK3SXOAYEUV3W  # Base32, 32 chars
```

### Optional (email OTP fallback)
```bash
PICASSO_GMAIL_IMAP_USER=serenity22is@gmail.com  # Gmail account with IMAP access
PICASSO_GMAIL_APP_PASSWORD=<16-char-app-password>  # Google App Password (no spaces)
```

### Optional (manual fallback)
```bash
PICASSO_SESSION_TOKEN=<26-char-alphanumeric>  # From browser cookie, used if auto-login fails
```

### Existing (used by picasso_client.py)
```bash
PICASSO_REDBOX_URL=https://aerpackit.flightconex.de/redbox
PICASSO_AGENCY_ID=629818
PICASSO_BRANCH=PICL_707
PICASSO_COCKPIT_URL=https://cockpit.thegoodconsolidator.com
```

---

## Keycloak Account State

This is the current state of the Keycloak account at `account.picassotravel.com`.
If anything breaks, this is the reference for what the account should look like.

| Property | Value |
|----------|-------|
| Username | `mysteskyrion@gmail.com` |
| Email | `serenity22is@gmail.com` (changed from mysteskyrion) |
| Email verified | `true` |
| 2FA method | TOTP authenticator app (device: "MYSTES-AutoLogin") |
| Passkey | Deleted (was causing issues) |
| emailCodeEnabled | `false` (user-level preference, realm still enforces OTP) |
| Realm | `picasso-com` |
| ROPC client | `admin-cli` (requires `totp` parameter after TOTP registration) |

**Important**: Username and email are DIFFERENT. Username = login identity, email = where OTP codes go.

---

## Token Lifecycle

```
Startup
  └─ Load .picasso_token.json (if exists and <24h old)
       └─ Token valid? → Use it
       └─ Token expired/missing? → Auto-login
            └─ Strategy A succeeds? → Cache + persist + use
            └─ Strategy A fails? → Try Strategy B
            └─ Strategy B fails? → Use manual PICASSO_SESSION_TOKEN
            └─ All fail? → Raise error

During operation (picasso_client.py)
  └─ search_flights() gets 401/403
       └─ Call token_manager.invalidate()
       └─ Retry search (triggers fresh auto-login)
       └─ Still fails? → Return error to user
```

Token persistence format (`.picasso_token.json`):
```json
{
  "token": "pmcge6s9mn5thgtj470u1sbs5e",
  "obtained_at": 1739404800.0,
  "expires_at": 1739491200.0,
  "strategy": "A_playwright_totp"
}
```

---

## Public API (`picasso_auth.token_manager`)

| Method | Returns | Purpose |
|--------|---------|---------|
| `get_token()` | `str` | Get valid token (auto-refreshes if needed) |
| `invalidate()` | `None` | Force token refresh on next `get_token()` |
| `check_token_health()` | `dict` | Validates token against Redbox API, returns status |
| `get_status()` | `dict` | Token metadata (age, strategy, expiry) |
| `keycloak_get_jwt()` | `str` | Get Keycloak JWT for Account API operations |

---

## Integration Points

### picasso_client.py
```python
from picasso_auth import token_manager

class PicassoClient:
    @property
    def session_token(self):
        return token_manager.get_token()

    def search_flights(self, ...):
        # ... search logic ...
        # On 401: token_manager.invalidate() → retry
```

### search.py
```python
def search_global(...):
    # Priority: Picasso (via picasso_client) → Amadeus fallback
    results = search_with_picasso(origin, destination, date, ...)
```

---

## Troubleshooting

### Token stops working / 401 errors
1. Delete `.picasso_token.json` — forces fresh login on next search
2. Test manually: `python3 -c "from picasso_auth import token_manager; print(token_manager.get_token())"`
3. If auto-login fails, check if Keycloak login page changed (CSS selectors in picasso_auth.py)

### TOTP codes rejected
1. Verify `PICASSO_TOTP_SECRET` in `.env` is exactly 32 Base32 characters (A-Z, 2-7)
2. Check system clock sync (TOTP is time-based, 30s window)
3. Test: `python3 -c "import pyotp; print(pyotp.TOTP('MNVHOUDZMRVDANLJPFAWK3SXOAYEUV3W').now())"`

### Email OTP fallback not working
1. Keycloak emails go to `serenity22is@gmail.com` (NOT mysteskyrion)
2. Verify Gmail App Password: `python3 -c "import imaplib; m=imaplib.IMAP4_SSL('imap.gmail.com'); print(m.login('serenity22is@gmail.com','ojhguycigskatdjt'))"`
3. Ensure "IMAP access" is enabled in Gmail settings

### Need to change Keycloak 2FA
1. Get JWT: `token_manager.keycloak_get_jwt()`
2. Use Keycloak Account API: `GET /realms/picasso-com/account/credentials`
3. Delete TOTP credential, set up new one
4. Update `PICASSO_TOTP_SECRET` in `.env`

### Gmail accounts confusion
- `mysteskyrion@gmail.com` = Keycloak USERNAME (login identity)
- `serenity22is@gmail.com` = Keycloak EMAIL (where OTP codes go) + Gmail IMAP account
- These are SEPARATE Google accounts with SEPARATE inboxes
- App Password was created under the serenity22is Google account
- IMAP only works with serenity22is (that's where the App Password lives)

---

## Key Discoveries (from Build #121 session)

1. **Keycloak username ≠ email** — Changing the email doesn't change the login username
2. **emailCodeEnabled is user-level only** — Setting it to `false` doesn't disable realm-level OTP enforcement
3. **admin-cli ROPC requires `totp` after TOTP registration** — Must pass `totp` param in token request
4. **TOTP secret is per-setup-session** — Each "Set up authenticator" page generates a NEW secret; must extract and submit in the SAME browser session
5. **IMAP UIDNEXT pattern** — Use `mail.status("INBOX", "(UIDNEXT)")` before triggering OTP, then search `UID {uidnext}:*` to only check new emails (avoids scanning 142k+ unread)
6. **Playwright is NOT in Docker** — Auto-login runs on dev machines only; Render deployment uses manual token or pre-obtained token
7. **Token is 26-char alphanumeric** — Cookie name: `redbox-session-token`, set by Cockpit SSO redirect

---

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `pyotp` | >=2.9.0 | TOTP code generation |
| `playwright` | (existing) | Headless browser automation |
| `requests` | (existing) | HTTP for Keycloak API |

Playwright is already used by `google_flights_scraper.py` — no new browser dependency.

---

## Security Notes

- `.env` contains all credentials — NEVER commit (gitignored)
- `.picasso_token.json` contains session token — NEVER commit (gitignored)
- TOTP secret is equivalent to a password — treat with same care
- Gmail App Password grants full IMAP access — rotate if compromised
- All credentials are read from environment at module load time
