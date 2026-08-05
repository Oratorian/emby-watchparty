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
- Production startup validation is strict. Invalid boot settings leave the
  process up but serving nothing, with the failing fields named.
- Configuration is environment-only. There is no setup page and no bootstrap
  token; 3.0 development builds briefly had both and they are gone.
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

## When boot configuration is invalid

The process stays reachable and serves nothing. `/api/health` returns HTTP 200
with `status: setup_required`, `/api/ready` returns 503, and every other route
returns 503, so an orchestrator can distinguish "misconfigured" from "dead"
without restart-looping the container.

The failing fields are named on stderr in a framed banner and again through the
application logger:

```
========================================================================
  Emby Watch Party cannot start: invalid boot configuration.

    CORS_ALLOWED_ORIGINS: must be explicit in production
    SESSION_COOKIE_SECURE: must be true in production
    SESSION_SECRET: must be at least 32 characters in production

  Set these in the environment (container template, compose
  environment:, or .env) and restart. Nothing else is served
  until they are valid.
========================================================================
```

Fix the named variables where your deployment defines them, then restart. On
Unraid, CasaOS, Portainer or TrueNAS that is the container template; under
Compose it is the `environment:` block or `.env`.

Treat `SESSION_SECRET` and the Emby API key as credentials. Never attach them
to an issue or support log.

### Upgrading from a 3.0 development build

If you completed the old interactive setup, you will have a
`data/bootstrap.json` and possibly a `data/setup-token`. Both are now ignored
and are removed on the next successful boot. **Copy any values you set only
through that form into your environment before upgrading**, because they are no
longer read from the file.

## Boot-setting precedence

Precedence is:

1. Process environment
2. Untracked `.env`
3. Code defaults

Process-environment and `.env` are one explicit-operator tier, with process
values winning. Reading `.env` does not mutate the running process environment.

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
BEHIND_PROXY=true
TRUSTED_PROXY_CIDRS=172.16.0.0/12
```

### `BEHIND_PROXY` is new in 3.0 and has no default

Production refuses to boot until you state it. That is deliberate, because
guessing wrong is silent and expensive.

Rate limiting keys on the address a connection arrives from. Behind a reverse
proxy that address is the **proxy**, identical for every viewer, so all of them
share one bucket. With the shipped defaults that means 5 party creations per
hour and 30 socket connects per minute for the entire deployment, and the person
affected simply sees it not work, with nothing in the UI naming a limit. 2.x was
unaffected because none of these limits were enforced.

- **`BEHIND_PROXY=true`** makes `TRUSTED_PROXY_CIDRS` mandatory. Setting it true
  with an empty CIDR list is refused at boot, in every environment, because it
  is a self-contradiction.
- **`BEHIND_PROXY=false`** is correct for a directly reachable server, and an
  empty `TRUSTED_PROXY_CIDRS` is then the *safer* setting: with no proxy in
  front, trusting a forwarded header would let any client forge its own bucket.

Set `TRUSTED_PROXY_CIDRS` to the network your proxy connects **from**, not the
client's address. `172.16.0.0/12` covers the default Docker bridge networks;
use `127.0.0.1/32` for a proxy on the host. Direct clients outside those
networks cannot influence forwarded-IP resolution.

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

### `ENABLE_HLS_TOKEN_VALIDATION` moved, and your setting came with it

The toggle is gone from **Admin → Security**. Nothing was reset, and you do not
need to set it again. On first 3.0 boot the existing value is read out of your
`config.json` and becomes the starting value of the boot setting, so a
deployment that had it off stays off and one that had it on stays on.

Only the location changed. It is now a boot setting, which means it is set
through the environment and applied at startup; a runtime write through the
admin API is refused with an explicit "boot setting; restart required" rather
than being silently ignored. To change it, set `ENABLE_HLS_TOKEN_VALIDATION`
in the environment and restart.

Production requires it enabled, and startup validation fails loudly if it is
not, so the only deployments that can carry a disabled value forward are
development ones.

## Source and Windows installs

**Delete the old virtual environment and create a new one. Do not upgrade in
place.** This is not a tidiness preference; an in-place upgrade leaves an
environment that is half 2.1.x and half 3.0.

```bash
rm -rf .venv                      # Windows: Remove-Item -Recurse -Force .venv
python -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
```

Two reasons it has to be a fresh environment:

- `requirements.txt` is now generated with hashes. Any hash in a requirements
  file puts pip into `--require-hashes` mode, which then demands that every
  transitive dependency also be pinned with a hash valid for the running
  interpreter. A partially populated environment fails this in ways whose error
  messages point at the wrong package.
- 3.0 drops some distributions that 2.1.x installed, and **pip never removes a
  package just because it left the requirements file**. Upgrading in place
  leaves those behind, still importable, which is how you get a machine that
  behaves differently from a clean install and from CI.

Python 3.12 specifically: `pyproject.toml` pins `requires-python = ">=3.12,<3.13"`,
and the lock is compiled for it. 3.13 is not supported.

`uvicorn[standard]` installs platform-appropriate accelerators: Linux receives
`uvloop` and `httptools`; Windows automatically skips `uvloop` but keeps
`httptools`, `websockets`, and `watchfiles`.

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
