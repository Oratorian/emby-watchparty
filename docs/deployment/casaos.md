# CasaOS deployment

Import `deploy/casaos/docker-compose.yml`. Its service is derived from
`docker-compose.yml.example`, with CasaOS paths, environment entry, and top-level `x-casaos`
metadata added as a thin wrapper. Publishing to an AppStore is outside this project change.
CasaOS offers no protected secret primitive in this manifest. Host administrators can read saved
environment values.

The container bind and target are fixed at `0.0.0.0:5000`. Change only CasaOS's published host
port field when another external port is needed.

## Setup or 2.1.x migration

1. Disable automatic updates. Record old image/digest, installed Compose, ports, networks,
   variables, and volumes.
2. Back up installed Compose, `config.json`, data, avatars, logs, environment values, and every
   mapped path. Preserve old 2.1.x image and full configuration.
3. Ensure app data directories exist, and create `config.json` containing `{}` **only if
   it does not already exist**. A 2.1.x upgrade must keep its existing file: overwriting
   it discards every admin setting and blinds the preflight below. Use `echo {}` rather
   than `touch`, since an empty file is quarantined as invalid JSON on every boot.
4. Import manifest. Enter required values in app settings/Compose, leaving the container bind and
   port fixed. Secret fields start blank and fail closed.

   Two settings ship **commented out** because neither has a safe default, and the app
   refuses to start rather than guess:

   - `BEHIND_PROXY` must be declared `true` or `false`. Rate limiting keys on the
     connecting address, so behind a proxy that address is the proxy for every viewer and
     they all share one bucket. `true` also makes `TRUSTED_PROXY_CIDRS` mandatory.
   - `SESSION_COOKIE_SECURE` follows how you actually reach the app. Set `true` when a TLS
     terminator sits in front, and point the appliance tile at that HTTPS address. Set
     `false` only for a plain-HTTP LAN address: a Secure cookie is **silently discarded**
     by the browser over `http://`, so the app appears to start correctly and then rejects
     every request after party creation with "No party session".

   `APP_ENV=production` additionally requires `SESSION_COOKIE_SECURE=true`, so a plain-HTTP
   deployment needs either a TLS terminator or `APP_ENV=development`, which also drops the
   `SESSION_SECRET`, CORS and HLS-token gates. Prefer the terminator.
5. Duplicate candidate Compose with identical environment and volumes. Temporarily add:

   ```yaml
   command: ["python", "-m", "backend.migration_preflight", "--root", "/app", "--target", "production", "--deployment", "docker"]
   restart: "no"
   ```

6. Start candidate, read app logs, and block on every `ERROR` or `REQUIRED ACTION`; `INFO` records
   context. Do not rely on zero exit status when required actions exist.
7. Remove command override, restore `restart: unless-stopped`, and start 3.0.
8. Query `/api/health`, `/api/ready`, then complete shared playback checks.

When CasaOS UI cannot perform one-shot override safely, edit a secured copy of installed Compose
through supported host access. Never paste secrets into command lines or support output.

## Update and rollback

CasaOS rollback is manual. Save installed Compose, exact previous image/digest, and full mapped
data before update. Restore all three on failure. Do not assume a mutable tag re-pulls or that
CasaOS rolls back data. Never delete legacy files.
