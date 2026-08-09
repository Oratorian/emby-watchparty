# Portainer Docker Standalone deployment

Use generated `docker-compose.yml.example` as uploaded or Web Editor stack. Target is Docker
Standalone, not Swarm. Manage interpolation variables through Portainer stack environment.
Portainer administrators and raw container inspection can read environment values.

The imported service always listens on container port `5000`. To use another external port,
change only Portainer's published host port; keep `WATCH_PARTY_BIND=0.0.0.0`,
`WATCH_PARTY_PORT=5000`, and the container-side mapping unchanged.

## Setup or 2.1.x migration

1. Disable webhooks/automatic updates. Record old image/digest, stack file/version, environment,
   endpoint, network, ports, and volumes.
2. Back up stack configuration, separately export environment values securely, and back up
   `config.json`, data, avatars, logs, and all host paths. Preserve old image/configuration.
3. Use absolute Docker-host paths; create directories, and `config.json` containing `{}`
   **only if it does not already exist**. A 2.1.x upgrade must keep its existing file:
   overwriting it discards every admin setting and blinds the preflight below. Use
   `echo {}` rather than `touch`, since an empty file is quarantined as invalid JSON.
4. Upload/paste generated Compose. Enter all non-network stack variables. Set production security
   fields and declare proxy topology without a universal CIDR.
5. Before normal start, temporarily add to service:

   ```yaml
   command: ["python", "-m", "backend.migration_preflight", "--root", "/app", "--target", "production", "--deployment", "docker"]
   restart: "no"
   ```

6. Deploy candidate with exact environment/mounts. Read container Logs. Block on `ERROR` and
   `REQUIRED ACTION` even when exit status is zero; use `INFO` as context.
7. Restore normal command and `restart: unless-stopped`; redeploy stack.
8. Query `/api/health`, `/api/ready`, then complete shared playback checks.

Do not paste raw Inspect or rendered stack output into support channels. For difficult one-shot
workflows, create a temporary duplicate stack rather than exposing secrets in terminal commands.

## Update and rollback

Portainer editor history is not data rollback and environment values remain separate. Save old
stack, environment, image/digest, and full host-path backup. Restore all on failure. Never delete
legacy configuration or data.
