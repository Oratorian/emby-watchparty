"""
FastAPI dependency injection
Replaces the old Flask deps dict pattern
"""

from fastapi import Request

from backend.src.config import Config
from backend.src.emby_client import EmbyClient
from backend.src.party_manager import PartyManager
from backend.src.hls_token_manager import HLSTokenManager
from backend.src.stream_builder import StreamBuilder


def get_config(request: Request) -> Config:
    return request.app.state.config


def get_logger(request: Request):
    return request.app.state.logger


def get_emby_client(request: Request) -> EmbyClient:
    return request.app.state.emby_client


def get_party_manager(request: Request) -> PartyManager:
    return request.app.state.party_manager


def get_token_manager(request: Request) -> HLSTokenManager:
    return request.app.state.token_manager


def get_stream_builder(request: Request) -> StreamBuilder:
    return request.app.state.stream_builder
