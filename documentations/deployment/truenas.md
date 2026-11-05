# TrueNAS SCALE 24.10+ deployment

Use `deploy/truenas/custom-app.yml` through **Install via YAML**. Its service is derived from
`docker-compose.yml.example`, with TrueNAS host paths added as a thin wrapper. Replace `POOL` with
the existing dataset path. TrueNAS performs basic YAML validation only; this is not a catalog app.
Host-path datasets are outside catalog rollback protection.

The workload always binds `0.0.0.0:5000`. To expose another host port, change only the published
side of the TrueNAS port mapping; keep its container target and `WATCH_PARTY_PORT` at `5000`.

## Setup or 2.1.x migration

1. Disable automatic updates. Record old image/digest, Custom App YAML, environment, ports, and
   storage mappings.
2. Back up YAML and environment securely. Snapshot datasets containing `config.json`, data,
   avatars, and logs. Preserve old 2.1.x image/configuration.
3. Create host-path directories, and `config.json` containing `{}` **only if it does not
   already exist**. A 2.1.x upgrade must keep its existing file: overwriting it discards
   every admin setting and blinds the preflight below. Use `echo {}` rather than
   `touch`, since an empty file is quarantined as invalid JSON on every boot. Replace every `/mnt/POOL`
   placeholder before deployment.
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
5. For candidate preflight, temporarily add:

   ```yaml
   command: ["python", "-m", "backend.migration_preflight", "--root", "/app", "--target", "production", "--deployment", "docker"]
   restart: "no"
   ```

6. Deploy, inspect workload/container logs, and block on `ERROR` or `REQUIRED ACTION` even when
   exit status is zero. `INFO` is contextual.
7. Remove command override, restore restart policy, and redeploy normal app.
8. Query `/api/health`, `/api/ready`, then complete shared playback checks.

Use WebUI-supported configuration changes. If one-shot command override is difficult, create a
temporary Custom App copy with same env and mounts. Do not expose secrets through shell history.

## Update and rollback

Save prior YAML and exact image reference; snapshot host-path datasets separately. Restore YAML,
image, environment, and dataset snapshot on failure. Never claim TrueNAS app rollback restores
host paths. Keep legacy data until playback validation succeeds; delete nothing.
