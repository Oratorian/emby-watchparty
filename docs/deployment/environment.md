<!-- Generated from deploy/schema.json; do not edit. -->
<!-- Schema-Version: 1 -->
<!-- Schema-SHA256: 3d72f870f57b7dde8f468e08dbc1823e8e5e14ebe730af5ff84332064df098ed -->
# Deployment environment

Generated from `deploy/schema.json`. Every field requires container recreation.

| Variable | Type | Required | Secret | Validation | Safe example | Description |
| --- | --- | --- | --- | --- | --- | --- |
| `WATCH_PARTY_BIND` | string | always | no | <code>{"format":"ip_or_hostname"}</code> | <code>"0.0.0.0"</code> | Address listened on inside the container. Supplied container artifacts pin this to 0.0.0.0. |
| `WATCH_PARTY_PORT` | integer | always | no | <code>{"maximum":65535,"minimum":1}</code> | <code>5000</code> | Port listened on inside the container. Supplied container artifacts pin this to 5000; change only the published host port. |
| `APP_PREFIX` | path_prefix | optional | no | <code>{"maximum_length":256,"pattern":"^$&#124;^(?:/[A-Za-z0-9][A-Za-z0-9._~-]*)+$"}</code> | <code>"/watchparty"</code> | Optional slash-prefixed reverse-proxy subpath. |
| `SESSION_EXPIRY` | integer | always | no | <code>{"minimum":1}</code> | <code>86400</code> | Signed session-cookie lifetime in seconds. |
| `EMBY_SERVER_URL` | http_url | production | no | <code>{"schemes":["http","https"]}</code> | <code>"http://emby:8096"</code> | HTTP(S) URL reachable from the container to Emby. |
| `EMBY_API_KEY` | string | production | yes | <code>{"minimum_length":1}</code> | — | Dedicated Emby administrative API key. |
| `APP_ENV` | enum | always | no | <code>{"allowed":["development","production"]}</code> | <code>"production"</code> | Security validation mode; appliances use production. |
| `SESSION_SECRET` | string | production | yes | <code>{"minimum_length_in_production":32}</code> | — | Stable signing secret generated once and retained across updates. |
| `SESSION_COOKIE_SECURE` | boolean | always | no | <code>{"allowed_strings":["true","false","1","0","yes","no"]}</code> | <code>true</code> | Restrict session cookies to HTTPS. |
| `CORS_ALLOWED_ORIGINS` | csv_http_origins | production | no | <code>{"item_schemes":["http","https"]}</code> | <code>"https://watchparty.example.com"</code> | Comma-separated public HTTP(S) origins allowed by Socket.IO. |
| `TRUSTED_PROXY_CIDRS` | csv_cidr | when_proxy | no | <code>{"items":"cidr"}</code> | <code>"192.0.2.0/24"</code> | Comma-separated proxy source networks trusted for forwarded client IPs. |
| `ENABLE_HLS_TOKEN_VALIDATION` | boolean | always | no | <code>{"allowed_strings":["true","false","1","0","yes","no"]}</code> | <code>true</code> | Validate signed HLS playlist and segment tokens. |
| `BEHIND_PROXY` | boolean | production | no | <code>{"allowed_strings":["true","false","1","0","yes","no"]}</code> | <code>false</code> | Declare whether a reverse proxy terminates client connections. |

BEHIND_PROXY=true requires TRUSTED_PROXY_CIDRS; no universal CIDR is safe.
Production requires explicit origins, secure cookies, and HLS token validation.
Secret fields are intentionally blank. Generate and enter values outside tracked files.
