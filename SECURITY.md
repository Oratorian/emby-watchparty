# Security Policy

This policy describes security support, private vulnerability reporting, and the deployment requirements for Emby Watch Party 3.x. The application supports Emby and Jellyfin through the provider selected at startup.

## Supported Versions

| Version | Security support |
| --- | --- |
| Latest stable 3.x release, once published | Active release line, including security fixes. |
| Latest stable 2.x release | Security maintenance. Upgrade older 2.x patches to the latest supported patch. |
| Latest 3.0 prerelease | Testing support and fixes on the current prerelease; not a stable production release. |
| 1.6.7 legacy | Severe security vulnerabilities only, through 2026-12-31. |
| Older patches and other retired releases | Unsupported; upgrade to a supported release. |

Legacy fixes are limited to severe issues such as remote code execution, authentication bypass, or unauthenticated data exposure. Removing a legacy deployment template does not change the stated support deadline.

Pin the major line you intend to run: `:2` for stable 2.x and `:3` for stable 3.x after that image is published. `:latest` can cross a major-version boundary. Read the [migration guide](docs/Migration-HowTo.md) before upgrading from 2.x to 3.x, and retain a complete rollback backup until playback has been validated.

## Reporting a Vulnerability

**Do not open a public GitHub issue for an undisclosed vulnerability.**

Use [GitHub private vulnerability reporting](https://github.com/Oratorian/emby-watchparty/security/advisories) through the repository's **Report a vulnerability** action. Alternatively, contact the maintainers privately through GitHub. Discord and the public issue tracker are for ordinary support, not private disclosure.

Include:

- The affected application version or image digest and whether you use Emby or Jellyfin.
- Reproduction steps or a minimal proof of concept using test accounts and data.
- The affected route or event, expected behavior, and observed impact.
- Relevant deployment details, such as proxy topology and the settings that influence the issue.
- Suggested fixes, if available, and a contact method for follow-up.

Redact passwords, API keys, session cookies, recovery codes, and token-bearing playback URLs from attachments. Describe which setting was enabled without posting its real secret value.

### Response targets

- **Initial response:** within 72 hours.
- **Status update:** within 7 days.
- **Resolution:** depends on severity, with critical issues prioritized.

Coordinate public disclosure with the maintainers while a supported fix is prepared. Valid reports are acknowledged in release notes with the reporter's permission.

## Production Deployment

### Required boot settings

3.x validates production configuration before serving the normal application. Set these through the process/container environment or an untracked `.env`:

```dotenv
APP_ENV=production
MEDIA_SERVER_TYPE=emby
MEDIA_SERVER_URL=http://media-server.example.test:8096
MEDIA_SERVER_API_KEY=
SESSION_SECRET=
SESSION_COOKIE_SECURE=true
CORS_ALLOWED_ORIGINS=https://watchparty.example.com
ENABLE_HLS_TOKEN_VALIDATION=true
BEHIND_PROXY=true
TRUSTED_PROXY_CIDRS=192.0.2.20/32
```

Replace the example addresses and fill both secrets. Select `emby` or `jellyfin` explicitly, with a URL reachable from Watch Party and a dedicated administrative API key issued by that server. The provider is not auto-detected.

Generate `SESSION_SECRET` once, for example with `openssl rand -hex 32`, and keep it stable. Production requires at least 32 characters. Rotate it on suspected compromise; changing it invalidates existing signed cookies.

Production requires an HTTPS browser URL, secure cookies, explicit Socket.IO origins without `*`, and enabled HLS token validation. HTTP from a TLS reverse proxy to the backend is allowed. Declare `BEHIND_PROXY` explicitly; when it is `true`, supply valid, nonempty `TRUSTED_PROXY_CIDRS` for the actual proxy peers.

Retired `EMBY_SERVER_URL`, `EMBY_API_KEY`, `JELLYFIN_SERVER_URL`, and `JELLYFIN_API_KEY` declarations cause a startup error, even when empty. Rename and remove them rather than keeping both old and new names.

See the [environment reference](docs/deployment/environment.md), [Compose guide](docs/deployment/compose.md), and [reverse-proxy guide](https://github.com/Oratorian/emby-watchparty/wiki/Reverse-Proxy).

### Proxy trust and network exposure

Keep the media server on an internal network where practical. Viewers need access to Watch Party; they do not need direct access to the media server. Restrict the backend port to the intended proxy or private network.

Forward Socket.IO upgrade traffic and HLS requests through the same HTTPS endpoint. For a subpath, preserve `APP_PREFIX` in application requests and include it in health/readiness URLs. Public origin values contain scheme, host, and any nondefault port, without a path.

Forwarded client addresses are accepted only when the TCP peer is in `TRUSTED_PROXY_CIDRS`. The application examines the chain from the right, skipping trusted proxies to find the first untrusted address. Use the narrowest relevant peer networks, not every private network or `0.0.0.0/0`. A mismatched list can collapse unrelated viewers into one rate-limit bucket.

The supplied launcher keeps Uvicorn proxy-header rewriting disabled so the application can inspect the real peer. Do not add an unrestricted second trust layer when replacing that launcher. `CORS_ALLOWED_ORIGINS` restricts Socket.IO origins; it is not a replacement for REST authentication or authorization.

### Invalid configuration and recovery

Invalid boot settings leave a restricted diagnostic process running:

| Endpoint | Invalid boot configuration |
| --- | --- |
| `/api/health` | HTTP 200 with `status: setup_required`. |
| `/api/ready` | HTTP 503 with `status: setup_required`. |
| Normal application routes | HTTP 503. |

Add `APP_PREFIX` to the probes when configured. Read the invalid field names on stderr, correct the environment, and recreate the container or restart the source process. A passing Docker liveness check alone does not establish readiness.

There is no setup form or bootstrap token. Obsolete `data/bootstrap.json` and `data/setup-token` files from early 3.0 development builds are not configuration sources and are removed only after normal runtime startup succeeds.

Boot-setting precedence is process environment, then `.env`, then code defaults. HLS validation has one migration fallback: when not explicitly set, the old persisted value can be read from `config.json`. Production still rejects a disabled value. Set `ENABLE_HLS_TOKEN_VALIDATION=true` in the environment to override it.

### Secrets and persistence

Do not commit `.env` or publish raw container inspection, rendered Compose configuration, cookies, or environment exports. Restrict access to the platform's environment store and backups. On Linux source deployments, `chmod 600 .env` restricts the file to its owner.

The normal host-login flow submits account credentials to Watch Party for upstream authentication; the resulting host and administrator access tokens are retained in process memory. The configured administrative API key remains a deployment secret in the operator's environment store.

Leave `EMBY_WATCHPARTY_X_DEV_HOST` and `EMBY_WATCHPARTY_X_DEV_HOST_ACCEPT_RISK` unset in real deployments. Together they enable a private development shortcut that substitutes stored credentials for submitted host-login credentials. Production mode does not automatically disable this explicit override.

Preserve writable `/app/config.json`, `/app/data`, and `/app/images/avatars`, plus `/app/logs` if file logging is enabled. `config.json` must be a valid JSON file, not a directory or empty file. Follow the full deployment example rather than adding a read-only root filesystem without accounting for required writes.

Run **one application worker and one application instance** for a deployment. Parties, administrator sessions, HLS grants, and rate-limit buckets are process-local. Redis-backed clustering is not implemented. Restarting the process clears active room state; a stable signing secret does not make that state persistent.

## Authentication and Authorization

One authenticated host supplies the media-server account and library permissions used by the room. Guests can join without media-server accounts and receive proxied playback access through that host's session. Choose a host account whose library access is appropriate for the invited group.

Host authority requires both the expected browser identity and an opaque server-issued host-session grant, checked against the current host. A public `client_id`, display name, or broadcast host ID alone does not grant host or administrator rights.

- Any registered party member can play, pause, and seek. This shared control is intentional.
- **Stop Video** is restricted to the current video's selector.
- Room visibility and media-server favorites, played-state, and playlist mutations require the host.
- Deployment administration requires an authorized media-server administrator, either as the verified party host or through a standalone administrator session.

Hidden rooms are unlisted, not password-protected. Anyone holding the room code or link can attempt to join. Late-join voting coordinates playback; it is not a substitute for an invitation or access policy.

## Sessions and Playback Protection

### Session cookies

`ewp_session` is a signed, readable cookie, not encrypted storage. It carries party/browser identity, grants, and opaque handles where needed; upstream access tokens stay server-side. Do not treat cookie contents as confidential or put provider credentials into them.

The cookie uses `HttpOnly`, `SameSite=Lax`, and the configured `Secure` flag. These reduce browser-side exposure but are not an explicit CSRF-token scheme. TLS, correct origin configuration, and server-side authorization remain necessary.

`SESSION_EXPIRY` controls cookie lifetime, default `86400` seconds. Standalone administrator sessions use a bounded in-memory store with an idle timeout renewed on use; logout revokes the stored session.

Cookies are shared across ports on the same hostname, and the current cookie path is `/`. Use separate public hostnames or browser profiles for independent 2.x and 3.x instances; different ports or `APP_PREFIX` values alone do not isolate their sessions.

### HLS access

The HLS proxy requires the signed party-bound session cookie even when token validation is disabled for development. Production requires token validation enabled. Opaque HLS tokens are time-limited, checked against an active party and socket membership, and must name the same party as the session cookie.

An HLS URL is not a standalone public credential. Keep token-bearing playlists and segment URLs out of support reports and proxy access logs. Participant departure and party dissolution revoke their HLS tokens; registered playback plans are removed on stream teardown. Tokens can remain valid across stream changes within the same active party session.

Forwarded upstream query parameters are allowlisted. Caller-added unknown parameters on Emby master requests are rejected; unknown parameters on upstream variant/segment URLs are dropped. Registered Jellyfin resources are constrained to the playback plan's permitted origin and item paths, with unsafe traversal and redirects refused.

## Runtime Limits and Logging

Runtime settings are managed through `/admin` and persisted in `config.json`. They are not arbitrary boot variables. In particular, `HLS_TOKEN_EXPIRY`, party-size limits, log levels, and the configurable rate limits belong there.

Leave `ENABLE_RATE_LIMITING=true` for production. These limits are enforced when that switch is enabled:

| Setting | Default | Scope |
| --- | --- | --- |
| `RATE_LIMIT_PARTY_CREATION` | `5 per hour` | Party creation, per resolved client IP. |
| `RATE_LIMIT_API_CALLS` | `1000 per minute` | Other covered `/api` requests, per resolved client IP. |
| `RATE_LIMIT_LOGIN` | `10 per 15 minutes` | Standalone administrator login attempts, per resolved client IP. |
| `RATE_LIMIT_AVATAR_RECOVERY` | `10 per hour` | Avatar recovery, per resolved client IP. |
| `RATE_LIMIT_CHAT` | `5 per 3 seconds` | Chat messages, per Socket.IO connection. |
| `RATE_LIMIT_SOCKET_CONNECTIONS` | `30 per minute` | Socket.IO connections, per resolved client IP. |

The general API limiter excludes health/readiness probes and does not cover `/hls`. Invalid rate specifications are rejected without replacing the previous runtime value. Clients receive action-specific rejection messages and retry delays.

The current runtime also truncates chat messages to **2048 characters**, limits Socket.IO packets to **128 KiB**, and separately throttles upstream progress reports to one per connection every four seconds. A Socket.IO transport connection alone does not establish protected media access or host authority; room membership and HTTP session checks apply separately.

`MAX_USERS_PER_PARTY` limits room membership; `0` means no configured cap. Size that cap for actual media-server encoding and network capacity, including independent viewer streams.

Manage `LOG_LEVEL`, `CONSOLE_LOG_LEVEL`, and `LOG_TO_FILE` through runtime configuration. Restrict access to file logs and redact upstream diagnostic output before sharing it. Reverse proxies and media servers can record information beyond the application's own logging policy; check them for cookies, credentials, and playback tokens.

## Security Updates

Monitor [GitHub Releases](https://github.com/Oratorian/emby-watchparty/releases), [CHANGELOG.md](CHANGELOG.md), and [Security Advisories](https://github.com/Oratorian/emby-watchparty/security/advisories). Install supported security patches and use the documented migration process when crossing major versions.

The current CI scans container vulnerabilities and gates fixable HIGH/CRITICAL findings subject to reviewed ignore entries, while reporting unfixed findings separately. A passing scan is not a claim that the application or its deployment has no vulnerabilities. Private reports remain important for authorization, provider, proxy, and browser behavior that dependency scanners do not establish.
