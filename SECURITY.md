# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| latest 2.x minor    | :white_check_mark: |
| 1.6.6 ( EOL 2026-12-31 )  | :white_check_mark: |
| < 1.6.6 | :x:                |

> Be aware that 1.6.6 is considered a Legacy release, updates to it are only done when there are severe security vulnerabilities. ( This includes but is not limited to remote code execution, authentication bypass, or unauthenticated data exposure.)
>1.6.6 will reach its EOL by 2026-12-31

We recommend always running the latest version for security updates and improvements.

## Reporting a Vulnerability

We take security vulnerabilities seriously. If you discover a security issue, please report it responsibly.

### How to Report

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, please send a detailed report to the repository maintainers via:

1. **GitHub Security Advisories** (preferred): Use the "Report a vulnerability" button in the Security tab of this repository
2. **Private disclosure**: Contact the maintainers directly through GitHub

### What to Include

When reporting a vulnerability, please include:

- A clear description of the vulnerability
- Steps to reproduce the issue
- Potential impact assessment
- Any suggested fixes (if applicable)
- Your contact information for follow-up

### Response Timeline

- **Initial Response**: Within 72 hours
- **Status Update**: Within 7 days
- **Resolution Target**: Depends on severity (critical issues prioritized)

## Security Best Practices

### Deployment Security

#### Use HTTPS/TLS

Always deploy behind a reverse proxy with TLS termination when exposing to the internet:

```nginx
# Example nginx configuration
server {
    listen 443 ssl;
    server_name watchparty.example.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

#### Network Architecture

- Keep your Emby server on an internal network when possible
- Use VPN solutions (Tailscale, WireGuard) for remote access to internal services
- The watch party application acts as a proxy, so your Emby server doesn't need direct internet exposure

### Configuration Security

#### Environment Variables

Never commit your `.env` file. It contains sensitive credentials:

```bash
# These should NEVER be in version control
EMBY_API_KEY=your_api_key
SESSION_SECRET=your_session_signing_key
```

As of 2.0, `EMBY_USERNAME` and `EMBY_PASSWORD` are no longer stored in
`.env`. Per-user authentication is an in-app action: any party member
clicks "Login to Become Host" inside the party. The backend keeps no
long-lived user credentials at rest.

As of 2.0.0-beta18, `SESSION_SECRET` MUST be set for any production
deployment. It's the signing key for the party-bound session cookie;
if left empty, an ephemeral random key is generated at each boot and
every existing user session is invalidated on restart. Generate ONCE
with `openssl rand -hex 32` and treat it like any other long-lived
signing key -- rotate on suspected compromise, otherwise leave stable.

Ensure your `.env` file has restricted permissions:

```bash
chmod 600 .env
```

#### API Key Protection

- Use a dedicated Emby API key for the watch party application
- Limit API key permissions where possible
- Rotate API keys periodically
- Never share API keys in logs or error messages

### Application Security Features

#### Rate Limiting

The following rate limits are hardcoded in code and always active
(they cannot be disabled from `/admin`):

- **`/api/admin/login`** — 10 attempts / 15 minutes per IP. Blocks
  credential-stuffing against Emby admin accounts. Trusts the last
  hop of `X-Forwarded-For` for reverse-proxied deployments.
- **`chat_message`** — 5 messages / 3 seconds per socket, hard cap
  of 2 KiB per message. Blocks room-wide amplification via oversized
  or high-rate chat payloads.
- **`report_progress`** — one Emby-facing progress POST per socket
  every 4 seconds. Blocks event-loop-pinning spam from a malicious
  client under the host's Emby access token.
- **`/api/avatar/recover`** — per-IP recovery-code check bucket.

The admin-panel `ENABLE_RATE_LIMITING` / `RATE_LIMIT_PARTY_CREATION`
/ `RATE_LIMIT_API_CALLS` fields persist to `config.json` but do not
drive an active limiter yet -- treat them as advisory. A dedicated
HTTP-layer limiter is planned post-2.0.0. The above hardcoded limits
cover the most sensitive vectors in the meantime.

#### Token Validation

HLS streaming tokens provide time-limited access:

```env
ENABLE_HLS_TOKEN_VALIDATION=true
HLS_TOKEN_EXPIRY=86400  # 24 hours in seconds
```

Query parameters forwarded to Emby from the `/hls/...` proxy are
filtered against an allowlist as of 2.0.0-beta18, so a caller with
a valid HLS token cannot smuggle `Static=true`, `redirect=...`, or a
rogue `api_key=` into the upstream Emby request.

#### Session Security

- Cookie signing key comes from `SESSION_SECRET` in `.env` (new in
  2.0.0-beta18). Persistent across restarts and workers. Empty =
  ephemeral fallback with loud warning at boot.
- Cookie name is `ewp_session` (was `session` prior to beta18; the
  rename means upgrading from earlier 2.0 betas invalidates every
  existing session and re-prompts users to join).
- `SameSite=Lax` for CSRF protection on cross-site POST navigations.
- `Secure` flag driven by `SESSION_COOKIE_SECURE` env var. Set
  `true` for any HTTPS deployment; leave `false` for local dev.
- 14-day `max_age` on the cookie; content is cryptographically
  signed with `itsdangerous.TimestampSigner`.

#### Socket.IO Hardening (2.0.0-beta18)

- `max_http_buffer_size=128 KiB` (was 1 MB default). Caps any single
  packet at 128 KiB to shrink the CVE-2026-48804 binary-buffer
  amplification surface.
- `ping_timeout=30`, `ping_interval=12`. Zombie reconnect storms
  clear ~2x faster than at defaults.
- `cors_allowed_origins` from `CORS_ALLOWED_ORIGINS` env var
  (default `*` for backwards compat). Pin to real origin(s) in
  production.
- All `play` / `pause` / `seek` / `video_ended` handlers gate on the
  caller's `client_id` matching either the video's `selected_by` or
  the party's `host_client_id`. Spectators cannot drive party-wide
  playback.

#### Party Size Limits

Limit users per party to prevent resource exhaustion:

```env
MAX_USERS_PER_PARTY=10
```

### Docker Security

When running in Docker:

```yaml
services:
  emby-watchparty:
    image: ghcr.io/oratorian/emby-watchparty:latest
    read_only: true  # Read-only filesystem where possible
    security_opt:
      - no-new-privileges:true
    env_file:
      - .env
```

### Logging Security

- Avoid logging sensitive information (passwords, API keys, tokens)
- Configure appropriate log levels for production:

```env
LOG_LEVEL=WARNING
CONSOLE_LOG_LEVEL=ERROR
```

- Ensure log files have appropriate permissions when `LOG_TO_FILE=true`

## Known Security Considerations

### Authentication Model

- The application relies on Emby server authentication
- Users authenticate with their Emby credentials
- Library access respects Emby user permissions

### Session Handling

- Sessions are stored server-side
- Session IDs are cryptographically random
- Consider using Redis for session storage in clustered deployments

### WebSocket Security

- WebSocket connections should be protected by the same TLS termination as HTTP
- Per-sid rate limiting on chat and report_progress (see above)
- Client-supplied playback events (play/pause/seek/video_ended) are
  authorized against `selected_by` / `host_client_id`
- Invalid messages are rejected and logged

## Security Updates

Security updates are released as patch versions (e.g., 1.4.1, 1.4.2). Monitor:

- GitHub Releases for new versions
- CHANGELOG.md for security-related changes
- GitHub Security Advisories for vulnerability disclosures

## Acknowledgments

We appreciate responsible security researchers who help keep this project secure. Contributors who report valid security issues will be acknowledged (with permission) in release notes.
