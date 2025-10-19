"""
Configuration for Emby Watch Party application
"""

import os

# Logging configuration
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
LOG_FILE = os.getenv('LOG_FILE', 'logs/emby-watchparty.log')
LOG_FORMAT = 'rsyslog'  # rsyslog-style formatting
LOG_MAX_SIZE = 10 * 1024 * 1024  # 10MB
CONSOLE_LOG_LEVEL = 'WARNING'  # Only show warnings/errors in console when file logging is active

EMBY_SERVER_URL = os.getenv('EMBY_SERVER_URL', 'http://url.to.emby')
EMBY_API_KEY = os.getenv('EMBY_API_KEY', 'api-key')
EMBY_USERNAME = os.getenv('EMBY_USERNAME', 'user')
EMBY_PASSWORD = os.getenv('EMBY_PASSWORD', 'pw')