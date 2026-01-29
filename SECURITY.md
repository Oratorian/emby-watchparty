# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.4.x   | :white_check_mark: |
| < 1.4   | :x:                |

We recommend always running the latest version for security updates and improvements.

## Reporting a Vulnerability

We take security vulnerabilities seriously. If you discover a security issue, please report it responsibly.

### How to Report

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, please send a detailed report to the repository maintainers via:

1. **GitHub Security Advisories** (preferred): Use the "Report a vulnerability" button in the Security tab of this repository
2. **Private disclosure**: Contact the maintainers directly through GitHub

### What to Include

When reporting a vulnerability, please include:

- A clear description of the vulnerability
- Steps to reproduce the issue
- Potential impact assessment
- Any suggested fixes (if applicable)
- Your contact information for follow-up

### Response Timeline

- **Initial Response**: Within 48 hours
- **Status Update**: Within 7 days
- **Resolution Target**: Depends on severity (critical issues prioritized)

## Security Best Practices

### Deployment Security

#### Use HTTPS/TLS

Always deploy behind a reverse proxy with TLS termination when exposing to the internet:

```nginx
# Example nginx configuration
server {
    listen 443 ssl;
    server_name watchparty.example.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

#### Network Architecture

- Keep your Emby server on an internal network when possible
- Use VPN solutions (Tailscale, WireGuard) for remote access to internal services
- The watch party application acts as a proxy, so your Emby server doesn't need direct internet exposure

### Configuration Security

#### Environment Variables

Never commit your `.env` file. It contains sensitive credentials:

```bash
# These should NEVER be in version control
EMBY_API_KEY=your_api_key
EMBY_PASSWORD=your_password
```

Ensure your `.env` file has restricted permissions:

```bash
chmod 600 .env
```

#### API Key Protection

- Use a dedicated Emby API key for the watch party application
- Limit API key permissions where possible
- Rotate API keys periodically
- Never share API keys in logs or error messages

### Application Security Features

#### Rate Limiting

Enable rate limiting to prevent abuse:

```env
ENABLE_RATE_LIMITING=true
```

The application uses Flask-Limiter to protect against brute force and DoS attempts.

#### Token Validation

HLS streaming tokens provide time-limited access:

```env
ENABLE_HLS_TOKEN_VALIDATION=true
HLS_TOKEN_EXPIRY=86400  # 24 hours in seconds
```

#### Session Security

- Sessions expire after configurable time (`SESSION_EXPIRY`)
- Cookies use `SameSite=Lax` for CSRF protection
- Session tokens are cryptographically generated using Python's `secrets` module

#### Party Size Limits

Limit users per party to prevent resource exhaustion:

```env
MAX_USERS_PER_PARTY=10
```

### Docker Security

When running in Docker:

```yaml
services:
  emby-watchparty:
    image: ghcr.io/oratorian/emby-watchparty:latest
    read_only: true  # Read-only filesystem where possible
    security_opt:
      - no-new-privileges:true
    env_file:
      - .env
```

### Logging Security

- Avoid logging sensitive information (passwords, API keys, tokens)
- Configure appropriate log levels for production:

```env
LOG_LEVEL=WARNING
CONSOLE_LOG_LEVEL=ERROR
```

- Ensure log files have appropriate permissions when `LOG_TO_FILE=true`

## Known Security Considerations

### Authentication Model

- The application relies on Emby server authentication
- Users authenticate with their Emby credentials
- Library access respects Emby user permissions

### Session Handling

- Sessions are stored server-side
- Session IDs are cryptographically random
- Consider using Redis for session storage in clustered deployments

### WebSocket Security

- WebSocket connections should be protected by the same TLS termination as HTTP
- Rate limiting applies to WebSocket events
- Invalid messages are rejected and logged

## Security Updates

Security updates are released as patch versions (e.g., 1.4.1, 1.4.2). Monitor:

- GitHub Releases for new versions
- CHANGELOG.md for security-related changes
- GitHub Security Advisories for vulnerability disclosures

## Acknowledgments

We appreciate responsible security researchers who help keep this project secure. Contributors who report valid security issues will be acknowledged (with permission) in release notes.
