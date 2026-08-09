<!-- Generated from deploy/schema.json; do not edit. -->
<!-- Schema-Version: 1 -->
<!-- Schema-SHA256: 6da4b3538b883f26e2e26b1337045b2b28a8d05c01033454cf64d58b7e881d4c -->
# Deployment environment

Generated from `deploy/schema.json`. Every field requires container recreation.

| Variable | Type | Required | Secret | Description |
| --- | --- | --- | --- | --- |
| `WATCH_PARTY_BIND` | string | always | no | Address listened on inside the container. |
| `WATCH_PARTY_PORT` | integer | always | no | Port listened on inside the container. |
| `APP_PREFIX` | path_prefix | optional | no | Optional slash-prefixed reverse-proxy subpath. |
| `SESSION_EXPIRY` | integer | always | no | Signed session-cookie lifetime in seconds. |
| `EMBY_SERVER_URL` | http_url | production | no | HTTP(S) URL reachable from the container to Emby. |
| `EMBY_API_KEY` | string | production | yes | Dedicated Emby administrative API key. |
| `APP_ENV` | enum | always | no | Security validation mode; appliances use production. |
| `SESSION_SECRET` | string | production | yes | Stable signing secret generated once and retained across updates. |
| `SESSION_COOKIE_SECURE` | boolean | always | no | Restrict session cookies to HTTPS. |
| `CORS_ALLOWED_ORIGINS` | csv_http_origins | production | no | Comma-separated public HTTP(S) origins allowed by Socket.IO. |
| `TRUSTED_PROXY_CIDRS` | csv_cidr | when_proxy | no | Comma-separated proxy source networks trusted for forwarded client IPs. |
| `ENABLE_HLS_TOKEN_VALIDATION` | boolean | always | no | Validate signed HLS playlist and segment tokens. |
| `BEHIND_PROXY` | boolean | production | no | Declare whether a reverse proxy terminates client connections. |

BEHIND_PROXY=true requires TRUSTED_PROXY_CIDRS; no universal CIDR is safe.
Production requires explicit origins, secure cookies, and HLS token validation.
Secret fields are intentionally blank. Generate and enter values outside tracked files.
