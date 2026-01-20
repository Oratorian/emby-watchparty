"""
Configuration for Emby Watch Party application
Loads settings from .env file with fallback defaults
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from project root
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)


# ============== Application Configuration ==============

WATCH_PARTY_BIND = os.getenv('WATCH_PARTY_BIND', '0.0.0.0')
WATCH_PARTY_PORT = int(os.getenv('WATCH_PARTY_PORT', '5000'))

REQUIRE_LOGIN = os.getenv('REQUIRE_LOGIN', 'false').lower()
SESSION_EXPIRY = int(os.getenv('SESSION_EXPIRY', '86400'))  # Default: 24 hours (in seconds)


# ============== Emby Server Configuration ==============

EMBY_SERVER_URL = os.getenv('EMBY_SERVER_URL', 'http://localhost:8096')
EMBY_API_KEY = os.getenv('EMBY_API_KEY', '')
EMBY_USERNAME = os.getenv('EMBY_USERNAME', '')
EMBY_PASSWORD = os.getenv('EMBY_PASSWORD', '')


# ============== Logging Configuration ==============

LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
LOG_FILE = os.getenv('LOG_FILE', 'logs/emby-watchparty.log')
LOG_FORMAT = 'rsyslog'  # rsyslog-style formatting
LOG_MAX_SIZE = int(os.getenv('LOG_MAX_SIZE', '10'))  # Size in MB (rsyslog-logger 1.0.5+)
CONSOLE_LOG_LEVEL = os.getenv('CONSOLE_LOG_LEVEL', 'WARNING')


# ============== Security Configuration ==============
# Educational/Private Use Only - See README for deployment warnings

# Party size limits
MAX_USERS_PER_PARTY = int(os.getenv('MAX_USERS_PER_PARTY', '0'))  # 0 = unlimited

# HLS token validation (prevents direct stream access bypass)
ENABLE_HLS_TOKEN_VALIDATION = os.getenv('ENABLE_HLS_TOKEN_VALIDATION', 'true').lower()
HLS_TOKEN_EXPIRY = int(os.getenv('HLS_TOKEN_EXPIRY', '86400'))  # Default: 24 hours (in seconds)

# Rate limiting (prevents API abuse)
ENABLE_RATE_LIMITING = os.getenv('ENABLE_RATE_LIMITING', 'true').lower()
RATE_LIMIT_PARTY_CREATION = os.getenv('RATE_LIMIT_PARTY_CREATION', '5 per hour')  # Max party creations per IP
RATE_LIMIT_API_CALLS = os.getenv('RATE_LIMIT_API_CALLS', '1000 per minute')  # Max API calls per IP
