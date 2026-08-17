# Migration: 2.1.x → 3.0

This guide covers the 3.0 beta line built from `3.0-dev`. Read it before
upgrading a stable deployment. Keep the complete 2.1.x configuration and image
available for rollback until 3.0 has completed a real playback test.

Users upgrading from 1.x should first follow the migration guide shipped with
the latest 2.1.x release, then return here.

## Do you need to change anything?

**Yes. Two variables were renamed, and the old names are no longer read.**
Practically every 2.1.x deployment sets at least one of them, so this edit is
unavoidable. Past that, if your `.env` also satisfies the checks below, 3.0
boots on it unchanged.

### The server URL and API key were renamed

| 2.1.x | 3.0 |
|---|---|
| `EMBY_SERVER_URL` | `MEDIA_SERVER_URL` |
| `JELLYFIN_SERVER_URL` | `MEDIA_SERVER_URL` |
| `EMBY_API_KEY` | `MEDIA_SERVER_API_KEY` |
| `JELLYFIN_API_KEY` | `MEDIA_SERVER_API_KEY` |

Rename the key; the value does not change. `MEDIA_SERVER_TYPE` is untouched and
stays explicit, `emby` or `jellyfin`, with no auto-detection. It is the only
setting that was ever provider-specific: the address and the credential never
were, which is why one of each now serves both.

**There is no alias and no fallback read.** A retired name left in `.env` or in
the container environment fails the boot and names its replacement, rather than
being silently ignored:

```
EMBY_SERVER_URL: was replaced by MEDIA_SERVER_URL in 3.0; rename it and remove the old name
```

Failing is the point. Silently ignoring the old name would have started the
server against the default `http://localhost:8096` with an empty library, an
unhelpful symptom a long way from its cause. Rename the line and delete the old
one; keeping both is the same error.

The preflight below reports this as a `REQUIRED ACTION` naming your exact
situation, including the case where a deployment carries both an Emby and a
Jellyfin variant and a human has to decide which value survives.

**Checked in every environment, development included:**

- `APP_ENV` is `development` or `production`
- `WATCH_PARTY_PORT` is between 1 and 65535
- `APP_PREFIX`, if set, is slash-prefixed and uses only letters, numbers, dots,
  underscores, tildes or hyphens
- `MEDIA_SERVER_URL` is a valid HTTP(S) URL
- `TRUSTED_PROXY_CIDRS`, if set, contains valid IP networks
- `BEHIND_PROXY=true` is not paired with an empty `TRUSTED_PROXY_CIDRS`, which
  is a self-contradiction in any environment

**Checked additionally when `APP_ENV=production`:**

- `BEHIND_PROXY` is declared, either `true` or `false`. This is the one genuinely
  new requirement in 3.0 and it has no default
- `SESSION_SECRET` is set and at least 32 characters
- `SESSION_COOKIE_SECURE` is `true`
- `CORS_ALLOWED_ORIGINS` is explicit, not `*`
- `MEDIA_SERVER_API_KEY` is set
- `ENABLE_HLS_TOKEN_VALIDATION` is enabled

So for a production deployment coming from 2.1.x that already sets a session
secret, secure cookies and explicit origins, **the rename above plus
`BEHIND_PROXY` are normally the only edits**. Everything else in this guide is
either detail, a platform-specific note, or applies only if you build from
source.

**One exception, and it is a hard boot failure rather than a warning.** If you
ever turned HLS token validation **off** in **Admin → Security**, you must also
set it in the environment:

```env
ENABLE_HLS_TOKEN_VALIDATION=true
```

3.0 reads your old `config.json` value and carries it forward, which is normally
the helpful behaviour, but production refuses to start with that gate disabled.
So a deployment that had it off inherits `false`, fails validation on first boot,
and **cannot be fixed from the admin panel, because the toggle moved out of it.**
The environment variable is the only way back. If you never touched that setting
it has always been `true`, and there is nothing to do.

One behavioural change to be aware of even when nothing needs editing:
`SESSION_EXPIRY` now genuinely sets the session cookie lifetime, so with the
default `86400` people are asked to rejoin after 24 hours idle rather than 14
days. See the section on it below.

## Breaking changes

3.0 changes deployment requirements and configuration ownership:

- `EMBY_SERVER_URL` and `JELLYFIN_SERVER_URL` become `MEDIA_SERVER_URL`;
  `EMBY_API_KEY` and `JELLYFIN_API_KEY` become `MEDIA_SERVER_API_KEY`. No
  aliases, no fallback reads, and a retired name still present is a boot error.
  `MEDIA_SERVER_TYPE` is unchanged and still has to be stated.
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

## Run the read-only preflight

Back up `.env`, the Compose/container definition, `config.json`, `data/`,
`images/avatars/`, and every volume mapping first. Then run the 3.0 image's
preflight against the same environment and mounts the application will use:

```bash
docker compose run --rm --no-deps emby-watchparty python -m backend.migration_preflight
```

The command only reads migration inputs. It does not load the normal mutating
configuration path, write settings, move malformed files, clean stale setup
artifacts, or print session secrets, API keys, tokens, credentials, or cookies.
It exits `0` when inspection completed, even when work remains. It exits `1`
only when an input could not be inspected, such as malformed JSON or a path
that is a directory instead of a file.

Interpret every line by its prefix:

- `ERROR` means an input was malformed or unreadable. Fix it before relying on
  the rest of the report.
- `REQUIRED ACTION` is an operator step that must be completed or explicitly
  confirmed. This includes backup and rollback readiness; exit `0` does not
  certify that a backup exists.
- `INFO` records an effective setting, its safe source, a preserved path, or a
  behavior change to validate.

For a source checkout, include runtime checks:

```bash
python -m backend.migration_preflight --deployment source
```

On Windows use `.venv\Scripts\python.exe` in place of `python`. Windows results
are best effort and recommend Docker/Linux for production. On Unraid, CasaOS,
Portainer, and TrueNAS, run the same module as a one-shot command using the 3.0
image, the production container's environment, and the same read-only appdata
mounts; set the command override to
`python -m backend.migration_preflight --root /app`. Plain Docker users can use:

```bash
docker run --rm --env-file .env \
  -v "$PWD/config.json:/app/config.json:ro" \
  -v "$PWD/data:/app/data:ro" \
  -v "$PWD/images/avatars:/app/images/avatars:ro" \
  IMAGE python -m backend.migration_preflight --root /app
```

Replace `IMAGE` with the exact 3.0 image being tested. Never paste secret values
into a support request.

## Docker Compose upgrade

1. Stop the watch-party container. Emby can remain online.
2. Back up `.env`, the effective Compose configuration, `config.json`, `data/`,
   `images/avatars/`, and the volume mappings. Keep the old image reference.
3. Keep these mounts:

   ```yaml
   volumes:
     - ./data:/app/data
     - ./images/avatars:/app/images/avatars
     - ./config.json:/app/config.json
   ```

   Create the host-side `config.json` as a file before starting Compose.
4. Point the Compose service at the chosen 3.0 beta image (or `build: .` from
   `3.0-dev`) and pull it. The preflight ships *in* the 3.0 image; a 2.1.x
   image has no such module, so this has to come first.
5. Run the preflight and resolve every required production action.
6. Start the container and inspect its logs.

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

Treat `SESSION_SECRET` and `MEDIA_SERVER_API_KEY` as credentials. Never attach
them to an issue or support log.

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
3. Supported legacy persisted value (`ENABLE_HLS_TOKEN_VALIDATION` only)
4. Code defaults

Process-environment and `.env` are one explicit-operator tier, with process
values winning. Reading `.env` does not mutate the running process environment.
Runtime settings such as rate limits continue to come from `config.json`; the
preflight reports each effective value and its source because 3.0 enforces it.

## Required production boot values

A typical reverse-proxy deployment supplies:

```env
APP_ENV=production
MEDIA_SERVER_TYPE=emby
MEDIA_SERVER_URL=http://emby:8096
MEDIA_SERVER_API_KEY=your-dedicated-emby-api-key
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
hour and 30 socket connects per minute for the entire deployment. 2.x was
unaffected because none of these limits were enforced. 3.0 now names a blocked
action and its safe retry delay in the affected form or connection banner.

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

### `SESSION_EXPIRY` now actually sets the session cookie lifetime

`.env.example` has always described `SESSION_EXPIRY` as the session cookie
lifetime. It was not. The cookie was hardcoded to 14 days and the setting
governed only how long an administrator session survived server-side, so at
the shipped defaults the cookie outlived the admin session by thirteen days.

From 3.0 the cookie uses `SESSION_EXPIRY` as documented. **With the default
`86400` your users are asked to rejoin after 24 hours of inactivity rather
than 14 days.** If you want the old behaviour, set it explicitly:

```env
SESSION_EXPIRY=1209600
```

The administrator session TTL is now an idle timeout rather than an absolute
one, so it renews on use. Previously a host who logged in 24 hours earlier
lost admin controls part-way through a session, while the party cookie kept
working, so nothing on screen explained why the controls had disappeared.
Logging out still ends the session immediately.

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

## Performance

Nothing here needs action; it is recorded so a change in throughput after
upgrading is explainable rather than mysterious.

3.0 restores `uvicorn[standard]`, which pulls in the platform-appropriate
accelerators: `uvloop` and `httptools` on Linux, `httptools` and `websockets` on
Windows. Early 3.0 development builds shipped plain `uvicorn`, and on those the
HLS proxy ran on the pure-Python event loop and HTTP parser. If you tested a
development build and found streaming slower than 2.1.x, that is why, and the
release does not carry it.

Segment delivery also changed shape. 2.1.x read each `.ts` segment fully into
memory before responding; 3.0 streams it and tears the upstream Emby request
down when the client disconnects. Peak memory per viewer drops and an abandoned
seek no longer leaves a transcode running, but the first byte now depends on
Emby's own responsiveness rather than arriving after the whole segment was
buffered locally.

Run exactly one worker, as before. Party state, administrator sessions, HLS
grants and rate-limit buckets are all process-local, so a second worker does not
share them.

## Validation checklist

Before directing users to 3.0:

- `curl -i http://HOST:PORT<APP_PREFIX>/api/health` returns `200` with
  `status: ok`, not `setup_required`.
- `curl -i http://HOST:PORT<APP_PREFIX>/api/ready` returns `200` and reaches
  Emby.

  Both probes are mounted under `APP_PREFIX`. On a subpath deployment the
  unprefixed URL returns `404` against a perfectly healthy server, and against
  a misconfigured one it falls through to the unprefixed catch-all and returns
  `503`, which reads as "dead" rather than "misconfigured". Leave the
  placeholder out entirely when `APP_PREFIX` is empty. The preflight prints
  both URLs already resolved for your configuration.
- Administrator login, renewed admin controls, and logout work.
- Create two separate parties and verify an HLS URL from one cannot be used
  with the other party's cookie.
- Test the master playlist, media playlist, segment playback, byte ranges,
  pause/resume, forward and backward seeking, audio, subtitles, and an
  alternate media version.
- Disconnect/reconnect a participant, reload the host page, and confirm both
  identities resume the same party and receive a fresh playable stream.
- In a staging party, temporarily use a low rate limit and confirm create,
  join/session binding, Socket.IO reconnect, chat, login, and avatar recovery
  show the backend message and retry delay. Restore the production value.
- Confirm logs do not contain Emby tokens, session secrets, or setup tokens.
- Confirm `/hls` and health request logs remain at DEBUG volume.

Keep the old configuration and image until every playback check passes. The
automated fake-Emby gate is `cd frontend && npm run test:playback-gate`; it does
not replace testing real media, a physical iPhone/iPad, and the actual proxy.

## Rollback

Stop 3.0. Restore the full backup: the previous image reference, `.env`,
Compose/container definition, `config.json`, data, avatars, and volume mappings.
Then start the old container and validate its health. Do not point 2.1.x at
files 3.0 used or delete legacy data; restoring the complete backup is the
supported rollback.
