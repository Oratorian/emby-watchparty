"""
Emby Watch Party - Synchronized video watching for Emby media server
Author: Oratorian
GitHub: https://github.com/Oratorian

Application entry point. Uses the app factory for component wiring.
"""

from src.app_factory import create_app

app, socketio, config, logger = create_app()
