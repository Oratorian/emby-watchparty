# Unraid deployment

Import `deploy/unraid/emby-watchparty.xml`. Secret inputs use `Mask=true`; this hides UI text but
does not encrypt Docker environment or saved templates.

## Setup or 2.1.x migration

1. Disable automatic updates. Record old image tag/digest, container template, ports, networks,
   Post Arguments, and every path mapping.
2. Back up saved XML under `/boot/config/plugins/dockerMan/templates-user`, environment values,
   `config.json`, data, avatars, logs, and all mapped appdata. Preserve old image/configuration.
3. Create appdata directories and `config.json` containing `{}` before install.
4. Fill template variables. Keep `APP_ENV=production`, HLS validation enabled, and one container.
   Declare proxy topology; never copy a broad CIDR without matching actual proxy network.
5. For migration, duplicate candidate template with same variables and paths. Disable Auto-Start.
   Temporarily set Post Arguments to:

   ```text
   python -m backend.migration_preflight --root /app --target production --deployment docker
   ```

6. Create one-shot candidate, read Logs, and block on every `ERROR` or `REQUIRED ACTION` even if
   container exit code is zero. `INFO` is contextual.
7. Clear Post Arguments, retain same variables/mounts, and Apply to recreate normal container.
8. Open WebUI, query `/api/health` and `/api/ready`, then complete shared playback checks.

If duplicate command workflows are difficult, use Advanced View to copy existing template first;
do not put secrets in terminal command arguments. Console preflight after startup is diagnostic
fallback, not preferred migration gate.

## Update and rollback

Save XML and appdata backup plus immutable old image reference before Update. Unraid recreation
does not replace full rollback backup. Restore saved XML, previous image, and all appdata on
failure. Keep legacy state through playback validation; delete nothing.
