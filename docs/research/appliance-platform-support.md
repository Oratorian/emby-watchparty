# Appliance deployment research verification

Verified 2026-08-08 against primary project and platform sources. This note records packaging
support, not native compatibility test results.

## Accepted conclusions

- Docker Compose is common runtime model. Environment interpolation and service environment are
  distinct, and service `environment` has higher precedence than `env_file`.
  [Docker environment documentation](https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/)
- Unraid templates expose environment, port, path, logs, console, and edit/recreate workflows.
  Its WebGUI implements `Required` and password-style `Mask`; masking is presentation, not secret
  storage. [Unraid container documentation](https://docs.unraid.net/unraid-os/using-unraid-to/run-docker-containers/managing-and-customizing-containers/)
  and [WebGUI source](https://github.com/unraid/webgui/blob/master/emhttp/plugins/dynamix.docker.manager/include/CreateDocker.php)
- CasaOS AppStore v2 source is standard Compose plus top-level `x-casaos`. Runtime configuration
  stays in standard Compose sections.
  [CasaOS v2 specification](https://github.com/IceWhaleTech/CasaOS-AppStore/blob/main/docs/specs/compose-and-x-casaos.md)
- Portainer Docker Standalone accepts Compose stacks and separately managed environment variables.
  [Portainer stack documentation](https://docs.portainer.io/sts/user/docker/stacks/add)
- TrueNAS SCALE 24.10+ supports Custom Apps through Docker settings or Compose YAML. TrueNAS only
  performs basic YAML validation on Custom App YAML.
  [TrueNAS Custom App documentation](https://www.truenas.com/docs/scale/apps/installcustomappscreens/)
- TrueNAS host paths require separate backup/rollback handling; app rollback must not be described
  as complete data rollback.
  [TrueNAS Apps documentation](https://www.truenas.com/docs/scale/apps/apps/)

## Rejected or deferred conclusions

- No `--strict` preflight flag: PR #57 behavior remains unchanged. Operators treat every
  `REQUIRED ACTION` as blocking even when exit code is zero.
- No migration of admin-managed runtime settings from `config.json`: this deployment schema covers
  boot/appliance environment only. `config.json` remains mounted and backed up.
- No TrueNAS catalog package: Custom App YAML is supported first; catalog maintenance ownership is
  unresolved.
- No generated Unraid template: the maintainer owns the separate templates repository, which
  Community Apps indexes through `TemplateURL`. Its WebUI-driven packaging is reviewed there
  instead of being duplicated by this schema.
- No universal `TRUSTED_PROXY_CIDRS` default: topology must be explicit and deployment-specific.
- No CasaOS protected-secret or transactional-rollback claim: primary protocol defines packaging,
  not those guarantees.
- No native compatibility claim from schema or Compose validation. Real CasaOS, Portainer, and
  TrueNAS UI checks remain manual release gates; Unraid Community Apps packaging has its own review.

## Security boundary

Environment-only deployment does not make values secret from host or Docker administrators.
Generated artifacts leave `SESSION_SECRET` and `MEDIA_SERVER_API_KEY` blank, never print rendered
environment, never include client IPs or limiter buckets, and retain production HLS validation.
Operators keep full backups and previous image/configuration until real playback succeeds.
