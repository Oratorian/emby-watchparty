# Migration: 1.x → 2.0

This guide walks 1.x deployments through the upgrade to 2.0. Read
it end-to-end before touching production; most of the surprises
are in the **Breaking changes** section and the per-platform
checklists, not in the upgrade mechanics themselves.

## TL;DR

If you're rushed and your deployment is a typical Docker Compose
setup with `:latest`:

1. **Stop** the watch-party container (Emby can stay running).
2. **Edit `.env`:** delete `EMBY_USERNAME` and `EMBY_PASSWORD`
   lines. Append three new keys introduced in beta18:
   ```bash
   echo "SESSION_SECRET=$(openssl rand -hex 32)" >> .env
   echo "SESSION_COOKIE_SECURE=false" >> .env   # true for HTTPS
   echo "CORS_ALLOWED_ORIGINS=*" >> .env        # pin in prod
   ```
   Everything else stays.
3. **Edit `docker-compose.yml`:** switch image to
   `ghcr.io/oratorian/emby-watchparty:latest`, add three volume
   mounts (touch the config.json host file first):
   ```yaml
   - ./data:/app/data
   - ./images/avatars:/app/images/avatars
   - ./config.json:/app/config.json
   ```
4. **`docker compose pull && docker compose up -d`.**
5. **Visit your watch-party URL**, click "Login to Become Host",
   supply your Emby admin credentials. Library unlocks. Test a
   video.

Everything else in this guide is detail, special cases, or
rollback. If the above worked, you're done.

## Should I migrate, or stay on 1.x?

**Migrate if you want:**

- Per-user audio language, subtitle, and quality (no more "we
  all have to watch in Japanese because someone picked it")
- Mid-playback quality changes that don't pause the rest of the
  party
- Multi-version playback (Emby's "Versions" picker — pick mp4 vs
  mkv vs Director's Cut at video-select time)
- Late-joiner vote flow that prevents the keyframe-rounded
  scene-misalignment problem
- Custom chat avatars with three-word recovery codes
- A-Z library jump bar with right-click filter
- Reverse-proxy support that works end-to-end (`APP_PREFIX`)

**Stay on 1.x if:**

- Your party is small and you're on tight CPU/GPU headroom. 2.0
  runs one ffmpeg per viewer; 1.x shared one across the party,
  so a 5-person party costs 5x more transcoding in 2.0.
- You don't have Emby Premiere (so no hardware acceleration) AND
  your hardware can barely keep up with one transcode today.
- You're maintaining a deployment with no operator attention and
  can't do the env / mount changes.

**1.x support timeline:** the 1.6.7 release (which security-bumped
`python-socketio` to `>=5.16.2` for [CVE-2026-48804](https://github.com/advisories/GHSA-5w7q-77mv-v69f))
stays on the `legacy` branch and the `:legacy` Docker tag with
**security-only fixes through 2026-12-31**. After that date, no
further updates. Plan to migrate before then if you're
security-conscious.

## Breaking changes (must address)

The full per-beta breakdown is in the
[CHANGELOG](https://github.com/Oratorian/emby-watchparty/blob/main/CHANGELOG.md);
the summary below is the operator-facing slice.

### `.env` shrinks from ~20 keys to a handful

2.0 splits config into **boot-essential** (in `.env`, restart
required) and **runtime** (in `/admin`, hot-reloadable). Almost
everything except the network-binding values, the Emby admin key,
and the session-cookie hardening block moves to `/admin`.

| Key | 1.x location | 2.0 location |
|---|---|---|
| `WATCH_PARTY_BIND` | `.env` | `.env` (unchanged) |
| `WATCH_PARTY_PORT` | `.env` | `.env` (unchanged) |
| `SESSION_EXPIRY` | `.env` | `.env` (unchanged) |
| `APP_PREFIX` | `.env` | `.env` (unchanged) |
| `EMBY_SERVER_URL` | `.env` | `.env` (unchanged) |
| `EMBY_API_KEY` | `.env` | `.env` (unchanged) |
| `EMBY_USERNAME` | `.env` | **REMOVED** — host login is in-app |
| `EMBY_PASSWORD` | `.env` | **REMOVED** — host login is in-app |
| *(new in 2.0.0-beta18)* `SESSION_SECRET` | — | `.env` (`openssl rand -hex 32`) |
| *(new in 2.0.0-beta18)* `SESSION_COOKIE_SECURE` | — | `.env` (`true` for HTTPS deploys) |
| *(new in 2.0.0-beta18)* `CORS_ALLOWED_ORIGINS` | — | `.env` (comma-sep allowlist; `*` for backwards compat) |
| `REQUIRE_LOGIN` | `.env` | `/admin` → Auth section |
| `LOG_LEVEL` | `.env` | `/admin` → Logging section |
| `LOG_TO_FILE` | `.env` | `/admin` → Logging section |
| `LOG_FILE` | `.env` | `/admin` → Logging section |
| `LOG_FORMAT` | `.env` | `/admin` → Logging section |
| `LOG_MAX_SIZE` | `.env` | `/admin` → Logging section |
| `CONSOLE_LOG_LEVEL` | `.env` | `/admin` → Logging section |
| `MAX_USERS_PER_PARTY` | `.env` | `/admin` → Security section |
| `ENABLE_HLS_TOKEN_VALIDATION` | `.env` | `/admin` → Security section |
| `HLS_TOKEN_EXPIRY` | `.env` | `/admin` → Security section |
| `ENABLE_RATE_LIMITING` | `.env` | `/admin` → Security section |
| `RATE_LIMIT_PARTY_CREATION` | `.env` | `/admin` → Security section |
| `RATE_LIMIT_API_CALLS` | `.env` | `/admin` → Security section |
| `STATIC_SESSION_ENABLED` | `.env` | `/admin` → Session section |
| `STATIC_SESSION_ID` | `.env` | `/admin` → Session section |
| *(new in 2.0)* | — | `/admin` → Late Join Vote section |
| *(new in 2.0)* | — | `/admin` → Playback (`FORCE_TRANSCODE`) |
| *(new in 2.0)* | — | `/admin` → Quality (per-bitrate enable) |

**Important:** if you had any of the moved keys set to a non-default
value in your `.env`, you'll need to either (a) re-apply the same
value via `/admin` after upgrade, or (b) edit `config.json` directly
before first start. There is no automatic migration; the runtime
settings start at code defaults on first 2.0 boot.

### Upgrading to 2.0.0-beta18 (session cookie hardening)

beta18 introduced `SESSION_SECRET`, `SESSION_COOKIE_SECURE`, and
`CORS_ALLOWED_ORIGINS`. If you're coming from any earlier 2.0 beta:

1. **Generate a stable session secret** and add it to `.env`:
   ```bash
   echo "SESSION_SECRET=$(openssl rand -hex 32)" >> .env
   ```
   Without this, an ephemeral key is generated per boot with a warning
   in logs: every restart kicks every user out of their party with a
   401, and running under `--workers >1` produces non-deterministic
   session state (a cookie signed by worker A doesn't verify on worker
   B). Fine for local dev, catastrophic in production.
2. **Set `SESSION_COOKIE_SECURE=true` in production**, `false` in local
   dev. The default is `false`. Under HTTPS with `true`, browsers only
   send the cookie over TLS; under HTTP with `true`, cookies are
   stripped entirely and you lock yourself out.
3. **Pin `CORS_ALLOWED_ORIGINS` to your real origin(s)** for production
   (`https://watchparty.example.com`). The default `*` accepts any
   origin (backwards compat) but the socket rate limits + host lock
   still apply, so it's not a critical setting -- just cleaner.

On first boot after the upgrade, every existing session cookie stops
verifying (the cookie name changed from `session` to `ewp_session`).
Every current user is re-prompted to join their party. Post-upgrade
cookies persist across restarts as long as `SESSION_SECRET` is stable.

### Auth model: per-user creds are gone

In 1.x the operator put one `EMBY_USERNAME` / `EMBY_PASSWORD` in
`.env` and the backend used those credentials to talk to Emby on
behalf of every viewer. That credential pair is removed in 2.0.

The replacement is in-app: any party member clicks **Login to
Become Host** inside the party and supplies their own Emby
credentials. The backend authenticates against Emby, stores the
returned `access_token` against the party, and uses it to sign
every Emby call for the room. Other party members are anonymous
to Emby; their identity is the host's session.

- `EMBY_API_KEY` (admin server key) is still required in `.env`.
- The host's credentials never persist anywhere on disk. They're
  in-memory only and cleared when the host disconnects (with a
  5-second grace window) or explicitly logs out.

### HTTP API endpoints now require a party-bound session cookie

`/api/libraries`, `/api/items`, `/api/search`, `/api/item/<id>...`,
`/api/intro`, `/api/image`, `/api/subtitles`, and `/hls/...` now
all return:

- `401` without a party-bound session cookie
- `423 Locked` when the party has no host

The cookie is issued by the new `POST /api/party/<id>/join` step,
which the frontend handles automatically before the Socket.IO
handshake. Operators don't normally see these endpoints; this
matters only if you've written external scripts or integrations
hitting them directly.

### `POST /api/party/create` request body changed

| Mode | Body |
|---|---|
| Anonymous create (`REQUIRE_LOGIN=false`, default) | `{ client_id }` or empty |
| Authenticated create (`REQUIRE_LOGIN=true`) | `{ client_id, display_name, username, password }` |

External clients of this endpoint need updating; the bundled
frontend handles both cases.

### `/api/auth/login` is now "become host", not global login

In 1.x there was a global login concept. In 2.0, `/api/auth/login`
specifically promotes the caller to host of their currently-bound
party. It requires the party-bound session cookie. The bundled
frontend no longer has a `/login` route — host login happens
inside the party via the "Login to Become Host" button.

### Two new required volume mounts (Docker)

| Mount | Why required |
|---|---|
| `/app/data` | SQLite avatar DB (`avatars.db`). Holds the UUID → avatar mapping and bcrypt-hashed recovery codes. Without this mount, every container recreate wipes every member's avatar permanently. |
| `/app/images/avatars` | Uploaded avatar image files (PNG/JPG/WebP). Same persistence story. |

Plus one optional but recommended mount:

| Mount | Why |
|---|---|
| `/app/config.json` | Runtime admin settings (everything that moved from `.env` to `/admin`). Without this mount, `/admin` changes survive restarts of the same container but are wiped on recreate. **`touch config.json` on the host BEFORE first start** or Docker creates it as a directory. |

### Docker image registry changes

| Tag | 1.x | 2.0 |
|---|---|---|
| `:latest` | `oratorian/emby-watchparty:latest` (Docker Hub) | `ghcr.io/oratorian/emby-watchparty:latest` |
| `:1.6.7` | `oratorian/emby-watchparty:1.6.7` (Docker Hub) | `ghcr.io/oratorian/emby-watchparty:1.6.7` |
| `:legacy` *(new)* | — | `ghcr.io/oratorian/emby-watchparty:legacy` → 1.6.7 (alias, pins 1.x line) |
| `:nightly` / `:devel` | — | `ghcr.io/oratorian/emby-watchparty:nightly` → latest closed-beta build |

Docker Hub mirrors are still being pushed for compatibility, but
GHCR is now the source of truth and `:legacy` is GHCR-only.

### Branch rename at cutover

| Branch | Before cutover | After cutover |
|---|---|---|
| `main` | 1.6.7 codebase | renamed to `legacy`, still 1.6.7 |
| `2.0-Rework` | 2.0 development | renamed to `main` |
| `dev` | 1.x development | gone (rolled into `legacy`) |
| `legacy` | — | new, ex-`main` |

GitHub auto-redirects old branch URLs after rename, so existing
bookmarks keep working. CI / forks pinned to a specific branch
name will need updating.

## Step-by-step: Docker Compose user

### 1. Backup

```bash
# From the directory holding your docker-compose.yml
cp .env .env.1x-backup
cp docker-compose.yml docker-compose.yml.1x-backup
docker compose ps  # note running state
```

### 2. Stop the watch-party container only

```bash
docker compose stop emby-watchparty
```

Leave Emby running — no Emby-side changes are needed.

### 3. Edit `.env`

Remove `EMBY_USERNAME` and `EMBY_PASSWORD` lines. Optionally
remove every runtime setting (`REQUIRE_LOGIN`, `LOG_*`,
`STATIC_SESSION_*`, `MAX_USERS_PER_PARTY`, `ENABLE_*`,
`RATE_LIMIT_*`, `HLS_TOKEN_EXPIRY`) — these will be set via
`/admin` post-upgrade. Anything you leave is ignored.

Then ADD three new keys introduced in beta18 (session cookie
hardening). Skipping these makes 2.0 boot with an ephemeral
session key that kicks every user out on every restart -- fine
for local dev, not for production. Generate the secret ONCE and
leave it stable across restarts:

```bash
echo "SESSION_SECRET=$(openssl rand -hex 32)" >> .env
```

Nine keys remain (your existing values for the pre-beta18 ones
are fine; the example shows defaults):

```ini
# Application
WATCH_PARTY_BIND=0.0.0.0
WATCH_PARTY_PORT=5000
SESSION_EXPIRY=86400
APP_PREFIX=

# Session cookie (new in beta18) -- SESSION_SECRET must be stable
SESSION_SECRET=paste-openssl-rand-hex-32-output-here
SESSION_COOKIE_SECURE=false          # true for HTTPS deploys
CORS_ALLOWED_ORIGINS=*               # pin to your origin(s) in prod

# Emby
EMBY_SERVER_URL=http://emby:8096
EMBY_API_KEY=your-admin-api-key-here
```

### 4. Edit `docker-compose.yml`

Switch the image and add the new volume mounts. Diff against your
1.x compose:

```diff
   emby-watchparty:
-    image: oratorian/emby-watchparty:latest
+    image: ghcr.io/oratorian/emby-watchparty:latest
     env_file: .env
     ports:
       - "5000:5000"
     volumes:
+      - ./data:/app/data
+      - ./images/avatars:/app/images/avatars
+      - ./config.json:/app/config.json
       - ./logs:/app/logs
```

Touch the `config.json` host file BEFORE the next step:

```bash
mkdir -p data images/avatars
touch config.json
```

### 5. Pull and start

```bash
docker compose pull emby-watchparty
docker compose up -d emby-watchparty
docker compose logs -f emby-watchparty
```

Watch for the startup banner. You should see:

```
Emby Watch Party v2.0.0 - "Midnight Premiere"
Emby Server: http://emby:8096
Components initialized successfully
```

If you set `APP_PREFIX`, it logs that too.

### 6. First-boot host login

1. Open your watch-party URL.
2. Click **Create Party** (or join an existing if you have one).
3. The party will be LOCKED (no host yet).
4. Click **Login to Become Host** in the header.
5. Supply your Emby admin credentials.
6. The library should unlock.
7. Pick a video. Verify playback works.

### 7. Re-apply runtime settings (if you had non-defaults)

Visit `/admin` (Emby admin credentials required). Re-toggle any
of the moved settings to match your 1.x values:

- `REQUIRE_LOGIN` (Auth section)
- All logging settings (Logging section)
- Security toggles + rate-limit strings (Security section)
- `STATIC_SESSION_*` (Session section)
- `LATE_JOIN_VOTE_*` (Late Join Vote section, new in 2.0)
- `FORCE_TRANSCODE` (Playback section, new in 2.0)
- `ENABLED_QUALITY_OPTIONS` (Quality section, new in 2.0)

Save. Changes apply immediately; only the boot-only `.env`
values (bind, port, session expiry, APP_PREFIX, Emby URL / API
key, SESSION_SECRET / SESSION_COOKIE_SECURE / CORS_ALLOWED_ORIGINS)
require a restart.

## Step-by-step: Unraid user

The Community Applications template split into two entries at
the 2.0.0 cut:

- **`emby-watchparty`** (current, pinned to `:latest`) -- the
  2.0 template. New deployments install this.
- **`emby-watchparty-legacy`** (pinned to `:legacy`) -- keeps
  existing 1.x installs running as-is. Use this if you're not
  ready to migrate yet.

### Coming from a 1.x install

Two paths:

**Path A: Stay on 1.x for now.**

1. Uninstall your current `emby-watchparty` container from
   Docker (keep the appdata directory intact -- your `.env`,
   any files inside it are untouched).
2. In Community Applications, install the new
   `emby-watchparty-legacy` template.
3. Point the same appdata directory at the new container. It
   pins to `ghcr.io/oratorian/emby-watchparty:legacy` (= 1.6.7)
   and your 1.x config, `.env`, and behavior are unchanged.
4. Migrate to 2.0 later per Path B when you're ready.

**Path B: Migrate to 2.0 now.**

1. Stop and uninstall your current 1.x `emby-watchparty`
   container. Keep the appdata directory.
2. In Community Applications, install the new
   `emby-watchparty` template (2.0). Do NOT reuse fields
   blindly; the shape changed.
3. **Env fields (Required):**
   - `Emby Server URL` -- same as your 1.x value.
   - `Emby API Key` -- same as your 1.x `EMBY_API_KEY`. Per-user
     Emby credentials (`EMBY_USERNAME` / `EMBY_PASSWORD`) are
     gone; the template does not have those fields anymore. Host
     auth happens in-party via "Login to Become Host".
   - `Session Secret` -- generate ONCE with `openssl rand -hex 32`
     on any Linux box (or `python -c "import secrets; print(secrets.token_hex(32))"`).
     Paste the 64-char hex string in. Must stay stable across
     restarts, or every user gets kicked out on every restart.
   - `Session Cookie Secure` -- `true` if you access via HTTPS
     (behind a reverse proxy with TLS), `false` for local LAN
     `http://` access. Wrong choice locks you out.
4. **Env fields (Advanced):** `App Prefix`, `CORS Allowed Origins`,
   `Session Expiry`, `Bind Address`, `Container Port`. All
   optional; defaults are safe. If you had `APP_PREFIX` set in
   1.x, re-enter it here.
5. **Host paths (Required, three of them):**
   - `/app/data` -> `/mnt/user/appdata/emby-watchparty/data`
     (SQLite avatar DB)
   - `/app/images/avatars` -> `/mnt/user/appdata/emby-watchparty/avatars`
     (uploaded avatar files)
   - `/app/config.json` -> `/mnt/user/appdata/emby-watchparty/config.json`
     (runtime admin config)
6. **Before starting** -- touch the config.json file on the
   host, or Docker silently creates it as a directory and the
   backend crashes on first write:
   ```bash
   touch /mnt/user/appdata/emby-watchparty/config.json
   ```
7. Apply, wait for the container to come up. Watch logs for
   the startup banner.
8. First-boot host login per the Docker Compose section above
   (step 6).

If you installed manually (without a template), follow the
Docker Compose recipe and translate to Unraid's `Extra
Parameters` / `Variables` / `Paths` UI.

## Step-by-step: TrueNAS SCALE user

Same shape as Unraid:

1. Edit the app config.
2. Switch image repository to
   `ghcr.io/oratorian/emby-watchparty`.
3. Drop `EMBY_USERNAME` / `EMBY_PASSWORD` env vars. Add three
   new env vars introduced in beta18:
   - `SESSION_SECRET` -- generate ONCE with `openssl rand -hex 32`.
   - `SESSION_COOKIE_SECURE` -- `true` for HTTPS, `false` for HTTP.
   - `CORS_ALLOWED_ORIGINS` -- `*` for backwards compat, or your
     real origin(s).
4. Add three `Host Path` volumes:
   - `/mnt/tank/apps/emby-watchparty/data` → `/app/data`
   - `/mnt/tank/apps/emby-watchparty/images/avatars` → `/app/images/avatars`
   - `/mnt/tank/apps/emby-watchparty/config.json` → `/app/config.json`
     (touch the host file first, or SCALE creates it as a
     directory and the backend crashes on first write).
5. Save, wait for rollout, first-boot host login.

## Step-by-step: bare-metal user

The toolchain changed significantly: 1.x ran Python 3.8+ +
Flask, no Node needed. 2.0 needs **Python 3.12+** AND **Node
22+** because the Vue 3 frontend has to be built with Vite
before the FastAPI backend can serve it.

If your bare-metal box can install both, the recipe is:

```bash
git clone https://github.com/Oratorian/emby-watchparty.git
cd emby-watchparty
git checkout main   # after the 2.0.0 cutover; before, use 2.0-Rework

# Backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Frontend (one-time + on every update)
cd frontend
npm install
npm run build
cd ..

# Configure
cp .env.example .env
# edit .env — set EMBY_SERVER_URL and EMBY_API_KEY

# Run
.venv/bin/python -m backend.app
```

If installing Node is impractical, run the Docker image instead.
It's a single multi-stage build that bakes both toolchains.

## What does NOT carry over

- **Existing in-flight parties.** Parties are in-memory in both
  1.x and 2.0; any restart wipes them. Nothing to migrate.
- **Existing transcode sessions.** Same — restart kills them.
  Emby will clean up the orphaned `PlaySessionId`s on its own.
- **Configuration moved from `.env` to `config.json`.** Initial
  values are lost; re-apply via `/admin` after upgrade.
- **Anyone's avatar (you don't have any in 1.x).** Avatars are
  new in 2.0; there's nothing to migrate. Members will set them
  up on first use.

## What DOES carry over

- **Your Emby server.** No Emby-side changes needed.
- **The `.env` keys you keep:** bind, port, session expiry,
  APP_PREFIX, Emby URL, Emby admin API key. Plus three new keys
  introduced in beta18 -- SESSION_SECRET, SESSION_COOKIE_SECURE,
  CORS_ALLOWED_ORIGINS -- must be added before 2.0.0 boots
  cleanly in production.
- **Emby's library scopes** for your watch-party user (if you
  used a dedicated user). The new "Login to Become Host" flow
  uses the same Emby account; library access follows from there.
- **Browser data:** existing party codes typed into URLs still
  work as long as a 2.0 party with that code exists. Avatars are
  new, so first-time UUIDs will be assigned on first 2.0 visit.

## Rollback plan

If 2.0 misbehaves and you need to roll back:

1. **Stop the watch-party container.**
2. **Restore your backed-up `.env` and `docker-compose.yml`** —
   they had `EMBY_USERNAME` / `EMBY_PASSWORD` and the old image.
3. **Re-pin to the legacy image:**
   ```yaml
   image: ghcr.io/oratorian/emby-watchparty:legacy
   ```
   (= 1.6.7). Or pin to `:1.6.7` directly if you prefer the
   specific version.
4. **`docker compose up -d`.**

You don't need to remove the new `/app/data` and
`/app/images/avatars` volume mounts — 1.x ignores them silently.
The `config.json` mount is also harmless on 1.x.

The 2.0 data on those volumes (avatars.db, image files) stays put
on disk and will be re-used the next time you upgrade to 2.0
again.

## First-boot checklist after upgrade

Run through this list once after a successful upgrade so the
deployment is in the state you'll want it long-term:

- [ ] `/admin` opens with your Emby admin credentials
- [ ] `REQUIRE_LOGIN` set to your preference (Auth section)
- [ ] Logging configured (file vs console, level)
- [ ] Rate limits + per-IP caps set if you want them (Security)
- [ ] `MAX_USERS_PER_PARTY` set if you want a cap (Security)
- [ ] `LATE_JOIN_VOTE_TIMEOUT_SECONDS` + cooldown tuned (Late
      Join Vote)
- [ ] `FORCE_TRANSCODE` decision made (Playback) — leave off for
      cheaper transcoding, turn on if Skip Intro / large seeks
      restart from 0
- [ ] `ENABLED_QUALITY_OPTIONS` trimmed if you don't want every
      bitrate exposed (Quality)
- [ ] A test party works end-to-end: create, login-to-host,
      pick a video, change quality, chat, leave
- [ ] Avatar setup works: upload an image, get the recovery
      code, refresh the browser, recover the avatar

## Where to ask for help

- **General questions / "is this 2.0 behaviour intended?"** —
  the [project wiki FAQ](https://github.com/Oratorian/emby-watchparty/wiki/FAQ).
- **Migration trouble** — GitHub issue tagged `migration`.
  Include your 1.x version, your target 2.0 version, deployment
  platform, and the exact error message.
- **Discord** — the Watch Party support channel.

## Cutover timeline (operator-relevant dates)

- **2026-XX-XX (TBD):** 2.0.0 cut. Public release notes go up.
  Migration window opens.
- **2026-12-31:** 1.6.7 EOL. After this date, no further security
  fixes on the 1.x line. Migrate before then if you're security-
  conscious.
- **Indefinitely:** `:legacy` Docker tag (= 1.6.7) stays
  available for emergency pinning. The 1.6.7 image itself is
  not removed from GHCR.
