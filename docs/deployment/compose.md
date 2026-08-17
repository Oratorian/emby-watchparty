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
3. Copy examples to `docker-compose.yml` and `.env`. Create the directories, and
   `config.json` **only if it does not already exist**, so Compose cannot turn that path
   into a directory:

   ```sh
   mkdir -p data images/avatars logs
   [ -f config.json ] || echo {} > config.json
   ```

   **A 2.1.x upgrade must keep its existing `config.json`.** Overwriting it discards every
   admin setting, including the `ENABLE_HLS_TOKEN_VALIDATION=false` that makes production
   refuse to boot, which is the one thing the preflight in step 5 exists to warn you about.
   Use `echo {}` rather than `touch`: an empty file is not valid JSON, so it is quarantined
   as `config.json.corrupt-<timestamp>` on every boot.

4. Fill every required `.env` field except the pinned container bind/port. Generate
   `SESSION_SECRET` once. Set `BEHIND_PROXY` explicitly. If true, use only actual proxy source
   CIDRs. `MEDIA_SERVER_URL` and `MEDIA_SERVER_API_KEY` serve both providers; `MEDIA_SERVER_TYPE`
   is the only setting that distinguishes them, and Emby remains its default. For Jellyfin use:

   ```env
   MEDIA_SERVER_TYPE=jellyfin
   MEDIA_SERVER_URL=http://jellyfin:8096
   MEDIA_SERVER_API_KEY=your-dedicated-jellyfin-api-key
   ```

   The key must be issued by the server `MEDIA_SERVER_TYPE` names. Changing providers requires a
   restart. A 2.1.x environment still carrying `EMBY_SERVER_URL`, `JELLYFIN_SERVER_URL`,
   `EMBY_API_KEY` or `JELLYFIN_API_KEY` fails the boot with the name of its replacement: those
   names were retired in 3.0 and are never read. Under Compose the retired name can also sit in
   the service `environment:` block, which outranks `env_file`, so check both.
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

Jellyfin support is HLS-only. HLS stream copy/remux/transcode are supported;
progressive/direct-file playback, Live TV, and Jellyfin SyncPlay are not. The
app interoperates through Jellyfin HTTP contracts and does not reuse Jellyfin
Web source.

## Update and rollback

Back up first, record current digest, pull candidate, rerun preflight, then recreate only this
service. Rollback means restoring previous Compose/environment files, image reference, and full
data/config backup. Never delete legacy files after migration.
