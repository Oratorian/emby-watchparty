# CasaOS deployment

Import `deploy/casaos/docker-compose.yml`. Its service is derived from
`docker-compose.yml.example`, with CasaOS paths, environment entry, and top-level `x-casaos`
metadata added as a thin wrapper. Publishing to an AppStore is outside this project change.
CasaOS offers no protected secret primitive in this manifest. Host administrators can read saved
environment values.

## Setup or 2.1.x migration

1. Disable automatic updates. Record old image/digest, installed Compose, ports, networks,
   variables, and volumes.
2. Back up installed Compose, `config.json`, data, avatars, logs, environment values, and every
   mapped path. Preserve old 2.1.x image and full configuration.
3. Ensure app data directories exist and `config.json` contains `{}`.
4. Import manifest. Enter required values in app settings/Compose. Keep production security
   defaults; declare proxy topology explicitly. Secret fields start blank and fail closed.
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
