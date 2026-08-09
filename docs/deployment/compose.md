# Docker Compose deployment

Use `docker-compose.yml.example` and `.env.example`; both are generated from
`deploy/schema.json`.

The supplied container always binds `0.0.0.0:5000`. To publish another host port, change only
the left side of `HOST_PORT:5000` under `ports`; do not change `WATCH_PARTY_BIND`,
`WATCH_PARTY_PORT`, or the container-side port.

## Setup or 2.1.x migration

1. Disable automatic updates. Record old image tag/digest, Compose file, environment,
   ports, networks, and every volume mapping.
2. Back up `.env`, Compose configuration, `config.json`, `data/`, `images/avatars/`, and
   optional logs. Keep old 2.1.x image and complete configuration.
3. Copy examples to `docker-compose.yml` and `.env`. Create directories and an empty JSON
   object before Compose can turn the file path into a directory:

   ```sh
   mkdir -p data images/avatars logs
   printf '{}\n' > config.json
   ```

4. Fill every required `.env` field except the pinned container bind/port. Generate
   `SESSION_SECRET` once. Set `BEHIND_PROXY` explicitly. If true, use only actual proxy source
   CIDRs.
5. Run read-only preflight with exact candidate environment and volumes:

   ```sh
   docker compose run --rm --no-deps emby-watchparty \
     python -m backend.migration_preflight \
     --root /app --target production --deployment docker
   ```

6. Treat every `ERROR` and `REQUIRED ACTION` as blocking. `INFO` records context. Current
   preflight can exit zero while reporting a required action.
7. Start with `docker compose up -d emby-watchparty`.
8. Query `/api/health` and `/api/ready`; follow
   [appliance validation](appliance-migration.md) before accepting migration.

Do not publish `docker compose config` output for diagnosis: rendered output can contain
environment secrets.

## Update and rollback

Back up first, record current digest, pull candidate, rerun preflight, then recreate only this
service. Rollback means restoring previous Compose/environment files, image reference, and full
data/config backup. Never delete legacy files after migration.
