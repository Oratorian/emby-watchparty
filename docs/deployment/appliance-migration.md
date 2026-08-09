# Appliance migration, diagnosis, and acceptance

Platform guides: [Compose](compose.md), [Unraid](unraid.md), [CasaOS](casaos.md),
[Portainer](portainer.md), and [TrueNAS SCALE](truenas.md).

## Preflight interpretation

Preflight is read-only and never prints secret values. Run it in candidate image with same
environment and volumes as normal application.

- `ERROR`: input was unreadable or invalid. Stop.
- `REQUIRED ACTION`: operator change required. Stop even if process exits zero.
- `INFO`: observed context or guidance; review it.

Platforms with poor one-shot support should use temporary duplicate container/stack/app with
command override and restart disabled. Do not pass secrets on command line.

## Health and diagnosis

Query paths under configured `APP_PREFIX`:

| Health | Ready | Meaning |
| --- | --- | --- |
| `200 ok` | `200 ready` | Runtime ready |
| `200 ok` | `503 not_ready` | Inspect Emby reachability and storage |
| `200 setup_required` | `503 setup_required` | Invalid production configuration |
| Connection failure | Connection failure | Container, port, bind, or network failure |

Normal routes returning 503 during `setup_required` is expected fail-closed behavior. Read
container stderr for every invalid variable name. Logs, health, and readiness must never contain
secret values, limiter bucket identifiers, or client IPs. Do not share raw environment, Inspect,
cookies, URLs with credentials, or rendered Compose.

## Playback acceptance

After health and readiness pass, test through final public URL:

1. Login and create a party; join from second browser/device.
2. Browse Emby library and start direct play plus HLS/transcoded media.
3. Pause/resume and seek both directions; confirm second client follows.
4. Switch subtitles/audio and quality where available.
5. Refresh/disconnect/reconnect; confirm Socket.IO and party recovery.
6. Confirm HLS URLs expose no Emby API key and production token validation stays enabled.
7. Trigger or observe rate-limit feedback without exposing buckets/IPs.
8. Restart once; confirm stable `SESSION_SECRET` and `/api/ready` returns 200 again.

## Rollback rule

Keep complete 2.1.x image, environment, configuration, `config.json`, data, avatars, logs, and
volume mappings until playback acceptance succeeds. Rollback restores complete backup and
previous image/configuration. Never delete legacy configuration or data after migration.
