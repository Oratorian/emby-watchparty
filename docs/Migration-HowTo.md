# Migration: 2.1.x → 3.0

This guide covers the 3.0 beta line built from `3.0-dev`. Read it before
upgrading a stable deployment. Keep 2.1.x available for rollback until the
new setup has completed a real playback test.

Users upgrading from 1.x should first follow the migration guide shipped with
the latest 2.1.x release, then return here.

## Breaking changes

3.0 changes deployment requirements and configuration ownership:

- Python 3.12.x is required for source installs.
- Node 20.19 or newer is required when building the frontend from source. The
  project CI and Docker builder use Node 24.
- Run exactly one application worker. Party state, administrator sessions,
  HLS grants, and rate-limit buckets are process-local.
- Production startup validation is strict. Invalid boot settings enter the
  restricted setup application instead of starting the watch-party API.
- Boot configuration can be saved in persistent `data/bootstrap.json`.
- `ENABLE_HLS_TOKEN_VALIDATION` is a restart-required boot setting; its old
  runtime admin toggle is gone.
- Docker/Linux is the primary deployment platform. Windows remains a
  best-effort local-development convenience.

No migration should delete the old `.env`, `config.json`, `data/`, or avatar
directories before the new version has started successfully.

## Docker Compose upgrade

1. Stop the watch-party container. Emby can remain online.
2. Back up `.env`, `docker-compose.yml`, `config.json`, `data/`, and
   `images/avatars/`.
3. Keep these mounts:

   ```yaml
   volumes:
     - ./data:/app/data
     - ./images/avatars:/app/images/avatars
     - ./config.json:/app/config.json
   ```

   Create the host-side `config.json` as a file before starting Compose.
4. Pull the chosen 3.0 beta image or build from `3.0-dev`.
5. Start the container and inspect its logs.

The baked `/api/health` probe is liveness only. Setup mode intentionally
returns HTTP 200 with `status: setup_required` so Docker does not restart-loop.
`/api/ready` returns 503 until the normal application is available.

## First-run setup

Setup mode exposes only `/setup`, `/api/setup`, `/api/health`, and
`/api/ready`; normal API, Socket.IO, HLS, admin, and SPA routes return 503.

1. Read the one-time token from the console or `data/setup-token`. The file is
   mode `0600` where supported and is removed after a successful save.
2. Open `/setup` under the configured application prefix.
3. Choose local development or production HTTPS and submit the form.
4. Restart the process after setup reports that configuration was saved.
5. Confirm `/api/health` returns `status: ok` and `/api/ready` succeeds.

Treat the setup token, `SESSION_SECRET`, Emby API key, and
`data/bootstrap.json` as credentials. Never attach them to an issue or support
log.

## Boot-setting precedence

Precedence is:

1. Process environment
2. Untracked `.env`
3. `data/bootstrap.json`
4. Code defaults

Process-environment and `.env` fields remain external: setup validates their
effective values but does not copy them into `bootstrap.json`. This prevents
secrets injected by Compose, an environment file, or a secrets manager from
being duplicated into the persistent data mount.

If an explicit environment value is invalid, setup cannot override it. Fix or
remove that value and restart.

The bootstrap file includes a configured sentinel. If persistent `data/`
exists but the bootstrap file or sentinel disappears, 3.0 enters setup mode
instead of silently falling back to development defaults.

## Required production boot values

A typical reverse-proxy deployment supplies:

```env
APP_ENV=production
EMBY_SERVER_URL=http://emby:8096
EMBY_API_KEY=your-dedicated-emby-api-key
SESSION_SECRET=one-stable-random-secret-at-least-32-characters
SESSION_COOKIE_SECURE=true
CORS_ALLOWED_ORIGINS=https://watchparty.example.com
ENABLE_HLS_TOKEN_VALIDATION=true
TRUSTED_PROXY_CIDRS=172.16.0.0/12
```

Set `TRUSTED_PROXY_CIDRS` only to networks that actually contain your reverse
proxy. Direct clients outside those networks cannot influence forwarded-IP
resolution.

For local plain HTTP, use `APP_ENV=development`,
`SESSION_COOKIE_SECURE=false`, and bind only to a trusted local interface.
Disabled HLS token validation is development-only and still requires a valid
signed party session cookie.

## Runtime settings

Runtime settings remain in `config.json` and the admin panel. Rate limits and
party-size controls remain under **Admin → Security**. Malformed rate-limit
specifications are rejected without replacing or persisting the prior value.

Boot settings, including HLS token validation, are not exposed through the
runtime admin API and require restart.

## Source and Windows installs

Create a fresh Python 3.12 virtual environment and install the hash-locked
requirements. `uvicorn[standard]` installs platform-appropriate accelerators:
Linux receives `uvloop` and `httptools`; Windows automatically skips `uvloop`
but keeps `httptools`, `websockets`, and `watchfiles`.

The PowerShell launcher resolves the repository from `$PSScriptRoot`. It is a
local convenience, not the primary production deployment path.

## Validation checklist

Before directing users to 3.0:

- `/api/health` reports `ok`, not `setup_required`.
- `/api/ready` succeeds and reaches Emby.
- Administrator login and logout work.
- Create two separate parties and verify an HLS URL from one cannot be used
  with the other party's cookie.
- Test master playlist, variant playlist, segment playback, seeking, audio,
  subtitles, and an alternate media version.
- Refresh and reconnect a participant using the same browser identity.
- Confirm logs do not contain Emby tokens, session secrets, or setup tokens.
- Confirm `/hls` and health request logs remain at DEBUG volume.

## Rollback

Stop 3.0, restore the backed-up 2.1.x image and configuration, then start the
old container. Do not point 2.1.x at files you allowed 3.0 to modify unless you
have verified their compatibility; restoring the backup is safer.
