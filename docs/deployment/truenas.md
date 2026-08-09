# TrueNAS SCALE 24.10+ deployment

Use `deploy/truenas/custom-app.yml` through **Install via YAML**. Its service is derived from
`docker-compose.yml.example`, with TrueNAS host paths added as a thin wrapper. Replace `POOL` with
the existing dataset path. TrueNAS performs basic YAML validation only; this is not a catalog app.
Host-path datasets are outside catalog rollback protection.

## Setup or 2.1.x migration

1. Disable automatic updates. Record old image/digest, Custom App YAML, environment, ports, and
   storage mappings.
2. Back up YAML and environment securely. Snapshot datasets containing `config.json`, data,
   avatars, and logs. Preserve old 2.1.x image/configuration.
3. Create host-path directories and `config.json` containing `{}`. Replace every `/mnt/POOL`
   placeholder before deployment.
4. Paste YAML and fill blank required environment values. Keep production security defaults.
   Declare proxy topology using actual source CIDRs only.
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
