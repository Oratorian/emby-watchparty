"""
Configuration for Emby Watch Party application
Loads settings from .env file as a typed dataclass
"""

import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv


def _bool(value: str) -> bool:
    """Convert env string to bool"""
    return value.lower() in ('true', '1', 'yes')


@dataclass(frozen=True)
class Config:
    """Application configuration loaded from environment variables"""

    # Application
    WATCH_PARTY_BIND: str
    WATCH_PARTY_PORT: int
    APP_PREFIX: str
    REQUIRE_LOGIN: bool
    SESSION_EXPIRY: int
    STATIC_SESSION_ENABLED: bool
    STATIC_SESSION_ID: str

    # Emby Server
    EMBY_SERVER_URL: str
    EMBY_API_KEY: str
    EMBY_USERNAME: str
    EMBY_PASSWORD: str

    # Logging
    LOG_LEVEL: str
    LOG_TO_FILE: bool
    LOG_FILE: str
    LOG_FORMAT: str
    LOG_MAX_SIZE: int
    CONSOLE_LOG_LEVEL: str

    # Security
    MAX_USERS_PER_PARTY: int
    ENABLE_HLS_TOKEN_VALIDATION: bool
    HLS_TOKEN_EXPIRY: int
    ENABLE_RATE_LIMITING: bool
    RATE_LIMIT_PARTY_CREATION: str
    RATE_LIMIT_API_CALLS: str

    @classmethod
    def from_env(cls) -> 'Config':
        """Load configuration from .env file and environment variables"""
        env_path = Path(__file__).parent.parent / '.env'
        load_dotenv(env_path)

        return cls(
            # Application
            WATCH_PARTY_BIND=os.getenv('WATCH_PARTY_BIND', '0.0.0.0'),
            WATCH_PARTY_PORT=int(os.getenv('WATCH_PARTY_PORT', '5000')),
            APP_PREFIX=os.getenv('APP_PREFIX', '').rstrip('/'),
            REQUIRE_LOGIN=_bool(os.getenv('REQUIRE_LOGIN', 'false')),
            SESSION_EXPIRY=int(os.getenv('SESSION_EXPIRY', '86400')),
            STATIC_SESSION_ENABLED=_bool(os.getenv('STATIC_SESSION_ENABLED', 'false')),
            STATIC_SESSION_ID=os.getenv('STATIC_SESSION_ID', 'PARTY').upper(),

            # Emby Server
            EMBY_SERVER_URL=os.getenv('EMBY_SERVER_URL', 'http://localhost:8096'),
            EMBY_API_KEY=os.getenv('EMBY_API_KEY', ''),
            EMBY_USERNAME=os.getenv('EMBY_USERNAME', ''),
            EMBY_PASSWORD=os.getenv('EMBY_PASSWORD', ''),

            # Logging
            LOG_LEVEL=os.getenv('LOG_LEVEL', 'INFO'),
            LOG_TO_FILE=_bool(os.getenv('LOG_TO_FILE', 'true')),
            LOG_FILE=os.getenv('LOG_FILE', 'logs/emby-watchparty.log'),
            LOG_FORMAT='rsyslog',
            LOG_MAX_SIZE=int(os.getenv('LOG_MAX_SIZE', '10')),
            CONSOLE_LOG_LEVEL=os.getenv('CONSOLE_LOG_LEVEL', 'WARNING'),

            # Security
            MAX_USERS_PER_PARTY=int(os.getenv('MAX_USERS_PER_PARTY', '0')),
            ENABLE_HLS_TOKEN_VALIDATION=_bool(os.getenv('ENABLE_HLS_TOKEN_VALIDATION', 'true')),
            HLS_TOKEN_EXPIRY=int(os.getenv('HLS_TOKEN_EXPIRY', '86400')),
            ENABLE_RATE_LIMITING=_bool(os.getenv('ENABLE_RATE_LIMITING', 'true')),
            RATE_LIMIT_PARTY_CREATION=f"{os.getenv('RATE_LIMIT_PARTY_CREATION', '5')} per hour",
            RATE_LIMIT_API_CALLS=f"{os.getenv('RATE_LIMIT_API_CALLS', '1000')} per minute",
        )
